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
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db.session import async_engine, get_db

from backend.app.db.session import AsyncSessionLocal
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
        "Đài KTTV Nam Bộ ghi nhận: "
        "Mực nước tại trạm Phú An đạt 1.58m lúc 17h30 ngày 24/10/2026. "
        "Tại trạm Nhà Bè đạt 1.63m lúc 17h30 ngày 24/10/2026."
    )

    now = datetime.now(timezone.utc)
    results = adapter.parse_bulletin_text(bulletin, default_date=now)

    assert len(results) == 2
    stations = {r["station_id"]: r["water_level_m"] for r in results}
    assert stations["tram_phu_an"] == 1.58
    assert stations["tram_nha_be"] == 1.63


class MemoryRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, **kwargs):
        self.values[key] = value
        return True

    async def delete(self, key):
        self.values.pop(key, None)

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_hydrology_persistence_and_cache():
    """Commits stay inside an outer transaction; no fixture reaches runtime DB/cache."""
    redis = MemoryRedis()
    now = datetime.now(timezone.utc)
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False,
                                    join_transaction_mode="create_savepoint") as session:
                obs = await hydrology_service.record_observation(
                    session=session, redis=redis, station_id="tram_phu_an",
                    water_level_m=1.52, observed_at=now,
                    source_url="https://kttv.gov.vn/bulletin/isolated-test-fixture",
                    source_verified=True,
                )
                assert obs.id is not None and obs.alarm_level == 2
                assert obs.quality_status == "OBSERVED_LIVE"
                history = await hydrology_service.get_station_history(session, "tram_phu_an", limit=5)
                assert history[0].water_level_m == 1.52
                latest = await hydrology_service.get_latest_observations(session, redis)
                station = next(s for s in latest.stations if s.station_id == "tram_phu_an")
                assert station.water_level_m == 1.52
                assert latest.max_alarm_level >= 2
                tide = await fetch_tide_signal(redis_client=redis)
                assert tide.tide_level_meters == 1.52 and tide.is_high_tide_alert is True
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_hydrology_api_endpoints(monkeypatch):
    """Exercise real HTTP contracts against rollback-only DB and isolated Redis."""
    import backend.app.main as main
    redis = MemoryRedis()
    monkeypatch.setattr(main, "get_redis_client", lambda: redis)
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False,
                                    join_transaction_mode="create_savepoint") as session:
                async def isolated_db():
                    yield session
                app.dependency_overrides[get_db] = isolated_db
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.get("/api/v1/hydrology/stations")
                    assert response.status_code == 200
                    assert {s["station_id"] for s in response.json()} >= {"tram_phu_an", "tram_nha_be"}
                    bulletin = (
                        "Trạm Phú An ghi nhận 1.45m lúc 17h30 ngày 24/10/2026. "
                        "Trạm Nhà Bè ghi nhận 1.51m lúc 17h30 ngày 24/10/2026."
                    )
                    from backend.app.main import require_service_access
                    app.dependency_overrides[require_service_access] = lambda: None
                    try:
                        response = await client.post("/api/v1/hydrology/ingest", json={"bulletin_text": bulletin})
                    finally:
                        app.dependency_overrides.pop(require_service_access, None)
                    assert response.status_code == 200
                    assert len(response.json()) == 2
                    assert all(s["quality_status"] == "UNVERIFIED" and s["water_level_m"] is None
                               for s in response.json())
                    latest = await client.get("/api/v1/hydrology/latest")
                    assert latest.status_code == 200
                    assert latest.json()["quality_status"] == "UNAVAILABLE"
                    assert latest.json()["max_alarm_level"] is None
                    history = await client.get("/api/v1/hydrology/history?station_id=tram_phu_an&limit=10")
                    assert history.status_code == 200 and history.json()
        finally:
            app.dependency_overrides.pop(get_db, None)
            await transaction.rollback()
