"""Metric definitions independent of inference. Undefined denominators are null."""
from __future__ import annotations

import numpy as np

CLASSES = ("motorcycle", "car", "bus", "truck")


def divide(numerator, denominator):
    return float(numerator / denominator) if denominator else None


def binary_counts(prediction, target, region=None):
    prediction, target = np.asarray(prediction, dtype=bool), np.asarray(target, dtype=bool)
    if prediction.shape != target.shape or prediction.ndim != 2:
        raise ValueError("Prediction and mask must be equally sized 2D arrays")
    selected = np.ones(target.shape, dtype=bool) if region is None else np.asarray(region, dtype=bool)
    if selected.shape != target.shape or not selected.any():
        raise ValueError("Evaluation region must contain pixels and match mask")
    p, t = prediction[selected], target[selected]
    return {"tp": int(np.sum(p & t)), "fp": int(np.sum(p & ~t)),
            "fn": int(np.sum(~p & t)), "tn": int(np.sum(~p & ~t))}


def segmentation_metrics(counts):
    tp, fp, fn, tn = (counts[k] for k in ("tp", "fp", "fn", "tn"))
    return {**counts, "global_iou": divide(tp, tp + fp + fn),
            "dice_f1": divide(2 * tp, 2 * tp + fp + fn),
            "pixel_precision": divide(tp, tp + fp), "pixel_recall": divide(tp, tp + fn),
            "false_positive_rate": divide(fp, fp + tn), "false_negative_rate": divide(fn, fn + tp),
            "confusion_matrix": [[tn, fp], [fn, tp]], "confusion_labels": ["background", "water"]}


def aggregate_segmentation(rows):
    if not rows:
        return {"status": "NOT EVALUATED", "reason": "No annotated samples in this group", "samples": 0}
    result = segmentation_metrics({k: sum(row[k] for row in rows) for k in ("tp", "fp", "fn", "tn")})
    valid = [row["global_iou"] for row in rows if row["global_iou"] is not None]
    return {**result, "samples": len(rows), "mean_iou_per_image": float(np.mean(valid)) if valid else None,
            "mean_iou_defined_images": len(valid), "empty_union_images": len(rows) - len(valid)}


def box_iou(a, b):
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return divide(overlap, union) or 0.0


def _class_matches(predictions, targets, cls, iou_threshold):
    ground_truth = [t for t in targets if t["class"] == cls]
    candidates = sorted((p for p in predictions if p["class"] == cls), key=lambda p: -p["score"])
    used, matches = set(), []
    for prediction in candidates:
        eligible = [(box_iou(prediction["bbox"], truth["bbox"]), index)
                    for index, truth in enumerate(ground_truth)
                    if index not in used and truth["image_id"] == prediction["image_id"]]
        best = max(eligible, default=(0.0, -1))
        matched = best[0] >= iou_threshold
        if matched:
            used.add(best[1])
        matches.append(int(matched))
    return matches, len(ground_truth)


def average_precision(matches, ground_truth_count):
    """101-point interpolated AP; no GT -> undefined, GT but no predictions -> 0."""
    if ground_truth_count == 0:
        return None
    if not matches:
        return 0.0
    true_positive = np.cumsum(matches)
    recall = true_positive / ground_truth_count
    precision = true_positive / np.arange(1, len(matches) + 1)
    return float(np.mean([max(precision[recall >= r], default=0.0) for r in np.linspace(0, 1, 101)]))


def detection_metrics(predictions, targets, score_threshold=0.5):
    """Four classes, single-class 1:1 greedy matching; no COCO area/crowd/maxDet semantics."""
    thresholds = np.linspace(0.5, 0.95, 10)
    per_class = {}
    for cls in CLASSES:
        matches, total = _class_matches(predictions, targets, cls, 0.5)
        aps = [average_precision(_class_matches(predictions, targets, cls, float(threshold))[0], total)
               for threshold in thresholds]
        selected = [p for p in predictions if p["score"] >= score_threshold]
        fixed_matches, _ = _class_matches(selected, targets, cls, 0.5)
        tp, fp, fn = sum(fixed_matches), len(fixed_matches) - sum(fixed_matches), total - sum(fixed_matches)
        per_class[cls] = {"ground_truth_objects": total, "ap50": average_precision(matches, total),
                          "ap50_95": float(np.mean(aps)) if total else None,
                          "tp": tp, "fp": fp, "fn": fn, "precision": divide(tp, tp + fp),
                          "recall": divide(tp, tp + fn), "f1": divide(2 * tp, 2 * tp + fp + fn)}
    defined = [row for row in per_class.values() if row["ground_truth_objects"]]
    sums = {k: sum(row[k] for row in per_class.values()) for k in ("tp", "fp", "fn")}
    tp, fp, fn = (sums[k] for k in ("tp", "fp", "fn"))
    # Class-agnostic matching exposes class mistakes in the matrix; per-class counts above
    # count a class mistake as one FP and one FN. Matrix rows=true, columns=predicted.
    labels = [*CLASSES, "background"]
    matrix = np.zeros((5, 5), dtype=int)
    used = set()
    for prediction in sorted((p for p in predictions if p["score"] >= score_threshold), key=lambda p: -p["score"]):
        eligible = [(box_iou(prediction["bbox"], truth["bbox"]), index) for index, truth in enumerate(targets)
                    if index not in used and truth["image_id"] == prediction["image_id"]]
        best = max(eligible, default=(0, -1))
        true_cls = "background"
        if best[0] >= 0.5:
            used.add(best[1])
            true_cls = targets[best[1]]["class"]
        matrix[labels.index(true_cls), labels.index(prediction["class"])] += 1
    for index, truth in enumerate(targets):
        if index not in used:
            matrix[labels.index(truth["class"]), 4] += 1
    return {"map50": float(np.mean([row["ap50"] for row in defined])) if defined else None,
            "map50_95": float(np.mean([row["ap50_95"] for row in defined])) if defined else None,
            "classes_with_ground_truth": len(defined), "per_class": per_class, **sums,
            "precision": divide(tp, tp + fp), "recall": divide(tp, tp + fn),
            "f1": divide(2 * tp, 2 * tp + fp + fn), "score_threshold": score_threshold,
            "confusion_matrix": matrix.tolist(), "confusion_labels": labels,
            "ap_protocol": "101 recall points; IoU .50:.05:.95; greedy score-ordered same-class one-to-one; macro over classes with GT; production-filtered detections, not COCO official evaluator"}
