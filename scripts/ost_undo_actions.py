#!/usr/bin/env python3
"""
Cleanup helper for OST workflows.
"""

from __future__ import annotations

import argparse
import time

import pyautogui

from mouse_takeover_guard import install_pyautogui_takeover_guard

install_pyautogui_takeover_guard(pyautogui)


def release_modifier_keys() -> None:
    for key in ("ctrl", "shift", "alt", "win", "command"):
        try:
            pyautogui.keyUp(key)
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup helper using keyboard shortcuts.")
    parser.add_argument("--clear-count", type=int, default=2)
    parser.add_argument("--delay-ms", type=int, default=260)
    parser.add_argument("--mode", choices=["clear", "undo"], default="clear")
    args = parser.parse_args()

    clear_count = max(1, int(args.clear_count))
    delay_s = max(0.0, int(args.delay_ms) / 1000.0)
    release_modifier_keys()
    if str(args.mode) == "undo":
        for _ in range(clear_count):
            pyautogui.hotkey("ctrl", "z")
            time.sleep(delay_s)
            release_modifier_keys()
    else:
        for _ in range(clear_count):
            pyautogui.hotkey("ctrl", "a")
            time.sleep(max(0.08, delay_s / 3.0))
            pyautogui.press("delete")
            time.sleep(delay_s)
            release_modifier_keys()
    pyautogui.press("esc")
    release_modifier_keys()
    time.sleep(0.12)
    print(f"cleanup_mode={args.mode} actions_applied={clear_count}")
    return 0


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.04
    raise SystemExit(main())
