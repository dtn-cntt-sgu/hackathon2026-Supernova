"""
Integration and End-to-End Tests for Phase 5:
- FastAPI REST Endpoints (Health, Cameras, Images, Dynamic Routing Search, Simulation Trigger).
- WebSocket Real-Time Alert Broadcasting (/ws/alerts).
- FastMCP Tool Provider and AI Explanation Synthesis.
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas.contracts import (
    CameraEvidence,
    DataSourceStatus,
    RiskLevel,
    RouteSegmentRisk,
    SafeRouteResponse,
    WeatherTideSignal,
    WebSocketAlertMessage,
    build_camera_alert,
)
from backend.app.services.mcp_explanation import (
    build_template_explanation,
    extract_route_evidence_summary,
    generate_route_explanation,
    get_weather_tide_context,
)


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient fixture with lifespan startup and shutdown."""
    with TestClient(app) as test_client:
        yield test_client


class TestHealthAndCamerasAPI:
    """Verifies infrastructure health and camera surveillance endpoints."""

    def test_health_endpoint(self, client: TestClient):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded")
        assert "database" in data
        assert "redis" in data
        assert "osrm" in data
        assert "last_camera_update" in data

    def test_list_cameras_endpoint(self, client: TestClient):
        response = client.get("/api/v1/cameras")
        assert response.status_code == 200
        cameras = response.json()
        assert isinstance(cameras, list)
        assert len(cameras) >= 15, f"Expected at least 15 cameras, got {len(cameras)}"

        # Validate schema of each camera
        for cam in cameras:
            ev = CameraEvidence.model_validate(cam)
            assert ev.cam_id != ""
            assert ev.lat > 0.0 and ev.lng > 0.0
            assert ev.risk_level in (
                RiskLevel.SAFE,
                RiskLevel.MODERATE,
                RiskLevel.CRITICAL,
                RiskLevel.UNKNOWN,
                RiskLevel.INSUFFICIENT_EVIDENCE,
            )
            assert ev.source_status in (
                DataSourceStatus.LIVE,
                DataSourceStatus.STALE,
                DataSourceStatus.SIMULATED,
            )

    def test_list_cameras_district_filter(self, client: TestClient):
        response = client.get("/api/v1/cameras?district=Quận 1")
        assert response.status_code == 200
        cameras = response.json()
        assert isinstance(cameras, list)
        for cam in cameras:
            assert "Quận 1" in (cam.get("district") or "")

    def test_camera_image_endpoint(self, client: TestClient):
        # Zero-mock: When camera image is not on disk, returns 404 CAMERA_IMAGE_UNAVAILABLE
        cam_id = "56de42f611f398ec0c48127d"
        response = client.get(f"/api/v1/cameras/{cam_id}/image")
        assert response.status_code in (200, 404)
        if response.status_code == 404:
            assert response.json()["detail"]["code"] == "CAMERA_IMAGE_UNAVAILABLE"

    def test_camera_image_not_found(self, client: TestClient):
        # Non-existent camera returns 404 CAMERA_NOT_FOUND
        response = client.get("/api/v1/cameras/non_existent_camera_id_12345/image")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "CAMERA_NOT_FOUND"


