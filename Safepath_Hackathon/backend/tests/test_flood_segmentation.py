"""
Test Suite for SafePathAI Flood Water Semantic Segmentation AI Pipeline.

Covers:
1. Model Manifest Verification: SHA-256, byte size, input/output tensor dimensions.
2. ONNX Weight Loading: FloodSegmenter initializes with VERIFIED_ONNX_INFERENCE and VALIDATED_HCMC_ROAD_FLOOD provenance.
3. Inference on Dry Road: Verifies no false-positive flood detection on asphalt.
4. Inference on Flooded Road: Detects water mask and calculates flood_ratio correctly.
5. Road ROI Masking: Ensures water pixels outside designated road polygon are zeroed.
6. Latency SLA: Validates p95 inference latency <= 50ms on standard CPU.
"""

import os
import time
import cv2
import numpy as np
import pytest

from backend.app.services.vision import (
    DEFAULT_FLOOD_UNET_PATH,
    FloodSegmenter,
    PreprocessResult,
    preprocess_camera_image,
    verified_model_manifest_entry,
)
from scripts.ml.prepare_flood_dataset import generate_synthetic_road_flood_sample


def test_flood_model_manifest_integrity():
    """Validates manifest SHA-256, dimensions, and benchmark metrics."""
    assert os.path.exists(DEFAULT_FLOOD_UNET_PATH), f"Missing ONNX file: {DEFAULT_FLOOD_UNET_PATH}"
    entry = verified_model_manifest_entry("flood_segmenter", DEFAULT_FLOOD_UNET_PATH)
    assert entry is not None, "Failed model manifest verification"

    assert entry["provenance_status"] == "VALIDATED_HCMC_ROAD_FLOOD"
    assert entry["expected_input"]["shape"] == [1, 3, 256, 256]
    assert entry["expected_output"]["shape"] == [1, 1, 256, 256]

    metrics = entry["benchmark_metrics"]
    assert metrics["iou"] >= 0.70, f"IoU {metrics['iou']} < 0.70"
    assert metrics["f1_score"] >= 0.80, f"F1 {metrics['f1_score']} < 0.80"
    assert metrics["rain_night_reflection_reviewed"] is True
    assert entry.get("validation_scope") == "CONTROLLED_SYNTHETIC_AND_CURATED_HCMC_TEST_SPLIT"
    assert entry.get("field_calibration_status") == "PENDING_LIVE_FIELD_CALIBRATION"

    veh_entry = verified_model_manifest_entry("vehicle_detector", "data/models/vgg16_ssd_hcmc.onnx")
    assert veh_entry is not None
    assert veh_entry.get("validation_scope") == "HCMUTE_VOC_CHECKPOINT_EPOCH_170_LOSS_1_8998"
    assert veh_entry.get("field_calibration_status") == "VALIDATED_ON_PUBLIC_HCMC_VOC_DATASET"


def test_flood_segmenter_initialization():
    """Ensures FloodSegmenter loads official ONNX weights without fallback."""
    segmenter = FloodSegmenter(model_path=DEFAULT_FLOOD_UNET_PATH)
    assert segmenter.model_status == "VERIFIED_ONNX_INFERENCE"
    assert segmenter.provenance_status == "VALIDATED_HCMC_ROAD_FLOOD"
    assert segmenter.session is not None
    assert segmenter.model_sha256 is not None
    assert len(segmenter.model_sha256) == 64


def _make_dummy_prep(img: np.ndarray, roi_mask: np.ndarray) -> PreprocessResult:
    h, w = img.shape[:2]
    return PreprocessResult(
        original_image=img,
        roi_mask=roi_mask,
        roi_image=cv2.bitwise_and(img, img, mask=roi_mask),
        roi_pixel_count=int(np.count_nonzero(roi_mask)),
        mean_luminance=100.0,
        laplacian_var=100.0,
        is_dark=False,
        is_blurry=False,
        height=h,
        width=w,
    )


def test_flood_inference_dry_road():
    """Validates that dry road image produces zero or near-zero flood ratio."""
    segmenter = FloodSegmenter(model_path=DEFAULT_FLOOD_UNET_PATH)

    dry_img, _ = generate_synthetic_road_flood_sample(
        is_flooded=False, is_wet_sheen_negative=False, img_size=256
    )
    h, w = dry_img.shape[:2]
    roi_mask = np.ones((h, w), dtype=np.uint8) * 255

    prep = _make_dummy_prep(dry_img, roi_mask)

    result = segmenter.segment_flood_water(prep)
    assert result.model_status == "VERIFIED_ONNX_INFERENCE"
    assert result.is_available is True
    assert result.flood_ratio is not None
    assert result.flood_ratio <= 0.05, f"False positive flood on dry road: {result.flood_ratio}"


def test_flood_inference_flooded_street():
    """Validates that flooded scene produces positive flood ratio and water mask."""
    segmenter = FloodSegmenter(model_path=DEFAULT_FLOOD_UNET_PATH)

    flood_img, ground_truth_mask = generate_synthetic_road_flood_sample(
        is_flooded=True, flood_depth_level="MODERATE", img_size=256
    )
    h, w = flood_img.shape[:2]
    roi_mask = np.ones((h, w), dtype=np.uint8) * 255

    prep = _make_dummy_prep(flood_img, roi_mask)

    result = segmenter.segment_flood_water(prep)
    assert result.model_status == "VERIFIED_ONNX_INFERENCE"
    assert result.is_available is True
    assert result.flood_ratio is not None
    assert result.flood_ratio >= 0.15, f"Failed to detect water, ratio: {result.flood_ratio}"
    assert result.water_mask is not None
    assert result.water_pixel_count > 0


def test_flood_inference_roi_masking():
    """Ensures pixels outside ROI mask are strictly ignored."""
    segmenter = FloodSegmenter(model_path=DEFAULT_FLOOD_UNET_PATH)

    flood_img, _ = generate_synthetic_road_flood_sample(
        is_flooded=True, flood_depth_level="SEVERE", img_size=256
    )
    h, w = flood_img.shape[:2]

    # Create restricted ROI covering only upper half of roadway (where water hasn't reached)
    restricted_roi = np.zeros((h, w), dtype=np.uint8)
    restricted_roi[: int(h * 0.35), :] = 255

    prep = _make_dummy_prep(flood_img, restricted_roi)

    result = segmenter.segment_flood_water(prep)
    assert result.water_mask is not None
    # All pixels outside restricted_roi must be 0
    outside_roi = cv2.bitwise_and(result.water_mask, cv2.bitwise_not(restricted_roi))
    assert np.count_nonzero(outside_roi) == 0


def test_flood_inference_latency_sla():
    """Validates p95 inference latency <= 50ms."""
    segmenter = FloodSegmenter(model_path=DEFAULT_FLOOD_UNET_PATH)

    dummy_img = np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8)
    h, w = dummy_img.shape[:2]
    roi_mask = np.ones((h, w), dtype=np.uint8) * 255

    prep = _make_dummy_prep(dummy_img, roi_mask)

    # Warmup
    for _ in range(5):
        segmenter.segment_flood_water(prep)

    # Benchmark 30 runs
    latencies = []
    for _ in range(30):
        t0 = time.perf_counter()
        segmenter.segment_flood_water(prep)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    p95 = float(np.percentile(latencies, 95))
    assert p95 <= 50.0, f"p95 latency {p95:.2f}ms exceeds 50ms SLA"
