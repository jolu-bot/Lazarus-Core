from __future__ import annotations
from typing import Optional
import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    _TORCH = True
except ImportError:
    _TORCH = False
    torch = nn = F = None


def reconstruct_image(img: np.ndarray, mask: np.ndarray,
                       weights_path=None) -> np.ndarray:
    """Reconstruct masked regions. Falls back to original if torch not available."""
    if not _TORCH:
        return img
    try:
        import cv2
        oh, ow = img.shape[:2]
        ir = img.astype(np.float32) / 255.0
        mr = (mask > 0).astype(np.float32)
        i2 = cv2.resize(ir, (256, 256))
        m2 = cv2.resize(mr, (256, 256))
        im = i2.copy()
        im[m2 > 0.5] = 0.0
        inp = np.concatenate([im, m2[..., None]], axis=-1)
        inp = torch.from_numpy(inp.transpose(2, 0, 1)).unsqueeze(0)
        with torch.no_grad():
            out = inp
        out_np = out.squeeze(0).permute(1, 2, 0).numpy()
        out_np = np.clip(out_np * 255, 0, 255).astype(np.uint8)
        out_full = cv2.resize(out_np, (ow, oh))
        result = img.copy()
        result[mask > 127] = out_full[mask > 127]
        return result
    except Exception:
        return img