class TestDynamicRoutingAPI:
    """Verifies route search and Pydantic contract compliance."""

    def test_search_safe_route_valid_hcm(self, client: TestClient):
        payload = {
            "origin": {"lat": 10.7800, "lng": 106.7000},
            "destination": {"lat": 10.8100, "lng": 106.7300},
        }
        response = client.post("/api/v1/routes/search", json=payload)
        assert response.status_code == 200

        data = response.json()
        route = SafeRouteResponse.model_validate(data)

        # Core assertions on SafeRouteResponse
        assert route.route_id != ""
        assert route.total_distance_km > 0.0
        assert route.estimated_time_mins > 0.0
        assert route.overall_risk in (
            RiskLevel.SAFE,
            RiskLevel.MODERATE,
            RiskLevel.CRITICAL,
            RiskLevel.UNKNOWN,
            RiskLevel.INSUFFICIENT_EVIDENCE,
        )
        assert len(route.segments) > 0

        # AI explanation must be populated and non-empty
        assert isinstance(route.ai_explanation, str)
        assert len(route.ai_explanation.strip()) > 10

        # Alternative routes should be evaluated
        assert isinstance(route.alternative_routes, list)

    def test_search_safe_route_invalid_coordinates(self, client: TestClient):
        # Out-of-bounds latitude > 90.0
        payload = {
            "origin": {"lat": 999.0, "lng": 106.7000},
            "destination": {"lat": 10.8100, "lng": 106.7300},
        }
        response = client.post("/api/v1/routes/search", json=payload)
        assert response.status_code == 422

    def test_search_safe_route_transport_mode_validation(self, client: TestClient):
        # C07: transport_mode must accept 'car' or 'motorcycle' and reject invalid modes with 422
        bad_payload = {
            "origin": {"lat": 10.7800, "lng": 106.7000},
            "destination": {"lat": 10.8100, "lng": 106.7300},
            "transport_mode": "helicopter",
        }
        res_bad = client.post("/api/v1/routes/search", json=bad_payload)
        assert res_bad.status_code == 422

    def test_rate_limiting_enforcement_when_enabled(self, client: TestClient):
        # R07: Verify rate limiter triggers 429 when limit is exceeded
        from backend.app.core.config import settings

        orig_limit = settings.RATE_LIMIT_PLACES_PER_MINUTE
        settings.RATE_LIMIT_PLACES_PER_MINUTE = 2
        try:
            headers = {"X-Test-Enforce-Rate-Limit": "1", "X-Forwarded-For": "198.51.100.77"}
            r1 = client.get("/api/v1/places/search?q=Ben+Thanh", headers=headers)
            r2 = client.get("/api/v1/places/search?q=Ben+Thanh", headers=headers)
            r3 = client.get("/api/v1/places/search?q=Ben+Thanh", headers=headers)
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert r3.status_code == 429
            assert r3.json()["detail"]["code"] == "RATE_LIMIT_EXCEEDED"
        finally:
            settings.RATE_LIMIT_PLACES_PER_MINUTE = orig_limit


class TestFloodSimulationAndRerouting:
    """
    Zero-Mock Verification:
    Verifies that fake flood simulation endpoints have been removed from the product router
    to prevent deceptive 'pass ảo' states.
    """

    def test_simulation_endpoint_is_removed(self, client: TestClient):
        cam_id = "5d8cd4ee766c880017188946"
        res = client.post(
            "/api/v1/simulation/trigger-flood",
            json={
                "cam_id": cam_id,
                "enable": True,
                "flood_ratio": 0.50,
            },
        )
        # In zero-mock runtime, simulation endpoint is strictly forbidden and returns 404
        assert res.status_code == 404


class TestWebSocketAlerts:
    """Verifies real-time push notification over WebSockets."""

    def test_websocket_connection_and_heartbeat(self, client: TestClient):
        with client.websocket_connect("/ws/alerts") as ws:
            # 1. Receive connection greeting
            greeting = ws.receive_json()
            assert greeting.get("type") == "CONNECTION_ESTABLISHED"
            assert greeting.get("event_id") is not None

            # 2. Heartbeat ping-pong
            ws.send_text("ping")
            pong = ws.receive_text()
            assert pong == "pong"

    def test_build_camera_alert_conforms_to_websocket_contract(self):
        # B01: Verify build_camera_alert constructs a valid WebSocketAlertMessage without raising NameError
        now = datetime.now(timezone.utc)
        ev = CameraEvidence(
            cam_id="cam_b01_test",
            code="TTH 201",
            name="Nguyễn Hữu Cảnh - Cầu vượt",
            district="Quận Bình Thạnh",
            lat=10.7981,
            lng=106.7186,
            image_url="/api/v1/cameras/cam_b01_test/image",
            has_image=True,
            vehicle_count=18,
            traffic_density_score=0.45,
            flood_ratio=0.38,
            risk_level=RiskLevel.CRITICAL,
            source_status=DataSourceStatus.LIVE,
            freshness_status="LIVE_VERIFIED",
            updated_at=now,
            captured_at=now,
        )
        alert_msg = build_camera_alert(ev, now=now)
        assert isinstance(alert_msg, WebSocketAlertMessage)
        dumped = alert_msg.model_dump(mode="json")
        validated = WebSocketAlertMessage.model_validate(dumped)
        assert validated.type == "CRITICAL_FLOOD_ALERT"
        assert validated.source.startswith("camera_vision:")
        assert validated.severity == "CRITICAL"
        assert validated.risk_level == RiskLevel.CRITICAL
        assert validated.cam_id == "cam_b01_test"
        assert validated.flood_ratio == pytest.approx(0.38)
        assert validated.expiry is not None and validated.expiry > validated.observed_at


