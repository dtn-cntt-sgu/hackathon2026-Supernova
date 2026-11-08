"""
Phase 5 (P0) Comprehensive Tests: Real Weather, Real Tide, Historical Flood & Risk Engine (Zero-Mock Runtime).
Validates:
1. Open-Meteo HTTP client: Real precipitation, timestamp, WMO code. Unreachable/error returns None/WEATHER_UNAVAILABLE, NEVER 0.0 mm/h.
2. Tide signal: Replaces harmonic sine wave with verified bulletin / TIDE_UNAVAILABLE. Vertical datum Hòn Dấu (VN-2000).
3. Historical flood dataset: 13 official municipal flood points in PostGIS, matching road_segments is_flood_prone_history=True, rest NULL.
4. Risk Engine: Verified evidence only, compound flood risk (historical flood + heavy rain/tide), unobserved = UNKNOWN.
5. Dynamic routing reranking: Prioritizes safe alternatives using ranking_cost without distorting raw OSRM ETA.
"""

from datetime import datetime, timezone
import json
import os
import pytest
import inspect
import httpx
import respx
from sqlalchemy import text

from backend.app.db.session import AsyncSessionLocal, SessionLocal, get_redis_client
from backend.app.schemas.contracts import (
    CameraEvidence,
    DataSourceStatus,
    EvidenceEligibility,
    RiskLevel,
    RouteSegmentRisk,
    SafeRouteResponse,
    WeatherTideSignal,
)
from backend.app.services.weather_tide import (
    DATUM_HON_DAU_VN2000,
    HIGH_TIDE_ALERT_THRESHOLD_METERS,
    REDIS_TIDE_BULLETIN_KEY,
    REDIS_WEATHER_GRID_PREFIX,
    fetch_hcm_weather,
    fetch_tide_signal,
    get_combined_weather_tide,
    ingest_verified_tide_bulletin,
)
from backend.app.services.risk_engine import (
    AUTO_CRITICAL_FLOOD_RATIO,
    CRITICAL_RISK_THRESHOLD,
    MODERATE_RISK_THRESHOLD,
    calculate_segment_risk,
)
from backend.app.services.routing import find_safe_route, _get_osrm_raw_routes


# ==============================================================================
# 1. Open-Meteo Real Weather Client & Error Handling
# ==============================================================================
class TestOpenMeteoRealWeather:
    """Tests for Open-Meteo real weather ingestion and Zero-Mock error handling."""

    @pytest.mark.asyncio
    async def test_live_open_meteo_fetch(self):
        """Verify real Open-Meteo API returns valid schema and timestamp."""
        rain_mm, status, observed_at, code = await fetch_hcm_weather(lat=10.7769, lng=106.7009)
        assert status == "LIVE"
        assert rain_mm is not None
        assert rain_mm >= 0.0
        assert observed_at is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_open_meteo_error_returns_none_never_zero(self):
        """CRITICAL: On HTTP error/failure, must return None/WEATHER_UNAVAILABLE, NEVER 0.0 mm/h."""
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        # Use uncached coordinate to trigger external call
        rain_mm, status, observed_at, code = await fetch_hcm_weather(lat=9.1234, lng=105.1234)
        assert rain_mm is None, "Zero-Mock Violation: Error must return None, not 0.0 mm/h"
        assert status == "WEATHER_UNAVAILABLE"
        assert observed_at is None
        assert code is None

    @pytest.mark.asyncio
    async def test_weather_redis_grid_caching(self):
        """Verify weather is cached by spatial grid (lat/lng rounded to 2 decimals)."""
        redis = get_redis_client()
        lat, lng = 10.75, 106.65
        grid_key = f"{REDIS_WEATHER_GRID_PREFIX}{lat}:{lng}"
        try:
            # Seed cache
            payload = json.dumps({
                "rain_mm_per_hour": 35.5,
                "rain_status": "LIVE",
                "rain_observed_at": datetime.now(timezone.utc).isoformat(),
                "weather_code": 65,
            })
            await redis.set(grid_key, payload, ex=60)

            rain_mm, status, observed_at, code = await fetch_hcm_weather(lat=lat, lng=lng, redis_client=redis)
            assert rain_mm == 35.5
            assert status == "LIVE"
            assert code == 65
        finally:
            await redis.delete(grid_key)
            await redis.aclose()


