"""Explicit local annotation manifest. No downloads or inferred human labels."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .metrics import CLASSES

GROUPS = ("dry", "wet", "flooded", "rain", "night")


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _local_file(base, value):
    if not isinstance(value, str) or not value or "://" in value:
        raise ValueError("Dataset paths must reference existing local files")
    path = (base / value).resolve()
    if not path.is_file():
        raise ValueError(f"Missing dataset file: {value}")
    return path


def load_dataset(manifest_path, task):
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text())
    for field in ("dataset_id", "source", "license", "annotation_source"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"Missing provenance field: {field}")
    if manifest.get("task") != task or manifest.get("annotation_type") not in ("human", "synthetic"):
        raise ValueError("Specify task flood/vehicle and annotation_type human/synthetic")
    if not isinstance(manifest.get("records"), list) or not manifest["records"]:
        raise ValueError("No labelled records supplied")
    records, seen_ids, hashes, cameras = [], set(), {}, {}
    for raw in manifest["records"]:
        record = dict(raw)
        if not isinstance(record.get("id"), str) or not record["id"] or record["id"] in seen_ids:
            raise ValueError("Every record needs a unique nonempty string id")
        seen_ids.add(record["id"])
        if record.get("split") not in ("train", "val", "test"):
            raise ValueError("Every record needs explicit train/val/test split")
        record["image"] = _local_file(path.parent, record.get("image"))
        with Image.open(record["image"]) as image:
            width, height = image.size
            # Also detect equal decoded pixels in differently encoded files.
            pixel_hash = hashlib.sha256(image.convert("RGB").tobytes() + str(image.size).encode()).hexdigest()
        record["sha256"] = file_sha256(record["image"])
        for digest in (record["sha256"], pixel_hash):
            prior = hashes.setdefault(digest, set())
            if record["split"] in prior:
                raise ValueError("Duplicate image content within split")
            prior.add(record["split"])
        camera = record.get("camera_id")
        if camera:
            cameras.setdefault(str(camera), set()).add(record["split"])
        groups = record.get("groups", [])
        if not isinstance(groups, list) or any(g not in GROUPS for g in groups):
            raise ValueError("groups must list dry/wet/flooded/rain/night")
        if record["split"] == "test":
            if task == "flood":
                record["mask"] = _local_file(path.parent, record.get("mask"))
                with Image.open(record["mask"]) as mask_image:
                    if mask_image.mode not in ("1", "L"):
                        raise ValueError("Masks must be binary grayscale, not RGB/palette")
                    mask = np.asarray(mask_image)
                if mask.shape != (height, width) or not set(np.unique(mask)).issubset({0, 1, 255}):
                    raise ValueError("Mask must match original image size and use only 0/1/255")
            else:
                if not isinstance(record.get("boxes"), list):
                    raise ValueError("Vehicle test records require boxes (empty list = reviewed negative)")
                for box in record["boxes"]:
                    bounds = box.get("bbox")
                    if box.get("class") not in CLASSES or not isinstance(bounds, list) or len(bounds) != 4:
                        raise ValueError("Boxes require supported class and [x1,y1,x2,y2]")
                    if not all(isinstance(v, (float, int)) and not isinstance(v, bool) and np.isfinite(v) for v in bounds):
                        raise ValueError("Bounding boxes must contain finite pixel coordinates")
                    x1, y1, x2, y2 = bounds
                    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                        raise ValueError("Box outside image or has zero/negative area")
        records.append(record)
    if any("test" in splits and len(splits) > 1 for splits in hashes.values()):
        raise ValueError("Content leakage between test and train/val")
    if any("test" in splits and len(splits) > 1 for splits in cameras.values()):
        raise ValueError("Camera grouping leakage between test and train/val")
    tests = [record for record in records if record["split"] == "test"]
    if not tests:
        raise ValueError("No test records available")
    references = sum(record["split"] != "test" for record in records)
    audit = {"dataset_id": manifest["dataset_id"], "manifest_sha256": file_sha256(path),
             "source": manifest["source"], "license": manifest["license"],
             "annotation_type": manifest["annotation_type"], "annotation_source": manifest["annotation_source"],
             "test_samples": len(tests), "reference_train_val_samples": references,
             "content_duplicates": 0, "camera_overlap": 0,
             "training_independence": "UNKNOWN: checked only supplied references, not the original model training corpus",
             "camera_groups_known": sum(bool(record.get("camera_id")) for record in tests),
             "public_examples_authorized": manifest.get("allow_public_examples") is True,
             "scope": "Synthetic controlled samples; not field accuracy" if manifest["annotation_type"] == "synthetic" else "Declared human annotations; independent field validation is not established by this manifest"}
    return tests, audit


def write_template(output, task):
    payload = {"dataset_id": "REPLACE", "task": task, "source": "REPLACE with origin and acquisition date",
               "license": "REPLACE with permission/license", "annotation_type": "human",
               "annotation_source": "REPLACE with annotator/review protocol", "allow_public_examples": False,
               "records": []}
    Path(output).write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", choices=["flood", "vehicle"], required=True)
    args = parser.parse_args()
    write_template(args.output, args.task)
