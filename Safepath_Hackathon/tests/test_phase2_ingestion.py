"""
Phase 2 Unit and Integration Tests for SafePathAI.
Validates:
1. Camera URL formatting and HTTP headers.
2. 3-Tier Fallback mechanism (LIVE, STALE, SIMULATED) under network success/errors.
3. Anti-ban rate limiting and session cookie warmup.
4. Weather and Tide ingestion (Open-Meteo & semi-diurnal tide model + Redis sync).
"""

from datetime import datetime, timezone
import json
import os
import shutil
import tempfile
import pytest
import respx
import httpx
from PIL import Image

from backend.app.core.config import settings
from backend.app.db.session import get_redis_client
from backend.app.schemas.contracts import DataSourceStatus, WeatherTideSignal
from backend.app.services.scraper import (
    build_camera_image_url,
    get_camera_request_headers,
    warmup_session_cookie,
    scrape_camera_image,
    scrape_active_cameras,
    MIN_VALID_IMAGE_BYTES,
)
from backend.app.services.weather_tide import (
    REDIS_TIDE_BULLETIN_KEY,
    fetch_hcm_weather,
    fetch_tide_signal,
    get_combined_weather_tide,
    sync_weather_tide_to_redis,
    get_cached_weather_tide,
    HIGH_TIDE_ALERT_THRESHOLD_METERS,
)


