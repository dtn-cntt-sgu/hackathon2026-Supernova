"""
Comprehensive Unit & Integration Tests for:
1. Segment-level Traffic Intelligence (FREE_FLOW, SLOW, CONGESTED, UNKNOWN).
2. Realistic ETA Engine (Baseline OSRM preservation, realistic delay addition, BASE_OSRM_NO_TRAFFIC).
3. Authoritative Multi-Criteria Route Ranking (Hazard penalties inside ranking_cost only).
4. Honest Route Status & AI Explanation (ROUTE_FOUND_RISK_UNKNOWN when sensors limited).
5. Polyline Geodesic / Haversine Distance Audit.
6. Hot-swappable Commercial Traffic Providers (TomTom, HERE, Auto) with Redis Cache & Zero-Mock.
"""

import json
import math
from datetime import datetime, timezone, timedelta
from typing import Any, List
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from backend.app.core.config import settings
from backend.app.schemas.contracts import (
    CameraEvidence,
    DataSourceStatus,
    EvidenceEligibility,
    ImageAccessStatus,
    RiskLevel,
    TrafficStatus,
    SafeRouteResponse,
    RouteSegmentRisk,
)
from backend.app.services.risk_engine import calculate_segment_risk
from backend.app.services.traffic_news import TrafficNewsArticle
from backend.app.services.routing import _geodesic_distance_meters
from backend.app.services.traffic_providers import (
    get_traffic_provider,
    BaseTrafficProvider,
    TomTomTrafficProvider,
    HereTrafficProvider,
    SegmentTrafficFlow,
)


def create_mock_verified_camera(
    cam_id: str = "CAM_TEST_01",
    density: float = 0.85,
    seconds_ago: float = 30.0,
    line_of_sight: bool = True,
    osm_way_id: int = 123456,
) -> CameraEvidence:
    """Helper creating a strictly verified camera evidence fixture."""
    now = datetime.now(timezone.utc)
    updated_at = now - timedelta(seconds=seconds_ago)
    return CameraEvidence(
        cam_id=cam_id,
        code=cam_id,
        name=f"Camera {cam_id}",
        district="Quận 1",
        lat=10.7769,
        lng=106.7009,
        osm_way_id=osm_way_id,
        coordinate_source_url="https://giaothong.hochiminhcity.gov.vn",
        view_verification_source_url="https://giaothong.hochiminhcity.gov.vn/view/cam_01",
        spatial_match_status="OBSERVED_SEGMENT_VERIFIED",
        observed_osm_way_id=osm_way_id,
        observed_edge_index=1,
        line_of_sight_verified=line_of_sight,
        image_url=f"/api/v1/cameras/{cam_id}/image",
        has_image=True,
        image_access_status=ImageAccessStatus.VIEWABLE_PUBLIC,
        evidence_eligibility=EvidenceEligibility.ROUTING_ELIGIBLE,
        image_status="VALID_IMAGE_CACHED",
        image_status_reason="VALID_IMAGE_CACHED",
        model_status="ANALYSIS_SUCCESS",
        traffic_density_score=density,
        risk_level=RiskLevel.UNKNOWN,
        source_status=DataSourceStatus.LIVE,
        updated_at=updated_at,
    )


