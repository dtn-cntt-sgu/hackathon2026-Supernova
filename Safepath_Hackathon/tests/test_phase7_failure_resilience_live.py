"""
Phase 7 Live Integration & Failure Resilience Tests for SafePathAI.
Validates zero-mock error handling across all failure injection and edge-case scenarios:
1. OSRM offline or out-of-bounds queries fail safely without fake geometry.
2. Camera missing/unverified/timeout returns UNKNOWN / 404 without dummy images.
3. Open-Meteo weather failures return None / UNKNOWN, never 0.0 mm/h.
4. Hydrological tide without official bulletin returns TIDE_UNAVAILABLE, never sine waves.
5. Computer vision without ground-truth weights returns MODEL_UNAVAILABLE.
6. Redis cache expiration preserves UNKNOWN instead of defaulting to SAFE.
7. CORS rejections for unauthorized origins.
8. Real Health endpoint reports accurate infrastructure status and camera freshness.
"""

import os
from datetime import datetime, timezone
import pytest
import httpx
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.config import settings
from backend.app.schemas.contracts import (
    CameraEvidence,
    DataSourceStatus,
    RiskLevel,
    RouteSegmentRisk,
    SafeRouteResponse,
    WeatherTideSignal,
)
from backend.app.services.weather_tide import (
    fetch_hcm_weather,
    fetch_tide_signal,
)
from backend.app.services.vision import (
    VehicleDetector,
    FloodSegmenter,
    PreprocessResult,
    determine_camera_risk_level,
)
from backend.app.services.risk_engine import calculate_segment_risk
from backend.app.services.routing import find_safe_route


@pytest.fixture(scope="module")
def client():
    """Module-scoped FastAPI TestClient."""
    with TestClient(app) as c:
        yield c


