"""
Unit & Integration Tests for SafePathAI Real-Time Hydrology & Tidal Ingestion.

Covers:
1. Station Registry: Exact coordinates, river names, and datum verification.
2. Alarm Levels: Strict compliance with Decision 18/2021/QD-TTg (1.40, 1.50, 1.60m).
3. Quality Status Assessment: OBSERVED_LIVE, OBSERVED_STALE, FORECAST, UNAVAILABLE.
4. Bulletin Text Parsing: Vietnamese natural language extraction for Phú An & Nhà Bè.
5. Database Persistence: Async SQLAlchemy insert, refresh, and history querying.
6. Redis Synchronization: Per-station and composite cache propagation.
7. Weather-Tide Compatibility: fetch_tide_signal integration and alert propagation.
8. REST Endpoints: GET /stations, GET /latest, GET /history, POST /ingest.
"""

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from backend.app.db.session import AsyncSessionLocal, get_redis_client
from backend.app.main import app
from backend.app.services.hydrology_service import (
    HCMC_HYDROLOGY_STATIONS,
    compute_alarm_level,
    get_alarm_description,
    assess_quality_status,
    hydrology_service,
    HydrologySourceAdapter,
)
from backend.app.services.weather_tide import (
    DATUM_HON_DAU_VN2000,
    REDIS_TIDE_BULLETIN_KEY,
    TIDE_ALARM_LEVEL_1_METERS,
    TIDE_ALARM_LEVEL_2_METERS,
    TIDE_ALARM_LEVEL_3_METERS,
    fetch_tide_signal,
)


def test_hydrology_station_registry():
    """Verifies official HCMC stations, coordinates, rivers, and vertical datum."""
    assert "tram_phu_an" in HCMC_HYDROLOGY_STATIONS
    assert "tram_nha_be" in HCMC_HYDROLOGY_STATIONS

    phu_an = HCMC_HYDROLOGY_STATIONS["tram_phu_an"]
    assert phu_an["station_name"] == "Trạm Phú An"
    assert phu_an["river_name"] == "Sông Sài Gòn"
    assert phu_an["latitude"] == pytest.approx(10.793, abs=0.005)
    assert phu_an["longitude"] == pytest.approx(106.711, abs=0.005)
    assert phu_an["vertical_datum"] == DATUM_HON_DAU_VN2000

    nha_be = HCMC_HYDROLOGY_STATIONS["tram_nha_be"]
    assert nha_be["station_name"] == "Trạm Nhà Bè"
    assert nha_be["river_name"] == "Sông Đồng Điền"
    assert nha_be["latitude"] == pytest.approx(10.655, abs=0.005)
    assert nha_be["longitude"] == pytest.approx(106.745, abs=0.005)


def test_alarm_level_thresholds():
    """Validates alarm levels against official thresholds."""
    assert compute_alarm_level(1.20) == 0
    assert compute_alarm_level(1.39) == 0
    assert compute_alarm_level(1.40) == 1
    assert compute_alarm_level(1.49) == 1
    assert compute_alarm_level(1.50) == 2
    assert compute_alarm_level(1.59) == 2
    assert compute_alarm_level(1.60) == 3
    assert compute_alarm_level(1.75) == 3

    desc_0 = get_alarm_description(0)
    desc_1 = get_alarm_description(1)
    desc_2 = get_alarm_description(2)
    desc_3 = get_alarm_description(3)

    assert "Bình thường" in desc_0
    assert "Báo động I" in desc_1
    assert "Báo động II" in desc_2
    assert "Báo động III" in desc_3


def test_quality_status_assessment():
    """Validates quality status tagging based on freshness."""
    now = datetime.now(timezone.utc)

    # 1 hour ago -> OBSERVED_LIVE
    live_time = now - timedelta(hours=1)
    assert assess_quality_status(live_time, now=now) == "OBSERVED_LIVE"

    # 12 hours ago -> OBSERVED_STALE
    stale_time = now - timedelta(hours=12)
    assert assess_quality_status(stale_time, now=now) == "OBSERVED_STALE"

    # 72 hours ago -> UNAVAILABLE
    old_time = now - timedelta(hours=72)
    assert assess_quality_status(old_time, now=now) == "UNAVAILABLE"

    # Future or flagged -> FORECAST
    future_time = now + timedelta(hours=6)
    assert assess_quality_status(future_time, now=now) == "FORECAST"
    assert assess_quality_status(live_time, is_forecast=True, now=now) == "FORECAST"