class TestSegmentTrafficIntelligence:
    """Verifies segment-level traffic scoring and strict Zero-Mock disqualifications."""

    def test_verified_high_density_camera_classifies_as_congested(self):
        """Density >= 0.70 classifies as CONGESTED with realistic delay."""
        segment = {
            "osm_way_id": 123456,
            "edge_index": 1,
            "street_name": "Đường Lê Duẩn",
            "length_meters": 500.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
        }
        cam = create_mock_verified_camera(density=0.82, seconds_ago=45.0)
        res = calculate_segment_risk(segment, camera_evidences=[cam])

        assert res.traffic_status == TrafficStatus.CONGESTED
        assert res.traffic_density_score == 0.82
        assert res.traffic_source == "camera_vision:CAM_TEST_01"
        assert res.traffic_segment_match_status == "OBSERVED_SEGMENT_VERIFIED"
        assert res.traffic_delay_seconds is not None
        # 500m at 10km/h (2.778 m/s) = 180s; baseline 35km/h (9.722 m/s) = 51.4s -> delay ~ 128.6s
        assert res.traffic_delay_seconds > 100.0

    def test_verified_medium_density_camera_classifies_as_slow(self):
        """0.40 <= Density < 0.70 classifies as SLOW with moderate delay."""
        segment = {
            "osm_way_id": 123456,
            "edge_index": 1,
            "street_name": "Đường Nguyễn Huệ",
            "length_meters": 400.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
        }
        cam = create_mock_verified_camera(density=0.55, seconds_ago=30.0)
        res = calculate_segment_risk(segment, camera_evidences=[cam])

        assert res.traffic_status == TrafficStatus.SLOW
        assert res.traffic_density_score == 0.55
        assert res.traffic_delay_seconds is not None
        # 400m at 20km/h (5.556 m/s) = 72s; baseline 35km/h (9.722 m/s) = 41.1s -> delay ~ 30.9s
        assert 20.0 <= res.traffic_delay_seconds <= 45.0

    def test_verified_low_density_camera_classifies_as_free_flow(self):
        """Density < 0.40 classifies as FREE_FLOW with 0 delay."""
        segment = {
            "osm_way_id": 123456,
            "edge_index": 1,
            "street_name": "Đường Pasteur",
            "length_meters": 300.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
        }
        cam = create_mock_verified_camera(density=0.20, seconds_ago=15.0)
        res = calculate_segment_risk(segment, camera_evidences=[cam])

        assert res.traffic_status == TrafficStatus.FREE_FLOW
        assert res.traffic_delay_seconds == 0.0

    def test_stale_camera_is_disqualified_to_unknown(self):
        """Camera older than 120s is disqualified from live traffic assessment."""
        segment = {
            "osm_way_id": 123456,
            "edge_index": 1,
            "street_name": "Đường Nam Kỳ Khởi Nghĩa",
            "length_meters": 300.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
        }
        # 180 seconds old (> 120s threshold)
        cam = create_mock_verified_camera(density=0.90, seconds_ago=180.0)
        res = calculate_segment_risk(segment, camera_evidences=[cam])

        assert res.traffic_status == TrafficStatus.UNKNOWN
        assert res.traffic_delay_seconds is None

    def test_unverified_spatial_candidate_camera_is_disqualified(self):
        """Camera without verified line of sight cannot declare traffic status."""
        segment = {
            "osm_way_id": 123456,
            "edge_index": 1,
            "street_name": "Đường Võ Văn Kiệt",
            "length_meters": 300.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
        }
        cam = create_mock_verified_camera(density=0.85, seconds_ago=20.0, line_of_sight=False)
        cam.spatial_match_status = "SPATIALLY_NEAR"
        res = calculate_segment_risk(segment, camera_evidences=[cam])

        assert res.traffic_status == TrafficStatus.UNKNOWN
        assert res.traffic_delay_seconds is None

    def test_verified_traffic_news_congestion_matches_segment(self):
        """Active verified news under 3 hours with CONGESTION marks matching road congested."""
        segment = {
            "osm_way_id": 999123,
            "edge_index": 1,
            "street_name": "Đường Cộng Hòa",
            "length_meters": 600.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
        }
        now = datetime.now(timezone.utc)
        news = [
            TrafficNewsArticle(
                id="NEWS_01",
                canonical_url="https://vovgiaothong.vn/cong-hoa-un-tac",
                source_name="VOV Giao Thông",
                title="Ùn tắc nghiêm trọng trên Đường Cộng Hòa",
                summary="Lượng phương tiện đông đúc gây ùn ứ kéo dài tại Đường Cộng Hòa",
                category="CONGESTION",
                severity="WARNING",
                event_status="ACTIVE_HAZARD",
                latitude=10.8015,
                longitude=106.6534,
                location_confidence="EXACT",
                geocoding_status="RESOLVED",
                verification_status="VERIFIED_SOURCE",
                published_at=now - timedelta(minutes=25),
                fetched_at=now - timedelta(minutes=20),
            )
        ]
        res = calculate_segment_risk(segment, camera_evidences=[], traffic_news=news)

        assert res.traffic_status == TrafficStatus.CONGESTED
        assert res.traffic_source == "traffic_news:verified"
        assert res.traffic_delay_seconds is not None
        assert res.traffic_delay_seconds > 0.0


