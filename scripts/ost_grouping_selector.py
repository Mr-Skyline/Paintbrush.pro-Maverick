#!/usr/bin/env python3
"""
OST Grouping Selector

Analyzes the current OST page screenshot, finds candidate takeoff groupings,
scores them for completeness/quality, and optionally clicks the best one.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

import cv2
import mss
import numpy as np
import pyautogui
import pytesseract

from mouse_takeover_guard import install_pyautogui_takeover_guard
from ocr_engine import create_ocr_engine, OcrEngine
from ost_window_guard import (
    clamp_point_to_active_window,
    focus_window as focus_window_guard,
    set_active_window_rect,
)

install_pyautogui_takeover_guard(pyautogui)


def configure_tesseract() -> str | None:
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for p in candidates:
        if pathlib.Path(p).exists():
            pytesseract.pytesseract.tesseract_cmd = p
            return p
    return None


def load_unit_aliases(path: pathlib.Path) -> Dict[str, List[str]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, List[str]] = {}
        for k, v in raw.items():
            if isinstance(v, list):
                out[str(k).lower()] = [str(x).lower() for x in v]
        return out
    except Exception:
        return {}


def norm_token(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def normalize_unit_label(raw_label: str, text: str, aliases: Dict[str, List[str]]) -> str:
    if raw_label and raw_label != "unknown":
        return raw_label
    t = text.lower()
    t_norm = norm_token(t)
    for canon, vals in aliases.items():
        for v in vals:
            if v in t:
                return canon
            if norm_token(v) and norm_token(v) in t_norm:
                return canon
    return raw_label or "unknown"


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def grab_monitor(monitor_index: int) -> Tuple[np.ndarray, Dict[str, int]]:
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}. Range is 1..{len(mons)-1}")
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
    # Heuristic: canvas occupies center-right body under top toolbars.
    x0 = int(w * 0.20)
    y0 = int(h * 0.12)
    x1 = int(w * 0.92)
    y1 = int(h * 0.95)
    return x0, y0, x1, y1


def find_group_candidates(canvas: np.ndarray, min_area: int = 15000) -> List[Tuple[int, int, int, int]]:
    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    # isolate "ink" from white background
    _, inv = cv2.threshold(gray, 235, 255, cv2.THRESH_BINARY_INV)
    boxes: List[Tuple[int, int, int, int]] = []

    # Multi-pass kernels: smaller first to avoid collapsing the whole canvas.
    for kx, ky, it in ((7, 7, 1), (11, 11, 1), (15, 15, 1)):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kx, ky))
        merged = cv2.morphologyEx(inv, cv2.MORPH_CLOSE, kernel, iterations=it)
        contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            area = w * h
            if area < min_area:
                continue
            # Reject near full-canvas blobs.
            if area > int(canvas.shape[0] * canvas.shape[1] * 0.92):
                continue
            aspect = w / max(h, 1)
            if aspect < 0.35 or aspect > 4.5:
                continue
            boxes.append((x, y, w, h))

    if not boxes:
        return []

    # De-duplicate by IoU-ish containment
    deduped: List[Tuple[int, int, int, int]] = []
    boxes = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
    for b in boxes:
        bx, by, bw, bh = b
        b_area = bw * bh
        keep = True
        for ex, ey, ew, eh in deduped:
            ix0 = max(bx, ex)
            iy0 = max(by, ey)
            ix1 = min(bx + bw, ex + ew)
            iy1 = min(by + bh, ey + eh)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            inter = (ix1 - ix0) * (iy1 - iy0)
            contain_ratio = inter / max(1, b_area)
            if contain_ratio > 0.78:
                keep = False
                break
        if keep:
            deduped.append(b)

    return deduped[:20]


def component_cluster_candidates(canvas: np.ndarray) -> List[Tuple[int, int, int, int]]:
    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    ink = (gray < 238).astype(np.uint8) * 255
    # Connect local linework/text per grouping without merging entire page.
    ink = cv2.dilate(ink, np.ones((5, 5), np.uint8), iterations=2)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    h, w = gray.shape[:2]
    full_area = w * h
    out: List[Tuple[int, int, int, int]] = []
    for i in range(1, num_labels):
        x, y, cw, ch, area = stats[i]
        bbox_area = int(cw * ch)
        if bbox_area < 12000:
            continue
        if bbox_area > int(full_area * 0.55):
            continue
        aspect = cw / max(ch, 1)
        if aspect < 0.25 or aspect > 4.2:
            continue
        # Require real signal in original image to avoid empty blobs.
        roi = gray[y : y + ch, x : x + cw]
        ink_density = float((roi < 235).sum()) / float(max(1, roi.size))
        if ink_density < 0.015:
            continue
        pad = 4
        xx0 = max(0, x - pad)
        yy0 = max(0, y - pad)
        xx1 = min(w, x + cw + pad)
        yy1 = min(h, y + ch + pad)
        out.append((xx0, yy0, xx1 - xx0, yy1 - yy0))
    out = sorted(out, key=lambda b: b[2] * b[3], reverse=True)
    return out[:30]


def _largest_gap_center(mask_1d: np.ndarray, min_gap: int = 14) -> int | None:
    """
    mask_1d: True where whitespace, False where ink.
    Returns center index of the largest whitespace run.
    """
    best_len = 0
    best_center = None
    n = len(mask_1d)
    i = 0
    while i < n:
        if not mask_1d[i]:
            i += 1
            continue
        j = i
        while j < n and mask_1d[j]:
            j += 1
        run_len = j - i
        if run_len >= min_gap and run_len > best_len:
            best_len = run_len
            best_center = i + run_len // 2
        i = j
    return best_center


def _partition_by_whitespace(
    ink01: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    depth: int,
    max_depth: int = 5,
) -> List[Tuple[int, int, int, int]]:
    # stop conditions
    if depth >= max_depth or w < 120 or h < 120:
        return [(x, y, w, h)]

    roi = ink01[y : y + h, x : x + w]
    if roi.size == 0:
        return []

    # projection profiles (ink fraction by column/row)
    col_ink = roi.mean(axis=0)  # shape (w,)
    row_ink = roi.mean(axis=1)  # shape (h,)

    # whitespace columns/rows are where ink is very low
    col_ws = col_ink < 0.006
    row_ws = row_ink < 0.006
    vx = _largest_gap_center(col_ws, min_gap=max(12, w // 60))
    hy = _largest_gap_center(row_ws, min_gap=max(12, h // 60))

    # prefer split with larger whitespace run implied by center existence and balance
    split_axis = None
    if vx is not None and 0.22 * w < vx < 0.78 * w:
        split_axis = "v"
    if hy is not None and 0.22 * h < hy < 0.78 * h:
        if split_axis is None:
            split_axis = "h"
        else:
            # choose axis with better balance (closer to half)
            v_bal = abs(0.5 - (vx / max(1, w)))
            h_bal = abs(0.5 - (hy / max(1, h)))
            split_axis = "v" if v_bal < h_bal else "h"

    if split_axis == "v" and vx is not None:
        gap = max(6, w // 160)
        left = _partition_by_whitespace(ink01, x, y, vx - gap, h, depth + 1, max_depth)
        right = _partition_by_whitespace(ink01, x + vx + gap, y, w - vx - gap, h, depth + 1, max_depth)
        return left + right
    if split_axis == "h" and hy is not None:
        gap = max(6, h // 160)
        top = _partition_by_whitespace(ink01, x, y, w, hy - gap, depth + 1, max_depth)
        bottom = _partition_by_whitespace(ink01, x, y + hy + gap, w, h - hy - gap, depth + 1, max_depth)
        return top + bottom

    return [(x, y, w, h)]


def layout_adaptive_candidates(canvas: np.ndarray) -> List[Tuple[int, int, int, int]]:
    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    # ink01: 1 where ink-ish, 0 where background
    ink01 = (gray < 235).astype(np.float32)
    h, w = gray.shape[:2]
    raw = _partition_by_whitespace(ink01, 0, 0, w, h, depth=0, max_depth=6)
    out: List[Tuple[int, int, int, int]] = []
    for x, y, cw, ch in raw:
        if cw < 80 or ch < 80:
            continue
        roi = ink01[y : y + ch, x : x + cw]
        if roi.size == 0:
            continue
        ink_density = float(roi.mean())
        area = cw * ch
        if area < 12000:
            continue
        # reject near-empty regions and near-full-page regions
        if ink_density < 0.01:
            continue
        if area > int(w * h * 0.92):
            continue
        # trim small margins
        pad = 6
        xx0 = max(0, x + pad)
        yy0 = max(0, y + pad)
        xx1 = min(w, x + cw - pad)
        yy1 = min(h, y + ch - pad)
        if xx1 - xx0 < 60 or yy1 - yy0 < 60:
            continue
        out.append((xx0, yy0, xx1 - xx0, yy1 - yy0))

    # dedupe near-duplicates by containment
    out = sorted(out, key=lambda b: b[2] * b[3], reverse=True)
    dedup: List[Tuple[int, int, int, int]] = []
    for bx, by, bw, bh in out:
        b_area = bw * bh
        keep = True
        for ex, ey, ew, eh in dedup:
            ix0 = max(bx, ex)
            iy0 = max(by, ey)
            ix1 = min(bx + bw, ex + ew)
            iy1 = min(by + bh, ey + eh)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            inter = (ix1 - ix0) * (iy1 - iy0)
            if inter / max(1, b_area) > 0.80:
                keep = False
                break
        if keep:
            dedup.append((bx, by, bw, bh))
    return dedup[:24]


def parse_unit_label(text: str) -> str:
    t = text.lower()
    m = re.search(r"\bunit[\s:._-]*([a-z0-9]{1,6})", t)
    if m:
        return f"unit-{m.group(1)}"
    m2 = re.search(r"\bu[\s:._-]*([a-z0-9]{1,4})\b", t)
    if m2:
        return f"unit-{m2.group(1)}"
    # fallback by first strong token
    words = re.findall(r"[a-z0-9]{2,}", t)
    return words[0] if words else "unknown"


def ocr_text(crop: np.ndarray, ocr: OcrEngine) -> Tuple[str, Dict[str, Any]]:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC)
    th = cv2.adaptiveThreshold(
        up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7
    )
    res = ocr.ocr_text(th, context="OST grouping candidate OCR", psm=6)
    txt = str(res.get("text", "") or "")
    meta = {
        "engine_used": str(res.get("engine_used", "")),
        "fallback_used": bool(res.get("fallback_used", False)),
        "ok": bool(res.get("ok", False)),
    }
    return txt[:1000], meta


def score_candidate(crop: np.ndarray, text: str) -> Dict[str, float]:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    nonwhite = float((gray < 235).sum())
    total = float(gray.size) if gray.size else 1.0
    ink_density = nonwhite / total

    # overlay coverage (blue/cyan markup colors in screenshot)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    blue1 = cv2.inRange(hsv, np.array([90, 50, 40], dtype=np.uint8), np.array([130, 255, 255], dtype=np.uint8))
    overlay_cov = float((blue1 > 0).sum()) / total

    # drawing detail from edges
    edges = cv2.Canny(gray, 80, 160)
    edge_density = float((edges > 0).sum()) / total

    t = text.lower()
    completeness_hits = 0
    for token in ("plan", "rcp", "reflected", "ceiling", "finish", "floor", "unit"):
        if token in t:
            completeness_hits += 1
    words = re.findall(r"[a-z0-9]{2,}", t)
    text_len = len(t.strip())
    word_count = len(words)

    # weighted score for "complete, labeled, content-rich"
    score = (
        min(1.0, overlay_cov * 18.0) * 35.0
        + min(1.0, edge_density * 28.0) * 25.0
        + min(1.0, completeness_hits / 5.0) * 25.0
        + min(1.0, word_count / 24.0) * 10.0
        + min(1.0, ink_density * 5.0) * 5.0
    )
    return {
        "score": round(score, 2),
        "ink_density": round(ink_density, 4),
        "overlay_coverage": round(overlay_cov, 4),
        "edge_density": round(edge_density, 4),
        "completeness_hits": float(completeness_hits),
        "text_len": float(text_len),
        "word_count": float(word_count),
    }


def analyze(monitor_index: int, aliases: Dict[str, List[str]], ocr: OcrEngine) -> Dict[str, Any]:
    img, mon = grab_monitor(monitor_index)
    x0, y0, x1, y1 = detect_canvas_region(img)
    canvas = img[y0:y1, x0:x1]
    boxes = component_cluster_candidates(canvas)
    if len(boxes) < 2:
        boxes = find_group_candidates(canvas)
    if len(boxes) < 2:
        boxes = layout_adaptive_candidates(canvas)

    candidates = []
    ocr_call_samples: List[Dict[str, Any]] = []
    for idx, (x, y, w, h) in enumerate(boxes, start=1):
        pad = 6
        xx0 = max(0, x - pad)
        yy0 = max(0, y - pad)
        xx1 = min(canvas.shape[1], x + w + pad)
        yy1 = min(canvas.shape[0], y + h + pad)
        crop = canvas[yy0:yy1, xx0:xx1]
        text, ocr_meta = ocr_text(crop, ocr=ocr)
        ocr_call_samples.append({"rank_seed": idx, **ocr_meta})
        label_raw = parse_unit_label(text)
        label = normalize_unit_label(label_raw, text, aliases)
        s = score_candidate(crop, text)
        center_local = (int((xx0 + xx1) / 2), int((yy0 + yy1) / 2))
        center_global = (mon["left"] + x0 + center_local[0], mon["top"] + y0 + center_local[1])
        candidates.append(
            {
                "rank_seed": idx,
                "unit_label": label,
                "unit_label_raw": label_raw,
                "bbox_canvas": {"x": int(xx0), "y": int(yy0), "w": int(xx1 - xx0), "h": int(yy1 - yy0)},
                "center_global": {"x": int(center_global[0]), "y": int(center_global[1])},
                "ocr_text": text.strip(),
                "score": s["score"],
                "score_components": s,
            }
        )

    # keep best candidate per unit_label
    best_by_unit: Dict[str, Dict[str, Any]] = {}
    for c in candidates:
        key = c["unit_label"]
        if key not in best_by_unit or c["score"] > best_by_unit[key]["score"]:
            best_by_unit[key] = c

    best_all = max(candidates, key=lambda c: c["score"]) if candidates else None
    return {
        "ts": datetime.now().isoformat(),
        "monitor": mon,
        "canvas_region": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        "candidate_count": len(candidates),
        "best_overall": best_all,
        "best_by_unit": best_by_unit,
        "candidates": sorted(candidates, key=lambda c: c["score"], reverse=True),
        "ocr_diagnostics": {
            "engine": ocr.get_diagnostics(),
            "call_samples": ocr_call_samples[:80],
        },
    }


def maybe_click(target: Dict[str, Any] | None, click: bool) -> None:
    if not click or not target:
        return
    pt = target.get("center_global", {})
    x = int(pt.get("x", 0))
    y = int(pt.get("y", 0))
    cx, cy, adjusted = clamp_point_to_active_window(x, y, margin_px=10)
    if adjusted:
        print(f"ost_window_clamp from=({x},{y}) to=({cx},{cy})")
    pyautogui.moveTo(cx, cy, duration=0.2)
    pyautogui.click()


def main() -> int:
    parser = argparse.ArgumentParser(description="Select best takeoff grouping on current OST page")
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--window-title-contains", default="On-Screen Takeoff")
    parser.add_argument("--unit-label", default="", help="Optional unit label filter, e.g. unit-b2")
    parser.add_argument(
        "--unit-aliases",
        default="scripts/ost_unit_aliases.json",
        help="Unit label alias mapping JSON path",
    )
    parser.add_argument("--click-best", action="store_true", help="Click best detected grouping")
    parser.add_argument(
        "--output",
        default="output/ost-grouping-selector/latest.json",
        help="Where to write analysis JSON",
    )
    args = parser.parse_args()
    focus_window_guard(str(args.window_title_contains), sleep_s=0.2)
    set_active_window_rect(str(args.window_title_contains))
    _ = configure_tesseract()
    aliases = load_unit_aliases(pathlib.Path(args.unit_aliases))
    ocr = create_ocr_engine()
    result = analyze(args.monitor_index, aliases=aliases, ocr=ocr)
    unit = args.unit_label.strip().lower()
    target = None
    if unit:
        target = result["best_by_unit"].get(unit)
    if target is None:
        target = result.get("best_overall")

    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "query_unit_label": unit or None,
        "selected_target": target,
        "analysis": result,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"analysis_saved={out_path}")
    if target:
        print(f"selected_unit={target.get('unit_label')} score={target.get('score')}")
    else:
        print("selected_unit=None")

    maybe_click(target, args.click_best)
    if args.click_best and target:
        print("clicked_best=true")
    return 0


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    raise SystemExit(main())
