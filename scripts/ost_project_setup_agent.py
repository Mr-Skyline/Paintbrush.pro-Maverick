#!/usr/bin/env python3
"""
OST Project Setup Agent (black-box UI)

Runs a configurable action sequence to set up a project in OST after intake.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, List

try:
    import mss
    import pyautogui
    import pygetwindow as gw
except Exception as exc:  # pragma: no cover
    print(
        "Missing dependencies. Install with:\n"
        "  pip install pyautogui pygetwindow mss pillow\n"
        f"Import error: {exc}"
    )
    raise

from mouse_takeover_guard import install_pyautogui_takeover_guard
from ost_window_guard import (
    clamp_point_to_active_window,
    focus_window as focus_window_guard,
    set_active_window_rect,
)

install_pyautogui_takeover_guard(pyautogui)


DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "window_title_contains": "On-Screen Takeoff",
    "monitor_index": 1,
    "click_delay_ms": 350,
    "typing_interval_ms": 10,
    "use_ui_atlas": True,
    "ui_atlas_path": "scripts/ost_ui_atlas.json",
    "adaptive_retries": {
        "enabled": True,
        "click_anchor_retries": 2,
    },
    "maverick_logging": {
        "enabled": True,
        "runtime_config_path": "scripts/maverick_runtime.config.json",
        "project_id": "",
    },
    "anchors": {},
    "steps": [],
}


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def try_read_atlas(path: pathlib.Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def sleep_ms(ms: int) -> None:
    time.sleep(max(ms, 0) / 1000.0)


def render_template(text: str, ctx: Dict[str, str]) -> str:
    out = str(text)
    for k, v in ctx.items():
        out = out.replace(f"{{{{{k}}}}}", str(v))
    return out


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_takeoff_plans_dir(project_dir: pathlib.Path) -> pathlib.Path | None:
    candidates: List[pathlib.Path] = []
    for p in project_dir.iterdir():
        if not p.is_dir():
            continue
        n = norm_name(p.name)
        # Accept common naming variants: TAKE-OFF PLANS, TAKE OFF PLANS, takeoffplans, etc.
        if "takeoff" in n and "plan" in n:
            candidates.append(p)
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x.name.lower())[0]


def first_upload_file(folder: pathlib.Path) -> pathlib.Path | None:
    if not folder.exists() or not folder.is_dir():
        return None
    files = [p for p in folder.iterdir() if p.is_file()]
    if not files:
        return None
    pdfs = sorted([p for p in files if p.suffix.lower() == ".pdf"], key=lambda x: x.name.lower())
    if pdfs:
        return pdfs[0]
    return sorted(files, key=lambda x: x.name.lower())[0]


def focus_window(title_contains: str) -> bool:
    return focus_window_guard(title_contains, sleep_s=0.25)


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


def click_point(x: int, y: int, delay_ms: int, double: bool = False) -> None:
    cx, cy, adjusted = clamp_point_to_active_window(int(x), int(y), margin_px=10)
    if adjusted:
        print(f"ost_window_clamp from=({int(x)},{int(y)}) to=({cx},{cy})")
    pyautogui.moveTo(cx, cy, duration=0.15)
    if double:
        pyautogui.doubleClick()
    else:
        pyautogui.click()
    sleep_ms(delay_ms)


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
    mcfg = cfg.get("maverick_logging", {}) if isinstance(cfg, dict) else {}
    enabled = bool((mcfg or {}).get("enabled", True))
    if not enabled:
        return {"enabled": False, "skipped": True, "reason": "maverick_logging_disabled"}

    runtime_cfg = str((mcfg or {}).get("runtime_config_path", "scripts/maverick_runtime.config.json"))
    project = (project_id or str((mcfg or {}).get("project_id", ""))).strip()
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


def run_setup(
    config_path: pathlib.Path,
    project_name: str,
    project_dir: pathlib.Path,
    plan_pdf: str,
    out_dir: pathlib.Path,
    dry_run: bool,
    project_id: str = "",
) -> int:
    cfg = read_json(config_path)
    cfg_enabled = bool(cfg.get("enabled", False))
    if not cfg_enabled:
        mav = maverick_log_step(
            cfg=cfg,
            project_id=project_id,
            action="project_setup_workflow",
            outcome="failure",
            archetype="setup-workflow",
            expected="Setup agent enabled and runnable",
            observed="Setup agent disabled by configuration",
            error="setup_agent_disabled",
        )
        result = {
            "ok": False,
            "skipped": True,
            "reason": "setup_agent_disabled",
            "config_path": str(config_path),
            "maverick_log": mav,
        }
        write_json(out_dir / "setup_result.json", result)
        print("setup_skipped=disabled")
        return 0

    title = str(cfg.get("window_title_contains", "On-Screen Takeoff"))
    monitor_index = int(cfg.get("monitor_index", 1))
    click_delay_ms = int(cfg.get("click_delay_ms", 350))
    typing_interval_s = max(0.0, int(cfg.get("typing_interval_ms", 10)) / 1000.0)
    steps = cfg.get("steps", []) or []
    anchors = dict(cfg.get("anchors", {}) or {})
    use_ui_atlas = bool(cfg.get("use_ui_atlas", True))
    atlas_path = pathlib.Path(str(cfg.get("ui_atlas_path", "scripts/ost_ui_atlas.json")))
    atlas = try_read_atlas(atlas_path) if use_ui_atlas else None
    adaptive_cfg = cfg.get("adaptive_retries", {}) if isinstance(cfg, dict) else {}
    anchor_retries = max(1, int((adaptive_cfg or {}).get("click_anchor_retries", 2)))
    if isinstance(atlas, dict) and isinstance(atlas.get("anchors"), dict):
        anchors.update(atlas.get("anchors") or {})

    out_dir.mkdir(parents=True, exist_ok=True)
    actions: List[Dict[str, Any]] = []
    takeoff_dir = find_takeoff_plans_dir(project_dir)
    takeoff_first = first_upload_file(takeoff_dir) if takeoff_dir else None
    resolved_plan_pdf = str(takeoff_first) if takeoff_first else str(plan_pdf or "")
    ctx = {
        "project_name": project_name,
        "project_dir": str(project_dir),
        "plan_pdf": resolved_plan_pdf,
        "takeoff_plans_dir": str(takeoff_dir) if takeoff_dir else "",
        "takeoff_plans_first_file": str(takeoff_first) if takeoff_first else "",
        "timestamp": now_tag(),
    }

    focused = focus_window(title)
    set_active_window_rect(title)
    actions.append({"step": "focus_window", "ok": focused, "title_contains": title})
    screenshot_monitor(monitor_index, out_dir / "01_before.png")
    if not focused:
        mav = maverick_log_step(
            cfg=cfg,
            project_id=project_id,
            action="setup_focus_window",
            outcome="failure",
            archetype="setup-focus-window",
            expected="OST window focused",
            observed=f"Window title containing {title!r} not focused",
            error="window_not_found_or_focus_failed",
        )
        result = {
            "ok": False,
            "skipped": False,
            "failed_step": "focus_window",
            "actions": actions,
            "maverick_log": mav,
        }
        write_json(out_dir / "setup_result.json", result)
        print("setup_failed=focus_window")
        return 3

    for idx, raw in enumerate(steps, start=1):
        if not isinstance(raw, dict):
            actions.append({"step": f"step_{idx}", "skipped": True, "reason": "invalid_step"})
            continue
        step_type = str(raw.get("type", "")).strip().lower()
        label = str(raw.get("label", f"step_{idx}"))
        rec: Dict[str, Any] = {"index": idx, "label": label, "type": step_type}

        if step_type in {"sleep", "sleep_ms"}:
            ms = int(raw.get("ms", raw.get("sleep_ms", 500)))
            rec["ms"] = ms
            if not dry_run:
                sleep_ms(ms)
            actions.append(rec)
            continue

        if step_type == "screenshot":
            tag = str(raw.get("tag", f"shot_{idx:02d}"))
            shot = out_dir / f"{idx:02d}_{tag}.png"
            if not dry_run:
                screenshot_monitor(monitor_index, shot)
            rec["file"] = str(shot)
            actions.append(rec)
            continue

        if step_type in {"click_anchor", "double_click_anchor"}:
            name = str(raw.get("anchor", "")).strip()
            rec["anchor"] = name
            pt = anchors.get(name)
            if not isinstance(pt, dict) or "x" not in pt or "y" not in pt:
                rec["error"] = "missing_anchor"
                rec["maverick_log"] = maverick_log_step(
                    cfg=cfg,
                    project_id=project_id,
                    action="setup_click_anchor",
                    outcome="failure",
                    archetype="setup-missing-anchor",
                    expected=f"Anchor {name} resolved",
                    observed=f"Anchor {name} missing",
                    error="missing_anchor",
                )
                actions.append(rec)
                continue
            x, y = int(pt["x"]), int(pt["y"])
            rec["point"] = {"x": x, "y": y}
            if not dry_run:
                for attempt in range(1, anchor_retries + 1):
                    click_point(x, y, click_delay_ms, double=(step_type == "double_click_anchor"))
                    actions.append(
                        {
                            "index": idx,
                            "label": f"{label} retry",
                            "type": f"{step_type}_attempt",
                            "anchor": name,
                            "attempt": attempt,
                            "point": {"x": x, "y": y},
                        }
                    )
            actions.append(rec)
            continue

        if step_type in {"click_point", "double_click_point"}:
            x, y = int(raw.get("x", 0)), int(raw.get("y", 0))
            rec["point"] = {"x": x, "y": y}
            if not dry_run:
                click_point(x, y, click_delay_ms, double=(step_type == "double_click_point"))
            actions.append(rec)
            continue

        if step_type == "hotkey":
            keys = [str(k) for k in (raw.get("keys") or [])]
            rec["keys"] = keys
            if not dry_run and keys:
                pyautogui.hotkey(*keys)
                sleep_ms(click_delay_ms)
            actions.append(rec)
            continue

        if step_type == "press":
            key = str(raw.get("key", "enter"))
            rec["key"] = key
            if not dry_run:
                pyautogui.press(key)
                sleep_ms(click_delay_ms)
            actions.append(rec)
            continue

        if step_type in {"type_text", "paste_text"}:
            txt = render_template(str(raw.get("text", "")), ctx)
            rec["text_preview"] = txt[:200]
            if not dry_run:
                if step_type == "paste_text":
                    try:
                        import pyperclip  # type: ignore

                        pyperclip.copy(txt)
                        pyautogui.hotkey("ctrl", "v")
                    except Exception:
                        pyautogui.write(txt, interval=typing_interval_s)
                else:
                    pyautogui.write(txt, interval=typing_interval_s)
                sleep_ms(click_delay_ms)
            actions.append(rec)
            continue

        rec["skipped"] = True
        rec["reason"] = "unknown_step_type"
        actions.append(rec)

    if not dry_run:
        screenshot_monitor(monitor_index, out_dir / "99_after.png")

    result = {
        "ok": True,
        "skipped": False,
        "dry_run": dry_run,
        "config_path": str(config_path),
        "project_name": project_name,
        "project_dir": str(project_dir),
        "plan_pdf": resolved_plan_pdf,
        "takeoff_plans_dir": str(takeoff_dir) if takeoff_dir else "",
        "takeoff_plans_first_file": str(takeoff_first) if takeoff_first else "",
        "actions": actions,
        "maverick_log": maverick_log_step(
            cfg=cfg,
            project_id=project_id,
            action="project_setup_workflow",
            outcome="success",
            archetype="setup-workflow",
            expected="Configured setup steps complete",
            observed="Setup workflow completed",
            resolution="setup_result_written",
        ),
    }
    write_json(out_dir / "setup_result.json", result)
    print(f"setup_result={out_dir / 'setup_result.json'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OST project setup workflow runner")
    parser.add_argument("--config", default="scripts/ost_project_setup_agent.config.json")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--plan-pdf", default="")
    parser.add_argument("--out-dir", default="output/ost-project-setup/latest")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project-id", default="", help="Project id forwarded to Maverick logs")
    args = parser.parse_args()

    return run_setup(
        config_path=pathlib.Path(args.config),
        project_name=str(args.project_name),
        project_dir=pathlib.Path(args.project_dir),
        plan_pdf=str(args.plan_pdf),
        out_dir=pathlib.Path(args.out_dir),
        dry_run=bool(args.dry_run),
        project_id=str(args.project_id),
    )


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.07
    raise SystemExit(main())