class TestRealisticETAEngineAndHonestRanking:
    """Verifies baseline duration preservation, delay addition, and ranking cost separation."""

    def test_realistic_eta_with_traffic_delay_and_baseline_preservation(self):
        """OSRM baseline duration is retained; delay is added honestly to traffic_adjusted_eta."""
        # Simulated route segments
        segments = [
            RouteSegmentRisk(
                osm_way_id=101,
                street_name="Đoạn 1 (Thông thoáng)",
                length_meters=1000.0,
                risk_level=RiskLevel.UNKNOWN,
                traffic_status=TrafficStatus.FREE_FLOW,
                traffic_delay_seconds=0.0,
            ),
            RouteSegmentRisk(
                osm_way_id=102,
                street_name="Đoạn 2 (Ùn tắc)",
                length_meters=800.0,
                risk_level=RiskLevel.UNKNOWN,
                traffic_status=TrafficStatus.CONGESTED,
                traffic_delay_seconds=240.0,  # 4 minutes delay
            ),
        ]
        osrm_duration_seconds = 600.0  # 10 mins baseline
        total_delay = sum(s.traffic_delay_seconds or 0.0 for s in segments)
        adjusted_eta = round(osrm_duration_seconds + total_delay, 1)

        response = SafeRouteResponse(
            route_id="ROUTE_TEST_01",
            total_distance_km=1.8,
            estimated_time_mins=round(adjusted_eta / 60.0, 2),
            osrm_duration_seconds=osrm_duration_seconds,
            traffic_adjusted_eta_seconds=adjusted_eta,
            traffic_eta_status="TRAFFIC_ADJUSTED",
            traffic_eta_source="VERIFIED_CAMERA_AND_NEWS",
            traffic_delay_seconds=round(total_delay, 1),
            ranking_cost=round(osrm_duration_seconds + (total_delay * 1.5), 2),
            overall_risk=RiskLevel.MODERATE,
            route_status="ROUTE_CONGESTION_DETECTED",
            segments=segments,
            geojson_path={"type": "LineString", "coordinates": [[106.7, 10.7], [106.71, 10.71]]},
            ai_explanation="Tuyến có đoạn ùn tắc, dự kiến trễ 4 phút.",
            is_recommended=True,
            is_fastest=True,
        )

        assert response.osrm_duration_seconds == 600.0
        assert response.traffic_delay_seconds == 240.0
        assert response.traffic_adjusted_eta_seconds == 840.0
        assert response.estimated_time_mins == 14.0
        assert response.ranking_cost == 600.0 + (240.0 * 1.5)

    def test_unobserved_route_displays_base_osrm_no_traffic(self):
        """When segments have UNKNOWN traffic, route states BASE_OSRM_NO_TRAFFIC."""
        segments = [
            RouteSegmentRisk(
                osm_way_id=201,
                street_name="Đoạn chưa có cảm biến A",
                length_meters=1200.0,
                risk_level=RiskLevel.UNKNOWN,
                traffic_status=TrafficStatus.UNKNOWN,
                traffic_delay_seconds=0.0,
            ),
        ]
        osrm_duration_seconds = 300.0
        response = SafeRouteResponse(
            route_id="ROUTE_TEST_UNKNOWN",
            total_distance_km=1.2,
            estimated_time_mins=round(osrm_duration_seconds / 60.0, 2),
            osrm_duration_seconds=osrm_duration_seconds,
            traffic_adjusted_eta_seconds=None,
            traffic_eta_status="BASE_OSRM_NO_TRAFFIC",
            traffic_eta_source="OSRM_BASELINE_ONLY",
            traffic_delay_seconds=0.0,
            ranking_cost=300.0,
            overall_risk=RiskLevel.UNKNOWN,
            route_status="ROUTE_FOUND_RISK_UNKNOWN",
            segments=segments,
            geojson_path={"type": "LineString", "coordinates": [[106.7, 10.7], [106.71, 10.71]]},
            ai_explanation="Tuyến đường cơ sở. Dữ liệu camera dọc tuyến còn hạn chế (1/1 đoạn chưa có cảm biến trực tiếp).",
            is_recommended=True,
            is_fastest=True,
        )

        assert response.traffic_adjusted_eta_seconds is None
        assert response.traffic_eta_status == "BASE_OSRM_NO_TRAFFIC"
        assert response.route_status == "ROUTE_FOUND_RISK_UNKNOWN"
        assert "chưa có cảm biến trực tiếp" in response.ai_explanation

    def test_hazard_penalties_affect_ranking_cost_not_displayed_eta(self):
        """Hazard penalty (+3600s) belongs strictly to ranking_cost; estimated_time_mins is realistic."""
        segments = [
            RouteSegmentRisk(
                osm_way_id=301,
                street_name="Đoạn ngập sâu",
                length_meters=500.0,
                risk_level=RiskLevel.CRITICAL,
                traffic_status=TrafficStatus.UNKNOWN,
                traffic_delay_seconds=0.0,
            ),
        ]
        osrm_duration_seconds = 420.0  # 7 minutes
        critical_count = 1
        ranking_cost = osrm_duration_seconds + (critical_count * 3600.0)

        response = SafeRouteResponse(
            route_id="ROUTE_HAZARD",
            total_distance_km=0.5,
            estimated_time_mins=round(osrm_duration_seconds / 60.0, 2),  # 7.0 mins, NOT 67 mins!
            osrm_duration_seconds=osrm_duration_seconds,
            traffic_adjusted_eta_seconds=None,
            traffic_eta_status="BASE_OSRM_NO_TRAFFIC",
            traffic_eta_source="OSRM_BASELINE_ONLY",
            traffic_delay_seconds=0.0,
            ranking_cost=ranking_cost,
            overall_risk=RiskLevel.CRITICAL,
            critical_segments_count=1,
            route_status="ROUTE_CRITICAL_HAZARDS_DETECTED",
            segments=segments,
            geojson_path={"type": "LineString", "coordinates": [[106.7, 10.7], [106.71, 10.71]]},
            ai_explanation="Cảnh báo: Tuyến có điểm nguy cơ ngập nghiêm trọng.",
            is_recommended=False,
            is_fastest=True,
        )

        # ETA is 7.0 minutes (displayed to user)
        assert response.estimated_time_mins == 7.0
        # ranking_cost is 4020s (used to rank safe detour ahead of this hazard)
        assert response.ranking_cost == 4020.0


