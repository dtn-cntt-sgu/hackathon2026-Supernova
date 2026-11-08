#!/usr/bin/env python3
"""
Export and verification script for HCMC-finetuned VGG16-SSD vehicle detection model
from https://github.com/LeNguyenGiaBao/vehicle_detection
Trained on 2,586 HCMC traffic camera frames (16,753 annotated objects: motorcycle, car, bus, truck).
"""

import collections
import hashlib
import itertools
import math
import os
from typing import List, Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

SSDBoxSizes = collections.namedtuple("SSDBoxSizes", ["min", "max"])
SSDSpec = collections.namedtuple("SSDSpec", ["feature_map_size", "shrinkage", "box_sizes", "aspect_ratios"])
GraphPath = collections.namedtuple("GraphPath", ["s0", "name", "s1"])

CLASS_NAMES = ["BACKGROUND", "motorcycle", "car", "bus", "truck"]
IMAGE_SIZE = 300
IMAGE_MEAN = np.array([123.0, 117.0, 104.0], dtype=np.float32)
IMAGE_STD = 1.0
IOU_THRESHOLD = 0.45
CENTER_VARIANCE = 0.1
SIZE_VARIANCE = 0.2

SPECS = [
    SSDSpec(38, 8, SSDBoxSizes(30, 60), [2]),
    SSDSpec(19, 16, SSDBoxSizes(60, 111), [2, 3]),
    SSDSpec(10, 32, SSDBoxSizes(111, 162), [2, 3]),
    SSDSpec(5, 64, SSDBoxSizes(162, 213), [2, 3]),
    SSDSpec(3, 100, SSDBoxSizes(213, 264), [2]),
    SSDSpec(1, 300, SSDBoxSizes(264, 315), [2]),
]


def generate_ssd_priors(specs: List[SSDSpec], image_size: int = 300, clamp: bool = True) -> torch.Tensor:
    priors = []
    for spec in specs:
        scale = image_size / spec.shrinkage
        for j, i in itertools.product(range(spec.feature_map_size), repeat=2):
            x_center = (i + 0.5) / scale
            y_center = (j + 0.5) / scale

            size = spec.box_sizes.min
            h = w = size / image_size
            priors.append([x_center, y_center, w, h])

            size = math.sqrt(spec.box_sizes.max * spec.box_sizes.min)
            h = w = size / image_size
            priors.append([x_center, y_center, w, h])

            size = spec.box_sizes.min
            h = w = size / image_size
            for ratio in spec.aspect_ratios:
                ratio = math.sqrt(ratio)
                priors.append([x_center, y_center, w * ratio, h / ratio])
                priors.append([x_center, y_center, w / ratio, h * ratio])

    priors_tensor = torch.tensor(priors, dtype=torch.float32)
    if clamp:
        torch.clamp(priors_tensor, 0.0, 1.0, out=priors_tensor)
    return priors_tensor


PRIORS = generate_ssd_priors(SPECS, IMAGE_SIZE)


def convert_locations_to_boxes(
    locations: torch.Tensor,
    priors: torch.Tensor,
    center_variance: float,
    size_variance: float,
) -> torch.Tensor:
    if priors.dim() + 1 == locations.dim():
        priors = priors.unsqueeze(0)
    return torch.cat(
        [
            locations[..., :2] * center_variance * priors[..., 2:] + priors[..., :2],
            torch.exp(locations[..., 2:] * size_variance) * priors[..., 2:],
        ],
        dim=locations.dim() - 1,
    )


def center_form_to_corner_form(locations: torch.Tensor) -> torch.Tensor:
    return torch.cat(
        [
            locations[..., :2] - locations[..., 2:] / 2.0,
            locations[..., :2] + locations[..., 2:] / 2.0,
        ],
        locations.dim() - 1,
    )


def vgg() -> nn.ModuleList:
    cfgs = [64, 64, "M", 128, 128, "M", 256, 256, 256, "C", 512, 512, 512, "M", 512, 512, 512]
    layers = []
    in_channels = 3
    for cfg in cfgs:
        if cfg == "M":
            layers += [nn.MaxPool2d(kernel_size=2, stride=2)]
        elif cfg == "C":
            layers += [nn.MaxPool2d(kernel_size=2, stride=2, ceil_mode=True)]
        else:
            conv2d = nn.Conv2d(in_channels, cfg, kernel_size=3, padding=1)
            layers += [conv2d, nn.ReLU(inplace=True)]
            in_channels = cfg
    pool5 = nn.MaxPool2d(kernel_size=3, stride=1, padding=1)
    conv6 = nn.Conv2d(512, 1024, kernel_size=3, padding=6, dilation=6)
    conv7 = nn.Conv2d(1024, 1024, kernel_size=1)
    layers += [pool5, conv6, nn.ReLU(inplace=True), conv7, nn.ReLU(inplace=True)]
    return nn.ModuleList(layers)


def extras_module() -> nn.ModuleList:
    return nn.ModuleList(
        [
            nn.Sequential(
                nn.Conv2d(in_channels=1024, out_channels=256, kernel_size=1),
                nn.ReLU(),
                nn.Conv2d(in_channels=256, out_channels=512, kernel_size=3, stride=2, padding=1),
                nn.ReLU(),
            ),
            nn.Sequential(
                nn.Conv2d(in_channels=512, out_channels=128, kernel_size=1),
                nn.ReLU(),
                nn.Conv2d(in_channels=128, out_channels=256, kernel_size=3, stride=2, padding=1),
                nn.ReLU(),
            ),
            nn.Sequential(
                nn.Conv2d(in_channels=256, out_channels=128, kernel_size=1),
                nn.ReLU(),
                nn.Conv2d(in_channels=128, out_channels=256, kernel_size=3),
                nn.ReLU(),
            ),
            nn.Sequential(
                nn.Conv2d(in_channels=256, out_channels=128, kernel_size=1),
                nn.ReLU(),
                nn.Conv2d(in_channels=128, out_channels=256, kernel_size=3),
                nn.ReLU(),
            ),
        ]
    )


