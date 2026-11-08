"""
SafePathAI Flood Segmentation Model Training Loop.

Trains FloodUNet using combined BCE + Dice Loss to segment road flood water.
Monitors validation IoU and F1-score, saving the best model checkpoint.
"""

import os
import sys
sys.path.insert(0, os.path.abspath("."))
import argparse
import glob
import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from scripts.ml.model import FloodUNet


class FloodDataset(Dataset):
    def __init__(self, data_dir: str, split: str = "train"):
        self.img_paths = sorted(glob.glob(os.path.join(data_dir, split, "images", "*.png")))
        self.mask_paths = sorted(glob.glob(os.path.join(data_dir, split, "masks", "*.png")))
        assert len(self.img_paths) == len(self.mask_paths), f"Mismatch in {split} images and masks"

    def __len__(self):
        return len(self.img_paths)

    def __getitem__(self, idx):
        img_bgr = cv2.imread(self.img_paths[idx])
        mask_gray = cv2.imread(self.mask_paths[idx], cv2.IMREAD_GRAYSCALE)

        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        img_rgb = cv2.resize(img_rgb, (256, 256), interpolation=cv2.INTER_LINEAR)
        mask_gray = cv2.resize(mask_gray, (256, 256), interpolation=cv2.INTER_NEAREST)

        # Normalize image to [0, 1]
        img_tensor = torch.from_numpy(img_rgb).permute(2, 0, 1).float() / 255.0
        # Binary mask [0, 1]
        mask_tensor = torch.from_numpy((mask_gray > 127).astype(np.float32)).unsqueeze(0)

        return img_tensor, mask_tensor


def dice_loss(pred_logits: torch.Tensor, targets: torch.Tensor, smooth: float = 1e-5) -> torch.Tensor:
    probs = torch.sigmoid(pred_logits)
    probs_flat = probs.view(-1)
    targets_flat = targets.view(-1)
    intersection = (probs_flat * targets_flat).sum()
    dice = (2.0 * intersection + smooth) / (probs_flat.sum() + targets_flat.sum() + smooth)
    return 1.0 - dice


def compute_metrics(pred_logits: torch.Tensor, targets: torch.Tensor, threshold: float = 0.5):
    probs = torch.sigmoid(pred_logits)
    preds = (probs >= threshold).float()

    preds_flat = preds.view(-1)
    targets_flat = targets.view(-1)

    intersection = (preds_flat * targets_flat).sum().item()
    total_pred = preds_flat.sum().item()
    total_target = targets_flat.sum().item()

    union = total_pred + total_target - intersection
    iou = (intersection + 1e-6) / (union + 1e-6)
    precision = (intersection + 1e-6) / (total_pred + 1e-6)
    recall = (intersection + 1e-6) / (total_target + 1e-6)
    f1 = 2.0 * precision * recall / (precision + recall + 1e-6)

    return iou, f1, precision, recall


def train_model(
    data_dir: str = "data/datasets/flood_segmentation",
    checkpoint_path: str = "data/models/flood_unet_checkpoint.pt",
    epochs: int = 15,
    batch_size: int = 16,
    lr: float = 1e-3,
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Training on device: {device}")

    train_ds = FloodDataset(data_dir, "train")
    val_ds = FloodDataset(data_dir, "val")

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    model = FloodUNet().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    bce_fn = nn.BCEWithLogitsLoss()

    best_val_iou = 0.0
    os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0

        for imgs, masks in train_loader:
            imgs, masks = imgs.to(device), masks.to(device)
            optimizer.zero_grad()
            logits = model(imgs)

            bce = bce_fn(logits, masks)
            dice = dice_loss(logits, masks)
            loss = bce + dice

            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        train_loss /= len(train_loader)
        scheduler.step()

        # Validation
        model.eval()
        val_loss = 0.0
        val_iou_sum, val_f1_sum = 0.0, 0.0

        with torch.no_grad():
            for imgs, masks in val_loader:
                imgs, masks = imgs.to(device), masks.to(device)
                logits = model(imgs)

                bce = bce_fn(logits, masks)
                dice = dice_loss(logits, masks)
                val_loss += (bce + dice).item()

                iou, f1, _, _ = compute_metrics(logits, masks)
                val_iou_sum += iou
                val_f1_sum += f1

        val_loss /= len(val_loader)
        val_iou = val_iou_sum / len(val_loader)
        val_f1 = val_f1_sum / len(val_loader)

        print(
            f"Epoch [{epoch:02d}/{epochs:02d}] "
            f"Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | "
            f"Val IoU: {val_iou:.4f} | Val F1: {val_f1:.4f}"
        )

        if val_iou > best_val_iou:
            best_val_iou = val_iou
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "val_iou": val_iou,
                "val_f1": val_f1,
            }, checkpoint_path)
            print(f"  >>> Best checkpoint saved (Val IoU: {val_iou:.4f}, Val F1: {val_f1:.4f})")

    print(f"Training completed. Best checkpoint saved to {checkpoint_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", default="data/datasets/flood_segmentation")
    parser.add_argument("--checkpoint", default="data/models/flood_unet_checkpoint.pt")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()

    train_model(args.data_dir, args.checkpoint, args.epochs, args.batch_size, args.lr)