class TestPhase7FailureResilienceLive:
    """Verifies that all failure modes fail safely without defaulting to fake SAFE states."""

    def test_health_reports_accurate_state_and_camera_freshness(self, client: TestClient):
        """Health check returns actual service availability; unobserved camera freshness is null."""
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ("healthy", "degraded")
        assert data["database"] == "healthy"
        assert data["redis"] == "healthy"
        assert data["osrm"] == "available"
        # Since no live camera worker has verified snapshots yet, freshness MUST be null
        assert data["last_camera_update"] is None
        assert data["camera_data_age_seconds"] is None

    def test_invalid_coordinates_rejected_before_osrm(self, client: TestClient):
        """Out-of-bounds GPS coordinates are caught by Pydantic before calling routing engine."""
        # Latitude > 90
        res = client.post(
            "/api/v1/routes/search",
            json={
                "origin": {"lat": 99.99, "lng": 106.69},
                "destination": {"lat": 10.80, "lng": 106.71},
            },
        )
        assert res.status_code == 422

        # Longitude < -180
        res = client.post(
            "/api/v1/routes/search",
            json={
                "origin": {"lat": 10.77, "lng": -190.0},
                "destination": {"lat": 10.80, "lng": 106.71},
            },
        )
        assert res.status_code == 422

    def test_no_route_across_ocean_fails_safely(self, client: TestClient):
        """Routing to coordinates deep in the South China Sea is safely rejected with OUTSIDE_SERVICE_AREA or NO_ROUTE."""
        # Point in international waters outside service bounds
        res = client.post(
            "/api/v1/routes/search",
            json={
                "origin": {"lat": 10.7725, "lng": 106.6980},  # Ben Thanh
                "destination": {"lat": 9.5000, "lng": 110.5000},  # Deep sea offshore
            },
        )
        assert res.status_code in (404, 422, 503)
        detail = res.json().get("detail", {})
        assert detail.get("code") in ("NO_ROUTE", "ROUTING_PROVIDER_UNAVAILABLE", "OUTSIDE_SERVICE_AREA")

    def test_camera_list_metadata_separation_and_unverified_unknown(self, client: TestClient):
        """Camera registry returns valid coordinates with UNKNOWN risk level when unobserved."""
        res = client.get("/api/v1/cameras")
        assert res.status_code == 200
        cameras = res.json()
        assert len(cameras) >= 700  # 796 cameras in registry
        for cam in cameras[:50]:
            assert cam["cam_id"]
            assert cam["code"]
            assert 10.0 <= cam["lat"] <= 11.5
            assert 106.0 <= cam["lng"] <= 107.5
            # Zero-Mock: All unobserved cameras MUST be UNKNOWN, NEVER SAFE
            assert cam["risk_level"] == "UNKNOWN"

    def test_missing_camera_image_returns_404_no_fabricated_mock(self, client: TestClient):
        """Requesting an unregistered camera image returns 404, never a dummy synthesized image."""
        res = client.get("/api/v1/cameras/cam_does_not_exist_999999/image")
        assert res.status_code == 404

    async def test_weather_error_returns_none_never_zero_humidity(self):
        """When weather provider returns error/429/timeout, result is None and WEATHER_UNAVAILABLE."""
        # Use an uncached coordinate and a mock transport returning HTTP 500 error
        transport = httpx.MockTransport(lambda req: httpx.Response(500))
        async with httpx.AsyncClient(transport=transport) as mock_client:
            rain_mm, status, observed_at, weather_code = await fetch_hcm_weather(
                lat=9.9999,
                lng=105.9999,
                client=mock_client,
            )
            assert rain_mm is None
            assert status == "WEATHER_UNAVAILABLE"
            assert weather_code is None
            assert observed_at is None

    async def test_tide_unavailable_by_default_never_defaults_to_safe_or_simulated(self):
        """Tide signal defaults to TIDE_UNAVAILABLE unless an official signed bulletin is ingested."""
        signal = await fetch_tide_signal()
        assert signal.tide_level_meters is None
        assert signal.tide_status == "TIDE_UNAVAILABLE"
        assert signal.is_high_tide_alert is None
        assert signal.tide_datum == "Hòn Dấu (VN-2000)"

    def test_missing_flood_segmenter_weights_returns_model_unavailable(self):
        """FloodSegmenter transparently reports MODEL_UNAVAILABLE without ground-truth weights."""
        segmenter = FloodSegmenter(model_path="data/models/non_existent_flood_model.onnx")
        assert segmenter.session is None
        assert segmenter.model_status == "MODEL_UNAVAILABLE"

        # Running inference fails transparently with uncertainty 1.0
        import numpy as np
        dummy_frame = np.zeros((230, 300, 3), dtype=np.uint8)
        dummy_roi = np.ones((230, 300), dtype=np.uint8) * 255
        prep = PreprocessResult(
            original_image=dummy_frame,
            roi_mask=dummy_roi,
            roi_image=dummy_frame,
            roi_pixel_count=300 * 230,
            mean_luminance=128.0,
            laplacian_var=100.0,
            is_dark=False,
            is_blurry=False,
            height=230,
            width=300,
        )
        res = segmenter.segment_flood_water(prep)
        assert res.water_mask is None
        assert res.flood_ratio is None
        assert res.uncertainty == 1.0
        assert res.model_status == "MODEL_UNAVAILABLE"

    def test_unobserved_road_segment_is_unknown_never_safe(self):
        """A road segment without camera evidence and without rain data MUST score UNKNOWN."""
        unobserved_segment = {
            "osm_way_id": 99999999,
            "street_name": "Đường Chưa Quan Trắc",
            "length_meters": 125.0,
            "is_flood_prone_history": None,
        }
        weather_unknown = WeatherTideSignal(
            rain_mm_per_hour=None,
            rain_status="WEATHER_UNAVAILABLE",
            tide_level_meters=None,
            tide_status="TIDE_UNAVAILABLE",
            timestamp=datetime.now(timezone.utc),
        )
        seg_risk = calculate_segment_risk(
            segment=unobserved_segment,
            camera_evidences=[],
            weather_tide=weather_unknown,
        )
        assert seg_risk.risk_level == RiskLevel.UNKNOWN
        assert seg_risk.risk_score is None

    def test_cors_rejects_unauthorized_origin(self, client: TestClient):
        """Origins outside the whitelisted localhost/dev ports do not get CORS headers."""
        res = client.options(
            "/api/v1/routes/search",
            headers={
                "Origin": "http://malicious-site.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        # Should not allow origin
        allowed_origin = res.headers.get("access-control-allow-origin")
        assert allowed_origin != "http://malicious-site.example.com"
