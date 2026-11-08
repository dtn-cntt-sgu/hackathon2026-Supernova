"""
SafePathAI Flood Segmentation ONNX Exporter & Manifest Updater.

Exports trained PyTorch FloodUNet to ONNX:
- Input: 'input', shape [1, 3, 256, 256], float32
- Output: 'output', shape [1, 1, 256, 256], float32
- Validates exported ONNX via onnx.checker and onnxruntime.
- Computes SHA-256 and file size.
- Updates data/models/model_manifest.json with verified metrics.
"""

import os
import sys
sys.path.insert(0, os.path.abspath("."))
import argparse
import hashlib
import json
import torch
import onnx
import onnxruntime as ort
import numpy as np

from scripts.ml.model import FloodUNet
from scripts.ml.evaluate_flood_model import evaluate_checkpoint


def export_and_update_manifest(
    checkpoint_path: str = "data/models/flood_unet_checkpoint.pt",
    onnx_path: str = "data/models/flood_unet.onnx",
    manifest_path: str = "data/models/model_manifest.json",
    data_dir: str = "data/datasets/flood_segmentation",
):
    print(f"Loading checkpoint from: {checkpoint_path}")
    device = torch.device("cpu")
    model = FloodUNet()
    checkpoint = torch.load(checkpoint_path, map_location=device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    # 1. Run evaluation to get exact test metrics
    metrics = evaluate_checkpoint(data_dir=data_dir, checkpoint_path=checkpoint_path)
    assert metrics["mean_iou"] >= 0.70, f"IoU {metrics['mean_iou']} below 0.70 threshold"
    assert metrics["mean_f1"] >= 0.80, f"F1 {metrics['mean_f1']} below 0.80 threshold"

    # 2. Export to ONNX with static shape [1, 3, 256, 256]
    dummy_input = torch.randn(1, 3, 256, 256, dtype=torch.float32)
    os.makedirs(os.path.dirname(onnx_path), exist_ok=True)

    print(f"Exporting to ONNX: {onnx_path}")
    torch.onnx.export(
        model,
        dummy_input,
        onnx_path,
        export_params=True,
        opset_version=17,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["output"],
        dynamo=False,
    )

    # 3. Check ONNX model validity
    onnx_model = onnx.load(onnx_path)
    onnx.checker.check_model(onnx_model)
    print("ONNX model checker: PASSED")

    # 4. Verify ONNX Runtime inference
    session = ort.InferenceSession(onnx_path)
    input_meta = session.get_inputs()[0]
    output_meta = session.get_outputs()[0]

    assert input_meta.name == "input", f"Input name mismatch: {input_meta.name}"
    assert input_meta.shape == [1, 3, 256, 256], f"Input shape mismatch: {input_meta.shape}"
    assert output_meta.name == "output", f"Output name mismatch: {output_meta.name}"
    assert output_meta.shape == [1, 1, 256, 256], f"Output shape mismatch: {output_meta.shape}"

    test_in = np.random.randn(1, 3, 256, 256).astype(np.float32)
    test_out = session.run(["output"], {"input": test_in})[0]
    assert test_out.shape == (1, 1, 256, 256), f"Output shape mismatch: {test_out.shape}"
    print(f"ONNX Runtime inference verification: PASSED (Output min: {test_out.min():.2f}, max: {test_out.max():.2f})")

    # 5. Compute SHA-256 and byte size
    hasher = hashlib.sha256()
    with open(onnx_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    sha256_hex = hasher.hexdigest()
    size_bytes = os.path.getsize(onnx_path)

    print(f"Exported ONNX SHA-256: {sha256_hex}")
    print(f"Exported ONNX Size:    {size_bytes} bytes ({size_bytes / 1024 / 1024:.2f} MB)")

    # 6. Update model_manifest.json
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    manifest["models"]["flood_segmenter"] = {
        "model_name": "flood_unet.onnx",
        "model_type": "SEMANTIC_SEGMENTATION",
        "version": "1.0.0-hcmc-flood",
        "format": "ONNX",
        "file_path": "data/models/flood_unet.onnx",
        "sha256": sha256_hex,
        "size_bytes": size_bytes,
        "source_url": "local://scripts/ml/export_flood_onnx.py",
        "license": "SafePathAI Proprietary / Apache-2.0",
        "training_dataset": "HCMC Urban Road Flood & Tidal Overflow Dataset (Balanced Road / Murky Water / Rain Sheen)",
        "target_classes": {
            "0": "background_road",
            "1": "surface_water"
        },
        "expected_input": {
            "name": "input",
            "shape": [1, 3, 256, 256],
            "dtype": "float32",
            "normalization": "RGB [0.0, 1.0]"
        },
        "expected_output": {
            "name": "output",
            "shape": [1, 1, 256, 256],
            "dtype": "float32"
        },
        "benchmark_metrics": {
            "iou": metrics["mean_iou"],
            "f1_score": metrics["mean_f1"],
            "precision": metrics["mean_prec"],
            "recall": metrics["mean_rec"],
            "validation_dataset": f"HCMC Flood Test Split ({metrics['test_samples']} annotated frames)",
            "rain_night_review_status": metrics["rain_night_review_status"],
            "evaluation_scope": metrics["scope"]
        },
        "provenance_status": "VALIDATED_HCMC_ROAD_FLOOD",
        "deployment_validation": "PRODUCTION_HCMC_ROAD_SURFACE"
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Updated {manifest_path} with VALIDATED_HCMC_ROAD_FLOOD provenance!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="data/models/flood_unet_checkpoint.pt")
    parser.add_argument("--onnx_path", default="data/models/flood_unet.onnx")
    parser.add_argument("--manifest", default="data/models/model_manifest.json")
    parser.add_argument("--data_dir", default="data/datasets/flood_segmentation")
    args = parser.parse_args()

    export_and_update_manifest(args.checkpoint, args.onnx_path, args.manifest, args.data_dir)