def test_bulletin_text_parser():
    """Validates parsing of natural language Vietnamese hydrographic bulletins."""
    adapter = HydrologySourceAdapter()
    bulletin = (
        "Đài KTTV Nam Bộ thông báo: Đỉnh triều cao nhất ngày 24/10 xuất hiện vào buổi chiều. "
        "Mực nước tại trạm Phú An đạt 1.58m lúc 17h30. "
        "Tại trạm Nhà Bè đạt 1.63m (vượt Báo động 3)."
    )

    now = datetime.now(timezone.utc)
    results = adapter.parse_bulletin_text(bulletin, default_date=now)

    assert len(results) == 2
    stations = {r["station_id"]: r["water_level_m"] for r in results}
    assert stations["tram_phu_an"] == 1.58
    assert stations["tram_nha_be"] == 1.63


@pytest.mark.asyncio
async def test_hydrology_persistence_and_cache():
    """Validates persisting an observation to PostgreSQL and caching to Redis."""
    redis = get_redis_client()
    now = datetime.now(timezone.utc)

    try:
        async with AsyncSessionLocal() as session:
            obs = await hydrology_service.record_observation(
                session=session,
                redis=redis,
                station_id="tram_phu_an",
                water_level_m=1.52,
                observed_at=now,
                measurement_type="TIDAL_OBSERVATION",
            )
            assert obs.id is not None
            assert obs.alarm_level == 2
            assert obs.quality_status == "OBSERVED_LIVE"
            assert obs.vertical_datum == DATUM_HON_DAU_VN2000

            # Query history
            history = await hydrology_service.get_station_history(session, "tram_phu_an", limit=5)
            assert len(history) >= 1
            assert history[0].water_level_m == 1.52

            # Query latest composite
            latest = await hydrology_service.get_latest_observations(session, redis)
            assert latest.max_alarm_level >= 2
            assert latest.is_flood_warning is True
            pa_dto = next((s for s in latest.stations if s.station_id == "tram_phu_an"), None)
            assert pa_dto is not None
            assert pa_dto.water_level_m == 1.52

        # Verify integration with weather_tide.fetch_tide_signal
        tide_signal = await fetch_tide_signal(redis_client=redis)
        assert tide_signal.tide_level_meters == 1.52
        assert tide_signal.is_high_tide_alert is True
        assert tide_signal.tide_status == "LIVE"
    finally:
        await redis.delete(REDIS_TIDE_BULLETIN_KEY)
        await redis.aclose()


def test_hydrology_api_endpoints():
    """Validates the FastAPI HTTP endpoints for hydrology."""
    client = TestClient(app)

    # 1. GET /api/v1/hydrology/stations
    resp = client.get("/api/v1/hydrology/stations")
    assert resp.status_code == 200
    stations = resp.json()
    assert len(stations) >= 2
    ids = [s["station_id"] for s in stations]
    assert "tram_phu_an" in ids
    assert "tram_nha_be" in ids

    # 2. POST /api/v1/hydrology/ingest with bulletin text
    bulletin = "Bản tin KTTV: Mực nước trạm Phú An ghi nhận 1.45m, trạm Nhà Bè ghi nhận 1.51m."
    ingest_resp = client.post("/api/v1/hydrology/ingest", json={"bulletin_text": bulletin})
    assert ingest_resp.status_code == 200
    ingested = ingest_resp.json()
    assert len(ingested) == 2

    # 3. GET /api/v1/hydrology/latest
    latest_resp = client.get("/api/v1/hydrology/latest")
    assert latest_resp.status_code == 200
    latest_data = latest_resp.json()
    assert latest_data["max_alarm_level"] >= 1
    assert len(latest_data["stations"]) >= 2

    # 4. GET /api/v1/hydrology/history
    hist_resp = client.get("/api/v1/hydrology/history?station_id=tram_phu_an&limit=10")
    assert hist_resp.status_code == 200
    hist_data = hist_resp.json()
    assert isinstance(hist_data, list)
    assert len(hist_data) >= 1
    assert hist_data[0]["station_id"] == "tram_phu_an"
