"""
SafePathAI Flood Segmentation Model Evaluation Tool.

Evaluates trained checkpoint on held-out test split:
- Computes pooled global IoU, mean per-image IoU, Precision, Recall and F1.
- Does not certify rain/night or deployment accuracy without labelled provenance.
"""

import os
import sys
sys.path.insert(0, os.path.abspath("."))
import argparse


def evaluate_checkpoint(
    data_dir: str = "data/datasets/flood_segmentation",
    checkpoint_path: str = "data/models/flood_unet_checkpoint.pt",
) -> dict:
    import torch
    from torch.utils.data import DataLoader
    from scripts.ml.model import FloodUNet
    from scripts.ml.train_flood_model import FloodDataset

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Evaluating checkpoint: {checkpoint_path} on {device}")

    test_ds = FloodDataset(data_dir, "test")
    if not len(test_ds):
        raise ValueError("No labelled test images: accuracy NOT EVALUATED")
    test_loader = DataLoader(test_ds, batch_size=1, shuffle=False)

    model = FloodUNet().to(device)
    checkpoint = torch.load(checkpoint_path, map_location=device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    total_intersection = 0
    total_pred = 0
    total_target = 0
    count = 0
    per_image_iou = []

    with torch.no_grad():
        for imgs, masks in test_loader:
            imgs, masks = imgs.to(device), masks.to(device)
            probs = torch.sigmoid(model(imgs))
            preds = (probs >= 0.5).float()

            inter = (preds * masks).sum().item()
            p = preds.sum().item()
            t = masks.sum().item()

            total_intersection += inter
            total_pred += p
            total_target += t
            union_image = p + t - inter
            if union_image:
                per_image_iou.append(inter / union_image)
            count += 1

    union = total_pred + total_target - total_intersection
    dataset_iou = total_intersection / max(1e-6, union)
    precision = total_intersection / max(1e-6, total_pred)
    recall = total_intersection / max(1e-6, total_target)
    dataset_f1 = 2.0 * precision * recall / max(1e-6, (precision + recall))

    print("==================================================")
    print(" FLOOD MODEL EVALUATION RESULTS (TEST SPLIT)")
    print("==================================================")
    print(f"Test samples:     {count}")
    print(f"Global IoU:         {dataset_iou:.4f} (Threshold >= 0.70)")
    print(f"F1-Score:         {dataset_f1:.4f} (Threshold >= 0.80)")
    print(f"Pixel Precision:   {precision:.4f}")
    print(f"Pixel Recall:      {recall:.4f}")
    print("Rain/Night Review: NOT EVALUATED (no subgroup annotations supplied)")
    print("Scope: checkpoint full-image threshold .5; NOT deployment ROI evaluation or field accuracy")
    print("==================================================")

    return {
        "global_iou": round(dataset_iou, 4),
        "mean_iou_per_image": sum(per_image_iou) / len(per_image_iou) if per_image_iou else None,
        # Legacy exporter aliases: these are pooled global values, not means over images.
        "mean_iou": round(dataset_iou, 4),
        "mean_f1": round(dataset_f1, 4),
        "mean_prec": round(precision, 4),
        "mean_rec": round(recall, 4),
        "test_samples": count,
        "rain_night_review_status": "NOT EVALUATED",
        "scope": "Legacy checkpoint evaluation; provenance and deployment parity not verified",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-manifest", type=str, help="Use explicit provenance manifest and deployed ONNX pipeline")
    parser.add_argument("--output", default="reports/hackathon-benchmark")
    parser.add_argument("--data_dir", default="data/datasets/flood_segmentation")
    parser.add_argument("--checkpoint", default="data/models/flood_unet_checkpoint.pt")
    args = parser.parse_args()

    if args.dataset_manifest:
        from pathlib import Path
        from scripts.benchmark_eval.evaluation import evaluate_flood
        print(evaluate_flood(Path(args.output), Path(args.dataset_manifest)))
    else:
        evaluate_checkpoint(args.data_dir, args.checkpoint)
