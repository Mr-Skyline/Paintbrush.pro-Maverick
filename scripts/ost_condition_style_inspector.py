#!/usr/bin/env python3
"""
Open selected OST condition and read Style from properties dialog.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import time
from typing import Any, Dict

import mss
import numpy as np
import pyautogui
import pytesseract
from mouse_takeover_guard import install_pyautogui_takeover_guard
from ost_window_guard import clamp_point_to_active_window, set_active_window_rect

try:
    import pygetwindow as gw  # type: ignore
except Exception:  # pragma: no cover
    gw = None

install_pyautogui_takeover_guard(pyautogui)


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


def screenshot_monitor_np(monitor_index: int) -> np.ndarray:
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}.")
        shot = sct.grab(mons[monitor_index])
        return np.array(shot)[:, :, :3]


def center_dialog_roi(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    x0 = int(w * 0.22)
    y0 = int(h * 0.18)
    x1 = int(w * 0.78)
    y1 = int(h * 0.78)
    return img[y0:y1, x0:x1].copy()


def detect_style_from_text(text: str) -> str:
    low = str(text or "").lower()
    # Prefer explicit style line when present.
    m = re.search(r"style[^a-z0-9]{0,8}(linear|area|count|attachment)", low)
    if m:
        return str(m.group(1))
    # fallback keyword detection
    if "linear" in low:
        return "linear"
    if "area" in low:
        return "area"
    if "count" in low:
        return "count"
    if "attachment" in low:
        return "attachment"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect selected condition style")
    parser.add_argument("--x", type=int, required=True, help="Condition row x to open")
    parser.add_argument("--y", type=int, required=True, help="Condition row y to open")
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--window-title-contains", default="On-Screen Takeoff")
    parser.add_argument("--open-wait-ms", type=int, default=850)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()

    focused = focus_window(str(args.window_title_contains))
    set_active_window_rect(str(args.window_title_contains))
    style = ""
    text = ""
    click_variants = [
        (int(args.x), int(args.y)),
        (int(args.x) - 120, int(args.y)),
        (int(args.x) - 220, int(args.y)),
        (int(args.x) - 320, int(args.y)),
        (int(args.x) - 460, int(args.y)),
        (int(args.x) - 620, int(args.y)),
        (int(args.x) + 120, int(args.y)),
    ]
    for _ in range(max(1, int(args.retries))):
        for cx, cy in click_variants:
            sx, sy, _ = clamp_point_to_active_window(int(cx), int(cy), margin_px=10)
            pyautogui.moveTo(int(sx), int(sy), duration=0.15)
            pyautogui.doubleClick()
            time.sleep(max(0.3, int(args.open_wait_ms) / 1000.0))
            img = screenshot_monitor_np(max(1, int(args.monitor_index)))
            roi = center_dialog_roi(img)
            text = pytesseract.image_to_string(roi, config="--psm 6")
            style = detect_style_from_text(text)
            if style:
                break
            # Secondary OCR pass with sparse-text mode can help with dropdown rows.
            text2 = pytesseract.image_to_string(roi, config="--psm 11")
            style = detect_style_from_text(text2)
            text = f"{text}\n{text2}"
            if style:
                break
            pyautogui.press("esc")
            time.sleep(0.15)
            # Fallback open path: context menu -> Properties shortcut.
            pyautogui.moveTo(int(sx), int(sy), duration=0.12)
            pyautogui.click(button="right")
            time.sleep(0.2)
            pyautogui.press("p")
            time.sleep(max(0.35, int(args.open_wait_ms) / 1000.0))
            img = screenshot_monitor_np(max(1, int(args.monitor_index)))
            roi = center_dialog_roi(img)
            text = pytesseract.image_to_string(roi, config="--psm 6")
            style = detect_style_from_text(text)
            if not style:
                text2 = pytesseract.image_to_string(roi, config="--psm 11")
                style = detect_style_from_text(text2)
                text = f"{text}\n{text2}"
            if style:
                break
            pyautogui.press("esc")
            time.sleep(0.12)
        if style:
            break

    # Close the condition dialog and return to takeoff canvas.
    pyautogui.press("esc")
    time.sleep(0.12)
    pyautogui.press("esc")

    payload = {
        "ok": bool(style),
        "focused": focused,
        "x": int(args.x),
        "y": int(args.y),
        "style": style,
        "ocr_preview": " ".join((text or "").split())[:400],
    }
    if str(args.output_json or "").strip():
        write_json(pathlib.Path(str(args.output_json)), payload)
    print(json.dumps(payload, indent=2))
    return 0 if style else 4


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.04
    raise SystemExit(main())

