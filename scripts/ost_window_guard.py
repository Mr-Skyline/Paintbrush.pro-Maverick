#!/usr/bin/env python3
"""
Window-bound click guard helpers for OST automation.
"""

from __future__ import annotations

import time
from typing import Dict, Tuple

try:
    import pygetwindow as gw  # type: ignore
except Exception:  # pragma: no cover
    gw = None


ACTIVE_WINDOW_RECT: Dict[str, int] = {}


def focus_window(title_contains: str, sleep_s: float = 0.25) -> bool:
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
        time.sleep(max(0.05, float(sleep_s)))
        return True
    except Exception:
        return False


def set_active_window_rect(title_contains: str) -> Dict[str, int]:
    global ACTIVE_WINDOW_RECT
    if gw is None:
        ACTIVE_WINDOW_RECT = {}
        return {}
    try:
        wins = gw.getWindowsWithTitle(title_contains)
        if not wins:
            ACTIVE_WINDOW_RECT = {}
            return {}
        w = wins[0]
        ACTIVE_WINDOW_RECT = {
            "left": int(getattr(w, "left", 0) or 0),
            "top": int(getattr(w, "top", 0) or 0),
            "width": max(0, int(getattr(w, "width", 0) or 0)),
            "height": max(0, int(getattr(w, "height", 0) or 0)),
        }
        return dict(ACTIVE_WINDOW_RECT)
    except Exception:
        ACTIVE_WINDOW_RECT = {}
        return {}


def clamp_point_to_active_window(x: int, y: int, margin_px: int = 8) -> Tuple[int, int, bool]:
    rect = ACTIVE_WINDOW_RECT if isinstance(ACTIVE_WINDOW_RECT, dict) else {}
    if not rect:
        return int(x), int(y), False
    left = int(rect.get("left", 0) or 0)
    top = int(rect.get("top", 0) or 0)
    width = int(rect.get("width", 0) or 0)
    height = int(rect.get("height", 0) or 0)
    if width <= 0 or height <= 0:
        return int(x), int(y), False
    right = left + width
    bottom = top + height
    m = max(0, int(margin_px))
    min_x = left + m
    max_x = max(min_x, right - m)
    min_y = top + m
    max_y = max(min_y, bottom - m)
    cx = max(min_x, min(int(x), max_x))
    cy = max(min_y, min(int(y), max_y))
    return int(cx), int(cy), bool(cx != int(x) or cy != int(y))

