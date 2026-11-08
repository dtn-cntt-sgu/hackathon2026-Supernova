"""
HCMC Traffic Vehicle Detection Model (VGG16-SSD).
Ported and integrated from https://github.com/LeNguyenGiaBao/vehicle_detection
Finetuned on 2,586 HCMC traffic camera frames (giaothong.hochiminhcity.gov.vn)
with 16,753 annotated objects across 4 classes:
- 1: motorcycle (12,912 instances)
- 2: car (2,085 instances)
- 3: bus (411 instances)
- 4: truck (1,345 instances)
"""

import collections
import itertools
import math
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

SSDBoxSizes = collections.namedtuple("SSDBoxSizes", ["min", "max"])
SSDSpec = collections.namedtuple("SSDSpec", ["feature_map_size", "shrinkage", "box_sizes", "aspect_ratios"])
GraphPath = collections.namedtuple("GraphPath", ["s0", "name", "s1"])

SSD_CLASS_NAMES: Tuple[str, ...] = ("BACKGROUND", "motorcycle", "car", "bus", "truck")

# Map SSD class index (1..4) -> (class_name, COCO-compatible class_id, density_weight)
SSD_TO_VEHICLE_CLASS: Dict[int, Tuple[str, int, float]] = {
    1: ("motorcycle", 3, 1.0),
    2: ("car", 2, 2.5),
    3: ("bus", 5, 4.0),
    4: ("truck", 7, 4.0),
}

SSD_IMAGE_SIZE: int = 300
SSD_IMAGE_MEAN: np.ndarray = np.array([123.0, 117.0, 104.0], dtype=np.float32)  # RGB layout
SSD_IMAGE_STD: float = 1.0
SSD_IOU_THRESHOLD: float = 0.45
SSD_CENTER_VARIANCE: float = 0.1
SSD_SIZE_VARIANCE: float = 0.2
SSD_CANDIDATE_SIZE: int = 200

SSD_SPECS: List[SSDSpec] = [
    SSDSpec(38, 8, SSDBoxSizes(30, 60), [2]),
    SSDSpec(19, 16, SSDBoxSizes(60, 111), [2, 3]),
    SSDSpec(10, 32, SSDBoxSizes(111, 162), [2, 3]),
    SSDSpec(5, 64, SSDBoxSizes(162, 213), [2, 3]),
    SSDSpec(3, 100, SSDBoxSizes(213, 264), [2]),
    SSDSpec(1, 300, SSDBoxSizes(264, 315), [2]),
]


def preprocess_vgg16_ssd_frame(bgr_image: np.ndarray, dtype: type = np.float32) -> np.ndarray:
    """
    Applies the exact PredictionTransform from LeNguyenGiaBao/vehicle_detection:
    1. Convert BGR (OpenCV) to RGB layout (matching VOCDataset._read_image)
    2. Resize to 300x300
    3. Subtract RGB mean [123, 117, 104] and divide by std 1.0
    4. Transpose HWC -> NCHW [1, 3, 300, 300]
    """
    rgb_img = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb_img, (SSD_IMAGE_SIZE, SSD_IMAGE_SIZE))
    normalized = (resized.astype(np.float32) - SSD_IMAGE_MEAN) / SSD_IMAGE_STD
    chw = normalized.transpose(2, 0, 1)
    return np.ascontiguousarray(chw[None, ...], dtype=dtype)


def decode_vgg16_ssd_output(
    output: np.ndarray,
    conf_threshold: float = 0.20,
    candidate_size: int = SSD_CANDIDATE_SIZE,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, bool]:
    """
    Decodes VGG16-SSD ONNX output tensor of shape [1, 8732, 9]:
    - Columns 0..4: normalized corner coordinates [x1, y1, x2, y2] in [0.0, 1.0]
    - Columns 4..9: softmax class probabilities for [BACKGROUND, motorcycle, car, bus, truck]

    Returns (boxes_norm_xyxy, scores, coco_compatible_classes, needs_nms=True).
    """
    if output.ndim != 3 or output.shape[0] != 1 or output.shape[1:] != (8732, 9):
        raise ValueError(f"Unsupported VGG16-SSD output shape: {output.shape}")

    rows = output[0]
    valid_rows = np.isfinite(rows).all(axis=1)
    rows = rows[valid_rows]
    if len(rows) == 0:
        return (
            np.empty((0, 4), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int32),
            True,
        )

    boxes = rows[:, :4].astype(np.float32)
    probs = rows[:, 4:9].astype(np.float32)

    all_boxes: List[np.ndarray] = []
    all_scores: List[np.ndarray] = []
    all_classes: List[np.ndarray] = []

    for ssd_cid, (_, coco_cid, _) in SSD_TO_VEHICLE_CLASS.items():
        cls_probs = probs[:, ssd_cid]
        mask = cls_probs >= conf_threshold
        if not np.any(mask):
            continue
        cls_boxes = boxes[mask]
        cls_scores = cls_probs[mask]
        # Keep top candidate_size candidates per class as in original Predictor
        if len(cls_scores) > candidate_size:
            top_idx = np.argsort(cls_scores)[::-1][:candidate_size]
            cls_boxes = cls_boxes[top_idx]
            cls_scores = cls_scores[top_idx]
        all_boxes.append(cls_boxes)
        all_scores.append(cls_scores)
        all_classes.append(np.full(len(cls_scores), coco_cid, dtype=np.int32))

    if not all_boxes:
        return (
            np.empty((0, 4), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int32),
            True,
        )

    return (
        np.concatenate(all_boxes, axis=0),
        np.concatenate(all_scores, axis=0),
        np.concatenate(all_classes, axis=0),
        True,
    )


class PyTorchVGG16SSDSession:
    """
    ONNX-Runtime-compatible session wrapper around the native PyTorch VGG16-SSD model
    (`vgg16-ssd-Epoch-170-Loss-1.8997838258743287.pth`) so `.pth` weights can also be
    loaded directly into `VehicleDetector` if desired.
    """

    class _TensorMeta:
        def __init__(self, name: str, shape: List[int], type_str: str = "tensor(float)"):
            self.name = name
            self.shape = shape
            self.type = type_str

    def __init__(self, pth_path: str, device: Optional[str] = None):
        import torch
        from scripts.export_vgg16_ssd import SSD

        self.device = torch.device(device or ("cuda:0" if torch.cuda.is_available() else "cpu"))
        self.net = SSD(num_classes=len(SSD_CLASS_NAMES), is_test=True)
        self.net.load(pth_path)
        self.net.to(self.device)
        self.net.eval()

    def get_inputs(self):
        return [self._TensorMeta("images", [1, 3, 300, 300], "tensor(float)")]

    def get_outputs(self):
        return [self._TensorMeta("output0", [1, 8732, 9], "tensor(float)")]

    def run(self, output_names: List[str], input_feed: Dict[str, np.ndarray]) -> List[np.ndarray]:
        import torch

        blob = input_feed["images"]
        with torch.no_grad():
            tensor_in = torch.from_numpy(blob).to(self.device)
            out = self.net(tensor_in).cpu().numpy()
        return [out]
