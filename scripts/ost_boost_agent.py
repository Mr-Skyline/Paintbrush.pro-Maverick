#!/usr/bin/env python3
"""
OST Boost Agent (black-box desktop automation)

This script automates only the Boost workflow in licensed OST:
1) Focus OST window
2) Click "Takeoff Boost"
3) Click "Run" (or page-scope run button)
4) Capture before/after screenshots + OCR evidence

Usage:
  python scripts/ost_boost_agent.py calibrate --config scripts/ost_boost_agent.config.json
  python scripts/ost_boost_agent.py run --config scripts/ost_boost_agent.config.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Tuple

try:
    import cv2
    import mss
    import numpy as np
    import pyautogui
    import pygetwindow as gw
    import pytesseract
except Exception as exc:  # pragma: no cover
    print(
        "Missing dependencies. Install with:\n"
        "  pip install pyautogui pygetwindow mss pillow opencv-python pytesseract numpy\n"
        f"Import error: {exc}"
    )
    raise

from mouse_takeover_guard import install_pyautogui_takeover_guard

install_pyautogui_takeover_guard(pyautogui)


DEFAULT_CONFIG = {
    "strict_four_step": True,
    "use_ui_atlas": True,
    "ui_atlas_path": "scripts/ost_ui_atlas.json",
    "window_title_contains": "On-Screen Takeoff",
    "monitor_index": 1,
    "click_delay_ms": 450,
    "post_boost_open_wait_ms": 1200,
    "post_boost_ready_wait_ms": 4000,
    "ready_poll_ms": 500,
    "post_boost_run_wait_ms": 3500,
    "run_observe_total_ms": 12000,
    "run_observe_poll_ms": 1500,
    "max_open_retries": 2,
    "max_run_retries": 2,
    "run_click_strategy": "auto",
    "run_click_repeats": 1,
    "adaptive_retries": {
        "enabled": True,
        "max_open_retries_cap": 4,
        "max_run_retries_cap": 5,
        "scale_per_failures": 5
    },
    "require_scale_warning_absent": True,
    "anchors": {
        "boost_button": {"x": 930, "y": 61},
        "boost_run_button": {"x": 682, "y": 141},
        "boost_close_button": {"x": 930, "y": 95},
    },
    "boost_option_clicks": [],
    "auto_scale_preflight": {
        "enabled": False,
        "max_cycles": 1,
        "scale_clicks": []
    },
    "vision_checks": {
        "enabled": True,
        "open_change_threshold": 1.2,
        "run_change_threshold": 0.35,
        "run_full_change_threshold": 0.08,
        "open_black_frame_max_ratio": 0.85,
        "run_roi_half_width": 360,
        "run_roi_half_height": 220
    },
    "ocr_checks": {
        "enabled": True,
        "expected_any_after_run": ["boost", "finding", "review", "condition"],
    },
    "maverick_logging": {
        "enabled": True,
        "runtime_config_path": "scripts/maverick_runtime.config.json",
        "project_id": "",
    },
}


@dataclass
class Point:
    x: int
    y: int


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return DEFAULT_CONFIG.copy()
    return json.loads(path.read_text(encoding="utf-8"))


def try_read_atlas(path: pathlib.Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: pathlib.Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def sleep_ms(ms: int) -> None:
    time.sleep(max(ms, 0) / 1000.0)


def focus_ost_window(title_contains: str) -> bool:
    candidates = []
    for w in gw.getAllWindows():
        title = (w.title or "").strip()
        if title_contains.lower() in title.lower():
            candidates.append(w)
    if not candidates:
        return False
    win = candidates[0]
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(0.25)
        return True
    except Exception:
        return False


def screenshot_monitor(monitor_index: int, out_file: pathlib.Path) -> pathlib.Path:
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index < 1 or monitor_index >= len(monitors):
            raise ValueError(
                f"monitor_index={monitor_index} invalid; available 1..{len(monitors)-1}"
            )
        shot = sct.grab(monitors[monitor_index])
        out_file.parent.mkdir(parents=True, exist_ok=True)
        mss.tools.to_png(shot.rgb, shot.size, output=str(out_file))
        return out_file


def get_monitor_rect(monitor_index: int) -> Dict[str, int]:
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index < 1 or monitor_index >= len(monitors):
            raise ValueError(
                f"monitor_index={monitor_index} invalid; available 1..{len(monitors)-1}"
            )
        m = monitors[monitor_index]
        return {
            "left": int(m["left"]),
            "top": int(m["top"]),
            "width": int(m["width"]),
            "height": int(m["height"]),
        }


def load_img(path: pathlib.Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Cannot load image: {path}")
    return img


def mean_abs_diff(a_path: pathlib.Path, b_path: pathlib.Path) -> float:
    a = load_img(a_path)
    b = load_img(b_path)
    if a.shape != b.shape:
        h = min(a.shape[0], b.shape[0])
        w = min(a.shape[1], b.shape[1])
        a = a[:h, :w]
        b = b[:h, :w]
    diff = cv2.absdiff(a, b)
    return float(diff.mean())


def black_pixel_ratio(image_path: pathlib.Path, threshold: int = 18) -> float:
    img = load_img(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    black = (gray <= threshold).sum()
    total = gray.size if gray.size else 1
    return float(black / total)


def roi_mean_abs_diff(
    a_path: pathlib.Path,
    b_path: pathlib.Path,
    center: Point,
    half_w: int,
    half_h: int,
) -> float:
    a = load_img(a_path)
    b = load_img(b_path)
    if a.shape != b.shape:
        h = min(a.shape[0], b.shape[0])
        w = min(a.shape[1], b.shape[1])
        a = a[:h, :w]
        b = b[:h, :w]
    h, w = a.shape[:2]
    x0 = max(0, center.x - half_w)
    x1 = min(w, center.x + half_w)
    y0 = max(0, center.y - half_h)
    y1 = min(h, center.y + half_h)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    a_roi = a[y0:y1, x0:x1]
    b_roi = b[y0:y1, x0:x1]
    return float(cv2.absdiff(a_roi, b_roi).mean())


def detect_run_button_center_local(image_path: pathlib.Path) -> Point | None:
    """
    Detect blue "Run Takeoff Boost" button center in monitor-local coordinates.
    Heuristic: blue button in lower-right region of Boost dialog.
    """
    img = load_img(image_path)
    h, w = img.shape[:2]
    if h < 20 or w < 20:
        return None
    x0 = int(w * 0.50)
    y0 = int(h * 0.55)
    roi = img[y0:h, x0:w]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # Typical blue button range
    lo = np.array([95, 70, 70], dtype=np.uint8)
    hi = np.array([130, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lo, hi)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = -1.0
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < 900:
            continue
        aspect = cw / max(ch, 1)
        if aspect < 1.6 or aspect > 8.0:
            continue
        # Prefer large, bottom-right candidates
        cx = x + cw / 2
        cy = y + ch / 2
        score = area + cx * 0.8 + cy * 0.8
        if score > best_score:
            best_score = score
            best = (x, y, cw, ch)

    if not best:
        return None
    x, y, cw, ch = best
    return Point(x=x0 + x + cw // 2, y=y0 + y + ch // 2)


def local_to_global(pt: Point, mon: Dict[str, int]) -> Point:
    return Point(x=pt.x + mon["left"], y=pt.y + mon["top"])


def global_to_local(pt: Point, mon: Dict[str, int]) -> Point:
    return Point(x=pt.x - mon["left"], y=pt.y - mon["top"])


def release_modifier_keys() -> None:
    # Defensive: stale modifiers can turn clicks into select-all/highlight shortcuts.
    for key in ("ctrl", "shift", "alt", "win", "command"):
        try:
            pyautogui.keyUp(key)
        except Exception:
            pass


def click_point(pt: Point, click_delay_ms: int) -> None:
    release_modifier_keys()
    pyautogui.moveTo(pt.x, pt.y, duration=0.15)
    pyautogui.click()
    release_modifier_keys()
    sleep_ms(click_delay_ms)


def extract_text(image_path: pathlib.Path) -> str:
    try:
        return pytesseract.image_to_string(str(image_path)).lower()
    except Exception:
        return ""


def tesseract_available() -> bool:
    try:
        _ = pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def configure_tesseract_binary(cfg: Dict[str, Any]) -> str | None:
    configured = cfg.get("tesseract_cmd")
    candidates = []
    if isinstance(configured, str) and configured.strip():
        candidates.append(configured.strip())
    candidates.extend(
        [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    )
    for p in candidates:
        if pathlib.Path(p).exists():
            pytesseract.pytesseract.tesseract_cmd = p
            return p
    return None


def to_point(raw: Dict[str, Any]) -> Point:
    return Point(int(raw["x"]), int(raw["y"]))


def maverick_log_step(
    cfg: Dict[str, Any],
    action: str,
    outcome: str,
    archetype: str,
    expected: str,
    observed: str,
    error: str = "",
    resolution: str = "",
    project_id: str = "",
) -> Dict[str, Any]:
    mav = cfg.get("maverick_logging", {}) if isinstance(cfg, dict) else {}
    enabled = bool((mav or {}).get("enabled", True))
    if not enabled:
        return {"enabled": False, "skipped": True, "reason": "maverick_logging_disabled"}

    runtime_cfg = str((mav or {}).get("runtime_config_path", "scripts/maverick_runtime.config.json"))
    project = (project_id or str((mav or {}).get("project_id", ""))).strip()
    cmd = [
        sys.executable,
        "scripts/maverick_runtime.py",
        "--config",
        runtime_cfg,
        "log-step",
        "--project",
        project,
        "--action",
        action,
        "--outcome",
        outcome,
        "--archetype",
        archetype,
        "--expected",
        expected,
        "--observed",
        observed,
        "--error",
        error,
        "--resolution",
        resolution,
    ]
    try:
        root = pathlib.Path(__file__).resolve().parent.parent
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=25)
        return {
            "enabled": True,
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "").strip()[:500],
            "stderr": (proc.stderr or "").strip()[:500],
        }
    except Exception as exc:
        return {"enabled": True, "exit_code": -1, "error": str(exc)}


def adaptive_retry_limits(
    cfg: Dict[str, Any],
    base_open_retries: int,
    base_run_retries: int,
    project_id: str = "",
) -> Dict[str, int]:
    adap = cfg.get("adaptive_retries", {}) if isinstance(cfg, dict) else {}
    if not bool((adap or {}).get("enabled", True)):
        return {"open_retries": base_open_retries, "run_retries": base_run_retries, "failure_count": 0}
    scale = max(1, int((adap or {}).get("scale_per_failures", 5)))
    open_cap = max(base_open_retries, int((adap or {}).get("max_open_retries_cap", 4)))
    run_cap = max(base_run_retries, int((adap or {}).get("max_run_retries_cap", 5)))

    # Read failure counts from Maverick artifacts.
    mcfg = cfg.get("maverick_logging", {}) if isinstance(cfg, dict) else {}
    runtime_cfg = pathlib.Path(str((mcfg or {}).get("runtime_config_path", "scripts/maverick_runtime.config.json")))
    root = pathlib.Path(__file__).resolve().parent.parent
    if not runtime_cfg.is_absolute():
        runtime_cfg = root / runtime_cfg
    if runtime_cfg.exists():
        rt = read_json(runtime_cfg)
        output_root = pathlib.Path(str(rt.get("output_root", "output/maverick")))
    else:
        output_root = pathlib.Path("output/maverick")
    if not output_root.is_absolute():
        output_root = root / output_root
    failures_path = output_root / "failures.json"
    if not failures_path.exists():
        return {"open_retries": base_open_retries, "run_retries": base_run_retries, "failure_count": 0}
    failures = read_json(failures_path)
    counts = failures.get("counts", {}) if isinstance(failures, dict) else {}
    key = f"{project_id or str((mcfg or {}).get('project_id', '')) or '_global'}::boost-run-click"
    failure_count = int(((counts or {}).get(key, {}) or {}).get("count", 0))
    extra = failure_count // scale
    return {
        "open_retries": min(open_cap, base_open_retries + extra),
        "run_retries": min(run_cap, base_run_retries + extra),
        "failure_count": failure_count,
    }


def calibrate(config_path: pathlib.Path) -> int:
    cfg = read_json(config_path)
    anchors = cfg.setdefault("anchors", {})
    print("\nCalibration mode")
    print("Move your mouse over each target and press Enter.")
    print("Do this on the same monitor and window layout used for automation.\n")

    for key in ("boost_button", "boost_run_button"):
        input(f"Place mouse over '{key}' then press Enter...")
        pos = pyautogui.position()
        anchors[key] = {"x": int(pos.x), "y": int(pos.y)}
        print(f"  saved {key} = ({pos.x}, {pos.y})")

    write_json(config_path, cfg)
    print(f"\nSaved calibration: {config_path}")
    return 0


def run_boost(config_path: pathlib.Path, dry_run: bool = False, project_id: str = "") -> int:
    cfg = read_json(config_path)
    tesseract_path = configure_tesseract_binary(cfg)
    strict_four_step = bool(cfg.get("strict_four_step", True))
    use_ui_atlas = bool(cfg.get("use_ui_atlas", True))
    ui_atlas_path = pathlib.Path(str(cfg.get("ui_atlas_path", "scripts/ost_ui_atlas.json")))
    atlas = try_read_atlas(ui_atlas_path) if use_ui_atlas else None
    atlas_anchors = (atlas or {}).get("anchors", {}) if isinstance(atlas, dict) else {}
    title = str(cfg.get("window_title_contains", DEFAULT_CONFIG["window_title_contains"]))
    monitor_index = int(cfg.get("monitor_index", 1))
    click_delay_ms = int(cfg.get("click_delay_ms", 450))
    wait_open_ms = int(cfg.get("post_boost_open_wait_ms", 1200))
    wait_ready_ms = int(cfg.get("post_boost_ready_wait_ms", 4000))
    ready_poll_ms = int(cfg.get("ready_poll_ms", 500))
    wait_run_ms = int(cfg.get("post_boost_run_wait_ms", 3500))
    run_observe_total_ms = int(cfg.get("run_observe_total_ms", 12000))
    run_observe_poll_ms = int(cfg.get("run_observe_poll_ms", 1500))
    max_open_retries = int(cfg.get("max_open_retries", 2))
    max_run_retries = int(cfg.get("max_run_retries", 2))
    run_click_strategy = str(cfg.get("run_click_strategy", "auto")).lower()
    run_click_repeats = max(1, int(cfg.get("run_click_repeats", 1)))
    require_scale_warning_absent = bool(cfg.get("require_scale_warning_absent", True))
    anchors = cfg.get("anchors", {})
    if isinstance(atlas_anchors, dict):
        # Atlas anchors are source-of-truth when enabled.
        for key in ("boost_button", "boost_run_button", "boost_close_button"):
            if key in atlas_anchors:
                anchors[key] = atlas_anchors[key]
    option_clicks = cfg.get("boost_option_clicks", [])
    auto_scale = cfg.get("auto_scale_preflight", {})
    auto_scale_enabled = bool(auto_scale.get("enabled", False))
    auto_scale_max_cycles = int(auto_scale.get("max_cycles", 1))
    auto_scale_clicks = auto_scale.get("scale_clicks", [])
    vision = cfg.get("vision_checks", {})
    vision_enabled = bool(vision.get("enabled", True))
    open_change_threshold = float(vision.get("open_change_threshold", 1.2))
    run_change_threshold = float(vision.get("run_change_threshold", 0.35))
    run_full_change_threshold = float(vision.get("run_full_change_threshold", 0.08))
    open_black_frame_max_ratio = float(vision.get("open_black_frame_max_ratio", 0.85))
    run_roi_half_w = int(vision.get("run_roi_half_width", 360))
    run_roi_half_h = int(vision.get("run_roi_half_height", 220))

    if "boost_button" not in anchors or "boost_run_button" not in anchors:
        print("Config missing anchors. Run calibrate first.")
        return 2

    adaptive = adaptive_retry_limits(
        cfg=cfg,
        base_open_retries=max_open_retries,
        base_run_retries=max_run_retries,
        project_id=project_id,
    )
    max_open_retries = int(adaptive.get("open_retries", max_open_retries))
    max_run_retries = int(adaptive.get("run_retries", max_run_retries))

    if not focus_ost_window(title):
        mav = maverick_log_step(
            cfg=cfg,
            project_id=project_id,
            action="focus_ost_window",
            outcome="failure",
            archetype="boost-focus-window",
            expected="OST window focused",
            observed=f"could not find/focus window containing {title!r}",
            error="window_not_found_or_focus_failed",
        )
        print(f"Could not find/focus OST window containing title: {title!r}")
        if mav.get("enabled"):
            print(f"Maverick log: {json.dumps(mav)}")
        return 3

    monitor_rect = get_monitor_rect(monitor_index)
    boost_button = to_point(anchors["boost_button"])
    boost_run_button = to_point(anchors["boost_run_button"])
    boost_run_button_local = global_to_local(boost_run_button, monitor_rect)
    boost_close_button = to_point(anchors["boost_close_button"]) if "boost_close_button" in anchors else None

    evidence_dir = pathlib.Path("output") / "ost-boost-agent" / now_tag()
    before_file = evidence_dir / "01_before.png"
    open_file = evidence_dir / "02_after_open.png"
    open_ready_file = evidence_dir / "02_after_open_ready.png"
    done_file = evidence_dir / "03_after_run.png"
    log_file = evidence_dir / "run_log.json"

    screenshot_monitor(monitor_index, before_file)

    actions = []
    actions.append(
        {
            "step": "adaptive_retry_limits",
            "open_retries": max_open_retries,
            "run_retries": max_run_retries,
            "failure_count": int(adaptive.get("failure_count", 0)),
        }
    )
    actions.append({"step": "focus_ost_window", "ok": True, "title_contains": title})
    step_status = {
        "step1_open_boost": False,
        "step2_set_options": False,
        "step3_run": False,
        "step4_verify": False,
    }

    if dry_run:
        actions.append(
            {
                "step": "dry_run_only",
                "strict_four_step": strict_four_step,
                "use_ui_atlas": use_ui_atlas,
                "ui_atlas_path": str(ui_atlas_path),
                "atlas_loaded": atlas is not None,
                "run_click_strategy": run_click_strategy,
                "monitor_rect": monitor_rect,
                "boost_button": anchors["boost_button"],
                "boost_run_button": anchors["boost_run_button"],
                "boost_close_button": anchors.get("boost_close_button"),
                "boost_option_clicks": option_clicks,
                "auto_scale_preflight": auto_scale,
            }
        )
        write_json(log_file, {"dry_run": True, "actions": actions, "step_status": step_status})
        actions.append(
            {
                "step": "maverick_log_step",
                "result": maverick_log_step(
                    cfg=cfg,
                    project_id=project_id,
                    action="boost_workflow",
                    outcome="success",
                    archetype="boost-dry-run",
                    expected="Dry run metadata captured",
                    observed="Dry run completed without clicks",
                ),
            }
        )
        print(f"Dry run complete. Evidence: {evidence_dir}")
        return 0

    # Step 1: Open Boost dialog (with retries if needed)
    open_changed = False
    open_ready = False
    open_ui_confirmed = False
    # If Boost dialog is already open, accept current state and avoid toggling.
    before_text = extract_text(before_file)
    before_run_detect = detect_run_button_center_local(before_file)
    already_open = ("takeoff boost" in before_text) or (before_run_detect is not None)
    if already_open:
        open_changed = True
        open_ready = True
        open_file = before_file
        open_ready_file = before_file
        if before_run_detect is not None:
            boost_run_button_local = before_run_detect
        step_status["step1_open_boost"] = True
        actions.append(
            {
                "step": "boost_dialog_already_open",
                "detected": True,
                "detected_by_run_button": before_run_detect is not None,
            }
        )
    actions.append({"step": "playbook", "name": "open_boost_dialog_stabilize", "status": "started"})
    for attempt in range(1, max_open_retries + 1):
        if already_open:
            break
        click_point(boost_button, click_delay_ms)
        actions.append(
            {
                "step": "click_boost_button",
                "attempt": attempt,
                "point": anchors["boost_button"],
            }
        )
        sleep_ms(wait_open_ms)
        screenshot_monitor(monitor_index, open_file)
        open_text = extract_text(open_file)
        open_run_detect = detect_run_button_center_local(open_file)
        open_ui_confirmed = ("takeoff boost" in open_text.lower()) or (open_run_detect is not None)
        if open_run_detect is not None:
            boost_run_button_local = open_run_detect
        if vision_enabled:
            open_diff = mean_abs_diff(before_file, open_file)
            open_changed = open_diff >= open_change_threshold
            black_ratio = black_pixel_ratio(open_file)
            looks_ready = black_ratio <= open_black_frame_max_ratio
            actions.append(
                {
                    "step": "vision_open_check",
                    "attempt": attempt,
                    "mean_abs_diff": open_diff,
                    "black_ratio": black_ratio,
                    "black_ratio_max": open_black_frame_max_ratio,
                    "looks_ready": looks_ready,
                    "ui_confirmed": open_ui_confirmed,
                    "threshold": open_change_threshold,
                    "pass": open_changed and open_ui_confirmed,
                }
            )
            # If dialog is present but still black/loading, wait until it renders.
            if open_changed and open_ui_confirmed and not looks_ready:
                elapsed = 0
                idx = 0
                while elapsed < max(0, wait_ready_ms):
                    sleep_ms(ready_poll_ms)
                    elapsed += ready_poll_ms
                    idx += 1
                    probe = evidence_dir / f"02_after_open_probe_{attempt}_{idx}.png"
                    screenshot_monitor(monitor_index, probe)
                    probe_text = extract_text(probe)
                    probe_run_detect = detect_run_button_center_local(probe)
                    if probe_run_detect is not None:
                        boost_run_button_local = probe_run_detect
                    open_ui_confirmed = ("takeoff boost" in probe_text.lower()) or (probe_run_detect is not None)
                    black_ratio = black_pixel_ratio(probe)
                    looks_ready = black_ratio <= open_black_frame_max_ratio
                    actions.append(
                        {
                            "step": "vision_open_ready_probe",
                            "attempt": attempt,
                            "probe_index": idx,
                            "elapsed_ms": elapsed,
                            "black_ratio": black_ratio,
                            "black_ratio_max": open_black_frame_max_ratio,
                            "looks_ready": looks_ready,
                            "ui_confirmed": open_ui_confirmed,
                        }
                    )
                    if looks_ready and open_ui_confirmed:
                        open_ready_file = probe
                        open_ready = True
                        break
            elif open_changed and open_ui_confirmed and looks_ready:
                open_ready_file = open_file
                open_ready = True
        else:
            open_changed = open_ui_confirmed
            open_ready = open_ui_confirmed
        if open_changed and open_ui_confirmed:
            step_status["step1_open_boost"] = True
            actions.append({"step": "playbook", "name": "open_boost_dialog_stabilize", "status": "success", "attempt": attempt})
            break
    if strict_four_step and not step_status["step1_open_boost"]:
        result = {
            "ok": False,
            "timestamp": now_tag(),
            "monitor_index": monitor_index,
            "evidence_dir": str(evidence_dir),
            "status": {
                "strict_four_step": strict_four_step,
                "failed_step": 1,
                "step_status": step_status,
            },
            "actions": actions,
            "ocr_text_preview": "",
        }
        write_json(log_file, result)
        actions.append(
            {
                "step": "maverick_log_step",
                "result": maverick_log_step(
                    cfg=cfg,
                    project_id=project_id,
                    action="open_boost_dialog",
                    outcome="failure",
                    archetype="boost-open-dialog",
                    expected="Boost dialog detected after open click",
                    observed="Boost dialog not detected",
                    error="step1_open_boost_failed",
                ),
            }
        )
        print(f"Step 1 failed (Boost dialog not detected). Evidence: {evidence_dir}")
        return 4
    if strict_four_step and not open_ready:
        result = {
            "ok": False,
            "timestamp": now_tag(),
            "monitor_index": monitor_index,
            "evidence_dir": str(evidence_dir),
            "status": {
                "strict_four_step": strict_four_step,
                "failed_step": 1,
                "failure_reason": "boost_dialog_not_ready",
                "step_status": step_status,
            },
            "actions": actions,
            "ocr_text_preview": "",
        }
        write_json(log_file, result)
        actions.append(
            {
                "step": "maverick_log_step",
                "result": maverick_log_step(
                    cfg=cfg,
                    project_id=project_id,
                    action="open_boost_dialog",
                    outcome="failure",
                    archetype="boost-open-dialog",
                    expected="Boost dialog fully rendered",
                    observed="Boost dialog still loading/black",
                    error="boost_dialog_not_ready",
                ),
            }
        )
        print(f"Step 1 failed (Boost dialog still loading/black). Evidence: {evidence_dir}")
        return 4

    # Step 1.5: Preflight warning gate (scale warning indicates Run will not work correctly)
    preflight_text = ""
    has_scale_warning = False
    if require_scale_warning_absent:
        preflight_text = extract_text(open_ready_file)
        has_scale_warning = "must set the correct scale" in preflight_text
        actions.append(
            {
                "step": "preflight_scale_warning_check",
                "required_absent": True,
                "detected": has_scale_warning,
            }
        )

        # Optional Step 0 auto-scale cycle: close Boost, execute scale clicks, reopen and re-check.
        if has_scale_warning and auto_scale_enabled and isinstance(auto_scale_clicks, list):
            cycles = max(0, auto_scale_max_cycles)
            for cycle in range(1, cycles + 1):
                actions.append({"step": "auto_scale_cycle_start", "cycle": cycle})

                if boost_close_button is not None:
                    click_point(boost_close_button, click_delay_ms)
                    actions.append(
                        {
                            "step": "auto_scale_close_boost",
                            "cycle": cycle,
                            "point": {"x": boost_close_button.x, "y": boost_close_button.y},
                        }
                    )
                    sleep_ms(300)
                else:
                    actions.append(
                        {
                            "step": "auto_scale_close_boost",
                            "cycle": cycle,
                            "skipped": True,
                            "reason": "boost_close_button_missing",
                        }
                    )

                for idx, raw in enumerate(auto_scale_clicks, start=1):
                    if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
                        actions.append(
                            {
                                "step": "auto_scale_click",
                                "cycle": cycle,
                                "index": idx,
                                "skipped": True,
                                "reason": "invalid_point",
                                "value": raw,
                            }
                        )
                        continue
                    pt = to_point(raw)
                    click_point(pt, click_delay_ms)
                    wait_ms = int(raw.get("wait_ms", 200)) if isinstance(raw, dict) else 200
                    sleep_ms(wait_ms)
                    actions.append(
                        {
                            "step": "auto_scale_click",
                            "cycle": cycle,
                            "index": idx,
                            "point": {"x": pt.x, "y": pt.y},
                            "wait_ms": wait_ms,
                        }
                    )

                # Re-open boost and re-check warning
                open_changed = False
                for attempt in range(1, max_open_retries + 1):
                    click_point(boost_button, click_delay_ms)
                    actions.append(
                        {
                            "step": "click_boost_button_reopen",
                            "cycle": cycle,
                            "attempt": attempt,
                            "point": anchors["boost_button"],
                        }
                    )
                    sleep_ms(wait_open_ms)
                    screenshot_monitor(monitor_index, open_file)
                    if vision_enabled:
                        open_diff = mean_abs_diff(before_file, open_file)
                        open_changed = open_diff >= open_change_threshold
                        black_ratio = black_pixel_ratio(open_file)
                        looks_ready = black_ratio <= open_black_frame_max_ratio
                        actions.append(
                            {
                                "step": "vision_open_check_reopen",
                                "cycle": cycle,
                                "attempt": attempt,
                                "mean_abs_diff": open_diff,
                                "black_ratio": black_ratio,
                                "black_ratio_max": open_black_frame_max_ratio,
                                "looks_ready": looks_ready,
                                "threshold": open_change_threshold,
                                "pass": open_changed,
                            }
                        )
                        if open_changed and not looks_ready:
                            elapsed = 0
                            idx = 0
                            while elapsed < max(0, wait_ready_ms):
                                sleep_ms(ready_poll_ms)
                                elapsed += ready_poll_ms
                                idx += 1
                                probe = evidence_dir / f"02_after_reopen_probe_{cycle}_{attempt}_{idx}.png"
                                screenshot_monitor(monitor_index, probe)
                                black_ratio = black_pixel_ratio(probe)
                                looks_ready = black_ratio <= open_black_frame_max_ratio
                                actions.append(
                                    {
                                        "step": "vision_open_ready_probe_reopen",
                                        "cycle": cycle,
                                        "attempt": attempt,
                                        "probe_index": idx,
                                        "elapsed_ms": elapsed,
                                        "black_ratio": black_ratio,
                                        "black_ratio_max": open_black_frame_max_ratio,
                                        "looks_ready": looks_ready,
                                    }
                                )
                                if looks_ready:
                                    open_ready_file = probe
                                    break
                        elif open_changed and looks_ready:
                            open_ready_file = open_file
                    else:
                        open_changed = True
                    if open_changed:
                        break

                preflight_text = extract_text(open_ready_file)
                has_scale_warning = "must set the correct scale" in preflight_text
                actions.append(
                    {
                        "step": "preflight_scale_warning_recheck",
                        "cycle": cycle,
                        "detected": has_scale_warning,
                    }
                )
                if not has_scale_warning:
                    break

        if has_scale_warning:
            result = {
                "ok": False,
                "timestamp": now_tag(),
                "monitor_index": monitor_index,
                "evidence_dir": str(evidence_dir),
                "status": {
                    "strict_four_step": strict_four_step,
                    "failed_step": 1,
                    "failure_reason": "scale_warning_detected",
                    "step_status": step_status,
                },
                "actions": actions,
                "ocr_text_preview": preflight_text[:800],
            }
            write_json(log_file, result)
            actions.append(
                {
                    "step": "maverick_log_step",
                    "result": maverick_log_step(
                        cfg=cfg,
                        project_id=project_id,
                        action="boost_scale_preflight",
                        outcome="failure",
                        archetype="boost-scale-warning",
                        expected="No blocking scale warning before run",
                        observed="Scale warning detected",
                        error="scale_warning_detected",
                    ),
                }
            )
            print(f"Preflight blocked run: page scale warning detected. Evidence: {evidence_dir}")
            return 4

    # Step 2: Apply Boost option presets (if configured)
    if isinstance(option_clicks, list) and len(option_clicks) > 0:
        for idx, raw in enumerate(option_clicks, start=1):
            if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
                actions.append(
                    {
                        "step": "boost_option_click",
                        "index": idx,
                        "skipped": True,
                        "reason": "invalid_point",
                        "value": raw,
                    }
                )
                continue
            pt = to_point(raw)
            click_point(pt, click_delay_ms)
            actions.append(
                {
                    "step": "boost_option_click",
                    "index": idx,
                    "point": {"x": pt.x, "y": pt.y},
                }
            )
        step_status["step2_set_options"] = True
    else:
        # No-op presets are valid; this keeps strict sequencing deterministic.
        actions.append(
            {
                "step": "boost_option_click",
                "index": 0,
                "skipped": True,
                "reason": "no_option_presets_configured",
            }
        )
        step_status["step2_set_options"] = True
    if strict_four_step and not step_status["step2_set_options"]:
        result = {
            "ok": False,
            "timestamp": now_tag(),
            "monitor_index": monitor_index,
            "evidence_dir": str(evidence_dir),
            "status": {
                "strict_four_step": strict_four_step,
                "failed_step": 2,
                "step_status": step_status,
            },
            "actions": actions,
            "ocr_text_preview": "",
        }
        write_json(log_file, result)
        actions.append(
            {
                "step": "maverick_log_step",
                "result": maverick_log_step(
                    cfg=cfg,
                    project_id=project_id,
                    action="boost_set_options",
                    outcome="failure",
                    archetype="boost-set-options",
                    expected="Boost option presets applied",
                    observed="Step 2 did not complete",
                    error="step2_set_options_failed",
                ),
            }
        )
        print(f"Step 2 failed (Boost presets not applied). Evidence: {evidence_dir}")
        return 4

    # Step 3: Run Boost (with retries if needed)
    run_changed = False
    actions.append({"step": "playbook", "name": "run_button_recovery", "status": "started"})
    for attempt in range(1, max_run_retries + 1):
        click_target = boost_run_button
        # Stabilization playbook strategy:
        # attempt1=auto detect, attempt2=anchor fallback, attempt3+=auto detect with longer observe.
        strategy = run_click_strategy
        if attempt == 2:
            strategy = "anchor"
        elif attempt >= 3:
            strategy = "auto"
        auto_detected_local = detect_run_button_center_local(open_ready_file) if strategy == "auto" else None
        if auto_detected_local is not None:
            click_target = local_to_global(auto_detected_local, monitor_rect)
            boost_run_button_local = auto_detected_local
            actions.append(
                {
                    "step": "run_button_auto_detect",
                    "attempt": attempt,
                    "strategy": strategy,
                    "local_point": {"x": auto_detected_local.x, "y": auto_detected_local.y},
                    "global_point": {"x": click_target.x, "y": click_target.y},
                }
            )
        else:
            actions.append(
                {
                    "step": "run_button_auto_detect",
                    "attempt": attempt,
                    "strategy": strategy,
                    "fallback": "calibrated_anchor",
                    "global_point": {"x": click_target.x, "y": click_target.y},
                }
            )

        for repeat_idx in range(1, run_click_repeats + 1):
            click_point(click_target, click_delay_ms)
            actions.append(
                {
                    "step": "click_boost_run_button",
                    "attempt": attempt,
                    "repeat": repeat_idx,
                    "repeats_total": run_click_repeats,
                    "point": {"x": click_target.x, "y": click_target.y},
                }
            )
        sleep_ms(wait_run_ms)
        screenshot_monitor(monitor_index, done_file)
        if vision_enabled:
            run_roi_diff = roi_mean_abs_diff(
                open_file,
                done_file,
                center=boost_run_button_local,
                half_w=run_roi_half_w,
                half_h=run_roi_half_h,
            )
            run_full_diff = mean_abs_diff(open_file, done_file)
            run_changed = (
                run_roi_diff >= run_change_threshold
                or run_full_diff >= run_full_change_threshold
            )
            actions.append(
                {
                    "step": "vision_run_check",
                    "attempt": attempt,
                    "roi_mean_abs_diff": run_roi_diff,
                    "full_mean_abs_diff": run_full_diff,
                    "threshold": run_change_threshold,
                    "full_threshold": run_full_change_threshold,
                    "pass": run_changed,
                }
            )

            # Boost can take time; keep observing for visual state changes.
            elapsed = 0
            obs_idx = 0
            observe_total_ms = run_observe_total_ms + (attempt - 1) * max(0, run_observe_poll_ms)
            while (not run_changed) and elapsed < max(0, observe_total_ms):
                sleep_ms(run_observe_poll_ms)
                elapsed += run_observe_poll_ms
                obs_idx += 1
                obs_file = evidence_dir / f"03_after_run_obs_{attempt}_{obs_idx}.png"
                screenshot_monitor(monitor_index, obs_file)
                run_roi_diff = roi_mean_abs_diff(
                    open_file,
                    obs_file,
                    center=boost_run_button_local,
                    half_w=run_roi_half_w,
                    half_h=run_roi_half_h,
                )
                run_full_diff = mean_abs_diff(open_file, obs_file)
                run_changed = (
                    run_roi_diff >= run_change_threshold
                    or run_full_diff >= run_full_change_threshold
                )
                actions.append(
                    {
                        "step": "vision_run_observe",
                        "attempt": attempt,
                        "observe_index": obs_idx,
                        "elapsed_ms": elapsed,
                        "roi_mean_abs_diff": run_roi_diff,
                        "full_mean_abs_diff": run_full_diff,
                        "threshold": run_change_threshold,
                        "full_threshold": run_full_change_threshold,
                        "pass": run_changed,
                    }
                )
                if run_changed:
                    done_file = obs_file
                    break
        else:
            run_changed = True
        if run_changed:
            step_status["step3_run"] = True
            actions.append({"step": "playbook", "name": "run_button_recovery", "status": "success", "attempt": attempt})
            break
    if strict_four_step and not step_status["step3_run"]:
        result = {
            "ok": False,
            "timestamp": now_tag(),
            "monitor_index": monitor_index,
            "evidence_dir": str(evidence_dir),
            "status": {
                "strict_four_step": strict_four_step,
                "failed_step": 3,
                "step_status": step_status,
            },
            "actions": actions,
            "ocr_text_preview": "",
        }
        write_json(log_file, result)
        actions.append(
            {
                "step": "maverick_log_step",
                "result": maverick_log_step(
                    cfg=cfg,
                    project_id=project_id,
                    action="boost_run_click",
                    outcome="failure",
                    archetype="boost-run-click",
                    expected="Run click causes detectable workflow changes",
                    observed="No detectable visual changes after run click",
                    error="run_action_no_detectable_change",
                ),
            }
        )
        print(f"Step 3 failed (Run action did not produce detectable changes). Evidence: {evidence_dir}")
        return 4

    # Step 4: Verify completion (vision + OCR, OCR optional fallback)
    ocr_cfg = cfg.get("ocr_checks", {})
    ocr_enabled = bool(ocr_cfg.get("enabled", True))
    ocr_available = tesseract_available()
    ocr_pass = None
    ocr_text_preview = ""
    if ocr_enabled and ocr_available:
        after_text = extract_text(done_file)
        expects = [str(x).lower() for x in ocr_cfg.get("expected_any_after_run", [])]
        ocr_pass = any(token in after_text for token in expects) if expects else None
        ocr_text_preview = after_text[:800]
        actions.append(
            {
                "step": "ocr_check_after_run",
                "expected_any_after_run": expects,
                "pass": ocr_pass,
            }
        )
    elif ocr_enabled and not ocr_available:
        actions.append(
            {
                "step": "ocr_check_after_run",
                "skipped": True,
                "reason": "tesseract_not_found",
            }
        )

    final_ok = bool(open_changed and run_changed)
    step_status["step4_verify"] = final_ok
    completion_basis = (
        "vision"
        if run_changed
        else "none"
    )
    result = {
        "ok": final_ok,
        "timestamp": now_tag(),
        "monitor_index": monitor_index,
        "evidence_dir": str(evidence_dir),
        "status": {
            "strict_four_step": strict_four_step,
            "failed_step": None if final_ok else 4,
            "step_status": step_status,
            "open_changed": open_changed,
            "run_changed": run_changed,
            "completion_basis": completion_basis,
            "tesseract_cmd": tesseract_path,
            "ocr_available": ocr_available,
            "ocr_pass": ocr_pass,
        },
        "actions": actions,
        "ocr_text_preview": ocr_text_preview,
    }
    write_json(log_file, result)
    actions.append(
        {
            "step": "maverick_log_step",
            "result": maverick_log_step(
                cfg=cfg,
                project_id=project_id,
                action="boost_workflow",
                outcome="success" if result["ok"] else "failure",
                archetype="boost-workflow",
                expected="Boost workflow completes all strict steps",
                observed="Boost workflow complete" if result["ok"] else "Verification failed",
                error="" if result["ok"] else "step4_verify_failed",
                resolution="evidence_written",
            ),
        }
    )
    actions.append(
        {
            "step": "maverick_log_step",
            "result": maverick_log_step(
                cfg=cfg,
                project_id=project_id,
                action="boost_run_click",
                outcome="success" if step_status["step3_run"] else "failure",
                archetype="boost-run-click",
                expected="Run button interaction succeeds",
                observed="Run interaction succeeded" if step_status["step3_run"] else "Run interaction failed",
                error="" if step_status["step3_run"] else "run_step_failed",
                resolution="verification_complete" if result["ok"] else "",
            ),
        }
    )
    write_json(log_file, result)
    if result["ok"]:
        print(f"Boost run complete. Evidence: {evidence_dir}")
    else:
        print(f"Boost run uncertain/failed visual checks. Evidence: {evidence_dir}")
    if ocr_enabled and not ocr_available:
        print("OCR skipped: native tesseract.exe not found.")
    elif ocr_pass is False:
        print("Warning: OCR check did not find expected text tokens.")
    return 0 if result["ok"] else 4


def main() -> int:
    parser = argparse.ArgumentParser(description="OST Boost black-box agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cal = sub.add_parser("calibrate", help="Capture click points for Boost controls")
    p_cal.add_argument(
        "--config",
        default="scripts/ost_boost_agent.config.json",
        help="Path to config json",
    )

    p_run = sub.add_parser("run", help="Run Boost workflow once")
    p_run.add_argument(
        "--config",
        default="scripts/ost_boost_agent.config.json",
        help="Path to config json",
    )
    p_run.add_argument("--dry-run", action="store_true", help="No clicks; evidence only")
    p_run.add_argument(
        "--project-id",
        default="",
        help="Training/project id forwarded to Maverick step logging",
    )

    args = parser.parse_args()
    config_path = pathlib.Path(args.config)

    if args.cmd == "calibrate":
        return calibrate(config_path)
    if args.cmd == "run":
        return run_boost(config_path, dry_run=bool(args.dry_run), project_id=str(args.project_id))
    return 1


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.08
    sys.exit(main())
