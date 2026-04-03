#!/usr/bin/env python3
"""
OST condition-driven takeoff attempt runner.

Selects a condition row, optionally advances pages, and clicks the best
detected grouping candidate on each attempt.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List

import mss
import pyautogui

from mouse_takeover_guard import install_pyautogui_takeover_guard

try:
    import pygetwindow as gw  # type: ignore
except Exception:  # pragma: no cover
    gw = None

install_pyautogui_takeover_guard(pyautogui)


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


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


def screenshot_monitor(monitor_index: int, out_file: pathlib.Path) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}.")
        shot = sct.grab(mons[monitor_index])
        mss.tools.to_png(shot.rgb, shot.size, output=str(out_file))


def click_anchor(anchors: Dict[str, Any], name: str, delay_s: float = 0.45) -> Dict[str, Any]:
    pt = anchors.get(name, {})
    x = int(pt.get("x", 0))
    y = int(pt.get("y", 0))
    pyautogui.moveTo(x, y, duration=0.15)
    pyautogui.click()
    time.sleep(delay_s)
    return {"anchor": name, "x": x, "y": y}


def run_item_type_classifier(
    project_id: str,
    monitor_index: int,
    item_db_root: str,
    output_path: pathlib.Path,
    context_label: str,
) -> Dict[str, Any]:
    cmd = [
        "python",
        "scripts/ost_item_type_classifier.py",
        "--project-id",
        str(project_id),
        "--monitor-index",
        str(monitor_index),
        "--item-db-root",
        str(item_db_root),
        "--output",
        str(output_path),
        "--context-label",
        str(context_label),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    payload = read_json(output_path)
    summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    return {
        "command": cmd,
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "output_path": str(output_path),
        "summary": summary,
        "payload": payload,
    }


def undo_bad_work(undo_count: int, delay_s: float = 0.3) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for i in range(max(0, int(undo_count))):
        pyautogui.hotkey("ctrl", "a")
        time.sleep(max(0.08, delay_s / 3.0))
        pyautogui.press("delete")
        time.sleep(delay_s)
        actions.append({"step": "clear_select_all_delete", "index": i + 1})
    pyautogui.press("esc")
    time.sleep(0.2)
    actions.append({"step": "press_esc"})
    return actions


def run_attempts(
    setup_config_path: pathlib.Path,
    monitor_index: int,
    attempts: int,
    out_dir: pathlib.Path,
    window_title_contains: str,
    min_match_score: float,
    cleanup_bad_work: bool,
    cleanup_undo_count: int,
    project_id: str,
    item_db_root: str,
    classifier_confidence_threshold: float,
) -> int:
    cfg = read_json(setup_config_path)
    anchors = (cfg.get("anchors", {}) or {}) if isinstance(cfg, dict) else {}
    required = ["conditions_first_row", "conditions_second_row", "page_next_button"]
    missing = [k for k in required if k not in anchors]
    if missing:
        print(f"Missing anchors: {missing}")
        return 2

    focused = focus_window(window_title_contains)
    out_dir.mkdir(parents=True, exist_ok=True)
    events: List[Dict[str, Any]] = []

    for i in range(1, attempts + 1):
        row = "conditions_first_row" if i % 2 == 1 else "conditions_second_row"
        if i > 1:
            nav = click_anchor(anchors, "page_next_button")
            events.append({"attempt": i, "event": "next_page", "click": nav})
            time.sleep(1.0)

        cond = click_anchor(anchors, row)
        events.append({"attempt": i, "event": "select_condition", "condition_row": row, "click": cond})
        time.sleep(0.7)

        shot = out_dir / f"attempt_{i:02d}_before_click.png"
        screenshot_monitor(monitor_index, shot)
        pre_classifier = run_item_type_classifier(
            project_id=project_id,
            monitor_index=monitor_index,
            item_db_root=item_db_root,
            output_path=out_dir / f"attempt_{i:02d}_pre_item_classification.json",
            context_label="condition_attempt_pre_click",
        )

        grouping_out = out_dir / f"attempt_{i:02d}_grouping.json"
        cmd = [
            "python",
            "scripts/ost_grouping_selector.py",
            "--monitor-index",
            str(monitor_index),
            "--click-best",
            "--output",
            str(grouping_out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        payload = read_json(grouping_out)
        selected = payload.get("selected_target", {}) if isinstance(payload, dict) else {}
        selected_score = float(
            (selected.get("score", 0.0) if isinstance(selected, dict) else 0.0) or 0.0
        )
        selected_label = str((selected.get("unit_label", "") if isinstance(selected, dict) else "") or "")
        post_classifier = run_item_type_classifier(
            project_id=project_id,
            monitor_index=monitor_index,
            item_db_root=item_db_root,
            output_path=out_dir / f"attempt_{i:02d}_post_item_classification.json",
            context_label="condition_attempt_post_click",
        )
        post_classifier_conf = float(
            ((post_classifier.get("summary", {}) if isinstance(post_classifier, dict) else {}).get("top_confidence", 0.0) or 0.0)
        )
        bad_work = (
            (selected_score < float(min_match_score))
            or (selected_label.lower() == "unknown")
            or (post_classifier_conf < float(classifier_confidence_threshold))
        )
        cleanup_actions: List[Dict[str, Any]] = []
        if cleanup_bad_work and bad_work:
            cleanup_actions = undo_bad_work(int(cleanup_undo_count))
        events.append(
            {
                "attempt": i,
                "event": "grouping_selector",
                "output": str(grouping_out),
                "exit_code": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "selected_target": selected,
                "pre_item_classification": pre_classifier,
                "post_item_classification": post_classifier,
                "match_assessment": {
                    "score": selected_score,
                    "threshold": float(min_match_score),
                    "unit_label": selected_label,
                    "classifier_top_confidence": post_classifier_conf,
                    "classifier_threshold": float(classifier_confidence_threshold),
                    "bad_work": bad_work,
                },
                "cleanup_actions": cleanup_actions,
            }
        )
        time.sleep(1.0)
        screenshot_monitor(monitor_index, out_dir / f"attempt_{i:02d}_after_click.png")

    summary = {
        "ok": True,
        "timestamp": now_tag(),
        "focused_window": focused,
        "attempts": attempts,
        "monitor_index": monitor_index,
        "setup_config_path": str(setup_config_path),
        "events": events,
    }
    write_json(out_dir / "takeoff_attempt_summary.json", summary)
    print(f"takeoff_attempt_summary={out_dir / 'takeoff_attempt_summary.json'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run condition-based takeoff attempts in OST")
    parser.add_argument("--setup-config", default="scripts/ost_project_setup_agent.config.json")
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--out-dir", default="output/ost-condition-takeoff/latest")
    parser.add_argument("--window-title-contains", default="On-Screen Takeoff")
    parser.add_argument("--min-match-score", type=float, default=55.0)
    parser.add_argument("--cleanup-undo-count", type=int, default=2)
    parser.add_argument("--no-cleanup-bad-work", action="store_true")
    parser.add_argument("--project-id", default="TP-0001")
    parser.add_argument("--item-db-root", default="output/ost-training-lab/item_types")
    parser.add_argument("--classifier-confidence-threshold", type=float, default=0.5)
    args = parser.parse_args()

    return run_attempts(
        setup_config_path=pathlib.Path(args.setup_config),
        monitor_index=int(args.monitor_index),
        attempts=max(1, int(args.attempts)),
        out_dir=pathlib.Path(args.out_dir),
        window_title_contains=str(args.window_title_contains),
        min_match_score=float(args.min_match_score),
        cleanup_bad_work=not bool(args.no_cleanup_bad_work),
        cleanup_undo_count=int(args.cleanup_undo_count),
        project_id=str(args.project_id),
        item_db_root=str(args.item_db_root),
        classifier_confidence_threshold=float(args.classifier_confidence_threshold),
    )


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    raise SystemExit(main())
