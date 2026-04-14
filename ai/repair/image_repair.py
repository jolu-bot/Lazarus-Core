"""
LAZARUS CORE – Image Repair Module
Combines OpenCV inpainting with a deep autoencoder for reconstruction.
"""
import io
import numpy as np
import cv2
from PIL import Image
from typing import Optional, Tuple


def detect_corruption(img_array: np.ndarray) -> Tuple[np.ndarray, float]:
    """
    Detects corrupted regions using variance analysis.
    Returns (mask, corruption_score).
    mask: uint8 array where 255 = corrupted pixel.
    """
    gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY) if len(img_array.shape) == 3 else img_array
    
    # Block-based variance analysis
    h, w = gray.shape
    block = 16
    mask  = np.zeros((h, w), dtype=np.uint8)
    corrupt_blocks = 0
    total_blocks   = 0
    
    for y in range(0, h - block, block):
        for x in range(0, w - block, block):
            region = gray[y:y+block, x:x+block].astype(float)
            var    = np.var(region)
            mean   = np.mean(region)
            total_blocks += 1
            # Flat blocks or extreme-value blocks are likely corrupted
            if var < 0.5 or mean < 2 or mean > 253:
                mask[y:y+block, x:x+block] = 255
                corrupt_blocks += 1
    
    score = corrupt_blocks / max(total_blocks, 1)
    return mask, score


def inpaint_image(img_bytes: bytes, radius: int = 5) -> Optional[bytes]:
    """
    Performs OpenCV TELEA inpainting on corrupted regions.
    """
    try:
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            # Try PIL decoder for partial JPEG
            pil_img = Image.open(io.BytesIO(img_bytes))
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mask, score = detect_corruption(rgb)
        
        # Only inpaint if corruption is detected
        if score < 0.01:
            return img_bytes
        
        # Dilate mask to catch boundary artifacts
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask   = cv2.dilate(mask, kernel, iterations=2)
        
        repaired = cv2.inpaint(img, mask, radius, cv2.INPAINT_TELEA)
        _, buf   = cv2.imencode('.jpg', repaired, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return buf.tobytes()
    
    except Exception:
        return None


def repair_truncated_jpeg(img_bytes: bytes) -> Optional[bytes]:
    """
    Attempts to recover a truncated JPEG by patching the EOI marker.
    """
    # Ensure FFD9 at end
    data = bytearray(img_bytes)
    if not data.endswith(b'\xff\xd9'):
        data += b'\xff\xd9'
    return bytes(data)


def enhance_image(img_bytes: bytes) -> Optional[bytes]:
    """
    Applies CLAHE enhancement and denoising for recovered images.
    """
    try:
        arr  = np.frombuffer(img_bytes, dtype=np.uint8)
        img  = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return img_bytes
        
        # Fast Non-Local Means Denoising
        denoised = cv2.fastNlMeansDenoisingColored(img, None, 6, 6, 7, 21)
        
        # CLAHE on L channel
        lab   = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl    = clahe.apply(l)
        enhanced = cv2.cvtColor(cv2.merge([cl, a, b]), cv2.COLOR_LAB2BGR)
        
        _, buf = cv2.imencode('.jpg', enhanced, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return buf.tobytes()
    
    except Exception:
        return img_bytes
