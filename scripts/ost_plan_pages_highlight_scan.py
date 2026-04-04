#!/usr/bin/env python3
"""
OST Plan Pages Highlight Scanner

Scans the "Plan Pages" dropdown list, identifies highlighted entries (proxy for
pages with takeoffs), and writes an ordered ingestion candidate list.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import time
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


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


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


def screenshot_monitor_np(monitor_index: int) -> Tuple[np.ndarray, Dict[str, int]]:
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}. Range is 1..{len(mons)-1}")
        mon = mons[monitor_index]
        shot = sct.grab(mon)
        img = np.array(shot)[:, :, :3]
        return img, {
            "left": int(mon["left"]),
            "top": int(mon["top"]),
            "width": int(mon["width"]),
            "height": int(mon["height"]),
        }


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _fuzzy_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _load_config(path: str) -> Dict[str, Any]:
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _find_plan_pages_anchor_with_tesseract(img: np.ndarray, mon: Dict[str, int]) -> Dict[str, int]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(up, output_type=pytesseract.Output.DICT, config="--psm 6")
    n = len(data.get("text", []))
    words: List[Tuple[int, str, int, int, int, int]] = []
    for i in range(n):
        t = _norm_text(data["text"][i])
        if not t:
            continue
        x = int(data["left"][i])
        y = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])
        words.append((i, t.lower(), x, y, w, h))

    # Look for "plan pages" pair.
    for i in range(len(words) - 1):
        a = words[i]
        b = words[i + 1]
        if a[1] == "plan" and b[1].startswith("page"):
            rx = int((a[2] + b[2] + b[4]) / 2 / 1.5)
            ry = int((a[3] + a[5] // 2) / 1.5)
            return {"x": int(mon["left"] + rx + 140), "y": int(mon["top"] + ry)}

    # Fallback: single token containing both via OCR errors.
    for _, t, x, y, w, h in words:
        if "plan" in t and "page" in t:
            rx = int((x + w) / 1.5)
            ry = int((y + h // 2) / 1.5)
            return {"x": int(mon["left"] + rx + 120), "y": int(mon["top"] + ry)}
    return {}


def _resolve_dropdown_anchor(config: Dict[str, Any], img: np.ndarray, mon: Dict[str, int]) -> Dict[str, int]:
    anchors = config.get("anchors", {}) if isinstance(config.get("anchors", {}), dict) else {}
    direct = anchors.get("plan_pages_dropdown", {}) if isinstance(anchors.get("plan_pages_dropdown", {}), dict) else {}
    if int(direct.get("x", 0) or 0) > 0 and int(direct.get("y", 0) or 0) > 0:
        return {"x": int(direct["x"]), "y": int(direct["y"]), "source": "config_anchor"}
    auto = _find_plan_pages_anchor_with_tesseract(img, mon)
    if auto:
        return {"x": int(auto["x"]), "y": int(auto["y"]), "source": "ocr_anchor"}
    return {}


def _list_roi(mon: Dict[str, int], anchor_x: int, anchor_y: int, w: int, h: int) -> Tuple[int, int, int, int]:
    x0 = max(0, anchor_x - mon["left"] - int(w * 0.35))
    y0 = max(0, anchor_y - mon["top"] + 22)
    x1 = min(mon["width"], x0 + w)
    y1 = min(mon["height"], y0 + h)
    return x0, y0, x1, y1


def _row_highlight_score(row_img: np.ndarray) -> float:
    hsv = cv2.cvtColor(row_img, cv2.COLOR_BGR2HSV)
    sat_mask = cv2.inRange(hsv, np.array([0, 28, 0], dtype=np.uint8), np.array([179, 255, 255], dtype=np.uint8))
    dark_mask = cv2.inRange(hsv, np.array([0, 0, 0], dtype=np.uint8), np.array([179, 55, 220], dtype=np.uint8))
    total = float(max(1, row_img.shape[0] * row_img.shape[1]))
    sat_ratio = float((sat_mask > 0).sum()) / total
    dark_ratio = float((dark_mask > 0).sum()) / total
    return round((0.65 * sat_ratio) + (0.35 * dark_ratio), 5)


def _ocr_row_text(row_img: np.ndarray, ocr: OcrEngine) -> str:
    gray = cv2.cvtColor(row_img, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=1.7, fy=1.7, interpolation=cv2.INTER_CUBIC)
    thr = cv2.adaptiveThreshold(
        up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8
    )
    res = ocr.ocr_text(thr, context="OST Plan Pages row OCR", psm=7)
    txt = _norm_text(str(res.get("text", "")))
    if txt:
        return txt
    # Fallback with tesseract multi-line
    try:
        raw = pytesseract.image_to_string(thr, config="--psm 7")
        return _norm_text(raw)
    except Exception:
        return ""


def _scan_visible_rows(
    monitor_img: np.ndarray,
    mon: Dict[str, int],
    anchor_x: int,
    anchor_y: int,
    ocr: OcrEngine,
    list_width: int,
    list_height: int,
    row_height: int,
) -> Dict[str, Any]:
    x0, y0, x1, y1 = _list_roi(mon, anchor_x, anchor_y, list_width, list_height)
    roi = monitor_img[y0:y1, x0:x1]
    rows: List[Dict[str, Any]] = []
    if roi.size == 0:
        return {"rows": rows, "roi": {"x0": x0, "y0": y0, "x1": x1, "y1": y1}}

    max_rows = max(1, int(roi.shape[0] / max(16, row_height)))
    for ridx in range(max_rows):
        ry0 = int(ridx * row_height)
        ry1 = min(roi.shape[0], int((ridx + 1) * row_height))
        if ry1 - ry0 < 14:
            continue
        row_img = roi[ry0:ry1, :]
        text_img = row_img[:, : int(row_img.shape[1] * 0.86)]
        txt = _ocr_row_text(text_img, ocr=ocr)
        if not txt or len(_fuzzy_key(txt)) < 2:
            continue
        highlight_score = _row_highlight_score(row_img)
        cx = int(mon["left"] + x0 + int(row_img.shape[1] * 0.42))
        cy = int(mon["top"] + y0 + int((ry0 + ry1) / 2))
        rows.append(
            {
                "row_index": int(ridx),
                "text": txt,
                "key": _fuzzy_key(txt),
                "highlight_score": float(highlight_score),
                "click_point": {"x": cx, "y": cy},
            }
        )
    return {"rows": rows, "roi": {"x0": x0, "y0": y0, "x1": x1, "y1": y1}}


def _open_dropdown(anchor_x: int, anchor_y: int, delay_s: float) -> None:
    cx, cy, _ = clamp_point_to_active_window(anchor_x, anchor_y, margin_px=8)
    pyautogui.moveTo(cx, cy, duration=0.18)
    pyautogui.click()
    time.sleep(max(0.1, delay_s))


def _scroll_list(anchor_x: int, anchor_y: int, amount: int, delay_s: float) -> None:
    cx, cy, _ = clamp_point_to_active_window(anchor_x, anchor_y + 120, margin_px=20)
    pyautogui.moveTo(cx, cy, duration=0.05)
    pyautogui.scroll(int(amount))
    time.sleep(max(0.08, delay_s))


def _save_canvas_capture(monitor_index: int, out_dir: pathlib.Path, tag: str) -> str:
    img, _ = screenshot_monitor_np(monitor_index)
    out_path = out_dir / f"{tag}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), img)
    return str(out_path)


def run_scan(args: argparse.Namespace) -> Dict[str, Any]:
    focus_window_guard(str(args.window_title_contains), sleep_s=0.25)
    set_active_window_rect(str(args.window_title_contains))
    _ = configure_tesseract()
    cfg = _load_config(str(args.setup_config))
    ocr = create_ocr_engine()

    img, mon = screenshot_monitor_np(int(args.monitor_index))
    anchor = _resolve_dropdown_anchor(cfg, img=img, mon=mon)
    if not anchor:
        return {
            "ok": False,
            "reason": "plan_pages_dropdown_not_found",
            "hint": "Add anchors.plan_pages_dropdown to setup config or keep 'Plan Pages' label visible.",
        }

    ax = int(anchor["x"])
    ay = int(anchor["y"])
    _open_dropdown(ax, ay, delay_s=float(args.ui_delay_ms) / 1000.0)

    seen: Dict[str, Dict[str, Any]] = {}
    captures: List[Dict[str, Any]] = []
    scans: List[Dict[str, Any]] = []

    for step in range(max(1, int(args.scroll_steps))):
        frame, _ = screenshot_monitor_np(int(args.monitor_index))
        scan = _scan_visible_rows(
            monitor_img=frame,
            mon=mon,
            anchor_x=ax,
            anchor_y=ay,
            ocr=ocr,
            list_width=int(args.list_width_px),
            list_height=int(args.list_height_px),
            row_height=int(args.row_height_px),
        )
        rows = scan.get("rows", []) if isinstance(scan.get("rows", []), list) else []
        if rows:
            scores = sorted([float(r.get("highlight_score", 0.0) or 0.0) for r in rows])
            median = scores[len(scores) // 2]
            threshold = max(float(args.min_highlight_score), median + 0.015)
        else:
            threshold = float(args.min_highlight_score)

        step_rows: List[Dict[str, Any]] = []
        for row in rows:
            key = str(row.get("key", "") or "")
            is_high = float(row.get("highlight_score", 0.0) or 0.0) >= threshold
            row["is_highlighted"] = bool(is_high)
            row["scan_step"] = int(step)
            step_rows.append(row)
            if not key:
                continue
            existing = seen.get(key)
            if existing is None:
                seen[key] = dict(row)
            else:
                if float(row.get("highlight_score", 0.0) or 0.0) > float(existing.get("highlight_score", 0.0) or 0.0):
                    seen[key] = dict(row)
                elif bool(row.get("is_highlighted", False)) and not bool(existing.get("is_highlighted", False)):
                    seen[key]["is_highlighted"] = True

        scans.append(
            {
                "scan_step": int(step),
                "threshold": float(round(threshold, 5)),
                "row_count": len(step_rows),
                "rows": step_rows,
                "roi": scan.get("roi", {}),
            }
        )

        # Optional immediate capture pass for highlighted rows in current viewport.
        if bool(args.capture_highlighted):
            for row in step_rows:
                if not bool(row.get("is_highlighted", False)):
                    continue
                key = str(row.get("key", "") or "")
                if any(str(x.get("key", "")) == key for x in captures):
                    continue
                pt = row.get("click_point", {})
                cx = int(pt.get("x", 0) or 0)
                cy = int(pt.get("y", 0) or 0)
                if cx <= 0 or cy <= 0:
                    continue
                ccx, ccy, _ = clamp_point_to_active_window(cx, cy, margin_px=8)
                pyautogui.moveTo(ccx, ccy, duration=0.16)
                pyautogui.click()
                time.sleep(max(0.2, float(args.page_render_wait_ms) / 1000.0))
                shot = _save_canvas_capture(
                    monitor_index=int(args.monitor_index),
                    out_dir=pathlib.Path(args.capture_dir),
                    tag=f"page_{len(captures)+1:03d}_{key[:28]}",
                )
                captures.append({"key": key, "text": row.get("text", ""), "scan_step": int(step), "capture_png": shot})
                _open_dropdown(ax, ay, delay_s=float(args.ui_delay_ms) / 1000.0)

        if step < int(args.scroll_steps) - 1:
            _scroll_list(ax, ay, amount=-abs(int(args.scroll_amount)), delay_s=float(args.ui_delay_ms) / 1000.0)

    ordered_rows = sorted(seen.values(), key=lambda r: (int(r.get("scan_step", 0)), int(r.get("row_index", 0))))
    highlighted = [r for r in ordered_rows if bool(r.get("is_highlighted", False))]

    return {
        "ok": True,
        "created_at": datetime.now().isoformat(),
        "anchor": {"x": ax, "y": ay, "source": anchor.get("source", "unknown")},
        "monitor": mon,
        "selection_policy": {
            "signal": "dropdown_highlight",
            "notes": "Highlighted plan-page rows are prioritized as pages with existing takeoffs.",
        },
        "counts": {
            "unique_rows_seen": len(ordered_rows),
            "highlighted_rows": len(highlighted),
            "captures": len(captures),
        },
        "highlighted_pages": highlighted,
        "all_seen_pages": ordered_rows,
        "scan_steps": scans,
        "captures": captures,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Scan OST Plan Pages dropdown for highlighted rows")
    p.add_argument("--monitor-index", type=int, default=1)
    p.add_argument("--window-title-contains", default="On-Screen Takeoff")
    p.add_argument("--setup-config", default="scripts/ost_project_setup_agent.config.json")
    p.add_argument("--scroll-steps", type=int, default=12)
    p.add_argument("--scroll-amount", type=int, default=400)
    p.add_argument("--list-width-px", type=int, default=760)
    p.add_argument("--list-height-px", type=int, default=620)
    p.add_argument("--row-height-px", type=int, default=24)
    p.add_argument("--min-highlight-score", type=float, default=0.07)
    p.add_argument("--ui-delay-ms", type=int, default=260)
    p.add_argument("--capture-highlighted", action="store_true")
    p.add_argument("--page-render-wait-ms", type=int, default=800)
    p.add_argument("--capture-dir", default="output/ost-training-lab/plan_page_captures")
    p.add_argument(
        "--output-json",
        default="output/ost-training-lab/plan_pages_highlight_scan_latest.json",
    )
    args = p.parse_args()

    result = run_scan(args)
    out_path = pathlib.Path(args.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(str(out_path.resolve()))
    print(
        f"ok={str(bool(result.get('ok', False))).lower()} "
        f"highlighted_rows={int((result.get('counts', {}) or {}).get('highlighted_rows', 0) or 0)}"
    )
    return 0 if bool(result.get("ok", False)) else 1


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    raise SystemExit(main())