@pytest.fixture
def temp_storage_dir():
    """Provides an isolated temporary directory for camera image storage."""
    temp_dir = tempfile.mkdtemp(prefix="safepath_test_storage_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def _generate_test_jpeg(size_bytes: int = 4000) -> bytes:
    """Helper to generate a valid JPEG image payload with specific minimum size."""
    img = Image.new("RGB", (300, 230), color=(100, 150, 200))
    temp_file = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    temp_file.close()
    img.save(temp_file.name, format="JPEG", quality=95)
    with open(temp_file.name, "rb") as f:
        data = f.read()
    os.unlink(temp_file.name)
    # Pad if needed to reach size_bytes
    if len(data) < size_bytes:
        data += b"\x00" * (size_bytes - len(data))
    return data


# ==============================================================================
# 1. URL & Header Tests
# ==============================================================================
class TestCameraURLAndHeaders:
    """Tests for correct cURL URL format and HTTP request headers."""

    def test_build_camera_image_url(self):
        cam_id = "58af8b69bd82540010390c28"
        url = build_camera_image_url(cam_id)

        assert url.startswith(settings.HCMC_CAMERA_BASE_URL)
        assert f"id={cam_id}" in url
        # Phase 10: Canonical clean URL avoids clutter parameters (bg, w, h) that cause placeholder errors
        assert "bg=black" not in url
        assert "w=300" not in url
        assert "h=230" not in url

    def test_get_camera_request_headers(self, monkeypatch):
        # Without cookie
        monkeypatch.setattr(settings, "HCMC_CAMERA_COOKIE", "")
        headers = get_camera_request_headers()
        assert headers["Referer"] == "https://giaothong.hochiminhcity.gov.vn/"
        assert "image/" in headers["Accept"]
        assert "Chrome" in headers["User-Agent"]
        assert "Cookie" not in headers

        # With explicit cookie configured
        test_cookie = "ASP.NET_SessionId=abcdef12345; .VDMS=xyz987"
        monkeypatch.setattr(settings, "HCMC_CAMERA_COOKIE", test_cookie)
        headers_with_cookie = get_camera_request_headers()
        assert headers_with_cookie["Cookie"] == test_cookie


# ==============================================================================
# 2. 3-Tier Fallback Scraper Tests
# ==============================================================================
class TestScraperFallbackMechanisms:
    """Tests for LIVE, STALE, and SIMULATED fallback tiers under various HTTP responses."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_tier1_live_success(self, temp_storage_dir, monkeypatch):
        """Tier 1 (LIVE): Successful 200 response with image > 2500 bytes."""
        monkeypatch.setattr(settings, "CAMERA_INGESTION_PERMITTED", True)
        cam_id = "58af8b69bd82540010390c28"
        cam = {
            "cam_id": cam_id,
            "code": "TTH 35.4",
            "name": "Nam Kỳ Khởi Nghĩa - Võ Thị Sáu",
            "lat": 10.7868,
            "lng": 106.6882,
        }

        # Mock port 8007 CameraHandler.ashx returning valid 4KB JPEG
        valid_jpeg = _generate_test_jpeg(size_bytes=4000)
        route = respx.get(url__startswith=settings.HCMC_CAMERA_BASE_URL).mock(
            return_value=httpx.Response(
                200,
                content=valid_jpeg,
                headers={"Content-Type": "image/jpeg"},
            )
        )

        async with httpx.AsyncClient() as client:
            result = await scrape_camera_image(client, cam, storage_dir=temp_storage_dir)

        assert route.called
        assert result.source_status == DataSourceStatus.LIVE
        assert result.file_size >= MIN_VALID_IMAGE_BYTES
        assert os.path.exists(result.image_path)
        assert result.error_message is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_tier2_stale_fallback(self, temp_storage_dir, monkeypatch):
        """
        Tier 2 (STALE): Server returns 403/429/500 or network error,
        system falls back to the existing file in storage.
        """
        monkeypatch.setattr(settings, "CAMERA_INGESTION_PERMITTED", True)
        cam_id = "58af99abbd82540010390c39"
        cam = {
            "cam_id": cam_id,
            "code": "TTH 36.2",
            "name": "Điện Biên Phủ - Đinh Tiên Hoàng",
            "lat": 10.7902,
            "lng": 106.6983,
        }

        # Pre-seed existing stale image on disk
        local_path = os.path.join(temp_storage_dir, f"{cam_id}.jpg")
        stale_bytes = _generate_test_jpeg(size_bytes=3500)
        with open(local_path, "wb") as f:
            f.write(stale_bytes)

        # Mock server returning 403 Forbidden (e.g. cookie expired or IP rate-limited)
        respx.get(url__startswith=settings.HCMC_CAMERA_BASE_URL).mock(
            return_value=httpx.Response(403, text="Forbidden")
        )

        async with httpx.AsyncClient() as client:
            result = await scrape_camera_image(client, cam, storage_dir=temp_storage_dir)

        assert result.source_status == DataSourceStatus.STALE
        assert result.file_size == len(stale_bytes)
        assert os.path.exists(result.image_path)
        assert "403" in (result.error_message or "")

    @respx.mock
    @pytest.mark.asyncio
    async def test_tier3_simulated_fallback(self, temp_storage_dir, monkeypatch):
        """
        Tier 3 (SIMULATED): Request fails AND no local image exists on disk,
        system gracefully reports STALE without crashing or fabricating mock frames.
        """
        monkeypatch.setattr(settings, "CAMERA_INGESTION_PERMITTED", True)
        cam_id = "56de42f611f398ec0c481287"
        cam = {
            "cam_id": cam_id,
            "code": "TTH 6.1",
            "name": "Võ Văn Kiệt - Hồ Học Lãm",
            "lat": 10.7685,
            "lng": 106.6975,
        }

        # Mock server returning 429 Too Many Requests
        respx.get(url__startswith=settings.HCMC_CAMERA_BASE_URL).mock(
            return_value=httpx.Response(429, text="Too Many Requests")
        )

        async with httpx.AsyncClient() as client:
            result = await scrape_camera_image(client, cam, storage_dir=temp_storage_dir)

        # Zero-Mock: Fallback reports STALE without fabricating mock frames
        assert result.source_status in (DataSourceStatus.SIMULATED, DataSourceStatus.STALE)
        assert result.file_size >= 0
        assert result.image_path is None or os.path.exists(result.image_path)
        assert "failed" in (result.error_message or "").lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_empty_black_frame_falls_back(self, temp_storage_dir, monkeypatch):
        """
        If server returns 200 OK but image length is < 2500 bytes (signal-loss/blank frame),
        system must reject it as invalid live and trigger STALE/SIMULATED fallback.
        """
        monkeypatch.setattr(settings, "CAMERA_INGESTION_PERMITTED", True)
        cam_id = "5822b5ededeb6c0012a2d66a"
        cam = {
            "cam_id": cam_id,
            "code": "TTH 5.1",
            "name": "Mai Chí Thọ - Nguyễn Cơ Thạch",
            "lat": 10.7732,
            "lng": 106.7248,
        }

        # Server returns 200 with tiny 300-byte corrupted/black frame
        respx.get(url__startswith=settings.HCMC_CAMERA_BASE_URL).mock(
            return_value=httpx.Response(200, content=b"\x00" * 300, headers={"Content-Type": "image/jpeg"})
        )

        async with httpx.AsyncClient() as client:
            result = await scrape_camera_image(client, cam, storage_dir=temp_storage_dir)

        assert result.source_status in (DataSourceStatus.SIMULATED, DataSourceStatus.STALE)
        assert result.file_size >= 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_scrape_active_cameras_batch(self, temp_storage_dir, monkeypatch):
        """Verifies concurrent batch scraping of multiple cameras."""
        monkeypatch.setattr(settings, "CAMERA_INGESTION_PERMITTED", True)
        cams = [
            {"cam_id": "cam_batch_1", "code": "TTH 1", "name": "Cam 1", "lat": 10.7, "lng": 106.7},
            {"cam_id": "cam_batch_2", "code": "TTH 2", "name": "Cam 2", "lat": 10.8, "lng": 106.8},
        ]
        valid_jpeg = _generate_test_jpeg(size_bytes=3000)
        respx.get(url__startswith=settings.HCMC_CAMERA_BASE_URL).mock(
            return_value=httpx.Response(200, content=valid_jpeg, headers={"Content-Type": "image/jpeg"})
        )

        results = await scrape_active_cameras(
            cams, storage_dir=temp_storage_dir, max_concurrency=2, jitter_range=(0.0, 0.0)
        )
        assert len(results) == 2
        for r in results:
            assert r.source_status == DataSourceStatus.LIVE


# ==============================================================================
# 3. Session Warmup Tests
# ==============================================================================
class TestSessionWarmup:
    """Tests for automatic cookie jar warmup."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_warmup_session_cookie(self, monkeypatch):
        monkeypatch.setattr(settings, "HCMC_CAMERA_COOKIE", "")
        # Mock main portal response with Set-Cookie headers
        respx.get(settings.HCMC_CAMERA_REFERER).mock(
            return_value=httpx.Response(
                200,
                headers={"Set-Cookie": "ASP.NET_SessionId=test_sess_id; path=/; HttpOnly"},
            )
        )

        async with httpx.AsyncClient() as client:
            success = await warmup_session_cookie(client)
            assert success is True
            assert "ASP.NET_SessionId" in client.cookies


# ==============================================================================
# 4. Weather & Tide Ingestion Tests
# ==============================================================================
class TestWeatherTideIngestion:
    """Tests for Open-Meteo weather precipitation and tide signal calculation."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_fetch_hcm_weather_success(self):
        # Mock Open-Meteo API response with 12.5 mm rainfall
        open_meteo_url = settings.OPEN_METEO_URL
        respx.get(url__startswith=open_meteo_url).mock(
            return_value=httpx.Response(
                200,
                json={"utc_offset_seconds": 25200, "current": {"time": "2026-10-23T03:00", "precipitation": 12.5, "rain": 12.5, "weather_code": 61}},
            )
        )

        rain, status, observed_at, code = await fetch_hcm_weather(lat=9.9911, lng=105.9911)
        assert rain == 12.5
        assert status == "LIVE"
        assert code == 61
        assert observed_at.tzinfo is not None

    @respx.mock
    @pytest.mark.asyncio
    async def test_fetch_hcm_weather_error_fallback(self):
        # Open-Meteo API fails (500 or timeout), Zero-Mock: returns None, WEATHER_UNAVAILABLE
        open_meteo_url = settings.OPEN_METEO_URL
        respx.get(url__startswith=open_meteo_url).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        rain, status, observed_at, code = await fetch_hcm_weather(lat=8.1111, lng=104.2222)
        assert rain is None
        assert status == "WEATHER_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_fetch_tide_signal_unavailable_without_bulletin(self):
        # Normal tide without bulletin: TIDE_UNAVAILABLE, None
        redis = get_redis_client()
        await redis.delete(REDIS_TIDE_BULLETIN_KEY)
        try:
            normal_signal = await fetch_tide_signal(redis_client=redis)
            assert normal_signal.tide_status == "TIDE_UNAVAILABLE"
            assert normal_signal.tide_level_meters is None
            assert normal_signal.timestamp is None
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_redis_sync_and_retrieve(self):
        """Verifies storing and retrieving WeatherTideSignal to/from real Redis container."""
        test_signal = WeatherTideSignal(
            rain_mm_per_hour=35.0, rain_status="LIVE", tide_level_meters=1.65,
            tide_status="LIVE", is_high_tide_alert=True, timestamp=datetime.now(timezone.utc),
            source_url="https://example.org/test-bulletin",
        )

        # Save to Redis
        saved = await sync_weather_tide_to_redis(test_signal, ttl_seconds=60)
        assert saved.rain_mm_per_hour == 35.0
        assert saved.is_high_tide_alert is True

        # Read back from Redis
        cached = await get_cached_weather_tide()
        assert cached is not None
        assert cached.rain_mm_per_hour == 35.0
        assert cached.tide_level_meters == test_signal.tide_level_meters
        assert cached.is_high_tide_alert is True

