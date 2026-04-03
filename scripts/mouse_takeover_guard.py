#!/usr/bin/env python3
"""
Pause automation when user takes over mouse control.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Callable


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def install_pyautogui_takeover_guard(pyautogui: Any) -> None:
    if getattr(pyautogui, "_maverick_takeover_guard_installed", False):
        return

    enabled = _env_bool("MAVERICK_MOUSE_TAKEOVER_GUARD_ENABLED", True)
    if not enabled:
        pyautogui._maverick_takeover_guard_installed = True
        return

    pause_s = float(os.environ.get("MAVERICK_MOUSE_TAKEOVER_PAUSE_S", "15") or 15.0)
    threshold_px = float(os.environ.get("MAVERICK_MOUSE_TAKEOVER_THRESHOLD_PX", "12") or 12.0)
    own_grace_s = float(os.environ.get("MAVERICK_MOUSE_TAKEOVER_GRACE_S", "0.8") or 0.8)

    state = {
        "last_pos": None,
        "last_programmatic_at": 0.0,
    }

    def _dist(a: Any, b: Any) -> float:
        return math.hypot(float(a.x) - float(b.x), float(a.y) - float(b.y))

    def _pause_if_user_took_control() -> None:
        now = time.monotonic()
        pos = pyautogui.position()
        last_pos = state["last_pos"]
        last_prog = float(state["last_programmatic_at"] or 0.0)
        if (
            last_pos is not None
            and (now - last_prog) > own_grace_s
            and _dist(pos, last_pos) >= threshold_px
        ):
            print(
                f"mouse_takeover_detected pause_s={pause_s:.1f} "
                f"moved_px={_dist(pos, last_pos):.1f}"
            )
            time.sleep(max(0.0, pause_s))
        state["last_pos"] = pyautogui.position()

    def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            _pause_if_user_took_control()
            out = fn(*args, **kwargs)
            state["last_programmatic_at"] = time.monotonic()
            state["last_pos"] = pyautogui.position()
            return out

        return wrapped

    for name in (
        "click",
        "doubleClick",
        "rightClick",
        "moveTo",
        "dragTo",
        "dragRel",
        "mouseDown",
        "mouseUp",
        "press",
        "hotkey",
    ):
        if hasattr(pyautogui, name):
            setattr(pyautogui, name, _wrap(getattr(pyautogui, name)))

    pyautogui._maverick_takeover_guard_installed = True
    print(
        f"mouse_takeover_guard_enabled pause_s={pause_s:.1f} "
        f"threshold_px={threshold_px:.1f}"
    )

