#!/usr/bin/env python3
"""
OST UI Mapper

Creates/updates an atlas of stable UI anchors for black-box automation.

Examples:
  python scripts/ost_ui_mapper.py init --atlas scripts/ost_ui_atlas.json
  python scripts/ost_ui_mapper.py capture --atlas scripts/ost_ui_atlas.json
  python scripts/ost_ui_mapper.py show --atlas scripts/ost_ui_atlas.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime
from typing import Any, Dict, List, Tuple

import cv2
import mss
import numpy as np
import pyautogui

from mouse_takeover_guard import install_pyautogui_takeover_guard

install_pyautogui_takeover_guard(pyautogui)


DEFAULT_ATLAS = {
    "version": 1,
    "profile": "primary-ost-monitor",
    "description": "Anchor atlas for local OST black-box automation",
    "window_title_contains": "On-Screen Takeoff",
    "monitor": {
        "index": 1,
        "expected_width": 1920,
        "expected_height": 1080,
    },
    "anchors": {
        "boost_button": {"x": 0, "y": 0},
        "boost_run_button": {"x": 0, "y": 0},
        "boost_close_button": {"x": 0, "y": 0},
    },
    "relative_regions": {
        "boost_dialog_run_zone": {
            "description": "Lower-right area in Boost dialog where Run button is expected",
            "x_ratio_min": 0.5,
            "y_ratio_min": 0.55,
        }
    },
    "verification": {
        "require_scale_warning_absent": True,
        "open_change_threshold": 1.2,
        "run_change_threshold": 0.35,
        "run_full_change_threshold": 0.08,
    },
    "updated_at": "",
}


SETUP_ANCHOR_PROMPTS: List[Tuple[str, str]] = [
    ("training_playground_first_project", "Project row under Training Playground (not the header row)"),
    ("file_menu", "Top app menu: File"),
    ("new_project_menu_item", "File menu item: New Project"),
    ("project_name_input", "New Project dialog: Project Name input"),
    ("project_path_input", "New Project dialog: Project Path input"),
    ("project_pdf_input", "New Project dialog: Plan/PDF input"),
    ("project_ok_button", "New Project dialog: OK/Create button"),
]

BOOST_ANCHOR_PROMPTS: List[Tuple[str, str]] = [
    ("boost_button", "Top-right green Boost button"),
    ("boost_run_button", "Boost dialog blue Run button"),
    ("boost_close_button", "Boost dialog X close button"),
]


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return DEFAULT_ATLAS.copy()
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, data: Dict[str, Any]) -> None:
    data["updated_at"] = datetime.now().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_setup_config(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "enabled": False,
            "window_title_contains": "On-Screen Takeoff",
            "monitor_index": 1,
            "anchors": {},
            "steps": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def write_setup_config(path: pathlib.Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def cmd_init(atlas_path: pathlib.Path) -> int:
    atlas = read_json(atlas_path)
    write_json(atlas_path, atlas)
    print(f"Atlas initialized: {atlas_path}")
    return 0


def prompt_anchor(name: str) -> Dict[str, int]:
    input(f"Move mouse over '{name}' then press Enter...")
    pos = pyautogui.position()
    print(f"  captured {name}: ({pos.x}, {pos.y})")
    return {"x": int(pos.x), "y": int(pos.y)}


def cmd_capture(atlas_path: pathlib.Path) -> int:
    atlas = read_json(atlas_path)
    anchors = atlas.setdefault("anchors", {})
    print("\nCapture mode: OST UI anchors")
    print("Capture these in this order with OST visible:")
    print("- boost_button (top-right green button)")
    print("- boost_run_button (blue Run Takeoff Boost button inside dialog)")
    print("- boost_close_button (X at top-right of Boost dialog)\n")

    for key in ("boost_button", "boost_run_button", "boost_close_button"):
        anchors[key] = prompt_anchor(key)

    write_json(atlas_path, atlas)
    print(f"\nAtlas updated: {atlas_path}")
    return 0


def cmd_capture_full(atlas_path: pathlib.Path, setup_config_path: pathlib.Path) -> int:
    atlas = read_json(atlas_path)
    setup_cfg = read_setup_config(setup_config_path)
    atlas_anchors = atlas.setdefault("anchors", {})
    setup_anchors = setup_cfg.setdefault("anchors", {})

    print("\nFull capture mode: Boost + Project Setup")
    print("Move mouse over each target and press Enter.")
    print("Keep OST on the mapped monitor and open the requested dialog when prompted.\n")

    print("Phase 1/2: Boost controls")
    for key, label in BOOST_ANCHOR_PROMPTS:
        print(f"- {key}: {label}")
        pt = prompt_anchor(key)
        atlas_anchors[key] = pt

    print("\nPhase 2/2: New Project setup controls")
    for key, label in SETUP_ANCHOR_PROMPTS:
        print(f"- {key}: {label}")
        pt = prompt_anchor(key)
        setup_anchors[key] = pt

    write_json(atlas_path, atlas)
    write_setup_config(setup_config_path, setup_cfg)
    print("\nCapture complete.")
    print(f"Updated atlas: {atlas_path}")
    print(f"Updated setup config: {setup_config_path}")
    print("\nMapped anchors:")
    print(json.dumps({"boost": BOOST_ANCHOR_PROMPTS, "setup": SETUP_ANCHOR_PROMPTS}, indent=2))
    return 0


def cmd_capture_setup_anchor(setup_config_path: pathlib.Path, anchor_name: str) -> int:
    setup_cfg = read_setup_config(setup_config_path)
    anchors = setup_cfg.setdefault("anchors", {})
    print("\nCapture setup anchor")
    print(f"- anchor: {anchor_name}")
    pt = prompt_anchor(anchor_name)
    anchors[anchor_name] = pt
    write_setup_config(setup_config_path, setup_cfg)
    print(f"\nUpdated setup config: {setup_config_path}")
    print(json.dumps({anchor_name: pt}, indent=2))
    return 0


def cmd_capture_setup_anchor_delayed(setup_config_path: pathlib.Path, anchor_name: str, seconds: int) -> int:
    setup_cfg = read_setup_config(setup_config_path)
    anchors = setup_cfg.setdefault("anchors", {})
    wait_s = max(1, int(seconds))
    print("\nDelayed setup anchor capture")
    print(f"- anchor: {anchor_name}")
    print(f"- capturing in {wait_s} seconds...")
    for i in range(wait_s, 0, -1):
        print(f"  {i}...")
        sleep_s = 1.0
        import time
        time.sleep(sleep_s)
    pos = pyautogui.position()
    pt = {"x": int(pos.x), "y": int(pos.y)}
    anchors[anchor_name] = pt
    write_setup_config(setup_config_path, setup_cfg)
    print(f"\nUpdated setup config: {setup_config_path}")
    print(json.dumps({anchor_name: pt}, indent=2))
    return 0


def cmd_show(atlas_path: pathlib.Path) -> int:
    atlas = read_json(atlas_path)
    print(json.dumps(atlas, indent=2))
    return 0


def grab_monitor_image(monitor_index: int) -> tuple[np.ndarray, Dict[str, int]]:
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index < 1 or monitor_index >= len(monitors):
            raise ValueError(
                f"monitor_index={monitor_index} invalid; available 1..{len(monitors)-1}"
            )
        mon = monitors[monitor_index]
        shot = sct.grab(mon)
        # BGRA -> BGR
        img = np.array(shot)[:, :, :3]
        return img, {
            "left": int(mon["left"]),
            "top": int(mon["top"]),
            "width": int(mon["width"]),
            "height": int(mon["height"]),
        }


def detect_boost_button_local(img: np.ndarray) -> tuple[int, int] | None:
    h, w = img.shape[:2]
    roi = img[0 : int(h * 0.22), int(w * 0.55) : w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    lo = np.array([40, 70, 60], dtype=np.uint8)
    hi = np.array([95, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lo, hi)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = -1.0
    x_off = int(w * 0.55)
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < 500:
            continue
        aspect = cw / max(ch, 1)
        if aspect < 1.4 or aspect > 10:
            continue
        cx = x + cw / 2
        cy = y + ch / 2
        score = area + cx * 1.4 - cy * 0.2
        if score > best_score:
            best_score = score
            best = (int(x_off + cx), int(cy))
    return best


def detect_boost_run_button_local(img: np.ndarray) -> tuple[int, int] | None:
    h, w = img.shape[:2]
    roi = img[int(h * 0.50) : h, int(w * 0.45) : w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    lo = np.array([95, 70, 70], dtype=np.uint8)
    hi = np.array([130, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lo, hi)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = -1.0
    x_off = int(w * 0.45)
    y_off = int(h * 0.50)
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < 900:
            continue
        aspect = cw / max(ch, 1)
        if aspect < 1.6 or aspect > 8.0:
            continue
        cx = x + cw / 2
        cy = y + ch / 2
        score = area + cx * 0.8 + cy * 0.8
        if score > best_score:
            best_score = score
            best = (int(x_off + cx), int(y_off + cy))
    return best


def estimate_boost_close_from_run(run_local: tuple[int, int] | None) -> tuple[int, int] | None:
    if not run_local:
        return None
    rx, ry = run_local
    # Empirical offset for OST Boost dialog (stable on fixed monitor/layout).
    return (int(rx + 40), int(ry - 740))


def cmd_autodetect(atlas_path: pathlib.Path) -> int:
    atlas = read_json(atlas_path)
    monitor_index = int(atlas.get("monitor", {}).get("index", 1))
    img, mon = grab_monitor_image(monitor_index)
    anchors = atlas.setdefault("anchors", {})

    boost_local = detect_boost_button_local(img)
    run_local = detect_boost_run_button_local(img)
    close_local = estimate_boost_close_from_run(run_local)

    updates = {}
    if boost_local:
        updates["boost_button"] = {"x": mon["left"] + boost_local[0], "y": mon["top"] + boost_local[1]}
    if run_local:
        updates["boost_run_button"] = {"x": mon["left"] + run_local[0], "y": mon["top"] + run_local[1]}
    if close_local:
        updates["boost_close_button"] = {"x": mon["left"] + close_local[0], "y": mon["top"] + close_local[1]}

    anchors.update(updates)
    write_json(atlas_path, atlas)
    print("Autodetect complete.")
    print(json.dumps({"monitor": mon, "updated_anchors": updates}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OST UI Atlas mapper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("init", "capture", "show", "autodetect"):
        p = sub.add_parser(name)
        p.add_argument(
            "--atlas",
            default="scripts/ost_ui_atlas.json",
            help="Path to atlas json",
        )
    p_full = sub.add_parser("capture-full")
    p_full.add_argument(
        "--atlas",
        default="scripts/ost_ui_atlas.json",
        help="Path to atlas json",
    )
    p_full.add_argument(
        "--setup-config",
        default="scripts/ost_project_setup_agent.config.json",
        help="Path to setup agent config json",
    )
    p_one = sub.add_parser("capture-setup-anchor")
    p_one.add_argument(
        "--setup-config",
        default="scripts/ost_project_setup_agent.config.json",
        help="Path to setup agent config json",
    )
    p_one.add_argument(
        "--anchor",
        required=True,
        help="Setup anchor name to capture (e.g. training_playground_first_project)",
    )
    p_one_delay = sub.add_parser("capture-setup-anchor-delayed")
    p_one_delay.add_argument(
        "--setup-config",
        default="scripts/ost_project_setup_agent.config.json",
        help="Path to setup agent config json",
    )
    p_one_delay.add_argument(
        "--anchor",
        required=True,
        help="Setup anchor name to capture (e.g. training_playground_first_project)",
    )
    p_one_delay.add_argument(
        "--seconds",
        type=int,
        default=10,
        help="Seconds to wait before capturing current mouse position",
    )

    args = parser.parse_args()
    if args.cmd == "init":
        return cmd_init(pathlib.Path(args.atlas))
    if args.cmd == "capture":
        return cmd_capture(pathlib.Path(args.atlas))
    if args.cmd == "show":
        return cmd_show(pathlib.Path(args.atlas))
    if args.cmd == "autodetect":
        return cmd_autodetect(pathlib.Path(args.atlas))
    if args.cmd == "capture-full":
        return cmd_capture_full(pathlib.Path(args.atlas), pathlib.Path(args.setup_config))
    if args.cmd == "capture-setup-anchor":
        return cmd_capture_setup_anchor(pathlib.Path(args.setup_config), str(args.anchor))
    if args.cmd == "capture-setup-anchor-delayed":
        return cmd_capture_setup_anchor_delayed(
            pathlib.Path(args.setup_config), str(args.anchor), int(args.seconds)
        )
    return 1


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    raise SystemExit(main())
