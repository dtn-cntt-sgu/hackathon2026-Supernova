"""
Comprehensive Verification Suite for SafePath AI Full System Audit & Accuracy Improvements:
- ISSUE 1: Vehicle Detection & Counting (6-class taxonomy, IoU+IoMin deduplication, multi-scale tiling, invariant checks).
- ISSUE 2: Multi-Factor Traffic Density Analysis (PCU + perspective-weighted ROI occupancy + 6-level classification).
- ISSUE 3: Modular Traffic Camera Source Adapter (LIVE, RECENT, STALE, SIMULATED, UNAVAILABLE, SHA-256 freeze detection).
- ISSUE 4: Realistic HCMC Urban ETA Calculation Engine (1km, 3km, 5.5km off-peak/peak, 10km, Motorcycle vs Car vs Walking).
- ISSUE 5: Cross-Module Schema & API Contract Consistency.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas.contracts import (
    CameraEvidence,
    DataSourceStatus,
    ImageQualityAssessment,
    ImageQualityMetrics,
    RiskLevel,
    RouteSegmentRisk,
    SafeRouteResponse,
    TrafficDensityLevel,
    TrafficStatus,
    TransportMode,
)
from backend.app.services.camera_adapter import (
    CameraAdapterRegistry,
    HcmcVdmsCameraAdapter,
    classify_camera_data_status,
    validate_image_bytes_and_file,
)
from backend.app.services.routing import (
    calculate_hcmc_route_eta,
    normalize_transport_mode,
)
from backend.app.services.vision import (
    STANDARD_VEHICLE_CLASSES,
    DetectedVehicle,
    VehicleDetectionResult,
    VehicleDetector,
    _compute_iomin,
    _compute_iou,
    _merge_detections,
    classify_traffic_density_level,
    compute_multi_factor_traffic_density,
    preprocess_camera_image,
)


# ==============================================================================
# 1. ISSUE 1 & ISSUE 2: 10 Computer Vision & Traffic Density Scenarios
# ==============================================================================
class TestVehicleDetectionAndDensityScenarios:
    """Tests 10 distinct urban HCMC traffic scenarios for vehicle counting & density."""

    def _make_quality(self, is_low_quality: bool = False, is_low_light: bool = False, is_blurry: bool = False) -> ImageQualityAssessment:
        return ImageQualityAssessment(
            quality_status="POOR" if is_low_quality else "HIGH_QUALITY",
            quality_flags=["LOW_LIGHT"] if is_low_light else (["BLURRY"] if is_blurry else []),
            quality_metrics=ImageQualityMetrics(
                brightness_score=0.20 if is_low_light else 0.75,
                blur_score=0.25 if is_blurry else 0.85,
                noise_estimate=0.10,
                resolution_score=0.80,
                contrast_score=0.70,
                is_low_light=is_low_light,
                is_blurry=is_blurry,
                is_low_quality=is_low_quality,
            ),
        )

    def test_scenario_01_empty_road_free_flow(self):
        """Scenario 1: Empty road with good image quality -> 0 vehicles, FREE_FLOW."""
        score, level, roi_occ, conf = compute_multi_factor_traffic_density(
            vehicles=[],
            height=480,
            width=640,
            roi_pixel_count=200000,
            quality=self._make_quality(is_low_quality=False),
            is_available=True,
        )
        res = VehicleDetectionResult(
            model_status="VERIFIED_ONNX_INFERENCE",
            is_available=True,
            vehicle_count=0,
            traffic_density_score=score,
            vehicles=[],
            traffic_density_level=level,
            roi_occupancy_ratio=roi_occ,
            analysis_confidence=conf,
        )
        assert res.total_vehicles == 0
        assert sum(res.vehicle_counts.values()) == res.total_vehicles
        assert set(res.vehicle_counts.keys()) == set(STANDARD_VEHICLE_CLASSES)
        assert res.traffic_density_score == 0.0
        assert res.traffic_density_level == TrafficDensityLevel.FREE_FLOW

    def test_scenario_02_few_vehicles_light_traffic(self):
        """Scenario 2: Few vehicles (4 motorcycles, 1 car) -> LIGHT traffic."""
        vehicles = [
            DetectedVehicle("motorcycle", 0.82, (120, 300, 145, 345), 1.0),
            DetectedVehicle("motorcycle", 0.79, (180, 310, 205, 355), 1.0),
            DetectedVehicle("motorcycle", 0.85, (250, 290, 275, 335), 1.0),
            DetectedVehicle("motorcycle", 0.76, (310, 320, 335, 365), 1.0),
            DetectedVehicle("car", 0.91, (400, 280, 490, 360), 2.5),
        ]
        score, level, roi_occ, conf = compute_multi_factor_traffic_density(
            vehicles=vehicles,
            height=480,
            width=640,
            roi_pixel_count=220000,
            quality=self._make_quality(is_low_quality=False),
            is_available=True,
        )
        res = VehicleDetectionResult(
            model_status="VERIFIED_ONNX_INFERENCE",
            is_available=True,
            vehicle_count=len(vehicles),
            traffic_density_score=score,
            vehicles=vehicles,
            traffic_density_level=level,
            roi_occupancy_ratio=roi_occ,
            analysis_confidence=conf,
        )
        assert res.total_vehicles == 5
        assert sum(res.vehicle_counts.values()) == res.total_vehicles
        assert res.vehicle_counts["motorcycle"] == 4
        assert res.vehicle_counts["car"] == 1
        assert res.traffic_density_level in (TrafficDensityLevel.FREE_FLOW, TrafficDensityLevel.LIGHT)
        assert 0.05 < res.traffic_density_score < 0.35

    def test_scenario_03_many_motorcycles_hcmc_swarm(self):
        """Scenario 3: HCMC motorcycle swarm (22 motorcycles) -> MODERATE/HEAVY density."""
        vehicles = [
            DetectedVehicle(
                "motorcycle",
                0.78,
                (40 + (i % 7) * 80, 200 + (i // 7) * 70, 85 + (i % 7) * 80, 255 + (i // 7) * 70),
                1.0,
            )
            for i in range(22)
        ]
        score, level, roi_occ, conf = compute_multi_factor_traffic_density(
            vehicles=vehicles,
            height=480,
            width=640,
            roi_pixel_count=200000,
            quality=self._make_quality(is_low_quality=False),
            is_available=True,
        )
        res = VehicleDetectionResult(
            model_status="VERIFIED_ONNX_INFERENCE",
            is_available=True,
            vehicle_count=len(vehicles),
            traffic_density_score=score,
            vehicles=vehicles,
            traffic_density_level=level,
            roi_occupancy_ratio=roi_occ,
            analysis_confidence=conf,
        )
        assert res.total_vehicles == 22
        assert res.vehicle_counts["motorcycle"] == 22
        assert sum(res.vehicle_counts.values()) == 22
        assert res.traffic_density_level in (TrafficDensityLevel.MODERATE, TrafficDensityLevel.HEAVY)
        assert res.traffic_density_score >= 0.35

    def test_scenario_04_mixed_motorcycles_cars_bicycles(self):
        """Scenario 4: Mixed urban flow including bicycles (previously dropped class 1)."""
        vehicles = [
            DetectedVehicle("motorcycle", 0.84, (100, 260, 140, 320), 1.0),
            DetectedVehicle("motorcycle", 0.80, (160, 270, 200, 330), 1.0),
            DetectedVehicle("car", 0.90, (230, 240, 350, 340), 2.5),
            DetectedVehicle("car", 0.88, (370, 250, 490, 350), 2.5),
            DetectedVehicle("bicycle", 0.72, (520, 290, 555, 345), 0.8),
        ]
        res = VehicleDetectionResult(
            model_status="VERIFIED_ONNX_INFERENCE",
            is_available=True,
            vehicle_count=len(vehicles),
            traffic_density_score=0.32,
            vehicles=vehicles,
        )
        assert res.total_vehicles == 5
        assert res.vehicle_counts["motorcycle"] == 2
        assert res.vehicle_counts["car"] == 2
        assert res.vehicle_counts["bicycle"] == 1
        assert sum(res.vehicle_counts.values()) == res.total_vehicles
        # Legacy 4-key class_breakdown remains intact for backward compatibility
        assert set(res.class_breakdown.keys()) == {"motorcycle", "car", "bus", "truck"}

    def test_scenario_05_large_bus_and_truck_disambiguation(self):
        """Scenario 5: Large buses and trucks in frame and class-aware geometric disambiguation."""
        detector = VehicleDetector(model_path=None, fallback_to_heuristic=False)
        # Raw candidates: ([x, y, bw, bh], conf, coco_cid)
        # coco_cid: 3=motorcycle, 5=bus, 7=truck, 2=car
        raw_candidates = [
            ([0, 0, 620, 460], 0.90, 3),      # Spurious full-frame motorcycle (>30% frame area) -> rejected
            ([50, 180, 210, 200], 0.88, 5),   # Valid bus
            ([300, 190, 190, 180], 0.86, 7),  # Valid truck
            ([510, 250, 100, 90], 0.82, 2),   # Valid car
        ]
        filtered = detector._apply_class_aware_nms(
            raw_candidates,
            conf_threshold=0.25,
            nms_threshold=0.45,
            motorcycle_conf=0.20,
            frame_shape=(480, 640),
        )
        classes = [v.cls_name for v in filtered]
        assert "motorcycle" not in classes  # Giant box rejected
        assert "bus" in classes
        assert "truck" in classes
        assert "car" in classes
        assert len(filtered) == 3

    def test_scenario_06_heavy_congestion_gridlock(self):
        """Scenario 6: Heavy congestion (15 motorcycles, 6 cars, 2 buses, 1 truck) -> CONGESTED."""
        vehicles = []
        for i in range(15):
            x1 = 20 + (i % 5) * 110
            y1 = 180 + (i // 5) * 80
            vehicles.append(DetectedVehicle("motorcycle", 0.85, (x1, y1, x1 + 55, y1 + 65), 1.0))
        for i in range(6):
            x1 = 40 + (i % 3) * 180
            y1 = 220 + (i // 3) * 110
            vehicles.append(DetectedVehicle("car", 0.91, (x1, y1, x1 + 130, y1 + 95), 2.5))
        vehicles.append(DetectedVehicle("bus", 0.93, (60, 150, 280, 320), 4.0))
        vehicles.append(DetectedVehicle("bus", 0.89, (320, 160, 540, 330), 4.0))
        vehicles.append(DetectedVehicle("truck", 0.87, (180, 260, 380, 420), 4.0))

        score, level, roi_occ, conf = compute_multi_factor_traffic_density(
            vehicles=vehicles,
            height=480,
            width=640,
            roi_pixel_count=200000,
            quality=self._make_quality(is_low_quality=False),
            is_available=True,
        )
        assert level == TrafficDensityLevel.CONGESTED
        assert score >= 0.80
        assert roi_occ > 0.30

    def test_scenario_07_low_light_night_frame_zero_vehicles_is_unknown(self):
        """Scenario 7: Dark/low-light frame with 0 detections -> UNKNOWN (never falsely FREE_FLOW)."""
        score, level, roi_occ, conf = compute_multi_factor_traffic_density(
            vehicles=[],
            height=480,
            width=640,
            roi_pixel_count=200000,
            quality=self._make_quality(is_low_quality=True, is_low_light=True),
            is_available=True,
        )
        assert level == TrafficDensityLevel.UNKNOWN
        assert conf <= 0.35

    def test_scenario_08_blurry_degraded_frame_confidence_penalty(self):
        """Scenario 8: Blurry frame with vehicles penalizes analysis_confidence."""
        vehicles = [
            DetectedVehicle("car", 0.65, (200, 240, 320, 330), 2.5),
            DetectedVehicle("motorcycle", 0.58, (350, 260, 390, 320), 1.0),
        ]
        _, _, _, conf_clean = compute_multi_factor_traffic_density(
            vehicles=vehicles,
            height=480,
            width=640,
            roi_pixel_count=200000,
            quality=self._make_quality(is_low_quality=False),
            is_available=True,
        )
        _, _, _, conf_blurry = compute_multi_factor_traffic_density(
            vehicles=vehicles,
            height=480,
            width=640,
            roi_pixel_count=200000,
            quality=self._make_quality(is_low_quality=True, is_blurry=True),
            is_available=True,
        )
        assert conf_blurry < conf_clean

    def test_scenario_09_distant_small_vehicles_perspective_weight(self):
        """Scenario 9: Distant vehicles in upper road horizon receive perspective-normalized weight."""
        # Upper horizon vehicle (y near top of road ROI) vs lower foreground vehicle of same pixel size
        distant_veh = [DetectedVehicle("car", 0.80, (280, 120, 330, 155), 2.5)]
        near_veh = [DetectedVehicle("car", 0.80, (280, 400, 330, 435), 2.5)]

        score_dist, _, occ_dist, _ = compute_multi_factor_traffic_density(
            vehicles=distant_veh, height=480, width=640, roi_pixel_count=200000
        )
        score_near, _, occ_near, _ = compute_multi_factor_traffic_density(
            vehicles=near_veh, height=480, width=640, roi_pixel_count=200000
        )
        assert occ_dist > occ_near
        assert score_dist >= score_near

    def test_scenario_10_overlapping_and_nested_boxes_deduplication(self):
        """Scenario 10: Nested/duplicate bounding boxes across tiles or dual branches are merged into 1."""
        # Car box and a nested sub-box inside the same car (IoU < 0.45 but IoMin >= 0.85)
        outer_car = DetectedVehicle("car", 0.92, (100, 200, 260, 340), 2.5)
        inner_subbox = DetectedVehicle("car", 0.74, (120, 220, 200, 300), 2.5)

        iou = _compute_iou(outer_car.bbox, inner_subbox.bbox)
        iomin = _compute_iomin(outer_car.bbox, inner_subbox.bbox)
        assert iou < 0.45
        assert iomin == 1.0

        merged = _merge_detections([outer_car], [inner_subbox], iou_threshold=0.45)
        assert len(merged) == 1
        assert merged[0].confidence == 0.92


# ==============================================================================
# 2. ISSUE 3: Real-Time Camera Adapter & Strict Freshness Status Classification
# ==============================================================================
class TestCameraAdapterAndDataStatus:
    """Verifies LIVE, RECENT, STALE, SIMULATED, UNAVAILABLE and frozen frame detection."""

    def test_classify_camera_data_status_all_five_states(self):
        now = datetime.now(timezone.utc)

        # 1. UNAVAILABLE when image invalid
        st, reason = classify_camera_data_status(has_valid_image=False, now=now)
        assert st == DataSourceStatus.UNAVAILABLE

        # 2. SIMULATED when explicitly flagged
        st, reason = classify_camera_data_status(
            has_valid_image=True, is_simulated=True, captured_at=now, retrieved_at=now, now=now
        )
        assert st == DataSourceStatus.SIMULATED

        # 3. LIVE when both capture & retrieval are fresh (<= 300s)
        st, reason = classify_camera_data_status(
            has_valid_image=True,
            captured_at=now - timedelta(seconds=60),
            retrieved_at=now - timedelta(seconds=30),
            now=now,
            live_ttl_seconds=300,
        )
        assert st == DataSourceStatus.LIVE

        # 4. RECENT when retrieved recently without watermark capture timestamp, or 5-30 mins old
        st, reason = classify_camera_data_status(
            has_valid_image=True,
            captured_at=None,
            retrieved_at=now - timedelta(seconds=120),
            now=now,
            live_ttl_seconds=300,
            recent_ttl_seconds=1800,
        )
        assert st == DataSourceStatus.RECENT

        # 5. STALE when older than recent_ttl_seconds or frozen frame
        st, reason = classify_camera_data_status(
            has_valid_image=True,
            captured_at=now - timedelta(seconds=3600),
            retrieved_at=now - timedelta(seconds=3600),
            now=now,
            live_ttl_seconds=300,
            recent_ttl_seconds=1800,
        )
        assert st == DataSourceStatus.STALE

        st_frozen, reason_frozen = classify_camera_data_status(
            has_valid_image=True,
            captured_at=now,
            retrieved_at=now,
            now=now,
            is_frozen_frame=True,
        )
        assert st_frozen == DataSourceStatus.STALE
        assert "FROZEN" in reason_frozen

    @pytest.mark.asyncio
    async def test_hcmc_vdms_camera_adapter_validation_and_freeze_detection(self):
        adapter = HcmcVdmsCameraAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            cam_id = "cam_adapter_test_01"
            img_path = os.path.join(tmpdir, f"{cam_id}.jpg")
            # Write a valid 320x240 synthetic road image to temp storage
            frame = np.full((240, 320, 3), 120, dtype=np.uint8)
            cv2.imwrite(img_path, frame)

            now = datetime.now(timezone.utc)
            cam_meta = {
                "cam_id": cam_id,
                "name": "Camera Ngã tư Hàng Xanh",
                "district": "Quận Bình Thạnh",
                "lat": 10.8012,
                "lng": 106.7115,
                "captured_at": (now - timedelta(seconds=30)).isoformat(),
            }
            payload = await adapter.acquire_frame(cam_meta, storage_dir=tmpdir)
            assert payload.validation_passed is True
            assert payload.data_status == DataSourceStatus.LIVE
            assert payload.width == 320 and payload.height == 240
            assert payload.frame_sha256 is not None
            audit = payload.to_audit_record()
            assert audit["camera_id"] == cam_id
            assert audit["data_status"] == "LIVE"


# ==============================================================================
# 3. ISSUE 4: Realistic HCMC Route Planning & ETA Scenarios (8 Scenarios)
# ==============================================================================
class TestHcmcRealisticETAScenarios:
    """Tests 1km, 3km, 5.5km off-peak/peak, 10km, Motorcycle vs Car vs Walking, and Congestion."""

    def _build_urban_segments(
        self,
        total_distance_m: float,
        num_segments: int = 8,
        street_name: str = "Đường Nguyễn Thị Minh Khai",
        traffic_status: TrafficStatus = TrafficStatus.UNKNOWN,
        traffic_delay_per_seg: float = 0.0,
    ) -> list[RouteSegmentRisk]:
        seg_len = total_distance_m / max(1, num_segments)
        return [
            RouteSegmentRisk(
                osm_way_id=1000 + i,
                street_name=street_name,
                length_meters=seg_len,
                maneuver_type="turn" if i % 2 == 1 else "continue",
                risk_level=RiskLevel.SAFE,
                traffic_status=traffic_status,
                traffic_delay_seconds=traffic_delay_per_seg,
            )
            for i in range(num_segments)
        ]

    def test_eta_01_short_route_1km(self):
        """1.0 km urban route in HCMC."""
        segs = self._build_urban_segments(1000.0, num_segments=3)
        off_peak_dt = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)  # 10:00 AM HCMC

        moto = calculate_hcmc_route_eta(segs, 1000.0, 120.0, "motorcycle", departure_dt=off_peak_dt)
        car = calculate_hcmc_route_eta(segs, 1000.0, 120.0, "car", departure_dt=off_peak_dt)
        walk = calculate_hcmc_route_eta(segs, 1000.0, 120.0, "walking", departure_dt=off_peak_dt)

        assert moto["estimated_duration_seconds"] == pytest.approx(120 * 1.14)
        assert car["estimated_time_mins"] > moto["estimated_time_mins"]
        assert walk["estimated_duration_seconds"] == 750

    def test_eta_02_medium_route_3km(self):
        """3.0 km urban route in HCMC."""
        segs = self._build_urban_segments(3000.0, num_segments=6)
        off_peak_dt = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)  # 10:00 AM HCMC

        moto = calculate_hcmc_route_eta(segs, 3000.0, 390.0, "motorcycle", departure_dt=off_peak_dt)
        car = calculate_hcmc_route_eta(segs, 3000.0, 390.0, "car", departure_dt=off_peak_dt)

        assert moto["estimated_duration_seconds"] == pytest.approx(390 * 1.14)
        assert car["estimated_duration_seconds"] == pytest.approx(390 * 1.25)
        assert car["estimated_time_mins"] > moto["estimated_time_mins"]

    def test_eta_03_5_5km_uses_osrm_with_uncovered_time_estimate(self):
        """
        5.5 km urban route in HCMC (off-peak daytime 10:00 AM):
        Raw OSRM free-flow was 780s (13.0 mins).
        Uncovered time is based on OSRM plus the explicitly estimated time-of-day factor.
        """
        segs = self._build_urban_segments(5500.0, num_segments=10)
        daytime_dt = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)  # Thursday 10:00 AM HCMC

        moto = calculate_hcmc_route_eta(segs, 5500.0, 780.0, "motorcycle", departure_dt=daytime_dt)
        car = calculate_hcmc_route_eta(segs, 5500.0, 780.0, "car", departure_dt=daytime_dt)

        assert moto["duration_seconds"] == 780.0  # Raw OSRM preserved
        assert moto["estimated_duration_seconds"] == pytest.approx(780 * 1.14)
        assert car["estimated_duration_seconds"] == pytest.approx(780 * 1.25)
        assert moto["eta_breakdown"].additional_delay_seconds == 0
        assert moto["eta_breakdown"].confidence == 0
        assert car["estimated_time_mins"] > moto["estimated_time_mins"]

    def test_eta_04_5_5km_hcmc_rush_hour_peak(self):
        """5.5 km urban route in HCMC during Evening Rush Hour (17:30 local time)."""
        segs = self._build_urban_segments(5500.0, num_segments=10)
        daytime_dt = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)      # 10:00 AM HCMC
        rush_hour_dt = datetime(2026, 11, 5, 10, 30, tzinfo=timezone.utc)  # 17:30 PM HCMC

        moto_day = calculate_hcmc_route_eta(segs, 5500.0, 780.0, "motorcycle", departure_dt=daytime_dt)
        moto_peak = calculate_hcmc_route_eta(segs, 5500.0, 780.0, "motorcycle", departure_dt=rush_hour_dt)
        car_peak = calculate_hcmc_route_eta(segs, 5500.0, 780.0, "car", departure_dt=rush_hour_dt)

        assert moto_peak["estimated_time_mins"] > moto_day["estimated_time_mins"]
        assert moto_peak["estimated_duration_seconds"] == pytest.approx(780 * 1.38)
        assert car_peak["estimated_duration_seconds"] == pytest.approx(780 * 1.64)
        assert car_peak["eta_breakdown"].time_of_day_multiplier > 1.5

    def test_eta_05_10km_corridor_route(self):
        """10.0 km route across HCMC."""
        segs = self._build_urban_segments(10000.0, num_segments=16, street_name="Đường Điện Biên Phủ")
        daytime_dt = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)

        moto = calculate_hcmc_route_eta(segs, 10000.0, 1300.0, "motorcycle", departure_dt=daytime_dt)
        car = calculate_hcmc_route_eta(segs, 10000.0, 1300.0, "car", departure_dt=daytime_dt)

        assert moto["estimated_duration_seconds"] == pytest.approx(1300 * 1.14)
        assert car["estimated_duration_seconds"] == pytest.approx(1300 * 1.25)
        assert car["estimated_time_mins"] > moto["estimated_time_mins"]

    def test_eta_06_transport_mode_hierarchy_walking_car_motorcycle(self):
        """Explicit fallback mode factors apply only to uncovered road; walking uses distance."""
        segs = self._build_urban_segments(4000.0, num_segments=8)
        dt = datetime(2026, 11, 5, 10, 30, tzinfo=timezone.utc)  # 17:30 HCMC

        moto = calculate_hcmc_route_eta(segs, 4000.0, 540.0, "motorcycle", departure_dt=dt)
        car = calculate_hcmc_route_eta(segs, 4000.0, 540.0, "car", departure_dt=dt)
        walk = calculate_hcmc_route_eta(segs, 4000.0, 540.0, "walking", departure_dt=dt)

        assert moto["estimated_duration_seconds"] < car["estimated_duration_seconds"] < walk["estimated_duration_seconds"]
        assert moto["transport_mode"] == TransportMode.MOTORCYCLE
        assert car["transport_mode"] == TransportMode.CAR
        assert walk["transport_mode"] == TransportMode.WALKING

    def test_eta_07_live_congested_vs_free_flow_corridor(self):
        """Measured provider speed changes ETA; a density-only camera cannot do so."""
        segs_free = self._build_urban_segments(
            3500.0, num_segments=5, traffic_status=TrafficStatus.FREE_FLOW, traffic_delay_per_seg=0.0
        )
        segs_congested = self._build_urban_segments(
            3500.0, num_segments=5, traffic_status=TrafficStatus.CONGESTED, traffic_delay_per_seg=90.0
        )
        for collection, speed in ((segs_free, 35.0), (segs_congested, 10.0)):
            for seg in collection:
                seg.observed_speed_kmh = speed
                seg.free_flow_speed_kmh = 35.0
                seg.traffic_observed_length_meters = seg.length_meters
                seg.traffic_confidence = .9
                seg.traffic_freshness_seconds = 20.0
                seg.traffic_segment_match_status = "CORRIDOR_MATCHED"
        dt = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)

        res_free = calculate_hcmc_route_eta(segs_free, 3500.0, 480.0, "motorcycle", departure_dt=dt)
        res_cong = calculate_hcmc_route_eta(segs_congested, 3500.0, 480.0, "motorcycle", departure_dt=dt)

        assert res_free["is_live_traffic"] is True
        assert res_cong["is_live_traffic"] is True
        assert res_free["traffic_status"] == TrafficStatus.FREE_FLOW
        assert res_cong["traffic_status"] == TrafficStatus.CONGESTED
        assert res_cong["estimated_duration_seconds"] >= res_free["estimated_duration_seconds"] + 400.0

    def test_eta_08_api_routes_search_transport_modes_and_contract(self, monkeypatch):
        """End-to-end API test verifying transport_mode differentiation & full ETA contract."""
        # Isolate transport in this assembly/contract test; opt-in OSRM tests exercise the real service.
        from backend.tests.unit_routing_fixtures import install_unit_osrm
        install_unit_osrm(monkeypatch)
        with TestClient(app) as client:
            base_coords = {
                "origin": {"lat": 10.7725, "lng": 106.6980},
                "destination": {"lat": 10.8012, "lng": 106.7115},
            }
            r_moto = client.post("/api/v1/routes/search", json={**base_coords, "transport_mode": "motorcycle"})
            r_car = client.post("/api/v1/routes/search", json={**base_coords, "transport_mode": "car"})
            r_walk = client.post("/api/v1/routes/search", json={**base_coords, "transport_mode": "walking"})

            assert r_moto.status_code == 200
            assert r_car.status_code == 200
            assert r_walk.status_code == 200

            d_moto = SafeRouteResponse.model_validate(r_moto.json())
            d_car = SafeRouteResponse.model_validate(r_car.json())
            d_walk = SafeRouteResponse.model_validate(r_walk.json())

            assert d_moto.transport_mode == TransportMode.MOTORCYCLE
            assert d_car.transport_mode == TransportMode.CAR
            assert d_walk.transport_mode == TransportMode.WALKING

            assert d_moto.eta_breakdown is not None
            assert d_car.eta_breakdown is not None
            assert d_walk.eta_breakdown is not None

            assert d_moto.estimated_duration_seconds is not None
            assert d_car.estimated_duration_seconds is not None
            assert d_walk.estimated_duration_seconds is not None

            # The graph is a driving profile; do not invent a measured car/motorbike hierarchy.
            for route in (d_moto, d_car):
                assert route.estimated_duration_seconds == pytest.approx(
                    route.eta_breakdown.base_travel_time_seconds + route.eta_breakdown.traffic_delay_seconds)
                assert route.eta_breakdown.additional_delay_seconds == 0
            assert d_walk.estimated_duration_seconds == pytest.approx(
                d_walk.total_distance_km * 1000 / (4.8 / 3.6), abs=1.0)
            assert not d_walk.is_live_traffic and d_walk.traffic_coverage_ratio == 0
