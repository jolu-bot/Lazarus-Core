"""
LAZARUS CORE – AI Microservice (FastAPI)
Exposes image/video repair endpoints callable from Electron via HTTP.
"""
from __future__ import annotations

import io
import os
import base64
import hashlib
import numpy as np
import cv2
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn

from repair.image_repair import inpaint_image, repair_truncated_jpeg, enhance_image
from repair.image_repair import detect_corruption
try:
    from repair.model import reconstruct_image
except Exception:
    def reconstruct_image(img, mask, weights_path=None): return img


# ─── App ─────────────────────────────────────────────────────────
app = FastAPI(
    title="Lazarus Core AI",
    version="1.0.0",
    docs_url=None,   # Disable swagger in production
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ─── Auth ─────────────────────────────────────────────────────────
_AI_SECRET = os.environ.get("LAZARUS_AI_SECRET", "dev_only_secret_change_in_prod")

def _check_auth(x_api_key: Optional[str] = Header(default=None)):
    if os.environ.get("LAZARUS_AI_NOAUTH") == "1":
        return
    if x_api_key != _AI_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ─── Models ──────────────────────────────────────────────────────
class RepairResponse(BaseModel):
    success:    bool
    image_b64:  Optional[str] = None
    confidence: float = 0.0
    message:    str   = ""


class AnalyzeResponse(BaseModel):
    corruption_score: float
    is_repairable:    bool
    format_detected:  str


# ─── Routes ──────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_file(file: UploadFile = File(...),
                        x_api_key: Optional[str] = Header(default=None)):
    _check_auth(x_api_key)
    data = await file.read()
    
    fmt = "unknown"
    if data[:2] == b'\xff\xd8':
        fmt = "jpeg"
    elif data[:8] == b'\x89PNG\r\n\x1a\n':
        fmt = "png"
    elif data[:4] == b'%PDF':
        fmt = "pdf"
    
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    score = 1.0
    if img is not None:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        _, score = detect_corruption(rgb)
    
    return AnalyzeResponse(
        corruption_score=float(score),
        is_repairable=(score < 0.8),
        format_detected=fmt
    )


@app.post("/repair/image", response_model=RepairResponse)
async def repair_image(file: UploadFile = File(...),
                        enhance: bool = False,
                        use_ai: bool = False,
                        x_api_key: Optional[str] = Header(default=None)):
    _check_auth(x_api_key)
    data = await file.read()
    
    if not data:
        return RepairResponse(success=False, message="Empty file")
    
    # Fix truncated JPEG
    if data[:2] == b'\xff\xd8':
        data = repair_truncated_jpeg(data)
    
    result = inpaint_image(data)
    if result is None:
        return RepairResponse(success=False, message="Inpainting failed")
    
    if enhance:
        result = enhance_image(result) or result
    
    if use_ai:
        try:
            arr = np.frombuffer(result, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                rgb  = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                mask, _ = detect_corruption(rgb)
                reconstructed = reconstruct_image(rgb, mask)
                bgr  = cv2.cvtColor(reconstructed, cv2.COLOR_RGB2BGR)
                _, buf = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
                result = buf.tobytes()
        except Exception:
            pass  # Fall back to OpenCV result
    
    img_b64 = base64.b64encode(result).decode()
    return RepairResponse(success=True, image_b64=img_b64, confidence=0.82)


@app.post("/repair/batch")
async def repair_batch(files: list[UploadFile] = File(...),
                        x_api_key: Optional[str] = Header(default=None)):
    _check_auth(x_api_key)
    results = []
    for f in files:
        data = await f.read()
        repaired = inpaint_image(data)
        if repaired:
            img_b64 = base64.b64encode(repaired).decode()
            results.append({"name": f.filename, "success": True, "image_b64": img_b64})
        else:
            results.append({"name": f.filename, "success": False})
    return {"results": results}


@app.post("/enhance/image")
async def enhance_image_route(file: UploadFile = File(...),
                               x_api_key: Optional[str] = Header(default=None)):
    _check_auth(x_api_key)
    data    = await file.read()
    result  = enhance_image(data)
    if result is None:
        raise HTTPException(status_code=422, detail="Enhancement failed")
    return Response(content=result, media_type="image/jpeg")


# ─── Entry Point ─────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("LAZARUS_AI_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