def loc_conf_module(num_classes: int = 5, bbox_ratio_num: List[int] = [4, 6, 6, 6, 4, 4]):
    loc_layers = []
    conf_layers = []
    channels = [512, 1024, 512, 256, 256, 256]
    for ch, ratio_num in zip(channels, bbox_ratio_num):
        loc_layers.append(nn.Conv2d(ch, ratio_num * 4, kernel_size=3, padding=1))
        conf_layers.append(nn.Conv2d(ch, ratio_num * num_classes, kernel_size=3, padding=1))
    return nn.ModuleList(loc_layers), nn.ModuleList(conf_layers)


class SSD(nn.Module):
    def __init__(self, num_classes: int = 5, is_test: bool = True):
        super().__init__()
        self.num_classes = num_classes
        self.base_net = vgg()
        self.source_layer_indexes = [(23, nn.BatchNorm2d(512)), len(self.base_net)]
        self.extras = extras_module()
        self.regression_headers, self.classification_headers = loc_conf_module(self.num_classes)
        self.is_test = is_test
        self.source_layer_add_ons = nn.ModuleList(
            [t[1] for t in self.source_layer_indexes if isinstance(t, tuple) and not isinstance(t, GraphPath)]
        )
        self.register_buffer("priors", PRIORS.clone())

    def compute_header(self, i: int, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        confidence = self.classification_headers[i](x)
        confidence = confidence.permute(0, 2, 3, 1).contiguous()
        confidence = confidence.view(confidence.size(0), -1, self.num_classes)

        location = self.regression_headers[i](x)
        location = location.permute(0, 2, 3, 1).contiguous()
        location = location.view(location.size(0), -1, 4)
        return confidence, location

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        confidences = []
        locations = []
        start_layer_index = 0
        header_index = 0
        end_layer_index = 0
        for end_layer_index in self.source_layer_indexes:
            if isinstance(end_layer_index, tuple):
                added_layer = end_layer_index[1]
                end_layer_index = end_layer_index[0]
            else:
                added_layer = None
            for layer in self.base_net[start_layer_index:end_layer_index]:
                x = layer(x)
            y = added_layer(x) if added_layer is not None else x
            start_layer_index = end_layer_index
            confidence, location = self.compute_header(header_index, y)
            header_index += 1
            confidences.append(confidence)
            locations.append(location)

        for layer in self.base_net[end_layer_index:]:
            x = layer(x)

        for layer in self.extras:
            x = layer(x)
            confidence, location = self.compute_header(header_index, x)
            header_index += 1
            confidences.append(confidence)
            locations.append(location)

        confidences = torch.cat(confidences, 1)
        locations = torch.cat(locations, 1)

        confidences = F.softmax(confidences, dim=2)
        boxes = convert_locations_to_boxes(locations, self.priors, CENTER_VARIANCE, SIZE_VARIANCE)
        boxes = center_form_to_corner_form(boxes)
        # Concatenate [boxes (4), confidences (5)] -> shape [B, 8732, 9]
        return torch.cat([boxes, confidences], dim=2)

    def load(self, model_path: str) -> None:
        state_dict = torch.load(model_path, map_location="cpu", weights_only=True)
        self.load_state_dict(state_dict, strict=False)


def main():
    import onnx
    import onnxruntime as ort

    pth_path = "data/models/vgg16-ssd-Epoch-170-Loss-1.8997838258743287.pth"
    onnx_path = "data/models/vgg16_ssd_hcmc.onnx"

    print(f"[1/4] Loading PyTorch VGG16-SSD weights from {pth_path}...")
    net = SSD(num_classes=5, is_test=True)
    net.load(pth_path)
    net.eval()

    dummy = torch.zeros((1, 3, 300, 300), dtype=torch.float32)
    with torch.no_grad():
        pt_out = net(dummy).numpy()
    print(f"PyTorch output shape: {pt_out.shape}, dtype: {pt_out.dtype}")

    print(f"[2/4] Exporting to ONNX at {onnx_path}...")
    torch.onnx.export(
        net,
        dummy,
        onnx_path,
        input_names=["images"],
        output_names=["output0"],
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )

    print("[3/4] Validating ONNX model...")
    onnx_model = onnx.load(onnx_path)
    onnx.checker.check_model(onnx_model)

    session = ort.InferenceSession(onnx_path)
    ort_out = session.run(["output0"], {"images": dummy.numpy()})[0]
    max_diff = float(np.max(np.abs(pt_out - ort_out)))
    print(f"ONNX vs PyTorch max abs diff: {max_diff:.6e}")
    assert max_diff < 1e-4, f"Max diff too large: {max_diff}"

    file_size = os.path.getsize(onnx_path)
    hasher = hashlib.sha256()
    with open(onnx_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    sha256_hash = hasher.hexdigest()

    print(f"[4/4] Export complete!")
    print(f"  Path:    {onnx_path}")
    print(f"  Size:    {file_size} bytes ({file_size / (1024*1024):.2f} MB)")
    print(f"  SHA-256: {sha256_hash}")


if __name__ == "__main__":
    main()
