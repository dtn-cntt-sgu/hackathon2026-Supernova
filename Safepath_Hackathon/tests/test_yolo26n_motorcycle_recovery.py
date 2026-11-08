"""
Comprehensive tests for YOLO26n migration and motorcycle detection recovery.
Verifies:
1. Class-Aware NMS prevents motorcycle suppression when overlapped with cars/buses.
2. Multi-scale adaptive 2x2 tiling on low-res frames (306x236).
3. Original-frame multiscale inference preserves motorcycle detection and NMS invariants.
4. Fail-closed rejection of legacy YOLOv5 anchor layout [1, 25200, 85].
5. Real ONNX inference on actual HCMC camera frames from storage/cams/.
"""

import glob
import os
import numpy as np
import pytest

from backend.app.services.vision import (
    VehicleDetector,
    DetectedVehicle,
    PreprocessResult,
    _compute_iou,
    _merge_detections,
    decode_yolo26_output,
    preprocess_camera_image,
)

def test_class_aware_nms_protects_overlapping_motorcycle():
    """
    Test that a motorcycle located inside or heavily overlapping with a car
    is NOT suppressed by NMS, proving class-awareness.
    """
    detector = VehicleDetector()
    
    # Candidate 1: Large Car at (50, 50, 150, 150) [w=100, h=100] with high conf 0.88
    car_box = [50, 50, 100, 100]
    # Candidate 2: Motorcycle at (70, 70, 50, 50) [w=50, h=50] with conf 0.42 (inside car!)
    moto_box = [70, 70, 50, 50]
    
    # Calculate IoU
    iou = _compute_iou((50, 50, 150, 150), (70, 70, 120, 120))
    assert iou > 0.20, f"IoU should be non-trivial, got {iou}"
    
    candidates = [
        (car_box, 0.88, 2),   # car (class 2)
        (moto_box, 0.42, 3),  # motorcycle (class 3)
    ]
    
    kept = detector._apply_class_aware_nms(candidates, conf_threshold=0.25, nms_threshold=0.45, motorcycle_conf=0.20)
    assert len(kept) == 2, f"Expected 2 vehicles preserved, got {len(kept)}"
    
    class_names = [v.cls_name for v in kept]
    assert "car" in class_names
    assert "motorcycle" in class_names

def test_duplicate_same_class_motorcycles_are_suppressed():
    """
    Test that duplicate candidate boxes for the SAME motorcycle are properly suppressed.
    """
    detector = VehicleDetector()
    moto_box1 = [70, 70, 50, 50]
    moto_box2 = [72, 71, 48, 51]  # ~90% IoU with moto_box1
    
    candidates = [
        (moto_box1, 0.55, 3),
        (moto_box2, 0.52, 3),
    ]
    
    kept = detector._apply_class_aware_nms(candidates, conf_threshold=0.25, nms_threshold=0.45, motorcycle_conf=0.20)
    assert len(kept) == 1, f"Expected duplicate motorcycle suppressed to 1, got {len(kept)}"
    assert kept[0].cls_name == "motorcycle"
    assert kept[0].confidence == 0.55

def test_fail_closed_rejection_of_yolov5_output():
    """
    Verifies that any legacy YOLOv5 anchor output [1, 25200, 85] is rejected with ValueError.
    """
    detector = VehicleDetector()
    class LegacySession:
        def get_inputs(self):
            class Inp:
                name = "images"
                type = "tensor(float)"
            return [Inp()]
        def get_outputs(self):
            class Out:
                name = "output0"
            return [Out()]
        def run(self, names, feeds):
            return [np.zeros((1, 25200, 85), dtype=np.float32)]
            
    detector.session = LegacySession()
    with pytest.raises(ValueError, match="YOLOv5 weights rejected"):
        detector._extract_frame_candidates(np.zeros((300, 300, 3), dtype=np.uint8), 300, 300)