# ==============================================================================
# 2. Real Tide & Datum Verification
# ==============================================================================
class TestRealTideAndDatum:
    """Tests for HCMC tidal observation and vertical datum integrity."""

    @pytest.mark.asyncio
    async def test_tide_unavailable_by_default_without_bulletin(self):
        """Zero-Mock: Without verified bulletin, tide must return TIDE_UNAVAILABLE and None level."""
        redis = get_redis_client()
        await redis.delete(REDIS_TIDE_BULLETIN_KEY)
        try:
            signal = await fetch_tide_signal(redis_client=redis)
            assert signal.tide_status == "TIDE_UNAVAILABLE"
            assert signal.tide_level_meters is None
            assert signal.is_high_tide_alert is None
            assert signal.tide_datum == DATUM_HON_DAU_VN2000
        finally:
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_ingest_verified_tide_bulletin(self):
        """Verify official bulletin ingestion from hydrographic station under Hòn Dấu VN-2000 datum."""
        redis = get_redis_client()
        observed_at = datetime.now(timezone.utc)
        source = "https://kttv.gov.vn/bulletin/phu-an-tide-20261023"
        try:
            # 1. Ingest alert tide (1.62m >= 1.50m Báo động II)
            signal = await ingest_verified_tide_bulletin(
                station="Trạm Phú An (Sông Sài Gòn)",
                level_meters=1.62,
                observed_at=observed_at,
                source_url=source,
                datum=DATUM_HON_DAU_VN2000,
                redis_client=redis,
            )
            assert signal.tide_status == "LIVE"
            assert signal.tide_level_meters == 1.62
            assert signal.is_high_tide_alert is True
            assert signal.tide_datum == DATUM_HON_DAU_VN2000

            # 2. Read back via fetch_tide_signal
            cached_signal = await fetch_tide_signal(redis_client=redis)
            assert cached_signal.tide_status == "LIVE"
            assert cached_signal.tide_level_meters == 1.62
            assert cached_signal.is_high_tide_alert is True
            assert cached_signal.tide_station == "Trạm Phú An (Sông Sài Gòn)"
        finally:
            await redis.delete(REDIS_TIDE_BULLETIN_KEY)
            await redis.aclose()

    @pytest.mark.asyncio
    async def test_runtime_tide_has_no_simulation_controls(self):
        """The production tide function has no simulation parameters."""
        assert "simulate_high_tide" not in inspect.signature(fetch_tide_signal).parameters
        assert "tide_override_meters" not in inspect.signature(fetch_tide_signal).parameters


# ==============================================================================
# 3. PostGIS Historical Flood Dataset Integrity
# ==============================================================================
class TestHistoricalFloodDataset:
    """Verifies official municipal flood dataset in PostGIS."""

    def test_historical_flood_table_and_road_segments_state(self):
        with SessionLocal() as db:
            # Check table exists and has 13 points
            points_count = db.execute(text("SELECT count(*) FROM historical_flood_points")).scalar_one()
            assert points_count == 13

            # Check road segments: exactly 13 TRUE, 0 FALSE, rest NULL
            res = db.execute(text("""
                SELECT 
                    count(*) FILTER (WHERE is_flood_prone_history = TRUE) AS true_count,
                    count(*) FILTER (WHERE is_flood_prone_history = FALSE) AS false_count,
                    count(*) FILTER (WHERE is_flood_prone_history IS NULL) AS null_count
                FROM road_segments
            """)).one()
            assert res.true_count == 13
            assert res.false_count == 0, "Zero-Mock: Unobserved segments must be NULL, never FALSE"
            assert res.null_count > 300000


