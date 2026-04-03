#!/usr/bin/env python3
"""
OST item-type classifier.

Pattern-first analysis of current plan page to detect likely item types from
visual signals (color, line thickness, texture/hatch, edges) and compare those
signals with learned prototypes.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
from datetime import datetime
from typing import Any, Dict, List, Tuple

import cv2
import mss
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


def grab_monitor(monitor_index: int) -> Tuple[np.ndarray, Dict[str, int]]:
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}. Range 1..{len(mons)-1}")
        mon = mons[monitor_index]
        shot = sct.grab(mon)
        img = np.array(shot)[:, :, :3]  # BGRA -> BGR
        return img, {
            "left": int(mon["left"]),
            "top": int(mon["top"]),
            "width": int(mon["width"]),
            "height": int(mon["height"]),
        }


def detect_canvas_region(img: np.ndarray) -> Tuple[int, int, int, int]:
    h, w = img.shape[:2]
    x0 = int(w * 0.20)
    y0 = int(h * 0.12)
    x1 = int(w * 0.92)
    y1 = int(h * 0.95)
    return x0, y0, x1, y1


def mask_colored_markup(canvas: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(canvas, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    # Colored signals: non-black/non-white; avoid grayscale by requiring saturation.
    mask = ((s > 30) & (v > 28) & (v < 250)).astype(np.uint8) * 255
    # Clean small noise.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)
    return mask


def find_regions(mask: np.ndarray, min_area: int = 1200) -> List[Tuple[int, int, int, int]]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions: List[Tuple[int, int, int, int]] = []
    h, w = mask.shape[:2]
    full = float(h * w)
    for c in contours:
        x, y, rw, rh = cv2.boundingRect(c)
        area = rw * rh
        if area < min_area:
            continue
        if area > int(full * 0.45):
            continue
        asp = rw / max(1, rh)
        if asp < 0.12 or asp > 8.0:
            continue
        regions.append((x, y, rw, rh))
    regions.sort(key=lambda b: b[2] * b[3], reverse=True)
    return regions[:30]


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


def dominant_lab_colors(roi: np.ndarray, k: int = 3) -> List[List[float]]:
    if roi.size == 0:
        return []
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
    pixels = lab.reshape(-1, 3).astype(np.float32)
    if len(pixels) < k:
        k = max(1, len(pixels))
    if k <= 0:
        return []
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    compactness, labels, centers = cv2.kmeans(
        pixels, k, None, criteria, 2, cv2.KMEANS_PP_CENTERS
    )
    _ = compactness
    counts = np.bincount(labels.flatten(), minlength=k).astype(np.float32)
    order = np.argsort(counts)[::-1]
    out: List[List[float]] = []
    for idx in order[:k]:
        c = centers[int(idx)]
        out.append([round(float(c[0]), 2), round(float(c[1]), 2), round(float(c[2]), 2)])
    return out


def stroke_width_stats(mask_roi: np.ndarray) -> Tuple[float, float, float]:
    if mask_roi.size == 0:
        return 0.0, 0.0, 0.0
    ink = (mask_roi > 0).astype(np.uint8)
    if int(ink.sum()) <= 0:
        return 0.0, 0.0, 0.0
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    widths = dist[ink > 0].astype(np.float32).flatten()
    widths = widths[np.isfinite(widths)]
    widths = widths[(widths >= 0.0) & (widths <= 10000.0)]
    widths = np.clip(widths, 0.0, 10000.0)
    if widths.size == 0:
        return 0.0, 0.0, 0.0
    widths = widths * np.float32(2.0)
    p50 = float(np.percentile(widths, 50))
    p90 = float(np.percentile(widths, 90))
    iqr = float(np.percentile(widths, 75) - np.percentile(widths, 25))
    return p50, p90, iqr


def hatch_strength(gray_roi: np.ndarray) -> float:
    if gray_roi.size == 0:
        return 0.0
    edges = cv2.Canny(gray_roi, 80, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=28, minLineLength=16, maxLineGap=4)
    if lines is None:
        return 0.0
    angles: List[float] = []
    for line in lines:
        l = line[0]
        x1, y1, x2, y2 = int(l[0]), int(l[1]), int(l[2]), int(l[3])
        ang = (math.degrees(math.atan2((y2 - y1), (x2 - x1))) + 180.0) % 180.0
        angles.append(ang)
    if len(angles) < 4:
        return 0.0
    hist, _ = np.histogram(np.array(angles), bins=18, range=(0.0, 180.0))
    top_two = np.sort(hist)[-2:]
    if top_two.size < 2:
        return 0.0
    # Cross-hatch tends to have two dominant angle families.
    return float((top_two[0] + top_two[1]) / max(1, len(angles)))


def build_embedding(
    p50: float,
    p90: float,
    iqr: float,
    hatch: float,
    colorfulness: float,
    edge_density: float,
    fill_ratio: float,
    aspect: float,
) -> List[float]:
    vals = [p50, p90, iqr, hatch, colorfulness, edge_density, fill_ratio, aspect]
    safe = [float(v) if np.isfinite(v) else 0.0 for v in vals]
    p50, p90, iqr, hatch, colorfulness, edge_density, fill_ratio, aspect = safe
    # Normalize into stable ranges roughly [0,1].
    e = [
        min(1.0, p50 / 12.0),
        min(1.0, p90 / 18.0),
        min(1.0, iqr / 10.0),
        min(1.0, hatch / 0.7),
        min(1.0, colorfulness / 90.0),
        min(1.0, edge_density / 0.35),
        min(1.0, fill_ratio / 0.8),
        min(1.0, abs(aspect - 1.0) / 3.0),
    ]
    return [round(float(v), 4) for v in e]


def classify_embedding(embedding: List[float], store: Dict[str, Any]) -> List[Dict[str, Any]]:
    item_types = (store.get("item_types", {}) if isinstance(store, dict) else {}) or {}
    ranked: List[Dict[str, Any]] = []
    for key, row in item_types.items():
        if not isinstance(row, dict):
            continue
        proto = row.get("prototype_embedding", [])
        if not isinstance(proto, list):
            continue
        sim = cosine_similarity(embedding, [float(x) for x in proto if isinstance(x, (int, float))])
        thresholds = row.get("thresholds", {}) if isinstance(row.get("thresholds"), dict) else {}
        min_sim = float(thresholds.get("min_similarity", 0.55) or 0.55)
        conf = max(0.0, min(1.0, 0.5 + (sim - min_sim)))
        ranked.append(
            {
                "item_type": str(key),
                "similarity": round(sim, 4),
                "confidence": round(conf, 4),
                "description": str(row.get("description", "")),
            }
        )
    ranked.sort(key=lambda r: (float(r.get("confidence", 0.0)), float(r.get("similarity", 0.0))), reverse=True)
    return ranked


def classify_current_page(
    project_id: str,
    monitor_index: int,
    item_db_root: pathlib.Path,
    output_path: pathlib.Path,
    context_label: str,
    update_prototypes: bool,
) -> Dict[str, Any]:
    item_db_root.mkdir(parents=True, exist_ok=True)
    registry_path = item_db_root / "item_type_registry.json"
    events_path = item_db_root / "item_type_events.jsonl"
    store = read_json(registry_path, {})
    if not isinstance(store, dict):
        store = {}

    img, mon = grab_monitor(monitor_index)
    x0, y0, x1, y1 = detect_canvas_region(img)
    canvas = img[y0:y1, x0:x1].copy()
    color_mask = mask_colored_markup(canvas)
    regions = find_regions(color_mask)

    region_rows: List[Dict[str, Any]] = []
    agg_embeddings: List[List[float]] = []
    for idx, (rx, ry, rw, rh) in enumerate(regions, start=1):
        roi = canvas[ry : ry + rh, rx : rx + rw]
        roi_mask = color_mask[ry : ry + rh, rx : rx + rw]
        if roi.size == 0 or roi_mask.size == 0:
            continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        p50, p90, iqr = stroke_width_stats(roi_mask)
        edges = cv2.Canny(gray, 80, 160)
        edge_density = float((edges > 0).sum()) / float(max(1, edges.size))
        fill_ratio = float((roi_mask > 0).sum()) / float(max(1, roi_mask.size))
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        colorfulness = float(np.mean(hsv[:, :, 1]))
        hatch = hatch_strength(gray)
        asp = float(rw / max(1, rh))
        embedding = build_embedding(
            p50=p50,
            p90=p90,
            iqr=iqr,
            hatch=hatch,
            colorfulness=colorfulness,
            edge_density=edge_density,
            fill_ratio=fill_ratio,
            aspect=asp,
        )
        agg_embeddings.append(embedding)
        ranked = classify_embedding(embedding, store)
        top = ranked[0] if ranked else {"item_type": "unknown", "confidence": 0.0, "similarity": 0.0}
        region_rows.append(
            {
                "rank_seed": idx,
                "bbox_canvas": {"x": rx, "y": ry, "w": rw, "h": rh},
                "center_global": {
                    "x": int(mon["left"] + x0 + rx + rw / 2),
                    "y": int(mon["top"] + y0 + ry + rh / 2),
                },
                "dominant_lab_colors": dominant_lab_colors(roi, k=3),
                "features": {
                    "stroke_width_p50": round(p50, 4),
                    "stroke_width_p90": round(p90, 4),
                    "stroke_width_iqr": round(iqr, 4),
                    "hatch_strength": round(hatch, 4),
                    "edge_density": round(edge_density, 5),
                    "fill_ratio": round(fill_ratio, 5),
                    "colorfulness": round(colorfulness, 3),
                    "aspect_ratio": round(asp, 4),
                },
                "embedding": embedding,
                "ranked_item_types": ranked[:5],
                "top_item_type": top.get("item_type"),
                "top_confidence": top.get("confidence"),
                "top_similarity": top.get("similarity"),
            }
        )

    region_rows.sort(key=lambda r: float(r.get("top_confidence", 0.0)), reverse=True)
    ranked_items: List[Dict[str, Any]] = []
    for row in region_rows:
        ranked_items.append(
            {
                "item_type": row.get("top_item_type"),
                "confidence": row.get("top_confidence"),
                "similarity": row.get("top_similarity"),
                "region_center": row.get("center_global"),
                "bbox_canvas": row.get("bbox_canvas"),
            }
        )
    ranked_items.sort(key=lambda r: float(r.get("confidence", 0.0)), reverse=True)

    top_conf = float((ranked_items[0].get("confidence", 0.0) if ranked_items else 0.0) or 0.0)
    payload: Dict[str, Any] = {
        "ok": True,
        "ts": datetime.now().isoformat(),
        "session_id": f"CLS-{now_tag()}",
        "project_id": project_id,
        "context_label": context_label,
        "monitor_index": monitor_index,
        "monitor": mon,
        "canvas_region": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        "candidate_count": len(region_rows),
        "region_candidates": region_rows,
        "ranked_item_types": ranked_items[:10],
        "summary": {
            "top_item_type": ranked_items[0].get("item_type") if ranked_items else "unknown",
            "top_confidence": round(top_conf, 4),
            "classified_regions": len(region_rows),
        },
    }
    write_json(output_path, payload)
    append_jsonl(
        events_path,
        {
            "event": "classification",
            "ts": datetime.now().isoformat(),
            "project_id": project_id,
            "context_label": context_label,
            "output_path": str(output_path),
            "candidate_count": len(region_rows),
            "top_item_type": payload["summary"]["top_item_type"],
            "top_confidence": payload["summary"]["top_confidence"],
        },
    )

    if update_prototypes and region_rows:
        # Conservative prototype update: blend top candidate embedding into
        # selected item type prototype with small learning rate.
        best = region_rows[0]
        best_item = str(best.get("top_item_type", ""))
        emb = best.get("embedding", [])
        if best_item and isinstance(emb, list):
            item_types = (store.get("item_types", {}) if isinstance(store, dict) else {}) or {}
            row = item_types.get(best_item, {})
            if isinstance(row, dict) and isinstance(row.get("prototype_embedding"), list):
                old = [float(x) for x in row.get("prototype_embedding", []) if isinstance(x, (int, float))]
                new = [float(x) for x in emb if isinstance(x, (int, float))]
                if old and new:
                    n = min(len(old), len(new))
                    lr = 0.12
                    merged = [round(((1.0 - lr) * old[i]) + (lr * new[i]), 6) for i in range(n)]
                    row["prototype_embedding"] = merged
                    row["updated_at"] = datetime.now().isoformat()
                    item_types[best_item] = row
                    store["item_types"] = item_types
                    store["updated_at"] = datetime.now().isoformat()
                    write_json(registry_path, store)
                    append_jsonl(
                        events_path,
                        {
                            "event": "prototype_update",
                            "ts": datetime.now().isoformat(),
                            "project_id": project_id,
                            "item_type": best_item,
                            "learning_rate": lr,
                            "source_output": str(output_path),
                        },
                    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="OST item-type classifier")
    parser.add_argument("--project-id", default="TP-0001")
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--item-db-root", default="output/ost-training-lab/item_types")
    parser.add_argument("--output", default="")
    parser.add_argument("--context-label", default="manual_classifier_run")
    parser.add_argument("--update-prototypes", action="store_true")
    args = parser.parse_args()

    db_root = pathlib.Path(args.item_db_root)
    out = pathlib.Path(args.output) if str(args.output).strip() else (
        db_root / "classifications" / f"classification_{args.project_id}_{now_tag()}.json"
    )
    payload = classify_current_page(
        project_id=str(args.project_id),
        monitor_index=int(args.monitor_index),
        item_db_root=db_root,
        output_path=out,
        context_label=str(args.context_label),
        update_prototypes=bool(args.update_prototypes),
    )
    print(json.dumps({"ok": True, "output": str(out), "summary": payload.get("summary", {})}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