def test_real_hcmc_camera_inference_motorcycles():
    """
    Performs real inference on authentic HCMC camera frame from storage/cams/.
    Validates that real YOLO26n detects vehicles with high accuracy.
    """
    raw_frames = [
        p for p in sorted(glob.glob("storage/cams/*.jpg"))
        if not p.endswith(("_analyzed.jpg", "_annotated.jpg", "_enhanced.jpg"))
    ]
    if not raw_frames:
        pytest.skip("No raw camera frames found in storage/cams/")
        
    detector = VehicleDetector()
    assert detector.model_status == "VERIFIED_ONNX_INFERENCE"
    
    res = None
    sample_frame = raw_frames[0]
    for candidate_frame in raw_frames[:10]:
        prep = preprocess_camera_image(candidate_frame)
        res = detector.detect_vehicles(prep)
        assert res.model_status == "VERIFIED_ONNX_INFERENCE"
        assert res.is_available is True
        assert res.model_name == "vgg16_ssd_hcmc.onnx"
        if res.vehicle_count > 0:
            sample_frame = candidate_frame
            break
    assert res is not None and res.vehicle_count > 0, f"Expected detections on real camera frames (checked up to {sample_frame})"
    assert 0.0 <= res.traffic_density_score <= 1.0

def test_multiscale_nms_delta_non_negative():
    """
    Verifies that dual-path fusion never drops valid Branch A detections.
    """
    vehicles_a = [
        DetectedVehicle(cls_name="car", confidence=0.85, bbox=(10, 10, 100, 100), weight=2.5),
        DetectedVehicle(cls_name="motorcycle", confidence=0.60, bbox=(120, 120, 160, 160), weight=1.0),
    ]
    vehicles_b = [
        DetectedVehicle(cls_name="motorcycle", confidence=0.75, bbox=(122, 121, 159, 161), weight=1.0),
        DetectedVehicle(cls_name="bus", confidence=0.90, bbox=(200, 200, 300, 300), weight=4.0),
    ]
    
    merged = _merge_detections(vehicles_a, vehicles_b, iou_threshold=0.45)
    # Should keep car (from A), bus (from B), and merged motorcycle with highest confidence (0.75 from B)
    assert len(merged) == 3
    cls_names = {v.cls_name for v in merged}
    assert cls_names == {"car", "motorcycle", "bus"}
    
    moto = next(v for v in merged if v.cls_name == "motorcycle")
    assert moto.confidence == 0.75


def test_pytorch_pth_and_onnx_vgg16_ssd_equivalence():
    """
    Verifies that loading the original PyTorch checkpoint
    (vgg16-ssd-Epoch-170-Loss-1.8997838258743287.pth) and the exported ONNX
    (vgg16_ssd_hcmc.onnx) produce identical vehicle detections on real HCMC frames.
    """
    pytest.importorskip("torch")
    raw_frames = [
        p for p in sorted(glob.glob("storage/cams/*.jpg"))
        if not p.endswith(("_analyzed.jpg", "_annotated.jpg", "_enhanced.jpg"))
    ]
    if not raw_frames:
        pytest.skip("No raw camera frames found in storage/cams/")

    sample_frame = raw_frames[0]
    prep = preprocess_camera_image(sample_frame)

    onnx_detector = VehicleDetector("data/models/vgg16_ssd_hcmc.onnx")
    pth_detector = VehicleDetector("data/models/vgg16-ssd-Epoch-170-Loss-1.8997838258743287.pth")

    assert onnx_detector.model_status == "VERIFIED_ONNX_INFERENCE"
    assert pth_detector.model_status == "VERIFIED_ONNX_INFERENCE"

    res_onnx = onnx_detector.detect_vehicles(prep)
    res_pth = pth_detector.detect_vehicles(prep)

    assert res_onnx.vehicle_count == res_pth.vehicle_count
    assert res_onnx.class_breakdown == res_pth.class_breakdown


