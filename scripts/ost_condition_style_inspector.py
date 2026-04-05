#!/usr/bin/env python3
"""
Open the focused OST condition row (double-click), OCR the Style field from the
properties dialog, then close with Esc.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import time
from typing import Any, Dict, List, Tuple

import cv2
import mss
import mss.tools
import numpy as np
import pyautogui

from mouse_takeover_guard import install_pyautogui_takeover_guard
from ocr_engine import create_ocr_engine

try:
    import pygetwindow as gw  # type: ignore
except Exception:  # pragma: no cover
    gw = None

install_pyautogui_takeover_guard(pyautogui)

STYLE_ALIASES: List[Tuple[str, str]] = [
    ("attachment", "attachment"),
    ("linear", "linear"),
    ("count", "count"),
    ("area", "area"),
]


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


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
        time.sleep(0.35)
        return True
    except Exception:
        return False


def get_foreground_window_rect(title_contains: str) -> Dict[str, int] | None:
    if gw is None:
        return None
    try:
        wins = gw.getWindowsWithTitle(title_contains)
        if not wins:
            return None
        w = wins[0]
        return {
            "left": int(w.left),
            "top": int(w.top),
            "width": int(w.width),
            "height": int(w.height),
        }
    except Exception:
        return None


def clamp_to_rect(x: int, y: int, rect: Dict[str, int] | None, margin: int = 4) -> Tuple[int, int]:
    if not rect:
        return x, y
    left = int(rect["left"]) + margin
    top = int(rect["top"]) + margin
    right = int(rect["left"]) + int(rect["width"]) - margin
    bottom = int(rect["top"]) + int(rect["height"]) - margin
    if right <= left or bottom <= top:
        return x, y
    return max(left, min(x, right)), max(top, min(y, bottom))


def screenshot_monitor_png(monitor_index: int, out_path: pathlib.Path) -> Dict[str, int]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}")
        shot = sct.grab(mons[monitor_index])
        mss.tools.to_png(shot.rgb, shot.size, output=str(out_path))
        m = mons[monitor_index]
        return {
            "left": int(m["left"]),
            "top": int(m["top"]),
            "width": int(m["width"]),
            "height": int(m["height"]),
        }


def _ocr_dialog_region(
    monitor_index: int,
    ocr: Any,
    crop_fraction: float = 0.55,
) -> Tuple[str, Dict[str, Any]]:
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}")
        shot = sct.grab(mons[monitor_index])
        img = np.array(shot)[:, :, :3]
    h, w = img.shape[0], img.shape[1]
    cw = max(120, int(w * float(crop_fraction)))
    x0 = max(0, w - cw)
    roi = img[:, x0:w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
    res = ocr.ocr_text(thr, context="OST condition dialog Style OCR", psm=6)
    text = str(res.get("text", "") or "")
    return text, {"engine_used": res.get("engine_used"), "fallback_used": res.get("fallback_used")}


def parse_style_from_ocr(text: str) -> Tuple[str, str]:
    raw = str(text or "")
    lower = raw.lower()
    m = re.search(
        r"style\s*[:.]?\s*([a-z]+)",
        lower,
        re.IGNORECASE,
    )
    if m:
        token = re.sub(r"[^a-z]", "", m.group(1).lower())
        if token.startswith("lin") or token == "line":
            return "linear", raw
        if token.startswith("cou"):
            return "count", raw
        if "attach" in token:
            return "attachment", raw
        if "area" in token or token.startswith("ar"):
            return "area", raw
    for key, canonical in STYLE_ALIASES:
        if re.search(rf"\b{re.escape(key)}\b", lower):
            return canonical, raw
    return "", raw


def close_dialog() -> None:
    for _ in range(2):
        pyautogui.press("esc")
        time.sleep(0.12)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect OST condition Style via dialog OCR")
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--window-title-contains", default="On-Screen Takeoff")
    parser.add_argument("--click-x", type=int, required=True)
    parser.add_argument("--click-y", type=int, required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--screenshot-path", default="")
    args = parser.parse_args()

    focused = focus_window(str(args.window_title_contains))
    rect = get_foreground_window_rect(str(args.window_title_contains))
    cx, cy = clamp_to_rect(int(args.click_x), int(args.click_y), rect)

    pyautogui.moveTo(cx, cy, duration=0.12)
    time.sleep(0.08)
    pyautogui.doubleClick()
    time.sleep(0.75)

    shot_meta: Dict[str, Any] = {}
    if str(args.screenshot_path or "").strip():
        sp = pathlib.Path(str(args.screenshot_path))
        shot_meta = screenshot_monitor_png(max(1, int(args.monitor_index)), sp)

    ocr = create_ocr_engine()
    ocr_text, ocr_meta = _ocr_dialog_region(max(1, int(args.monitor_index)), ocr)
    style, raw_snippet = parse_style_from_ocr(ocr_text)
    ok = bool(style)

    close_dialog()
    time.sleep(0.2)

    payload: Dict[str, Any] = {
        "ok": ok,
        "focused_window": focused,
        "ost_window_rect": rect,
        "click_point": {"x": cx, "y": cy, "requested": {"x": int(args.click_x), "y": int(args.click_y)}},
        "style": style,
        "style_inspection_ok": ok,
        "ocr_text_sample": (raw_snippet[:1200] if raw_snippet else ""),
        "ocr_meta": ocr_meta,
        "screenshot": str(args.screenshot_path) if args.screenshot_path else "",
        "screenshot_monitor": shot_meta,
    }
    if str(args.output_json or "").strip():
        write_json(pathlib.Path(str(args.output_json)), payload)
    print(f"condition_style_inspector ok={ok} style={style or 'unknown'}")
    return 0 if ok else 1


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.04
    raise SystemExit(main())
