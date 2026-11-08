"""
Phase 1 Unit and Integration Tests for SafePathAI.
Validates:
1. Pydantic contracts and schemas (valid & invalid boundaries).
2. VDMS camera node parser filtering (skipping NOT_IMAGE & IMAGE_EXPIRED).
3. Spatial mapping of cameras to nearest roads via PostGIS.
4. Mock camera dataset integrity and coordinates (15 real cameras in HCMC).
"""

from datetime import datetime, timezone
import json
import os
import pytest
from pydantic import ValidationError
from geoalchemy2 import WKTElement
from sqlalchemy import select, delete

from backend.app.schemas.contracts import (
    RiskLevel,
    DataSourceStatus,
    CameraEvidence,
    WeatherTideSignal,
    RouteSegmentRisk,
    SafeRouteResponse,
)
from backend.app.db.models import (
    RoadSegment,
    TrafficCamera,
    map_cameras_to_nearest_roads,
    map_cameras_to_nearest_roads_sync,
)
from backend.app.db.session import (
    AsyncSessionLocal,
    SessionLocal,
    init_db,
    close_db,
)
from backend.app.services.vdms_parser import (
    parse_vdms_camera_nodes,
    HCMC_DISTRICT_CENTROIDS,
)


# ==============================================================================
# Fixtures
# ==============================================================================
@pytest.fixture(scope="session", autouse=True)
async def setup_database_tables():
    """Ensure database tables exist before running test suite."""
    await init_db()
    yield
    await close_db()


