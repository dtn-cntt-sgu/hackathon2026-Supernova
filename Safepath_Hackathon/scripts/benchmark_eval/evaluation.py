"""Evaluate deployed ONNX pipelines on explicitly supplied local ground truth."""
from __future__ import annotations

import csv
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .datasets import GROUPS, file_sha256, load_dataset
from .metrics import aggregate_segmentation, binary_counts, detection_metrics, segmentation_metrics

ROOT = Path(__file__).resolve().parents[2]


def _model_metadata(task):
    manifest = json.loads((ROOT / "data/models/model_manifest.json").read_text())
    entry = manifest["models"]["flood_segmenter" if task == "flood" else "vehicle_detector"]
    path = ROOT / entry["file_path"]
    actual = file_sha256(path) if path.is_file() else None
    return {"name": entry["model_name"], "version": entry["version"], "sha256": actual,
            "manifest_sha256": entry["sha256"], "hash_matches_manifest": actual == entry["sha256"],
            "supported_classes": entry["target_classes"]}


def _write(output, task, result):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result["measured_at"] = datetime.now(timezone.utc).isoformat()
    result["task"] = task
    (output / f"{task}_metrics.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def _csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["image_id"])
        writer.writeheader()
        writer.writerows(rows)


def _matrix(path, matrix, labels):
    size, margin = 85, 125
    image = Image.new("RGB", (margin + len(labels) * size + 25, margin + len(labels) * size + 40), "white")
    draw = ImageDraw.Draw(image)
    draw.text((10, 10), "Rows: ground truth | Columns: prediction", fill="black")
    maximum = max(1, max(max(row) for row in matrix))
    for i, label in enumerate(labels):
        draw.text((margin + i * size, margin - 22), label[:12], fill="black")
        draw.text((5, margin + i * size + 30), label[:15], fill="black")
        for j, value in enumerate(matrix[i]):
            shade = int(230 - 160 * value / maximum)
            draw.rectangle((margin + j * size, margin + i * size, margin + (j + 1) * size - 2,
                            margin + (i + 1) * size - 2), fill=(shade, shade, 250))
            draw.text((margin + j * size + 25, margin + i * size + 30), str(value), fill="black")
    image.save(path)


def _flood_examples(path, examples):
    canvas = Image.new("RGB", (4 * 256, len(examples) * 220), "white")
    draw = ImageDraw.Draw(canvas)
    for row, (original, truth, prediction) in enumerate(examples):
        errors = np.asarray(original).copy()
        errors[prediction & ~truth] = [255, 60, 60]
        errors[truth & ~prediction] = [60, 120, 255]
        images = [original, Image.fromarray(truth.astype("uint8") * 255).convert("RGB"),
                  Image.fromarray(prediction.astype("uint8") * 255).convert("RGB"), Image.fromarray(errors)]
        for col, (title, image) in enumerate(zip(["Original", "Ground Truth", "Prediction", "Errors: red FP / blue FN"], images)):
            draw.text((col * 256 + 5, row * 220 + 4), title, fill="black")
            image.thumbnail((256, 190))
            canvas.paste(image, (col * 256, row * 220 + 25))
    canvas.save(path)


def _setup(output, manifest, task):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Reusing an output directory must not retain examples from an older public run.
    for suffix in ("predictions.csv", "confusion_matrix.png", "examples.png"):
        (output / f"{task}_{suffix}").unlink(missing_ok=True)
    model = _model_metadata(task)
    if manifest is None:
        return output, None, {"status": "NOT EVALUATED", "reason": "No labelled test manifest supplied; no accuracy can be measured", "model": model}
    try:
        records, provenance = load_dataset(manifest, task)
    except (OSError, ValueError, TypeError, KeyError) as error:
        return output, None, {"status": "NOT EVALUATED", "reason": f"Invalid dataset ({type(error).__name__}); check the local manifest and annotation guide", "model": model}
    result = {"status": "LIMITED", "model": model, "dataset": provenance,
              "limitations": [provenance["scope"], provenance["training_independence"]],
              "artifacts": {"examples": "WITHHELD: source images are private by default"}}
    if not model["hash_matches_manifest"]:
        result.update(status="BLOCKED", reason="Deployment model is missing or differs from manifest")
        return output, None, result
    return output, records, result


def evaluate_flood(output: Path, dataset_manifest: Path | None = None):
    output, records, result = _setup(output, dataset_manifest, "flood")
    if records is None:
        return _write(output, "flood", result)
    try:
        from backend.app.services.vision import FloodSegmenter, preprocess_camera_image
        model = FloodSegmenter(fallback_to_heuristic=False)
        if model.model_status != "VERIFIED_ONNX_INFERENCE" or model.model_sha256 != result["model"]["sha256"]:
            raise RuntimeError("Verified FloodUNet ONNX unavailable; heuristic fallback prohibited")
        result["runtime"] = {"providers": model.session.get_providers(), "heuristic_fallback": False, "roi_top_crop_ratio": 0.25, "probability_threshold": 0.5}
        rows, examples = [], []
        for record in records:
            prep = preprocess_camera_image(str(record["image"]))
            inference = model.segment_flood_water(prep)
            if not inference.is_available or inference.water_mask is None or inference.model_status != "VERIFIED_ONNX_INFERENCE":
                raise RuntimeError("Flood inference failed; partial test set is not a complete accuracy benchmark")
            with Image.open(record["mask"]) as image:
                truth = np.asarray(image) > 0
            prediction = inference.water_mask > 0
            counts = binary_counts(prediction, truth, prep.roi_mask > 0)
            rows.append({"image_id": record["id"], "image_sha256": record["sha256"],
                         "groups": ",".join(record.get("groups", [])), **{k: v for k, v in segmentation_metrics(counts).items()
                         if k not in ("confusion_matrix", "confusion_labels")}})
            if result["dataset"]["public_examples_authorized"] and len(examples) < 4:
                with Image.open(record["image"]) as image:
                    examples.append((image.convert("RGB"), truth & (prep.roi_mask > 0), prediction))
        result["metrics"] = aggregate_segmentation(rows)
        result["groups"] = {group: aggregate_segmentation([row for row in rows if group in row["groups"].split(",")])
                            for group in GROUPS}
        result["method"] = "Production preprocess_camera_image + FloodSegmenter, sigmoid>=.5, top25% excluded from both GT and prediction; global metrics pool ROI pixels; mean IoU excludes empty unions (count reported)."
        result["checkpoint_onnx_parity"] = {"status": "BLOCKED" if importlib.util.find_spec("torch") is None else "NOT EVALUATED",
                                             "reason": "PyTorch unavailable" if importlib.util.find_spec("torch") is None else "Separate checkpoint parity comparison not run; deployment ONNX evaluated"}
        _csv(output / "flood_predictions.csv", rows)
        _matrix(output / "flood_confusion_matrix.png", result["metrics"]["confusion_matrix"], ["background", "water"])
        if examples:
            _flood_examples(output / "flood_examples.png", examples)
            result["artifacts"]["examples"] = "flood_examples.png"
    except Exception as error:
        result.update(status="BLOCKED", reason=f"Production inference failed ({type(error).__name__}); verify local model and dataset files")
    return _write(output, "flood", result)


def _vehicle_examples(path, examples):
    canvas = Image.new("RGB", (768, 240 * len(examples)), "white")
    draw = ImageDraw.Draw(canvas)
    for row, (original, truth, predictions) in enumerate(examples):
        for col, (title, boxes) in enumerate((("Ground Truth", truth), ("Production prediction", predictions))):
            image = original.copy()
            annotation = ImageDraw.Draw(image)
            for box in boxes:
                annotation.rectangle(box["bbox"], outline=(10, 210, 60) if col == 0 else (255, 100, 10), width=2)
                annotation.text(tuple(box["bbox"][:2]), box["class"], fill="white")
            image.thumbnail((384, 215))
            canvas.paste(image, (col * 384, row * 240 + 22))
            draw.text((col * 384 + 5, row * 240 + 4), title, fill="black")
    canvas.save(path)


def evaluate_vehicle(output: Path, dataset_manifest: Path | None = None, compare_baseline: bool = False):
    output, records, result = _setup(output, dataset_manifest, "vehicle")
    if records is None:
        return _write(output, "vehicle", result)
    try:
        from backend.app.services.vision import VehicleDetector, preprocess_camera_image
        model = VehicleDetector(fallback_to_heuristic=False)
        if model.model_status != "VERIFIED_ONNX_INFERENCE" or model.model_sha256 != result["model"]["sha256"]:
            raise RuntimeError("Verified VGG16-SSD unavailable; heuristic fallback prohibited")
        from backend.app.core.config import settings
        result["runtime"] = {"providers": model.session.get_providers(), "heuristic_fallback": False,
                             "confidence_threshold": 0.20, "motorcycle_confidence_threshold": min(0.20, settings.YOLO_MOTORCYCLE_CONF_THRESHOLD),
                             "nms_iou_threshold": 0.45}
        predictions, targets, baseline, rows, examples = [], [], [], [], []
        for record in records:
            prep = preprocess_camera_image(str(record["image"]))
            inferred = model.detect_vehicles(prep)
            if not inferred.is_available or inferred.model_status != "VERIFIED_ONNX_INFERENCE":
                raise RuntimeError("Vehicle inference failed; partial set is not scored")
            selected = [{"image_id": record["id"], "class": box.cls_name,
                         "bbox": list(box.bbox), "score": box.confidence} for box in inferred.vehicles]
            predictions.extend(selected)
            targets.extend({"image_id": record["id"], **box} for box in record["boxes"])
            rows.append({"image_id": record["id"], "image_sha256": record["sha256"],
                         "ground_truth_count": len(record["boxes"]), "prediction_count": len(selected),
                         "predictions": json.dumps(selected, separators=(",", ":"))})
            if compare_baseline:
                boxes = model._detect_onnx_frame(prep.original_image, prep.height, prep.width, conf_threshold=0.20)
                baseline.extend({"image_id": record["id"], "class": box.cls_name,
                                 "bbox": list(box.bbox), "score": box.confidence} for box in boxes)
            if result["dataset"]["public_examples_authorized"] and len(examples) < 4:
                with Image.open(record["image"]) as image:
                    examples.append((image.convert("RGB"), record["boxes"], selected))
        result["metrics"] = detection_metrics(predictions, targets)
        result["method"] = "Production VGG16-SSD adaptive tiling + class-aware NMS; AP uses retained production scores (confidence .20 except configured lower motorcycle threshold), PR/F1 at score>=.50 and IoU>=.50; original full-frame boxes. Not official COCO AP."
        result["baseline"] = {"status": "LIMITED", "name": "Same VGG16-SSD single-frame, same confidence .20 and NMS .45", "metrics": detection_metrics(baseline, targets)} if compare_baseline else {"status": "NOT EVALUATED", "reason": "Baseline comparison not requested"}
        _csv(output / "vehicle_predictions.csv", rows)
        _matrix(output / "vehicle_confusion_matrix.png", result["metrics"]["confusion_matrix"], result["metrics"]["confusion_labels"])
        if examples:
            _vehicle_examples(output / "vehicle_examples.png", examples)
            result["artifacts"]["examples"] = "vehicle_examples.png"
    except Exception as error:
        result.update(status="BLOCKED", reason=f"Production inference failed ({type(error).__name__}); verify local model and dataset files")
    return _write(output, "vehicle", result)