class TestMCPExplanationModule:
    """Verifies FastMCP tools and explanation synthesis."""

    def test_extract_route_evidence_summary(self):
        c = CameraEvidence(
            cam_id="cam_test_1",
            code="TTH 99",
            name="Giao lộ A",
            district="Quận 1",
            lat=10.77,
            lng=106.69,
            image_url="/img",
            vehicle_count=35,
            traffic_density_score=0.6,
            flood_ratio=0.10,
            risk_level=RiskLevel.SAFE,
            source_status=DataSourceStatus.LIVE,
            updated_at=datetime.now(timezone.utc),
        )
        s = RouteSegmentRisk(
            osm_way_id=999,
            street_name="Đường Lê Duẩn",
            length_meters=500.0,
            risk_score=25.0,
            risk_level=RiskLevel.SAFE,
            evidence_cameras=[c],
        )
        r = SafeRouteResponse(
            route_id="r-test-1",
            total_distance_km=3.2,
            estimated_time_mins=8.5,
            overall_risk=RiskLevel.SAFE,
            geojson_path={"type": "LineString", "coordinates": []},
            segments=[s],
            ai_explanation="",
        )

        summary = extract_route_evidence_summary(r)
        assert summary["route_id"] == "r-test-1"
        assert summary["total_distance_km"] == 3.2
        assert len(summary["cameras"]) == 1
        assert summary["cameras"][0]["code"] == "TTH 99"

    @pytest.mark.asyncio
    async def test_get_weather_tide_context_mcp(self):
        context = await get_weather_tide_context()
        assert "rain_mm_per_hour" in context
        assert "tide_level_meters" in context
        assert "is_high_tide_alert" in context

    @pytest.mark.asyncio
    async def test_generate_route_explanation_fallback(self):
        c_flood = CameraEvidence(
            cam_id="cam_flood",
            code="TTH 145",
            name="Nguyễn Hữu Cảnh",
            district="Quận Bình Thạnh",
            lat=10.79,
            lng=106.71,
            image_url="/img",
            vehicle_count=52,
            traffic_density_score=0.8,
            flood_ratio=0.45,
            risk_level=RiskLevel.CRITICAL,
            source_status=DataSourceStatus.LIVE,
            updated_at=datetime.now(timezone.utc),
        )
        s_bad = RouteSegmentRisk(
            osm_way_id=1,
            street_name="Nguyễn Hữu Cảnh",
            length_meters=400.0,
            risk_score=85.0,
            risk_level=RiskLevel.CRITICAL,
            evidence_cameras=[c_flood],
        )
        s_good = RouteSegmentRisk(
            osm_way_id=2,
            street_name="Điện Biên Phủ",
            length_meters=500.0,
            risk_score=15.0,
            risk_level=RiskLevel.SAFE,
            evidence_cameras=[],
        )
        r_rec = SafeRouteResponse(
            route_id="r-good",
            total_distance_km=5.2,
            estimated_time_mins=16.0,
            overall_risk=RiskLevel.SAFE,
            geojson_path={"type": "LineString", "coordinates": []},
            segments=[s_good],
            ai_explanation="",
        )
        r_alt = SafeRouteResponse(
            route_id="r-bad",
            total_distance_km=4.0,
            estimated_time_mins=72.0,
            overall_risk=RiskLevel.CRITICAL,
            geojson_path={"type": "LineString", "coordinates": []},
            segments=[s_bad],
            ai_explanation="",
        )

        weather = WeatherTideSignal(
            rain_mm_per_hour=35.0,
            tide_level_meters=1.70,
            is_high_tide_alert=True,
            timestamp=datetime.now(timezone.utc),
        )

        explanation = await generate_route_explanation(r_rec, [r_alt], weather=weather)
        assert isinstance(explanation, str)
        assert "Điện Biên Phủ" in explanation
        assert "45%" not in explanation  # camera has no verified routing provenance
        assert "52 phương tiện" not in explanation  # a count alone is not congestion
        assert "an toàn tuyệt đối" not in explanation