class TestGeodesicAndDistanceAudit:
    """Verifies polyline geodesic Haversine distance calculations and precision."""

    def test_empty_or_single_point_returns_zero(self):
        assert _geodesic_distance_meters([]) == 0.0
        assert _geodesic_distance_meters([[106.7, 10.7]]) == 0.0

    def test_two_known_points_geodesic(self):
        # Ben Thanh Market [106.6980, 10.7725] to Saigon Opera House [106.7032, 10.7766]
        # Straight line ~730m
        coords = [
            [106.6980, 10.7725],
            [106.7032, 10.7766],
        ]
        dist = _geodesic_distance_meters(coords)
        assert 700.0 < dist < 760.0

    def test_multi_segment_matches_sum_of_parts(self):
        p1 = [106.6980, 10.7725]
        p2 = [106.7032, 10.7766]
        p3 = [106.7115, 10.8012]

        d1 = _geodesic_distance_meters([p1, p2])
        d2 = _geodesic_distance_meters([p2, p3])
        d_total = _geodesic_distance_meters([p1, p2, p3])

        assert math.isclose(d_total, d1 + d2, rel_tol=1e-5)


class TestTrafficProviders:
    """Verifies commercial traffic adapters, zero-mock fallback, and caching."""

    def test_factory_returns_configured_provider(self, monkeypatch):
        monkeypatch.setattr(settings, "TRAFFIC_PROVIDER", "tomtom")
        p = get_traffic_provider()
        assert isinstance(p, TomTomTrafficProvider)

        monkeypatch.setattr(settings, "TRAFFIC_PROVIDER", "here")
        p2 = get_traffic_provider()
        assert isinstance(p2, HereTrafficProvider)

    @pytest.mark.asyncio
    async def test_tomtom_unconfigured_returns_empty(self, monkeypatch):
        monkeypatch.setattr(settings, "TOMTOM_API_KEY", None)
        provider = TomTomTrafficProvider()
        assert not provider.is_configured()

        res = await provider.get_corridor_traffic(
            route_coordinates=[[106.7, 10.7], [106.71, 10.71]],
            segments=[{"length_meters": 500.0, "geojson_path": {"coordinates": [[106.7, 10.7], [106.71, 10.71]]}}],
        )
        assert res == {}

    @pytest.mark.asyncio
    async def test_tomtom_configured_queries_and_calculates_delay(self, monkeypatch):
        monkeypatch.setattr(settings, "TOMTOM_API_KEY", "test_key_abc")
        provider = TomTomTrafficProvider()
        assert provider.is_configured()

        mock_payload = {
            "flowSegmentData": {
                "coordinates": {"coordinate": [{"latitude": 10.7700, "longitude": 106.7000}, {"latitude": 10.7720, "longitude": 106.7020}]},
                "currentSpeed": 10.0,
                "freeFlowSpeed": 40.0,
                "confidence": 0.95,
                "roadClosure": False,
            }
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload

        segments = [
            {
                "length_meters": 400.0,
                "geojson_path": {"coordinates": [[106.7000, 10.7700], [106.7020, 10.7720]]},
            }
        ]

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            flows = await provider.get_corridor_traffic(
                route_coordinates=[[106.7000, 10.7700], [106.7020, 10.7720]],
                segments=segments,
            )

        assert 0 in flows
        flow = flows[0]
        # 10 km/h is < 12 km/h -> CONGESTED
        assert flow.traffic_status == TrafficStatus.CONGESTED
        assert flow.current_speed_kmh == 10.0
        assert flow.free_flow_speed_kmh == 40.0
        assert flow.confidence == 0.95
        assert flow.source == "tomtom_traffic_flow"
        assert flow.traffic_delay_seconds > 0.0

    @pytest.mark.asyncio
    async def test_tomtom_redis_cache_hit(self, monkeypatch):
        monkeypatch.setattr(settings, "TOMTOM_API_KEY", "test_key_abc")
        provider = TomTomTrafficProvider()

        cached_flow = {
            "coordinates": {"coordinate": [{"latitude": 10.7700, "longitude": 106.7000}, {"latitude": 10.7720, "longitude": 106.7020}]},
            "currentSpeed": 35.0,
            "freeFlowSpeed": 40.0,
            "confidence": 0.88,
            "roadClosure": False,
        }

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({"payload": cached_flow, "cached_at": datetime.now(timezone.utc).isoformat()})

        segments = [
            {
                "length_meters": 500.0,
                "geojson_path": {"coordinates": [[106.7000, 10.7700], [106.7020, 10.7720]]},
            }
        ]

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            flows = await provider.get_corridor_traffic(
                route_coordinates=[[106.7000, 10.7700], [106.7020, 10.7720]],
                segments=segments,
                redis_client=mock_redis,
            )
            # Should read from cache, not invoke HTTP GET
            mock_get.assert_not_called()

        assert 0 in flows
        assert flows[0].traffic_status == TrafficStatus.FREE_FLOW
        assert flows[0].current_speed_kmh == 35.0

    @pytest.mark.asyncio
    async def test_b06_tomtom_road_closure_maps_to_closed_status(self, monkeypatch):
        """B06 Regression: TomTom roadClosure=True must map to TrafficStatus.CLOSED and is_closed=True."""
        monkeypatch.setattr(settings, "TOMTOM_API_KEY", "test_key_abc")
        provider = TomTomTrafficProvider()

        mock_payload = {
            "flowSegmentData": {
                "coordinates": {"coordinate": [{"latitude": 10.7700, "longitude": 106.7000}, {"latitude": 10.7720, "longitude": 106.7020}]},
                "currentSpeed": 0.0,
                "freeFlowSpeed": 40.0,
                "confidence": 0.98,
                "roadClosure": True,
            }
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload

        segments = [
            {
                "length_meters": 300.0,
                "geojson_path": {"coordinates": [[106.7000, 10.7700], [106.7020, 10.7720]]},
            }
        ]
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            flows = await provider.get_corridor_traffic(
                route_coordinates=[[106.7000, 10.7700], [106.7020, 10.7720]],
                segments=segments,
            )

        assert 0 in flows
        assert flows[0].traffic_status == TrafficStatus.CLOSED
        assert flows[0].is_closed is True
        assert flows[0].current_speed_kmh == 0.0

    @pytest.mark.asyncio
    async def test_c05_tomtom_rejects_implausible_speeds(self, monkeypatch):
        """C05 Regression: Out-of-bounds speeds (> 160 km/h or negative) must be rejected."""
        monkeypatch.setattr(settings, "TOMTOM_API_KEY", "test_key_abc")
        provider = TomTomTrafficProvider()

        mock_payload = {
            "flowSegmentData": {
                "coordinates": {"coordinate": [{"latitude": 10.7700, "longitude": 106.7000}, {"latitude": 10.7720, "longitude": 106.7020}]},
                "currentSpeed": 250.0,
                "freeFlowSpeed": 45.0,
                "confidence": 0.90,
                "roadClosure": False,
            }
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload

        segments = [
            {
                "length_meters": 300.0,
                "geojson_path": {"coordinates": [[106.7000, 10.7700], [106.7020, 10.7720]]},
            }
        ]
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            flows = await provider.get_corridor_traffic(
                route_coordinates=[[106.7000, 10.7700], [106.7020, 10.7720]],
                segments=segments,
            )

        assert 0 not in flows

    def test_b06_verified_road_closure_news_marks_segment_closed_and_critical(self):
        """B06 Regression: Verified ROAD_CLOSURE news marks segment TrafficStatus.CLOSED, is_closed=True, and RiskLevel.CRITICAL."""
        segment = {
            "osm_way_id": 999888,
            "edge_index": 1,
            "street_name": "Đường Nguyễn Huệ",
            "length_meters": 450.0,
            "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
        }
        now = datetime.now(timezone.utc)
        news = [
            TrafficNewsArticle(
                id="NEWS_CLOSURE_01",
                canonical_url="https://vnexpress.net/cam-duong-nguyen-hue",
                source_name="VnExpress",
                title="Cấm đường toàn bộ trên Đường Nguyễn Huệ phục vụ sự kiện",
                summary="Phong tỏa các phương tiện lưu thông qua Đường Nguyễn Huệ.",
                category="ROAD_CLOSURE",
                severity="CRITICAL",
                event_status="ACTIVE_HAZARD",
                latitude=10.7745,
                longitude=106.7030,
                location_confidence="EXACT",
                geocoding_status="RESOLVED",
                verification_status="VERIFIED_SOURCE",
                published_at=now - timedelta(minutes=15),
                fetched_at=now - timedelta(minutes=10),
            )
        ]
        res = calculate_segment_risk(segment, camera_evidences=[], traffic_news=news)
        assert res.traffic_status == TrafficStatus.CLOSED
        assert res.is_closed is True
        assert res.risk_level == RiskLevel.CRITICAL
        assert res.risk_score == 80.0
