from __future__ import annotations
from typing import Optional
import numpy as np

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    import torch
    import torch.nn as nn
    _TORCH = True
except ImportError:
    _TORCH = False
    torch = nn = None


def reconstruct_image(img: np.ndarray, mask: np.ndarray,
                       weights_path=None) -> np.ndarray:
    """
    Multi-method structural inpainting - no pre-trained weights required.

    Strategy (ordered by region size):
    1. Small  (<5%)  : OpenCV TELEA   (edge-preserving, fast)
    2. Medium (5-25%): Blend TELEA+NS (complementary strengths)
    3. Large  (>25%) : Boundary propagation (Gaussian onion-peeling)
                       starting from an NS seed

    All cases finish with frequency-domain Gaussian blending so there
    are no hard seams at region boundaries.
    """
    if not _CV2 or img is None or mask is None:
        return img
    try:
        if mask.max() == 0:
            return img

        mask_u8 = ((mask > 0) if mask.dtype == bool
                   else (mask > 127)).astype(np.uint8) * 255
        region_ratio = float(mask_u8.sum()) / (255 * img.shape[0] * img.shape[1])

        # Method A - TELEA (edge-preserving, fast)
        telea = cv2.inpaint(img, mask_u8, 3, cv2.INPAINT_TELEA)

        # Method B - Navier-Stokes (texture-aware, handles larger gaps)
        ns = cv2.inpaint(img, mask_u8, 5, cv2.INPAINT_NS)

        if region_ratio < 0.05:
            base = telea
        elif region_ratio < 0.25:
            base = cv2.addWeighted(telea, 0.55, ns, 0.45, 0)
        else:
            # Large region: propagate from NS seed boundary-inward
            base = _boundary_propagation(img, mask_u8, ns)

        # Smooth transitions with Gaussian-weighted blending
        result = _freq_blend(img, base, mask_u8)

        # Apply only to masked region
        final = img.copy()
        final[mask_u8 > 0] = result[mask_u8 > 0]
        return final

    except Exception:
        return img


def _boundary_propagation(img: np.ndarray, mask_u8: np.ndarray,
                            seed: np.ndarray) -> np.ndarray:
    """
    Onion-peeling: fill the unknown region layer by layer from the boundary.
    Each iteration, the frontier pixels (outermost unknown layer) receive
    the Gaussian-blurred value of the current result, then they are
    marked as known. Converges in O(sqrt(area)) iterations.
    """
    result  = seed.copy().astype(np.float32)
    current = (mask_u8 > 0).astype(np.uint8)
    kernel  = np.ones((5, 5), np.uint8)

    for _ in range(60):
        if current.max() == 0:
            break
        blurred  = cv2.GaussianBlur(result, (5, 5), 1.5)
        eroded   = cv2.erode(current, kernel, iterations=1)
        frontier = current - eroded
        result[frontier > 0] = blurred[frontier > 0]
        current = eroded

    return result.astype(np.uint8)


def _freq_blend(original: np.ndarray, inpainted: np.ndarray,
                 mask_u8: np.ndarray) -> np.ndarray:
    """
    Gaussian-feathered composite: blend inpainted result over original
    using a soft mask so region boundaries have no hard seam.
    """
    try:
        m  = cv2.GaussianBlur((mask_u8 > 0).astype(np.float32), (31, 31), 0)
        m3 = m[:, :, np.newaxis]
        blended = (inpainted.astype(np.float32) * m3 +
                   original.astype(np.float32)  * (1.0 - m3))
        return np.clip(blended, 0, 255).astype(np.uint8)
    except Exception:
        return inpainted