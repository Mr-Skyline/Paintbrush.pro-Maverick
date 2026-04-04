#!/usr/bin/env python3
"""
Shared utilities for symbol knowledge ingestion and query.
"""

from __future__ import annotations

import json
import math
import pathlib
from datetime import datetime
from typing import Any, Dict, List

import cv2
import numpy as np


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path: pathlib.Path, fallback: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return fallback


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_jsonl(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    va = np.array(a[:n], dtype=np.float32)
    vb = np.array(b[:n], dtype=np.float32)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na <= 1e-6 or nb <= 1e-6:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def compute_symbol_embedding(image_path: pathlib.Path) -> Dict[str, Any]:
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        return {"ok": False, "reason": "image_read_failed", "path": str(image_path)}
    h, w = img.shape[:2]
    if h <= 2 or w <= 2:
        return {"ok": False, "reason": "image_too_small", "path": str(image_path)}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)
    inv = 255 - thr
    ink = (inv > 0).astype(np.uint8)
    fill_ratio = float(ink.mean())

    edges = cv2.Canny(gray, 70, 140)
    edge_density = float((edges > 0).mean())

    # Hu moments for shape descriptor.
    moments = cv2.moments(ink.astype(np.uint8))
    hu = cv2.HuMoments(moments).flatten()
    hu = [float(-math.copysign(1.0, v) * math.log10(abs(v) + 1e-12)) for v in hu]

    # Aspect and compactness.
    contours, _ = cv2.findContours(ink.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total_area = 0.0
    total_perim = 0.0
    for c in contours:
        total_area += float(cv2.contourArea(c))
        total_perim += float(cv2.arcLength(c, True))
    compactness = float((4.0 * math.pi * total_area / max(1.0, total_perim * total_perim))) if total_perim > 0 else 0.0
    aspect = float(w / max(1, h))

    # 8-bin orientation histogram from Hough lines.
    ang_hist = np.zeros((8,), dtype=np.float32)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=20, minLineLength=8, maxLineGap=3)
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = [int(v) for v in line[0]]
            ang = (math.degrees(math.atan2((y2 - y1), (x2 - x1))) + 180.0) % 180.0
            bin_idx = min(7, int((ang / 180.0) * 8.0))
            ang_hist[bin_idx] += 1.0
    if float(ang_hist.sum()) > 0:
        ang_hist = ang_hist / float(ang_hist.sum())

    emb = [
        min(1.0, fill_ratio),
        min(1.0, edge_density / 0.35),
        min(1.0, abs(aspect - 1.0) / 3.0),
        min(1.0, compactness),
    ] + [max(-4.0, min(4.0, x)) / 4.0 for x in hu[:7]] + [float(v) for v in ang_hist.tolist()]
    emb = [round(float(v), 6) for v in emb]
    return {
        "ok": True,
        "path": str(image_path),
        "width": int(w),
        "height": int(h),
        "embedding": emb,
        "features": {
            "fill_ratio": round(fill_ratio, 6),
            "edge_density": round(edge_density, 6),
            "aspect": round(aspect, 6),
            "compactness": round(compactness, 6),
        },
    }