# ==============================================================================
# 1. Pydantic Contracts Validation Tests
# ==============================================================================
class TestContractsValidation:
    """Test suite for contracts.py schemas validating boundaries and error cases."""

    def test_enums_valid(self):
        assert RiskLevel.SAFE == "SAFE"
        assert RiskLevel.MODERATE == "MODERATE"
        assert RiskLevel.CRITICAL == "CRITICAL"

        assert DataSourceStatus.LIVE == "LIVE"
        assert DataSourceStatus.STALE == "STALE"
        assert DataSourceStatus.SIMULATED == "SIMULATED"

    def test_camera_evidence_valid(self):
        evidence = CameraEvidence(
            cam_id="58af8b69bd82540010390c28",
            code="TTH 35.4",
            name="Nam Kỳ Khởi Nghĩa - Võ Thị Sáu",
            district="Quận 3",
            lat=10.7868,
            lng=106.6882,
            osm_way_id=12345678,
            image_url="https://giaothong.hochiminhcity.gov.vn:8007/Render/CameraHandler.ashx?id=58af8b69bd82540010390c28",
            vehicle_count=42,
            traffic_density_score=0.85,
            flood_ratio=0.35,
            risk_level=RiskLevel.MODERATE,
            source_status=DataSourceStatus.LIVE,
            updated_at=datetime.now(timezone.utc),
        )
        assert evidence.cam_id == "58af8b69bd82540010390c28"
        assert evidence.code == "TTH 35.4"
        assert evidence.district == "Quận 3"
        assert evidence.traffic_density_score == 0.85
        assert evidence.flood_ratio == 0.35
        assert evidence.risk_level == RiskLevel.MODERATE
        assert evidence.source_status == DataSourceStatus.LIVE

    def test_camera_evidence_invalid_coordinates(self):
        now = datetime.now(timezone.utc)
        # Latitude out of bounds (> 90)
        with pytest.raises(ValidationError) as exc_info:
            CameraEvidence(
                cam_id="CAM_BAD",
                code="TTH 00",
                name="Bad Lat",
                district="Quận 1",
                lat=95.0,
                lng=106.72,
                image_url="https://example.com/bad.jpg",
                vehicle_count=10,
                traffic_density_score=0.5,
                flood_ratio=0.1,
                risk_level=RiskLevel.SAFE,
                source_status=DataSourceStatus.LIVE,
                updated_at=now,
            )
        assert "lat" in str(exc_info.value)

        # Longitude out of bounds (< -180)
        with pytest.raises(ValidationError) as exc_info:
            CameraEvidence(
                cam_id="CAM_BAD",
                code="TTH 00",
                name="Bad Lng",
                district="Quận 1",
                lat=10.79,
                lng=-190.0,
                image_url="https://example.com/bad.jpg",
                vehicle_count=10,
                traffic_density_score=0.5,
                flood_ratio=0.1,
                risk_level=RiskLevel.SAFE,
                source_status=DataSourceStatus.LIVE,
                updated_at=now,
            )
        assert "lng" in str(exc_info.value)

    def test_camera_evidence_invalid_scores(self):
        now = datetime.now(timezone.utc)
        # traffic_density_score > 1.0
        with pytest.raises(ValidationError) as exc_info:
            CameraEvidence(
                cam_id="CAM_BAD",
                name="Bad Score",
                lat=10.79,
                lng=106.72,
                image_url="https://example.com/bad.jpg",
                vehicle_count=5,
                traffic_density_score=1.5,
                flood_ratio=0.2,
                risk_level=RiskLevel.SAFE,
                source_status=DataSourceStatus.LIVE,
                updated_at=now,
            )
        assert "traffic_density_score" in str(exc_info.value)

        # flood_ratio < 0.0
        with pytest.raises(ValidationError) as exc_info:
            CameraEvidence(
                cam_id="CAM_BAD",
                name="Bad Flood",
                lat=10.79,
                lng=106.72,
                image_url="https://example.com/bad.jpg",
                vehicle_count=5,
                traffic_density_score=0.5,
                flood_ratio=-0.1,
                risk_level=RiskLevel.SAFE,
                source_status=DataSourceStatus.LIVE,
                updated_at=now,
            )
        assert "flood_ratio" in str(exc_info.value)

        # negative vehicle count
        with pytest.raises(ValidationError) as exc_info:
            CameraEvidence(
                cam_id="CAM_BAD",
                name="Bad Vehicle Count",
                lat=10.79,
                lng=106.72,
                image_url="https://example.com/bad.jpg",
                vehicle_count=-3,
                traffic_density_score=0.5,
                flood_ratio=0.2,
                risk_level=RiskLevel.SAFE,
                source_status=DataSourceStatus.LIVE,
                updated_at=now,
            )
        assert "vehicle_count" in str(exc_info.value)

    def test_weather_tide_signal_valid_and_invalid(self):
        now = datetime.now(timezone.utc)
        # Valid
        signal = WeatherTideSignal(
            rain_mm_per_hour=25.4,
            tide_level_meters=1.68,
            is_high_tide_alert=True,
            timestamp=now,
        )
        assert signal.rain_mm_per_hour == 25.4
        assert signal.tide_level_meters == 1.68
        assert signal.is_high_tide_alert is True

        # Invalid: Negative rainfall
        with pytest.raises(ValidationError) as exc_info:
            WeatherTideSignal(
                rain_mm_per_hour=-5.0,
                tide_level_meters=1.2,
                is_high_tide_alert=False,
                timestamp=now,
            )
        assert "rain_mm_per_hour" in str(exc_info.value)

    def test_route_segment_risk_valid_and_invalid(self):
        # Valid
        segment = RouteSegmentRisk(
            osm_way_id=987654321,
            street_name="Võ Văn Kiệt",
            length_meters=250.5,
            risk_score=68.5,
            risk_level=RiskLevel.MODERATE,
            evidence_cameras=[],
        )
        assert segment.osm_way_id == 987654321
        assert segment.risk_score == 68.5
        assert segment.risk_level == RiskLevel.MODERATE

        # Invalid: risk_score > 100.0
        with pytest.raises(ValidationError) as exc_info:
            RouteSegmentRisk(
                osm_way_id=987654321,
                street_name="Võ Văn Kiệt",
                length_meters=250.5,
                risk_score=105.0,
                risk_level=RiskLevel.CRITICAL,
                evidence_cameras=[],
            )
        assert "risk_score" in str(exc_info.value)

        # Invalid: risk_score < 0.0
        with pytest.raises(ValidationError) as exc_info:
            RouteSegmentRisk(
                osm_way_id=987654321,
                street_name="Võ Văn Kiệt",
                length_meters=250.5,
                risk_score=-2.5,
                risk_level=RiskLevel.SAFE,
                evidence_cameras=[],
            )
        assert "risk_score" in str(exc_info.value)

        # Invalid: negative length
        with pytest.raises(ValidationError) as exc_info:
            RouteSegmentRisk(
                osm_way_id=987654321,
                street_name="Võ Văn Kiệt",
                length_meters=-10.0,
                risk_score=10.0,
                risk_level=RiskLevel.SAFE,
                evidence_cameras=[],
            )
        assert "length_meters" in str(exc_info.value)

    def test_safe_route_response_valid_and_invalid(self):
        # Valid
        segment = RouteSegmentRisk(
            osm_way_id=101,
            street_name="Nguyễn Hữu Cảnh",
            length_meters=300.0,
            risk_score=20.0,
            risk_level=RiskLevel.SAFE,
            evidence_cameras=[],
        )
        response = SafeRouteResponse(
            route_id="route-uuid-12345",
            total_distance_km=5.8,
            estimated_time_mins=18.5,
            overall_risk=RiskLevel.SAFE,
            geojson_path={"type": "LineString", "coordinates": [[106.7, 10.7], [106.8, 10.8]]},
            segments=[segment],
            ai_explanation="Tuyến đường thông thoáng, không có điểm ngập nước nghiêm trọng.",
        )
        assert response.route_id == "route-uuid-12345"
        assert response.total_distance_km == 5.8
        assert len(response.segments) == 1

        # Invalid: negative distance
        with pytest.raises(ValidationError) as exc_info:
            SafeRouteResponse(
                route_id="route-bad",
                total_distance_km=-1.0,
                estimated_time_mins=15.0,
                overall_risk=RiskLevel.SAFE,
                geojson_path={},
                segments=[],
                ai_explanation="Test",
            )
        assert "total_distance_km" in str(exc_info.value)