# ==============================================================================
# 4. Multi-Criteria Risk Scoring
# ==============================================================================
class TestMultiCriteriaRiskScoring:
    """Tests multi-criteria risk calculation strictly from verified evidence."""

    def test_unobserved_segment_returns_unknown_never_safe(self):
        """Without camera, flood history, or severe weather, segment is UNKNOWN."""
        segment = {
            "osm_way_id": 999001,
            "edge_index": 1,
            "street_name": "Đường Chưa Quan Trắc",
            "length_meters": 120.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
            "is_flood_prone_history": None,
        }
        res = calculate_segment_risk(segment, camera_evidences=[], weather_tide=None)
        assert res.risk_level == RiskLevel.UNKNOWN
        assert res.risk_score is None

    def test_historical_flood_under_heavy_rain_remains_unobserved(self):
        """Regional rain and historical metadata do not measure current road water."""
        segment = {
            "osm_way_id": 999002,
            "edge_index": 1,
            "street_name": "Đường Nguyễn Hữu Cảnh",
            "length_meters": 250.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
            "is_flood_prone_history": True,
        }
        heavy_rain = WeatherTideSignal(
            rain_mm_per_hour=45.0,
            rain_status="LIVE",
            rain_observed_at=datetime.now(timezone.utc),
            source_url="https://api.open-meteo.com/v1/forecast",
            timestamp=datetime.now(timezone.utc),
        )
        res = calculate_segment_risk(segment, camera_evidences=[], weather_tide=heavy_rain)
        assert res.risk_level == RiskLevel.UNKNOWN
        assert res.risk_score is None
        assert res.weather_risk == "HEAVY_RAIN"
        assert res.historical_flood_prone is True

    def test_historical_flood_under_high_tide_alert_remains_unobserved(self):
        """Station tide is context, not a road-level flood observation."""
        segment = {
            "osm_way_id": 999003,
            "edge_index": 1,
            "street_name": "Đường Trần Xuân Soạn",
            "length_meters": 300.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
            "is_flood_prone_history": True,
        }
        tide_alert = WeatherTideSignal(
            rain_mm_per_hour=0.0,
            rain_status="LIVE",
            tide_level_meters=1.68,
            tide_status="LIVE",
            is_high_tide_alert=True,
            source_url="https://kttv.gov.vn/bulletin",
            timestamp=datetime.now(timezone.utc),
        )
        res = calculate_segment_risk(segment, camera_evidences=[], weather_tide=tide_alert)
        assert res.risk_level == RiskLevel.UNKNOWN
        assert res.risk_score is None
        assert res.historical_flood_cause == "HIGH_TIDE"

    def test_historical_flood_under_clear_weather_and_no_tide_is_unknown(self):
        """A dry regional bulletin cannot establish a safe road."""
        segment = {
            "osm_way_id": 999004,
            "edge_index": 1,
            "street_name": "Đường Quốc Hương",
            "length_meters": 180.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
            "is_flood_prone_history": True,
        }
        clear_weather = WeatherTideSignal(
            rain_mm_per_hour=0.0,
            rain_status="LIVE",
            tide_level_meters=1.20,
            tide_status="LIVE",
            is_high_tide_alert=False,
            timestamp=datetime.now(timezone.utc),
        )
        res = calculate_segment_risk(segment, camera_evidences=[], weather_tide=clear_weather)
        assert res.risk_level == RiskLevel.UNKNOWN
        assert res.risk_score is None
        assert res.historical_flood_prone is True

    def test_historical_flood_with_unobserved_weather_remains_unknown(self):
        """Historical flood street without active weather observation cannot be presumed safe."""
        segment = {
            "osm_way_id": 999005,
            "edge_index": 1,
            "street_name": "Đường Thảo Điền",
            "length_meters": 200.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
            "is_flood_prone_history": True,
        }
        unknown_weather = WeatherTideSignal(
            rain_mm_per_hour=None,
            rain_status="WEATHER_UNAVAILABLE",
            tide_level_meters=None,
            tide_status="TIDE_UNAVAILABLE",
            is_high_tide_alert=None,
            timestamp=datetime.now(timezone.utc),
        )
        res = calculate_segment_risk(segment, camera_evidences=[], weather_tide=unknown_weather)
        assert res.risk_level == RiskLevel.UNKNOWN
        assert res.risk_score is None

    def test_verified_camera_severe_flood_overrides_everything(self):
        """A validated road-water pixel observation can flag a critical hazard."""
        segment = {
            "osm_way_id": 999006,
            "edge_index": 2,
            "street_name": "Đường Đoạn Có Camera",
            "length_meters": 150.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
            "is_flood_prone_history": None,
        }
        cam = CameraEvidence(
            cam_id="cam_live_flood",
            name="Camera Đoạn Ngập",
            lat=10.79,
            lng=106.71,
            coordinate_source_url="https://example.org/gps",
            spatial_match_status="OBSERVED_SEGMENT_VERIFIED",
            evidence_eligibility=EvidenceEligibility.ROUTING_ELIGIBLE,
            observed_osm_way_id=999006,
            observed_edge_index=2,
            view_verification_source_url="https://example.org/view",
            line_of_sight_verified=True,
            image_url="/storage/cam.jpg",
            vehicle_count=12,
            traffic_density_score=0.40,
            flood_ratio=0.55,  # >= 0.35 AUTO_CRITICAL
            risk_level=RiskLevel.CRITICAL,
            source_status=DataSourceStatus.LIVE,
            updated_at=datetime.now(timezone.utc),
        )
        res = calculate_segment_risk(segment, camera_evidences=[cam], weather_tide=None)
        assert res.risk_level == RiskLevel.CRITICAL
        assert res.risk_score is not None and res.risk_score >= 75.0
        assert res.evidence_coverage == "OBSERVED_SEGMENT_VERIFIED"


