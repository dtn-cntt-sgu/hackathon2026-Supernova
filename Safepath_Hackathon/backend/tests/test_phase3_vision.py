"""
Phase 3 Unit and Integration Tests for SafePathAI Computer Vision Pipeline.
Validates:
1. OpenCV preprocessing (ROI polygon cropping, luminance & blurriness checks).
2. Vehicle detection and traffic density score normalization in [0.0, 1.0].
3. Flood water segmentation comparing dry vs flooded road surfaces.
4. Annotated visual evidence overlay (_analyzed.jpg) generation.
5. Integration with CameraEvidence Data Contracts and Redis Hash/Stream.
"""

import os
import shutil
import tempfile
import cv2
import numpy as np
import pytest

from backend.app.db.session import get_redis_client
from backend.app.schemas.contracts import (
    CameraEvidence,
    DataSourceStatus,
    EvidenceEligibility,
    RiskLevel,
)
from backend.app.services.vision import (
    CameraVisionPipeline,
    FloodSegmenter,
    VehicleDetector,
    determine_camera_risk_level,
    preprocess_camera_image,
    save_camera_evidence_to_redis,
    process_all_cameras_vision,
)


@pytest.fixture
def test_workspace(monkeypatch):
    """Creates a temporary workspace with synthesized dry and flooded test frames."""
    monkeypatch.setenv("VISION_ALLOW_HEURISTIC_BASELINE", "1")
    temp_dir = tempfile.mkdtemp(prefix="safepath_vision_test_")

    # 1. Synthesize Dry Road Frame (300x230)
    dry_img = np.full((230, 300, 3), 75, dtype=np.uint8)
    # Add asphalt surface texture noise
    noise = np.random.randint(-8, 8, (230, 300, 3), dtype=np.int16)
    dry_img = np.clip(dry_img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    # Top 25% sky/banner (first 57 rows)
    dry_img[:57, :] = [210, 210, 210]
    # White dashed lane markings
    dry_img[70:220, 148:152] = 240
    # Two synthetic vehicles on dry road
    # Vehicle 1: Motorcycle (small blob)
    dry_img[100:125, 60:85] = [30, 30, 180]
    # Vehicle 2: Car (medium rectangular blob)
    dry_img[140:175, 180:240] = [180, 40, 40]

    dry_path = os.path.join(temp_dir, "cam_dry.jpg")
    cv2.imwrite(dry_path, dry_img)

    # 2. Synthesize Flooded Road Frame (300x230)
    flood_img = dry_img.copy()
    # Extensive muddy flood water pool covering road surface (BGR: [70, 110, 140])
    flood_img[100:225, 20:280] = [70, 110, 140]

    flood_path = os.path.join(temp_dir, "cam_flood.jpg")
    cv2.imwrite(flood_path, flood_img)

    yield {
        "dir": temp_dir,
        "dry_path": dry_path,
        "flood_path": flood_path,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 1. Preprocessing Tests
# ==============================================================================
class TestVisionPreprocessing:
    """Tests for image cropping, ROI masking, and image quality metrics."""

    def test_preprocess_crop_and_quality(self, test_workspace):
        dry_path = test_workspace["dry_path"]
        prep = preprocess_camera_image(dry_path, top_crop_ratio=0.25)

        assert prep.height == 230
        assert prep.width == 300
        # Top 25% of 230 is 57 pixels; bottom 173 rows are in ROI
        expected_roi_pixels = (230 - 57) * 300
        assert prep.roi_pixel_count == expected_roi_pixels

        # Ensure top 25% of ROI mask is 0 (blacked out)
        assert np.count_nonzero(prep.roi_mask[:57, :]) == 0
        # Ensure bottom 75% of ROI mask is 255
        assert np.count_nonzero(prep.roi_mask[57:, :] == 255) == expected_roi_pixels

        # Quality metrics
        assert 0.0 <= prep.mean_luminance <= 255.0
        assert prep.laplacian_var >= 0.0
        assert prep.is_dark is False
        assert prep.is_blurry is False

    def test_preprocess_corrupted_file(self, test_workspace):
        # Non-existent file
        with pytest.raises(FileNotFoundError):
            preprocess_camera_image(os.path.join(test_workspace["dir"], "missing.jpg"))

        # Empty/corrupt file
        empty_path = os.path.join(test_workspace["dir"], "empty.jpg")
        with open(empty_path, "wb") as f:
            f.write(b"not an image")
        with pytest.raises(ValueError):
            preprocess_camera_image(empty_path)


# ==============================================================================
# 2. Vehicle Detection Tests
# ==============================================================================
class TestVehicleDetection:
    """Tests for vehicle detection and traffic density scoring."""

    def test_detect_vehicles_density_range(self, test_workspace):
        dry_path = test_workspace["dry_path"]
        prep = preprocess_camera_image(dry_path)

        detector = VehicleDetector()
        res = detector.detect_vehicles(prep)

        assert res.vehicle_count >= 1
        assert 0.0 <= res.traffic_density_score <= 1.0
        assert len(res.vehicles) == res.vehicle_count

        for veh in res.vehicles:
            assert veh.cls_name in ("motorcycle", "car", "bus", "truck")
            assert veh.weight >= 1.0
            x1, y1, x2, y2 = veh.bbox
            assert 0 <= x1 < x2 <= 300
            assert 0 <= y1 < y2 <= 230


# ==============================================================================
# 3. Flood Water Segmentation Tests
# ==============================================================================
class TestFloodWaterSegmentation:
    """Tests for flood water segmentation separating dry vs flooded scenes."""

    def test_segment_dry_vs_flood_water(self, test_workspace):
        prep_dry = preprocess_camera_image(test_workspace["dry_path"])
        prep_flood = preprocess_camera_image(test_workspace["flood_path"])

        segmenter = FloodSegmenter()
        res_dry = segmenter.segment_flood_water(prep_dry)
        res_flood = segmenter.segment_flood_water(prep_flood)

        # Dry road should have minimal or 0% flood ratio
        assert 0.0 <= res_dry.flood_ratio <= 1.0
        assert res_dry.flood_ratio < 0.10, f"Expected dry road flood_ratio < 0.10, got {res_dry.flood_ratio}"

        # Flooded road should detect substantial water coverage (>= 25%)
        assert 0.0 <= res_flood.flood_ratio <= 1.0
        assert res_flood.flood_ratio >= 0.25, f"Expected flooded road flood_ratio >= 0.25, got {res_flood.flood_ratio}"
        assert res_flood.water_pixel_count > res_dry.water_pixel_count


# ==============================================================================
# 4. Risk Level Determination Tests
# ==============================================================================
class TestRiskLevelEvaluation:
    """Tests for deterministic risk level calculation."""

    def test_determine_camera_risk_level(self):
        # Critical by flood
        assert determine_camera_risk_level(flood_ratio=0.30, traffic_density_score=0.20) == RiskLevel.CRITICAL
        # Critical by traffic gridlock
        assert determine_camera_risk_level(flood_ratio=0.05, traffic_density_score=0.90) == RiskLevel.CRITICAL
        # Moderate by flood
        assert determine_camera_risk_level(flood_ratio=0.15, traffic_density_score=0.20) == RiskLevel.MODERATE
        # Moderate by traffic
        assert determine_camera_risk_level(flood_ratio=0.02, traffic_density_score=0.60) == RiskLevel.MODERATE
        # Safe
        assert determine_camera_risk_level(flood_ratio=0.04, traffic_density_score=0.25) == RiskLevel.SAFE


# ==============================================================================
# 5. End-to-End Vision Pipeline Tests
# ==============================================================================
class TestEndToEndVisionPipeline:
    """Tests the full vision pipeline producing validated CameraEvidence."""

    def test_pipeline_camera_evidence_generation(self, test_workspace):
        pipeline = CameraVisionPipeline()
        cam_meta_dry = {
            "cam_id": "58af8b69bd82540010390c28",
            "code": "TTH 35.4",
            "name": "Nam Kỳ Khởi Nghĩa - Võ Thị Sáu",
            "district": "Quận 3",
            "lat": 10.7868,
            "lng": 106.6882,
            "source_status": DataSourceStatus.LIVE,
        }

        # Analyze dry frame
        evidence_dry = pipeline.analyze_camera_image(
            image_path=test_workspace["dry_path"],
            cam_meta=cam_meta_dry,
            storage_dir=test_workspace["dir"],
        )

        assert isinstance(evidence_dry, CameraEvidence)
        assert evidence_dry.cam_id == "58af8b69bd82540010390c28"
        assert evidence_dry.risk_level == RiskLevel.UNKNOWN
        assert evidence_dry.evidence_eligibility == EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING
        assert 0.0 <= evidence_dry.flood_ratio <= 1.0
        assert 0.0 <= evidence_dry.traffic_density_score <= 1.0

        # Check visual evidence overlay was created
        analyzed_path = os.path.join(test_workspace["dir"], f"{cam_meta_dry['cam_id']}_analyzed.jpg")
        assert os.path.exists(analyzed_path)
        analyzed_img = cv2.imread(analyzed_path)
        assert analyzed_img.shape == (230, 300, 3)

        # Analyze flooded frame
        cam_meta_flood = {
            "cam_id": "5d8cd4ee766c880017188946",
            "code": "TTH 145",
            "name": "Nguyễn Hữu Cảnh - Điện Biên Phủ",
            "district": "Quận Bình Thạnh",
            "lat": 10.7981,
            "lng": 106.7186,
            "source_status": DataSourceStatus.LIVE,
        }
        evidence_flood = pipeline.analyze_camera_image(
            image_path=test_workspace["flood_path"],
            cam_meta=cam_meta_flood,
            storage_dir=test_workspace["dir"],
        )
        assert evidence_flood.risk_level == RiskLevel.UNKNOWN
        assert evidence_flood.flood_ratio >= 0.25


# ==============================================================================
# 6. Redis Persistence & Stream Publishing Tests
# ==============================================================================
class TestRedisVisionPersistence:
    """Verifies that CameraEvidence is correctly saved to Redis Hash and Redis Stream."""

    @pytest.mark.asyncio
    async def test_save_evidence_to_redis_hash_and_stream(self, test_workspace):
        pipeline = CameraVisionPipeline()
        cam_meta = {
            "cam_id": "test_redis_cam_001",
            "code": "TTH 99.9",
            "name": "Test Redis Cam",
            "district": "Quận 1",
            "lat": 10.77,
            "lng": 106.70,
            "source_status": DataSourceStatus.LIVE,
        }

        evidence = pipeline.analyze_camera_image(
            image_path=test_workspace["flood_path"],
            cam_meta=cam_meta,
            storage_dir=test_workspace["dir"],
        )

        redis_client = get_redis_client()
        await save_camera_evidence_to_redis(evidence, redis_client=redis_client)

        # Verify Redis Hash: camera:state:{cam_id}
        hash_key = f"camera:state:{evidence.cam_id}"
        hash_data = await redis_client.hgetall(hash_key)
        assert hash_data is not None
        assert hash_data["cam_id"] == "test_redis_cam_001"
        assert hash_data["risk_level"] == RiskLevel.UNKNOWN.value
        assert float(hash_data["flood_ratio"]) >= 0.25

        # Verify Redis Stream: stream:camera_updates
        stream_events = await redis_client.xrevrange("stream:camera_updates", count=5)
        assert len(stream_events) > 0
        event_id, event_fields = stream_events[0]
        assert event_fields["cam_id"] == "test_redis_cam_001"
        assert event_fields["risk_level"] == RiskLevel.UNKNOWN.value
        assert "flood_ratio" in event_fields

        # Cleanup
        await redis_client.delete(hash_key)
        await redis_client.aclose()

    @pytest.mark.asyncio
    async def test_process_all_cameras_vision_batch(self, test_workspace):
        cams = [
            {
                "cam_id": "batch_cam_1",
                "code": "TTH 1",
                "name": "Batch Cam 1",
                "district": "Quận 1",
                "lat": 10.7,
                "lng": 106.7,
                "image_path": test_workspace["dry_path"],
                "source_status": DataSourceStatus.LIVE,
            },
            {
                "cam_id": "batch_cam_2",
                "code": "TTH 2",
                "name": "Batch Cam 2",
                "district": "Quận 2",
                "lat": 10.8,
                "lng": 106.8,
                "image_path": test_workspace["flood_path"],
                "source_status": DataSourceStatus.LIVE,
            },
        ]

        results = await process_all_cameras_vision(cams, storage_dir=test_workspace["dir"])
        assert len(results) == 2
        assert results[0].cam_id == "batch_cam_1"
        assert results[1].cam_id == "batch_cam_2"
        assert results[1].risk_level == RiskLevel.UNKNOWN