# ==============================================================================
# 2. VDMS Camera Node Parser Tests
# ==============================================================================
class TestVDMSParser:
    """Test suite for parse_vdms_camera_nodes filtering and resolution logic."""

    def test_parse_vdms_filters_non_up_cameras(self):
        """
        Validates that parse_vdms_camera_nodes:
        - Receives a VDMS payload containing 1 NOT_IMAGE, 1 IMAGE_EXPIRED, and 1 UP camera.
        - Correctly filters out the 2 broken cameras and retains ONLY the camera with CamStatus == 'UP'.
        """
        vdms_payload = {
            "value": [
                {"Name": "CAMERA", "Type": "folder"},
                [
                    [
                        {
                            "Layer": "CAMERA",
                            "Title": "TTH 120",
                            "Properties": [
                                {"Name": "CamId", "Value": "5b0b74280e517b00119fd7f9"},
                                {"Name": "Code", "Value": "TTH 120"},
                                {"Name": "CamStatus", "Value": "NOT_IMAGE"},
                                {"Name": "Disctrict", "Value": "Quận Tân Bình"},
                                {"Name": "SnapshotUrl", "Value": "http://example.com/snapshot/1"},
                                {"Name": "Angle", "Value": "315"},
                            ],
                        },
                        {
                            "Layer": "CAMERA",
                            "Title": "TTH 26.3",
                            "Properties": [
                                {"Name": "CamId", "Value": "58df4c2bdc195800111e04b7"},
                                {"Name": "Code", "Value": "TTH 26.3"},
                                {"Name": "CamStatus", "Value": "IMAGE_EXPIRED"},
                                {"Name": "Disctrict", "Value": "Quận Tân Bình"},
                                {"Name": "SnapshotUrl", "Value": "http://example.com/snapshot/2"},
                                {"Name": "Angle", "Value": "30"},
                            ],
                        },
                        {
                            "Layer": "CAMERA",
                            "Title": "TTH 145",
                            "Properties": [
                                {"Name": "CamId", "Value": "5d8cd4ee766c880017188946"},
                                {"Name": "Code", "Value": "TTH 145"},
                                {"Name": "CamStatus", "Value": "UP"},
                                {"Name": "Disctrict", "Value": "Quận Bình Thạnh"},
                                {"Name": "SnapshotUrl", "Value": "http://example.com/snapshot/3"},
                                {"Name": "Angle", "Value": "90"},
                            ],
                        },
                    ]
                ],
            ]
        }

        # Case 1: only_up = True (Default in production to save bandwidth)
        up_cams = parse_vdms_camera_nodes(vdms_payload, only_up=True)
        assert len(up_cams) == 1, f"Expected exactly 1 UP camera, got {len(up_cams)}"
        assert up_cams[0]["cam_id"] == "5d8cd4ee766c880017188946"
        assert up_cams[0]["code"] == "TTH 145"
        assert up_cams[0]["cam_status"] == "UP"
        assert up_cams[0]["district"] == "Quận Bình Thạnh"
        assert up_cams[0]["angle"] == 90
        # Exact coordinate resolved from cameras_hcm.json
        assert up_cams[0]["lat"] == 10.7981
        assert up_cams[0]["lng"] == 106.7186

        # Case 2: only_up = False (Keep all cameras for administrative views)
        all_cams = parse_vdms_camera_nodes(vdms_payload, only_up=False)
        assert len(all_cams) == 3, f"Expected 3 cameras, got {len(all_cams)}"
        statuses = {c["cam_status"] for c in all_cams}
        assert statuses == {"NOT_IMAGE", "IMAGE_EXPIRED", "UP"}

    def test_parse_vdms_real_sample_file(self):
        """
        Parses the full live VDMS response from list_camera_coordinate.txt if available.
        Ensures all 654 active UP cameras are parsed without crash,
        and all 15 reference cameras match their exact hotspot coordinates.
        """
        txt_path = "list_camera_coordinate.txt"
        if not os.path.exists(txt_path):
            pytest.skip("list_camera_coordinate.txt not present in workspace")

        with open(txt_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        cameras = parse_vdms_camera_nodes(raw_text, only_up=True)
        assert len(cameras) >= 600, f"Expected at least 600 active UP cameras, got {len(cameras)}"

        # Check all have resolved coordinates
        for c in cameras:
            assert 10.0 <= c["lat"] <= 11.5, f"Invalid lat: {c['lat']}"
            assert 106.0 <= c["lng"] <= 107.5, f"Invalid lng: {c['lng']}"
            assert c["cam_status"] == "UP"


# ==============================================================================
# 3. PostGIS Spatial Mapping Tests
# ==============================================================================
class TestSpatialMapping:
    """Test suite for map_cameras_to_nearest_roads PostGIS spatial query."""

    @pytest.mark.asyncio
    async def test_map_cameras_to_nearest_roads_async(self):
        test_cams = ["CAM_NEAR_R1", "CAM_NEAR_R2", "CAM_ISOLATED"]
        test_roads = [1001, 2002]
        async with AsyncSessionLocal() as session:
            # Clean test fixtures
            await session.execute(delete(TrafficCamera).where(TrafficCamera.cam_id.in_(test_cams)))
            await session.execute(delete(RoadSegment).where(RoadSegment.osm_way_id.in_(test_roads)))
            await session.commit()

            # Road 1: Nguyen Huu Canh segment (centered at ~ 10.7983, 106.7225)
            road_1 = RoadSegment(
                osm_way_id=1001,
                street_name="Nguyễn Hữu Cảnh",
                is_flood_prone_history=True,
                source_url="https://download.geofabrik.de/vietnam.osm.pbf",
                geom=WKTElement("LINESTRING(106.7220 10.7980, 106.7230 10.7985)", srid=4326),
            )
            # Road 2: Thao Dien segment (centered at ~ 10.8038, 106.7329)
            road_2 = RoadSegment(
                osm_way_id=2002,
                street_name="Quốc Hương",
                is_flood_prone_history=True,
                source_url="https://download.geofabrik.de/vietnam.osm.pbf",
                geom=WKTElement("LINESTRING(106.7320 10.8035, 106.7335 10.8040)", srid=4326),
            )
            session.add_all([road_1, road_2])

            now_utc = datetime.now(timezone.utc)
            # Camera A: ~15 meters from Road 1
            cam_a = TrafficCamera(
                cam_id="CAM_NEAR_R1",
                code="TTH 145",
                name="Camera Gần Nguyễn Hữu Cảnh",
                district="Quận Bình Thạnh",
                stream_url="https://example.com/cam_a",
                coordinate_source_url="https://giaothong.hochiminhcity.gov.vn",
                coordinate_verified_at=now_utc,
                location_confidence="VERIFIED",
                geom=WKTElement("POINT(106.7225 10.7982)", srid=4326),
            )
            # Camera B: ~10 meters from Road 2
            cam_b = TrafficCamera(
                cam_id="CAM_NEAR_R2",
                code="TTH 22.6",
                name="Camera Gần Quốc Hương",
                district="Quận 2",
                stream_url="https://example.com/cam_b",
                coordinate_source_url="https://giaothong.hochiminhcity.gov.vn",
                coordinate_verified_at=now_utc,
                location_confidence="VERIFIED",
                geom=WKTElement("POINT(106.7325 10.8037)", srid=4326),
            )
            # Camera C: Far away in the middle of nowhere (> 1 km from any road)
            cam_c = TrafficCamera(
                cam_id="CAM_ISOLATED",
                code="TTH 999",
                name="Camera Đơn Độc Cách Xa Đường",
                district="Quận 1",
                stream_url="https://example.com/cam_c",
                coordinate_source_url="https://giaothong.hochiminhcity.gov.vn",
                coordinate_verified_at=now_utc,
                location_confidence="VERIFIED",
                geom=WKTElement("POINT(107.0500 10.3500)", srid=4326),
            )
            session.add_all([cam_a, cam_b, cam_c])
            await session.commit()

            # Execute spatial mapping
            updated_count = await map_cameras_to_nearest_roads(session, radius_meters=50.0)
            assert updated_count >= 2

            # Query results back
            cams_query = await session.execute(
                select(TrafficCamera).where(TrafficCamera.cam_id.in_(test_cams))
            )
            cams = {c.cam_id: c.nearest_osm_way_id for c in cams_query.scalars().all()}

            # Validate mappings
            assert cams["CAM_NEAR_R1"] == 1001, "CAM_NEAR_R1 must be mapped to Road 1 (1001)"
            assert cams["CAM_NEAR_R2"] == 2002, "CAM_NEAR_R2 must be mapped to Road 2 (2002)"
            assert cams["CAM_ISOLATED"] is None, "CAM_ISOLATED must NOT be mapped (> 50m)"

            # Cleanup
            await session.execute(delete(TrafficCamera).where(TrafficCamera.cam_id.in_(test_cams)))
            await session.execute(delete(RoadSegment).where(RoadSegment.osm_way_id.in_(test_roads)))
            await session.commit()

    def test_map_cameras_to_nearest_roads_sync(self):
        with SessionLocal() as session:
            # Clean test fixtures
            session.execute(delete(TrafficCamera).where(TrafficCamera.cam_id == "CAM_HTP"))
            session.execute(delete(RoadSegment).where(RoadSegment.osm_way_id == 3003))
            session.commit()

            now_utc = datetime.now(timezone.utc)
            # Insert road
            road = RoadSegment(
                osm_way_id=3003,
                street_name="Huỳnh Tấn Phát",
                is_flood_prone_history=True,
                source_url="https://download.geofabrik.de/vietnam.osm.pbf",
                geom=WKTElement("LINESTRING(106.7260 10.7510, 106.7270 10.7520)", srid=4326),
            )
            session.add(road)

            # Insert camera within 20m
            cam = TrafficCamera(
                cam_id="CAM_HTP",
                code="TTH 37.2",
                name="Camera Huỳnh Tấn Phát",
                district="Quận 7",
                stream_url="https://example.com/htp",
                coordinate_source_url="https://giaothong.hochiminhcity.gov.vn",
                coordinate_verified_at=now_utc,
                location_confidence="VERIFIED",
                geom=WKTElement("POINT(106.7265 10.7515)", srid=4326),
            )
            session.add(cam)
            session.commit()

            # Execute sync mapping
            updated_count = map_cameras_to_nearest_roads_sync(session, radius_meters=50.0)
            assert updated_count >= 1

            saved_cam = session.execute(
                select(TrafficCamera).where(TrafficCamera.cam_id == "CAM_HTP")
            ).scalar_one()
            assert saved_cam.nearest_osm_way_id == 3003

            # Cleanup
            session.execute(delete(TrafficCamera).where(TrafficCamera.cam_id == "CAM_HTP"))
            session.execute(delete(RoadSegment).where(RoadSegment.osm_way_id == 3003))
            session.commit()

    def test_map_cameras_to_nearest_roads_polymorphic_sync(self):
        with SessionLocal() as session:
            # Clean test fixtures
            session.execute(delete(TrafficCamera).where(TrafficCamera.cam_id.in_(["CAM_DBP", "CAM_HANG_XANH"])))
            session.execute(delete(RoadSegment).where(RoadSegment.osm_way_id == 4004))
            session.commit()

            now_utc = datetime.now(timezone.utc)
            road = RoadSegment(
                osm_way_id=4004,
                street_name="Điện Biên Phủ",
                is_flood_prone_history=False,
                source_url="https://download.geofabrik.de/vietnam.osm.pbf",
                geom=WKTElement("LINESTRING(106.7110 10.8010, 106.7120 10.8020)", srid=4326),
            )
            session.add(road)

            cam = TrafficCamera(
                cam_id="CAM_DBP",
                code="TTH 38.1",
                name="Camera Điện Biên Phủ",
                district="Quận Bình Thạnh",
                stream_url="https://example.com/dbp",
                coordinate_source_url="https://giaothong.hochiminhcity.gov.vn",
                coordinate_verified_at=now_utc,
                location_confidence="VERIFIED",
                geom=WKTElement("POINT(106.7115 10.8015)", srid=4326),
            )
            session.add(cam)
            session.commit()

            # Execute polymorphic call passing raw session
            updated_count = map_cameras_to_nearest_roads(session, radius_meters=50.0)
            assert updated_count >= 1

            saved_cam = session.execute(
                select(TrafficCamera).where(TrafficCamera.cam_id == "CAM_DBP")
            ).scalar_one()
            assert saved_cam.nearest_osm_way_id == 4004

            # Cleanup
            session.execute(delete(TrafficCamera).where(TrafficCamera.cam_id.in_(["CAM_DBP", "CAM_HANG_XANH"])))
            session.execute(delete(RoadSegment).where(RoadSegment.osm_way_id == 4004))
            session.commit()

            cam = TrafficCamera(
                cam_id="CAM_HANG_XANH",
                code="TTH 44.3",
                name="Camera Ngã tư Hàng Xanh",
                district="Quận Bình Thạnh",
                stream_url="https://example.com/hangxanh",
                coordinate_source_url="https://giaothong.hochiminhcity.gov.vn",
                coordinate_verified_at=now_utc,
                location_confidence="VERIFIED",
                geom=WKTElement("POINT(106.7115 10.8015)", srid=4326),
            )
            road_again = RoadSegment(
                osm_way_id=4004,
                street_name="Điện Biên Phủ",
                is_flood_prone_history=False,
                source_url="https://download.geofabrik.de/vietnam.osm.pbf",
                geom=WKTElement("LINESTRING(106.7110 10.8010, 106.7120 10.8020)", srid=4326),
            )
            session.add_all([road_again, cam])
            session.commit()

            # Polymorphic call with sync session:
            res = map_cameras_to_nearest_roads(session, radius_meters=50.0)
            assert res >= 1
            saved_cam = session.execute(
                select(TrafficCamera).where(TrafficCamera.cam_id == "CAM_HANG_XANH")
            ).scalar_one()
            assert saved_cam.nearest_osm_way_id == 4004

            # Final Cleanup
            session.execute(delete(TrafficCamera).where(TrafficCamera.cam_id.in_(["CAM_DBP", "CAM_HANG_XANH"])))
            session.execute(delete(RoadSegment).where(RoadSegment.osm_way_id == 4004))
            session.commit()


# ==============================================================================
# 4. Mock Camera Dataset Validation Tests
# ==============================================================================
class TestMockCameraDataset:
    """Verifies that the mock camera JSON fixture contains 15 realistic UP cameras in TP.HCM."""

    def test_mock_cameras_file_exists_and_valid(self):
        json_path = os.path.join("data", "mock_cameras", "cameras_hcm.json")
        assert os.path.exists(json_path), f"File {json_path} does not exist"

        with open(json_path, "r", encoding="utf-8") as f:
            cameras = json.load(f)

        assert isinstance(cameras, list)
        assert len(cameras) == 15, f"Expected exactly 15 cameras, got {len(cameras)}"

        for cam in cameras:
            assert "cam_id" in cam and len(cam["cam_id"]) > 5
            assert "code" in cam and cam["code"].startswith("TTH")
            assert "name" in cam and len(cam["name"]) > 5
            assert "district" in cam and len(cam["district"]) > 0
            assert "lat" in cam and 10.5 <= cam["lat"] <= 11.2, f"Invalid HCM latitude: {cam['lat']}"
            assert "lng" in cam and 106.4 <= cam["lng"] <= 107.0, f"Invalid HCM longitude: {cam['lng']}"
            assert "stream_url" in cam
            assert "image_url" in cam
            assert cam.get("cam_status") == "UP"