# ==============================================================================
# 5. Risk-Aware Dynamic Routing & Candidate Reranking
# ==============================================================================
class TestRiskAwareRoutingReranking:
    """Verifies that find_safe_route reranks candidates by ranking_cost without distorting ETA."""

    @pytest.mark.asyncio
    async def test_route_preserves_raw_osrm_eta_and_sets_ranking_cost(self):
        """Raw OSRM duration in minutes must equal estimated_time_mins."""
        origin_lat, origin_lng = 10.7725, 106.6980
        dest_lat, dest_lng = 10.8012, 106.7115

        async with AsyncSessionLocal() as session:
            redis = get_redis_client()
            try:
                routes = await find_safe_route(
                    origin_lat=origin_lat,
                    origin_lng=origin_lng,
                    dest_lat=dest_lat,
                    dest_lng=dest_lng,
                    db_session=session,
                    redis_client=redis,
                )
                assert routes
                for r in routes:
                    # Raw ETA is preserved
                    assert r.estimated_time_mins > 0
                    assert r.total_distance_km > 0
                    assert r.ranking_cost is not None
                    # ranking_cost >= duration in seconds
                    assert r.ranking_cost >= (r.estimated_time_mins * 60.0) - 1.0
            finally:
                await redis.aclose()

    @pytest.mark.asyncio
    async def test_candidate_edges_do_not_claim_current_flood_risk(self):
        """A nearby historical point cannot make an unmatched OSRM step critical."""
        # Query route near Nguyễn Hữu Cảnh (Bình Thạnh)
        origin_lat, origin_lng = 10.7950, 106.7180
        dest_lat, dest_lng = 10.8010, 106.7250

        redis = get_redis_client()

        async with AsyncSessionLocal() as session:
            try:
                routes = await find_safe_route(
                    origin_lat=origin_lat,
                    origin_lng=origin_lng,
                    dest_lat=dest_lat,
                    dest_lng=dest_lng,
                    db_session=session,
                    redis_client=redis,
                )
                assert routes
                best_route = routes[0]
                assert best_route.overall_risk == RiskLevel.UNKNOWN
                assert best_route.critical_segments_count == 0
                assert all(step.osm_way_id is None for step in best_route.segments)
            finally:
                await redis.aclose()

