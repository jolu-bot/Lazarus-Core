"""
LAZARUS CORE – ImageAutoEncoder Training Script
Trains the autoencoder on a folder of images with synthetic corruption masks.

Usage:
    python train.py --data_dir /path/to/images --epochs 50 --out weights.pth

Requirements:
    pip install torch torchvision pillow numpy tqdm
"""
from __future__ import annotations

import argparse
import os
import random
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from repair.model import ImageAutoEncoder


# ─── Dataset ─────────────────────────────────────────────────────
class CorruptionDataset(Dataset):
    """
    Loads clean images and generates random corruption masks on-the-fly.
    Returns (corrupted_4ch_tensor, clean_3ch_tensor).
    """
    EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}

    def __init__(self, root: str, size: int = 256):
        self.paths  = [p for p in Path(root).rglob('*') if p.suffix.lower() in self.EXTS]
        self.size   = size
        self.tf     = transforms.Compose([
            transforms.Resize((size, size)),
            transforms.ToTensor(),   # [0,1] float32, C×H×W
        ])
        if not self.paths:
            raise ValueError(f"No images found in {root}")
        print(f"Dataset: {len(self.paths)} images from {root}")

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        img = Image.open(self.paths[idx]).convert('RGB')
        clean = self.tf(img)  # (3, H, W)

        mask = self._gen_mask(self.size)  # (1, H, W)

        # Zero out masked regions
        corrupted = clean.clone()
        corrupted *= (1.0 - mask)

        inp = torch.cat([corrupted, mask], dim=0)  # (4, H, W)
        return inp, clean

    def _gen_mask(self, size: int) -> torch.Tensor:
        """Creates a random block corruption mask."""
        mask = torch.zeros(1, size, size)
        num_blocks = random.randint(1, 5)
        for _ in range(num_blocks):
            bh = random.randint(size // 16, size // 4)
            bw = random.randint(size // 16, size // 4)
            y  = random.randint(0, size - bh)
            x  = random.randint(0, size - bw)
            mask[:, y:y+bh, x:x+bw] = 1.0
        return mask


# ─── Loss ────────────────────────────────────────────────────────
class ReconstructionLoss(nn.Module):
    """L1 + perceptual-like MSE loss, focused on masked regions."""
    def forward(self, pred: torch.Tensor, target: torch.Tensor,
                mask: torch.Tensor) -> torch.Tensor:
        # Global reconstruction
        l1   = torch.mean(torch.abs(pred - target))
        # Masked region penalty
        m    = mask.expand_as(pred)
        l1_m = torch.mean(torch.abs(pred * m - target * m))
        return l1 + 2.0 * l1_m


# ─── Training ────────────────────────────────────────────────────
def train(
    data_dir: str,
    output_path: str = 'weights.pth',
    epochs: int = 50,
    batch_size: int = 8,
    lr: float = 2e-4,
    val_split: float = 0.1,
    device_str: str = 'auto',
) -> None:
    device = torch.device(
        'cuda' if torch.cuda.is_available() else 'cpu'
        if device_str == 'auto' else device_str
    )
    print(f"Training on {device}")

    dataset = CorruptionDataset(data_dir)
    n_val   = max(1, int(len(dataset) * val_split))
    n_train = len(dataset) - n_val
    train_ds, val_ds = torch.utils.data.random_split(dataset, [n_train, n_val])

    train_dl = DataLoader(train_ds, batch_size=batch_size,
                          shuffle=True,  num_workers=2, pin_memory=True)
    val_dl   = DataLoader(val_ds,   batch_size=batch_size,
                          shuffle=False, num_workers=2, pin_memory=True)

    model     = ImageAutoEncoder(base_channels=64).to(device)
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = ReconstructionLoss()

    best_val_loss = float('inf')

    for epoch in range(1, epochs + 1):
        # ── Train ──────────────────────────────────────────────
        model.train()
        train_loss = 0.0
        for inp, clean in train_dl:
            inp, clean = inp.to(device), clean.to(device)
            mask = inp[:, 3:4]  # channel 3 is the mask

            optimizer.zero_grad()
            out  = model(inp)
            loss = criterion(out, clean, mask)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item()

        scheduler.step()
        train_loss /= len(train_dl)

        # ── Validate ───────────────────────────────────────────
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for inp, clean in val_dl:
                inp, clean = inp.to(device), clean.to(device)
                mask = inp[:, 3:4]
                out  = model(inp)
                val_loss += criterion(out, clean, mask).item()
        val_loss /= len(val_dl)

        print(f"Epoch {epoch:3d}/{epochs} | "
              f"train={train_loss:.4f} | val={val_loss:.4f}")

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.state_dict(), output_path)
            print(f"  Saved best model → {output_path}")

    print(f"\nTraining complete. Best val loss: {best_val_loss:.4f}")
    print(f"Weights saved to: {output_path}")


# ─── Entry ───────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Train Lazarus Core image autoencoder')
    parser.add_argument('--data_dir',   required=True,
                        help='Path to folder of training images')
    parser.add_argument('--out',        default='weights.pth',
                        help='Output weights file path')
    parser.add_argument('--epochs',     type=int,   default=50)
    parser.add_argument('--batch_size', type=int,   default=8)
    parser.add_argument('--lr',         type=float, default=2e-4)
    parser.add_argument('--device',     default='auto',
                        help='"auto", "cpu", "cuda", or "mps"')
    args = parser.parse_args()

    train(
        data_dir   = args.data_dir,
        output_path = args.out,
        epochs     = args.epochs,
        batch_size = args.batch_size,
        lr         = args.lr,
        device_str = args.device,
    )
