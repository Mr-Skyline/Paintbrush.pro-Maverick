#!/usr/bin/env python3
"""
Select an OST condition row, with OCR-based active-condition detection.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import time
from typing import Any, Dict, List, Tuple

import mss
import numpy as np
import pyautogui
import pytesseract
import cv2

from mouse_takeover_guard import install_pyautogui_takeover_guard
from ocr_engine import create_ocr_engine, OcrEngine

try:
    import pygetwindow as gw  # type: ignore
except Exception:  # pragma: no cover
    gw = None

install_pyautogui_takeover_guard(pyautogui)


def read_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def focus_window(title_contains: str) -> bool:
    if gw is None:
        return False
    try:
        wins = gw.getWindowsWithTitle(title_contains)
        if not wins:
            return False
        w = wins[0]
        if w.isMinimized:
            w.restore()
        w.activate()
        time.sleep(0.25)
        return True
    except Exception:
        return False


def monitor_rect(monitor_index: int) -> Dict[str, int]:
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}.")
        mon = mons[monitor_index]
        return {
            "left": int(mon["left"]),
            "top": int(mon["top"]),
            "width": int(mon["width"]),
            "height": int(mon["height"]),
        }


def clamp_point_to_safe_monitor_zone(
    x: int,
    y: int,
    monitor: Dict[str, int],
    bottom_margin_px: int = 120,
    side_margin_px: int = 8,
) -> Tuple[int, int, bool]:
    left = int(monitor["left"])
    top = int(monitor["top"])
    right = left + int(monitor["width"])
    bottom = top + int(monitor["height"])
    safe_x = max(left + side_margin_px, min(int(x), right - side_margin_px))
    safe_y = max(top + side_margin_px, min(int(y), bottom - max(40, bottom_margin_px)))
    changed = (safe_x != int(x)) or (safe_y != int(y))
    return safe_x, safe_y, changed


def screenshot_monitor_np(monitor_index: int) -> np.ndarray:
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}.")
        shot = sct.grab(mons[monitor_index])
        return np.array(shot)[:, :, :3]


def _safe_float(token: str) -> float:
    raw = str(token or "").strip().replace(",", "")
    try:
        return float(raw)
    except Exception:
        return 0.0


def _qty_positive(text: str) -> Tuple[bool, float]:
    nums = re.findall(r"\d+(?:\.\d+)?", text or "")
    vals = [_safe_float(n) for n in nums]
    vals = [v for v in vals if v > 0.0]
    if not vals:
        return False, 0.0
    return True, max(vals)


def _best_qty_from_texts(texts: List[str]) -> Tuple[bool, float, str]:
    best_val = 0.0
    best_txt = ""
    found = False
    for t in texts:
        ok, val = _qty_positive(t)
        if ok and val > best_val:
            best_val = val
            best_txt = str(t or "")
            found = True
    return found, best_val, best_txt


def _parse_preferred_keywords(raw: str) -> List[str]:
    toks = [t.strip().lower() for t in str(raw or "").split(",")]
    return [t for t in toks if t]


def detect_active_condition_row(
    cfg: Dict[str, Any],
    monitor_index: int,
    ocr: OcrEngine,
    preferred_keywords: List[str] | None = None,
) -> Dict[str, Any]:
    anchors = cfg.get("anchors", {}) if isinstance(cfg, dict) else {}
    a1 = anchors.get("conditions_first_row", {}) if isinstance(anchors, dict) else {}
    a2 = anchors.get("conditions_second_row", {}) if isinstance(anchors, dict) else {}
    if not (isinstance(a1, dict) and isinstance(a2, dict) and "x" in a1 and "y" in a1 and "x" in a2 and "y" in a2):
        return {"ok": False, "reason": "missing_condition_anchors"}

    mon = monitor_rect(monitor_index)
    img = screenshot_monitor_np(monitor_index)
    ax = int(a1["x"])
    ay = int(a1["y"])
    by = int(a2["y"])
    row_h = max(18, abs(by - ay))
    lx = ax - mon["left"]
    ly = ay - mon["top"]
    x0 = max(0, lx - 70)
    x1 = min(mon["width"], lx + 1120)
    y0 = max(0, ly - int(row_h * 0.45))
    y1 = min(mon["height"], ly + (row_h * 18))
    if x1 <= x0 or y1 <= y0:
        return {"ok": False, "reason": "invalid_conditions_roi"}

    roi = img[y0:y1, x0:x1]
    candidates: List[Dict[str, Any]] = []
    preferred_keywords = preferred_keywords or []
    ocr_calls: List[Dict[str, Any]] = []
    # Scan expected row bands and OCR name + quantity columns separately.
    panel_w = x1 - x0
    name_col_x0 = 0
    name_col_x1 = max(name_col_x0 + 60, panel_w - 260)
    for ridx in range(0, 16):
        ry0 = int(ridx * row_h)
        ry1 = min(roi.shape[0], int((ridx + 1) * row_h))
        if ry1 <= ry0 + 8:
            continue
        row_img = roi[ry0:ry1, :]
        gray = cv2.cvtColor(row_img, cv2.COLOR_BGR2GRAY)
        name_img = gray[:, name_col_x0:name_col_x1]
        qty_variants = []
        for span in (220, 300, 380):
            qx0 = max(0, panel_w - span)
            qx1 = panel_w
            qty_variants.append(gray[:, qx0:qx1])

        name_thr = cv2.adaptiveThreshold(name_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
        name_res = ocr.ocr_text(name_thr, context="OST conditions row name OCR", psm=6)
        name_txt = str(name_res.get("text", "") or "").strip()
        ocr_calls.append(
            {
                "field": "name",
                "engine_used": str(name_res.get("engine_used", "")),
                "fallback_used": bool(name_res.get("fallback_used", False)),
            }
        )
        qty_texts: List[str] = []
        for qimg in qty_variants:
            qthr = cv2.adaptiveThreshold(qimg, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
            qty_res = ocr.ocr_text(
                qthr,
                context="OST conditions quantity OCR",
                psm=7,
                whitelist="0123456789.,",
            )
            qtxt = str(qty_res.get("text", "") or "").strip()
            ocr_calls.append(
                {
                    "field": "qty",
                    "engine_used": str(qty_res.get("engine_used", "")),
                    "fallback_used": bool(qty_res.get("fallback_used", False)),
                }
            )
            if qtxt:
                qty_texts.append(qtxt)
        lower = name_txt.lower()
        if "unassigned" in lower or "(unassigned)" in lower:
            continue
        alpha_count = len(re.findall(r"[A-Za-z]", name_txt))
        if alpha_count < 2:
            continue
        has_qty, qty, qty_txt = _best_qty_from_texts(qty_texts)
        if not has_qty or qty <= 0.0:
            continue
        y_center = int((ry0 + ry1) / 2.0)
        # Prefer rows near top when multiple conditions are active.
        matched_keyword = ""
        for kw in preferred_keywords:
            if kw and kw in lower:
                matched_keyword = kw
                break
        score = float((1000 - ridx) + (qty * 0.01) + (2000 if matched_keyword else 0))
        candidates.append(
            {
                "row_index": ridx,
                "text": name_txt,
                "qty_text": qty_txt,
                "qty": round(qty, 3),
                "matched_keyword": matched_keyword,
                "score": round(score, 3),
                "y_center_local": y_center,
                "y_center_global": int(mon["top"] + y0 + y_center),
            }
        )

    if not candidates:
        return {
            "ok": False,
            "reason": "no_active_condition_detected",
            "ocr_diagnostics": {
                "engine": ocr.get_diagnostics(),
                "call_samples": ocr_calls[:60],
            },
            "roi_global": {
                "x": int(mon["left"] + x0),
                "y": int(mon["top"] + y0),
                "w": int(x1 - x0),
                "h": int(y1 - y0),
            },
        }
    candidates.sort(key=lambda c: float(c.get("score", 0.0)), reverse=True)
    best = candidates[0]
    return {
        "ok": True,
        "selected": best,
        "candidates": candidates[:12],
        "ocr_diagnostics": {
            "engine": ocr.get_diagnostics(),
            "call_samples": ocr_calls[:60],
        },
        "roi_global": {
            "x": int(mon["left"] + x0),
            "y": int(mon["top"] + y0),
            "w": int(x1 - x0),
            "h": int(y1 - y0),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Select condition row in OST (anchor or OCR active-qty mode)")
    parser.add_argument("--setup-config", default="scripts/ost_project_setup_agent.config.json")
    parser.add_argument("--condition-row", choices=["first", "second"], default="first")
    parser.add_argument(
        "--selection-mode",
        choices=["anchor_row", "active_qty_non_unassigned"],
        default="active_qty_non_unassigned",
    )
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--window-title-contains", default="On-Screen Takeoff")
    parser.add_argument("--click-delay-ms", type=int, default=450)
    parser.add_argument("--taskbar-safe-margin-px", type=int, default=120)
    parser.add_argument(
        "--prefer-contains",
        default="ceiling,ceil,cen,gwb,gyp,gypsum",
        help="Comma-separated preferred condition keywords.",
    )
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()

    cfg = read_json(pathlib.Path(args.setup_config))
    ocr = create_ocr_engine()
    anchors = cfg.get("anchors", {}) if isinstance(cfg, dict) else {}
    focused = focus_window(str(args.window_title_contains))
    key = "conditions_first_row" if args.condition_row == "first" else "conditions_second_row"
    pt = anchors.get(key, {}) if isinstance(anchors, dict) else {}
    if not isinstance(pt, dict) or "x" not in pt or "y" not in pt:
        print(f"missing_anchor={key}")
        return 2

    selection: Dict[str, Any] = {
        "ok": True,
        "selection_mode": args.selection_mode,
        "focused": focused,
        "fallback_anchor": {"name": key, "x": int(pt["x"]), "y": int(pt["y"])},
    }
    x, y = int(pt["x"]), int(pt["y"])
    mon = monitor_rect(max(1, int(args.monitor_index)))
    if args.selection_mode == "active_qty_non_unassigned":
        preferred = _parse_preferred_keywords(str(args.prefer_contains))
        selection["preferred_keywords"] = preferred
        detected = detect_active_condition_row(
            cfg=cfg,
            monitor_index=max(1, int(args.monitor_index)),
            ocr=ocr,
            preferred_keywords=preferred,
        )
        selection["active_detection"] = detected
        if bool(detected.get("ok", False)):
            sel = detected.get("selected", {})
            if isinstance(sel, dict):
                y = int(sel.get("y_center_global", y))
                selection["selected_condition_text"] = str(sel.get("text", ""))
                selection["selected_condition_qty"] = float(sel.get("qty", 0.0) or 0.0)
                selection["selected_condition_keyword"] = str(sel.get("matched_keyword", "") or "")
                selection["selected_by"] = "active_qty_non_unassigned"
        else:
            selection["selected_by"] = "fallback_anchor_row"
    else:
        selection["selected_by"] = "anchor_row"

    safe_x, safe_y, adjusted = clamp_point_to_safe_monitor_zone(
        x=x,
        y=y,
        monitor=mon,
        bottom_margin_px=max(40, int(args.taskbar_safe_margin_px)),
    )
    if adjusted:
        selection["taskbar_safe_adjustment"] = {
            "applied": True,
            "from": {"x": x, "y": y},
            "to": {"x": safe_x, "y": safe_y},
            "bottom_margin_px": max(40, int(args.taskbar_safe_margin_px)),
        }
    else:
        selection["taskbar_safe_adjustment"] = {"applied": False}

    pyautogui.click(x=safe_x, y=safe_y)
    time.sleep(max(0.15, int(args.click_delay_ms) / 1000.0))
    selection["click_point"] = {"x": safe_x, "y": safe_y}
    if str(args.output_json or "").strip():
        write_json(pathlib.Path(str(args.output_json)), selection)
    print(
        f"selected_condition_row={args.condition_row} mode={args.selection_mode} "
        f"selected_by={selection.get('selected_by')} focused={focused} point=({x},{y})"
    )
    return 0


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.04
    raise SystemExit(main())
