#!/usr/bin/env python3
"""
Attempt takeoff on blank drawing left of selected grouping.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

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
            raise ValueError(f"Invalid monitor index {monitor_index}")
        shot = sct.grab(mons[monitor_index])
        mss.tools.to_png(shot.rgb, shot.size, output=str(out_file))


def click_xy(x: int, y: int, double: bool = False) -> None:
    pyautogui.moveTo(x, y, duration=0.15)
    if double:
        pyautogui.doubleClick()
    else:
        pyautogui.click()


def release_modifier_keys() -> None:
    for key in ("ctrl", "shift", "alt", "win", "command"):
        try:
            pyautogui.keyUp(key)
        except Exception:
            pass


def unblock_ui_state() -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    release_modifier_keys()
    for i in range(3):
        pyautogui.press("esc")
        time.sleep(0.1)
        actions.append({"step": "press_esc", "index": i + 1})
    release_modifier_keys()
    try:
        pos = pyautogui.position()
        pyautogui.click(x=int(pos.x), y=int(pos.y))
        actions.append({"step": "refocus_click", "x": int(pos.x), "y": int(pos.y)})
    except Exception:
        actions.append({"step": "refocus_click_failed"})
    return actions


def undo_bad_work(undo_count: int, delay_s: float = 0.35) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for i in range(max(0, int(undo_count))):
        pyautogui.hotkey("ctrl", "a")
        time.sleep(max(0.08, delay_s / 3.0))
        pyautogui.press("delete")
        time.sleep(delay_s)
        actions.append({"step": "clear_select_all_delete", "index": i + 1})
    # Escape helps exit active digitizer modes after cleanup.
    pyautogui.press("esc")
    time.sleep(0.2)
    actions.append({"step": "press_esc"})
    return actions


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


def run_condition_selector(
    setup_config: str,
    condition_row: str,
    monitor_index: int,
    out_dir: pathlib.Path,
    window_title_contains: str,
    prefer_contains: str,
) -> Dict[str, Any]:
    out_json = out_dir / "condition_selection.json"
    cmd = [
        "python",
        "scripts/ost_select_condition_row.py",
        "--setup-config",
        str(setup_config),
        "--condition-row",
        str(condition_row),
        "--selection-mode",
        "active_qty_non_unassigned",
        "--monitor-index",
        str(monitor_index),
        "--window-title-contains",
        str(window_title_contains),
        "--prefer-contains",
        str(prefer_contains),
        "--output-json",
        str(out_json),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    payload = read_json(out_json)
    return {
        "command": cmd,
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "output_path": str(out_json),
        "selection": payload,
    }


def evaluate_condition_selection(
    selection_result: Dict[str, Any],
    min_qty: float,
    preferred_keywords: List[str] | None = None,
) -> Dict[str, Any]:
    sel = selection_result.get("selection", {}) if isinstance(selection_result, dict) else {}
    active = sel.get("active_detection", {}) if isinstance(sel, dict) else {}
    selected = active.get("selected", {}) if isinstance(active, dict) else {}
    selected_by = str(sel.get("selected_by", "") or "")
    text = str(sel.get("selected_condition_text", "") or "")
    qty = float(sel.get("selected_condition_qty", 0.0) or 0.0)
    click = sel.get("click_point", {}) if isinstance(sel, dict) else {}
    safe_adj = sel.get("taskbar_safe_adjustment", {}) if isinstance(sel, dict) else {}
    click_ok = isinstance(click, dict) and int(click.get("x", 0) or 0) > 0 and int(click.get("y", 0) or 0) > 0
    unassigned = "unassigned" in text.lower()
    preferred_keywords = preferred_keywords or []
    keyword = str(sel.get("selected_condition_keyword", "") or "").lower()
    prefer_hit = (not preferred_keywords) or bool(keyword and keyword in preferred_keywords)
    selected_row_y = int(selected.get("y_center_global", 0) or 0)
    click_y = int(click.get("y", 0) or 0) if isinstance(click, dict) else 0
    safe_applied = bool((safe_adj or {}).get("applied", False)) if isinstance(safe_adj, dict) else False
    y_aligned = selected_row_y <= 0 or click_y <= 0 or abs(selected_row_y - click_y) <= 120 or safe_applied
    is_verified = (
        selected_by == "active_qty_non_unassigned"
        and qty >= float(min_qty)
        and (not unassigned)
        and prefer_hit
        and click_ok
        and y_aligned
    )
    return {
        "verified": bool(is_verified),
        "selected_by": selected_by,
        "qty": float(qty),
        "text": text,
        "unassigned": bool(unassigned),
        "click_ok": bool(click_ok),
        "y_aligned": bool(y_aligned),
        "selected_row_y": selected_row_y,
        "click_y": click_y,
        "taskbar_safe_adjusted": safe_applied,
        "selected_keyword": keyword,
        "preferred_keywords": preferred_keywords,
        "preferred_keyword_hit": bool(prefer_hit),
    }


def _candidate_center_global(c: Dict[str, Any]) -> Tuple[int, int]:
    center = c.get("center_global", {}) if isinstance(c, dict) else {}
    return int(center.get("x", 0)), int(center.get("y", 0))


def _bbox_global_from_candidate(payload: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, int]:
    analysis = payload.get("analysis", {}) if isinstance(payload, dict) else {}
    mon = analysis.get("monitor", {}) if isinstance(analysis, dict) else {}
    canvas = analysis.get("canvas_region", {}) if isinstance(analysis, dict) else {}
    bbox = c.get("bbox_canvas", {}) if isinstance(c, dict) else {}
    mon_left = int(mon.get("left", 0))
    mon_top = int(mon.get("top", 0))
    x0 = int(canvas.get("x0", 0))
    y0 = int(canvas.get("y0", 0))
    bx = int(bbox.get("x", 0))
    by = int(bbox.get("y", 0))
    bw = int(bbox.get("w", 0))
    bh = int(bbox.get("h", 0))
    return {
        "x": mon_left + x0 + bx,
        "y": mon_top + y0 + by,
        "w": bw,
        "h": bh,
    }


def pick_left_target(
    payload: Dict[str, Any], fallback_gap: int, left_choice: str
) -> Tuple[int, int, str, Dict[str, Any]]:
    target = payload.get("selected_target", {}) if isinstance(payload, dict) else {}
    bbox = target.get("bbox_canvas", {}) if isinstance(target, dict) else {}
    cx, cy = _candidate_center_global(target)
    bw = int(bbox.get("w", 0))
    if cx <= 0 or cy <= 0 or bw <= 0:
        return 0, 0, "missing_selected_target", {}

    analysis = payload.get("analysis", {}) if isinstance(payload, dict) else {}
    candidates = analysis.get("candidates", []) if isinstance(analysis, dict) else []
    if isinstance(candidates, list):
        left_candidates: List[Tuple[float, Dict[str, Any]]] = []
        for c in candidates:
            if not isinstance(c, dict):
                continue
            ccx, ccy = _candidate_center_global(c)
            if ccx <= 0 or ccy <= 0:
                continue
            if ccx >= cx:
                continue
            dx = float(cx - ccx)
            dy = float(abs(cy - ccy))
            # Prefer nearest left candidate with similar vertical alignment.
            cost = dx + (dy * 0.85)
            left_candidates.append((cost, c))
        if left_candidates:
            left_candidates.sort(key=lambda x: x[0])
            if left_choice == "farthest":
                best = left_candidates[-1][1]
                method = "farthest_left_candidate_center"
            elif left_choice == "middle" and len(left_candidates) >= 3:
                best = left_candidates[len(left_candidates) // 2][1]
                method = "middle_left_candidate_center"
            else:
                best = left_candidates[0][1]
                method = "nearest_left_candidate_center"
            lx, ly = _candidate_center_global(best)
            if lx > 0 and ly > 0:
                return lx, ly, method, best

    # Fallback: click inside-left region of selected box, not far outside it.
    fallback_x = int(cx - max(28, int(bw * 0.62)))
    return fallback_x, cy, "selected_bbox_left_interior_fallback", target


def _nearest_candidate_to_point(payload: Dict[str, Any], px: int, py: int) -> Dict[str, Any]:
    analysis = payload.get("analysis", {}) if isinstance(payload, dict) else {}
    candidates = analysis.get("candidates", []) if isinstance(analysis, dict) else []
    if not isinstance(candidates, list):
        return {}
    best: Dict[str, Any] = {}
    best_cost = 10**12
    for c in candidates:
        if not isinstance(c, dict):
            continue
        cx, cy = _candidate_center_global(c)
        if cx <= 0 or cy <= 0:
            continue
        dx = abs(px - cx)
        dy = abs(py - cy)
        cost = dx + dy
        if cost < best_cost:
            best_cost = cost
            best = c
    return best


def _candidate_distance(px: int, py: int, c: Dict[str, Any]) -> int:
    cx, cy = _candidate_center_global(c)
    if cx <= 0 or cy <= 0:
        return 10**9
    return abs(px - cx) + abs(py - cy)


def _top_item_type(summary_payload: Dict[str, Any]) -> str:
    if not isinstance(summary_payload, dict):
        return ""
    summary = summary_payload.get("summary", {}) if isinstance(summary_payload.get("summary", {}), dict) else {}
    return str(summary.get("top_item_type", "") or "")


def build_self_review(
    *,
    reason: str,
    condition_verification: Dict[str, Any] | None = None,
    pre_click_adjustment: Dict[str, Any] | None = None,
    match_assessment: Dict[str, Any] | None = None,
    cleanup_ran: bool = False,
) -> Dict[str, Any]:
    cond = condition_verification or {}
    pre = pre_click_adjustment or {}
    match = match_assessment or {}
    score = float(match.get("score", 0.0) or 0.0)
    threshold = float(match.get("threshold", 0.0) or 0.0)
    cls_conf = float(match.get("classifier_top_confidence", 0.0) or 0.0)
    cls_threshold = float(match.get("classifier_threshold", 0.0) or 0.0)
    expected_item_match = bool(match.get("expected_item_type_match", True))
    keyword_hit = bool(cond.get("preferred_keyword_hit", False))
    y_aligned = bool(cond.get("y_aligned", False))
    adjusted = bool(pre.get("adjusted", False))

    qna: List[Dict[str, str]] = [
        {
            "question": "Why did my click not work?",
            "answer": (
                "Condition verification failed before draw."
                if reason == "condition_verification_failed"
                else (
                    "Expected target gate failed; chosen region was too far from Boost region."
                    if reason == "expected_target_gate_failed"
                    else (
                        "Click worked, but output did not match quality gates."
                        if reason in ("quality_gate_failed", "bad_work")
                        else "No click failure detected."
                    )
                )
            ),
        },
        {
            "question": "Why did I think my click would work there?",
            "answer": (
                f"Pre-click verification {'adjusted' if adjusted else 'accepted'} target with "
                f"distance={int(pre.get('distance_px', 0) or 0)}."
            ),
        },
        {
            "question": "Why does it make sense not to click there?",
            "answer": (
                "Because condition keyword/row alignment checks did not pass."
                if (not keyword_hit or not y_aligned)
                else (
                    "Because target is not consistent with expected Boost region/class."
                    if not expected_item_match
                    else "It may still be wrong if confidence gate is low."
                )
            ),
        },
        {
            "question": "What should I change in code or instructions?",
            "answer": (
                "Tighten preferred condition keywords and add expected target/class gate."
                if reason in ("condition_verification_failed", "expected_target_gate_failed")
                else "Increase target-shape fidelity and post-click verification before scoring."
            ),
        },
        {
            "question": "What evidence proved the decision?",
            "answer": (
                f"score={score:.2f}/{threshold:.2f}, classifier={cls_conf:.3f}/{cls_threshold:.3f}, "
                f"keyword_hit={keyword_hit}, y_aligned={y_aligned}, cleanup_ran={cleanup_ran}"
            ),
        },
    ]

    comprehensive_checklist = [
        "Did I verify window focus and monitor before any click?",
        "Did I capture a screenshot before the click and after the click?",
        "Did the selected condition contain a preferred keyword (ceiling/gwb variants)?",
        "Was selected condition quantity greater than zero?",
        "Was click location aligned with detected condition row?",
        "Was pre-click target within expected distance of Boost target center?",
        "Did takeoff start at a 90-degree corner as instructed?",
        "Did post-attempt score exceed threshold?",
        "Did classifier confidence exceed threshold?",
        "Did post item type match expected item type from Boost analysis?",
        "Did cleanup run to prevent compounding bad work?",
        "What one parameter should change next run (and why)?",
    ]

    next_adjustments = []
    if not keyword_hit:
        next_adjustments.append("Expand condition keyword aliases and OCR normalization for ceiling/GWB.")
    if not y_aligned:
        next_adjustments.append("Raise row alignment tolerance only when taskbar-safe clamp is active.")
    if score < threshold:
        next_adjustments.append("Alter polyline points to follow candidate bounds more tightly.")
    if cls_conf < cls_threshold:
        next_adjustments.append("Increase expected-target strictness and reject low-confidence regions earlier.")
    if not expected_item_match:
        next_adjustments.append("Require expected item type parity before finalizing match.")
    if not next_adjustments:
        next_adjustments.append("Keep parameters unchanged; current run satisfied all gates.")

    return {
        "reason": reason,
        "qna": qna,
        "comprehensive_checklist": comprehensive_checklist,
        "next_adjustments": next_adjustments,
    }


def _extract_ocr_diag(payload: Dict[str, Any]) -> Dict[str, Any]:
    analysis = payload.get("analysis", {}) if isinstance(payload, dict) else {}
    diag = analysis.get("ocr_diagnostics", {}) if isinstance(analysis, dict) else {}
    return diag if isinstance(diag, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Click blank drawing left of selected grouping")
    parser.add_argument("--setup-config", default="scripts/ost_project_setup_agent.config.json")
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--condition-row", choices=["first", "second"], default="first")
    parser.add_argument("--left-gap", type=int, default=45)
    parser.add_argument("--output-dir", default="output/ost-condition-takeoff/current_page_left_blank")
    parser.add_argument("--window-title-contains", default="On-Screen Takeoff")
    parser.add_argument(
        "--attempt-style",
        choices=["point", "polyline2", "polyline4"],
        default="polyline4",
        help="point=single/double click, polyline2=two-point stroke, polyline4=four-point perimeter stroke",
    )
    parser.add_argument(
        "--left-choice",
        choices=["nearest", "middle", "farthest"],
        default="nearest",
        help="How to pick the candidate to the left of selected grouping",
    )
    parser.add_argument(
        "--match-score-threshold",
        type=float,
        default=55.0,
        help="Minimum post-attempt score considered a valid copy of the example",
    )
    parser.add_argument(
        "--cleanup-undo-count",
        type=int,
        default=2,
        help="How many Ctrl+Z undos to apply when attempt is marked bad",
    )
    parser.add_argument(
        "--no-cleanup-bad-work",
        action="store_true",
        help="Disable auto cleanup of attempts that fail score threshold",
    )
    parser.add_argument("--project-id", default="TP-0001")
    parser.add_argument("--item-db-root", default="output/ost-training-lab/item_types")
    parser.add_argument(
        "--classifier-confidence-threshold",
        type=float,
        default=0.5,
        help="Minimum classifier confidence expected for reliable visual match",
    )
    parser.add_argument(
        "--pre-click-adjust-threshold",
        type=int,
        default=160,
        help="If intended click is farther than this (px), re-center to nearest analyzed candidate.",
    )
    parser.add_argument(
        "--condition-verify-retries",
        type=int,
        default=2,
        help="How many times to re-select condition if verification fails.",
    )
    parser.add_argument(
        "--condition-min-qty",
        type=float,
        default=1.0,
        help="Minimum quantity required to treat condition selection as valid.",
    )
    parser.add_argument(
        "--condition-prefer-contains",
        default="ceiling,ceil,cen,gwb,gyp,gypsum",
        help="Preferred condition keywords (comma-separated).",
    )
    parser.add_argument("--expected-target-x", type=int, default=0)
    parser.add_argument("--expected-target-y", type=int, default=0)
    parser.add_argument("--expected-item-type", default="")
    parser.add_argument(
        "--strict-expected-distance-threshold",
        type=int,
        default=220,
        help="Require selected target to be within this distance of expected Boost target center.",
    )
    parser.add_argument(
        "--pre-attempt-visible-delay-ms",
        type=int,
        default=2200,
        help="Pause before stroke so the user can visibly confirm the attempt start",
    )
    parser.add_argument(
        "--pre-clear-count",
        type=int,
        default=2,
        help="Always clear existing blocks before attempt (Ctrl+A, Delete).",
    )
    args = parser.parse_args()

    out_dir = pathlib.Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_cfg = read_json(pathlib.Path(args.setup_config))
    anchors = setup_cfg.get("anchors", {}) if isinstance(setup_cfg, dict) else {}
    row_anchor_name = "conditions_first_row" if args.condition_row == "first" else "conditions_second_row"
    row_anchor = anchors.get(row_anchor_name, {})
    if not row_anchor:
        print(f"missing_anchor={row_anchor_name}")
        return 2

    focused = focus_window(str(args.window_title_contains))
    time.sleep(0.2)
    pre_unblock_actions = unblock_ui_state()
    pre_clear_actions = undo_bad_work(max(0, int(args.pre_clear_count)))
    screenshot_monitor(int(args.monitor_index), out_dir / "before_attempt.png")
    pre_classifier_out = out_dir / "pre_item_classification.json"
    pre_classifier = run_item_type_classifier(
        project_id=str(args.project_id),
        monitor_index=int(args.monitor_index),
        item_db_root=str(args.item_db_root),
        output_path=pre_classifier_out,
        context_label="left_blank_pre_attempt",
    )

    condition_selection_attempts: List[Dict[str, Any]] = []
    max_condition_attempts = max(1, int(args.condition_verify_retries) + 1)
    condition_selection: Dict[str, Any] = {}
    condition_verification: Dict[str, Any] = {"verified": False}
    preferred_keywords = [
        t.strip().lower()
        for t in str(args.condition_prefer_contains or "").split(",")
        if t.strip()
    ]
    for _ in range(max_condition_attempts):
        sel = run_condition_selector(
            setup_config=str(args.setup_config),
            condition_row=str(args.condition_row),
            monitor_index=int(args.monitor_index),
            out_dir=out_dir,
            window_title_contains=str(args.window_title_contains),
            prefer_contains=str(args.condition_prefer_contains),
        )
        verdict = evaluate_condition_selection(
            sel,
            min_qty=float(args.condition_min_qty),
            preferred_keywords=preferred_keywords,
        )
        condition_selection_attempts.append({"selection": sel, "verification": verdict})
        condition_selection = sel
        condition_verification = verdict
        if bool(verdict.get("verified", False)):
            break
        time.sleep(0.45)
    if not bool(condition_verification.get("verified", False)):
        result = {
            "ok": False,
            "timestamp": now_tag(),
            "focused_window": focused,
            "condition_row": args.condition_row,
            "condition_selection": condition_selection,
            "condition_selection_attempts": condition_selection_attempts,
            "condition_verification": condition_verification,
            "reason": "condition_verification_failed",
            "self_review": build_self_review(
                reason="condition_verification_failed",
                condition_verification=condition_verification,
            ),
        }
        write_json(out_dir / "left_blank_takeoff_attempt.json", result)
        print(f"left_blank_takeoff_attempt={out_dir / 'left_blank_takeoff_attempt.json'}")
        return 4
    time.sleep(0.5)

    grouping_out = out_dir / "grouping_before_left_click.json"
    proc = subprocess.run(
        [
            "python",
            "scripts/ost_grouping_selector.py",
            "--monitor-index",
            str(args.monitor_index),
            "--click-best",
            "--output",
            str(grouping_out),
        ],
        capture_output=True,
        text=True,
    )
    payload = read_json(grouping_out)
    target = payload.get("selected_target", {}) if isinstance(payload, dict) else {}
    left_target_x, left_target_y, target_method, left_target_candidate = pick_left_target(
        payload, int(args.left_gap), str(args.left_choice)
    )
    if left_target_x <= 0 or left_target_y <= 0:
        print("left_blank_click=failed_missing_target")
        return 3

    pre_click_verify_screenshot = out_dir / "pre_click_verify.png"
    screenshot_monitor(int(args.monitor_index), pre_click_verify_screenshot)
    verify_out = out_dir / "grouping_pre_click_verify.json"
    verify_proc = subprocess.run(
        [
            "python",
            "scripts/ost_grouping_selector.py",
            "--monitor-index",
            str(args.monitor_index),
            "--output",
            str(verify_out),
        ],
        capture_output=True,
        text=True,
    )
    verify_payload = read_json(verify_out)
    verified_candidate = _nearest_candidate_to_point(verify_payload, int(left_target_x), int(left_target_y))
    pre_click_adjusted = False
    pre_click_distance = _candidate_distance(int(left_target_x), int(left_target_y), verified_candidate)
    expected_target_applied = False
    expected_target_failed = False
    expected_target_distance = -1
    expected_target_threshold = max(80, int(args.strict_expected_distance_threshold))
    expected_target_candidate: Dict[str, Any] = {}
    if int(args.expected_target_x) > 0 and int(args.expected_target_y) > 0:
        expected_target_candidate = _nearest_candidate_to_point(
            verify_payload, int(args.expected_target_x), int(args.expected_target_y)
        )
        expected_target_distance = _candidate_distance(
            int(args.expected_target_x), int(args.expected_target_y), expected_target_candidate
        )
        if expected_target_candidate and expected_target_distance <= expected_target_threshold:
            ex, ey = _candidate_center_global(expected_target_candidate)
            if ex > 0 and ey > 0:
                left_target_x, left_target_y = ex, ey
                left_target_candidate = expected_target_candidate
                pre_click_adjusted = True
                expected_target_applied = True
        else:
            expected_target_failed = True
    if verified_candidate and pre_click_distance > max(40, int(args.pre_click_adjust_threshold)):
        vx, vy = _candidate_center_global(verified_candidate)
        if vx > 0 and vy > 0:
            left_target_x, left_target_y = vx, vy
            left_target_candidate = verified_candidate
            pre_click_adjusted = True
    if expected_target_failed:
        result = {
            "ok": False,
            "timestamp": now_tag(),
            "focused_window": focused,
            "condition_row": args.condition_row,
            "condition_selection": condition_selection,
            "condition_selection_attempts": condition_selection_attempts,
            "condition_verification": condition_verification,
            "pre_click_verify_screenshot": str(pre_click_verify_screenshot),
            "pre_click_verify_payload": verify_payload,
            "reason": "expected_target_gate_failed",
            "expected_target": {
                "x": int(args.expected_target_x),
                "y": int(args.expected_target_y),
                "item_type": str(args.expected_item_type),
                "distance_px": int(expected_target_distance),
                "threshold_px": int(expected_target_threshold),
                "nearest_candidate": expected_target_candidate,
            },
            "self_review": build_self_review(
                reason="expected_target_gate_failed",
                condition_verification=condition_verification,
                pre_click_adjustment={
                    "adjusted": pre_click_adjusted,
                    "distance_px": int(pre_click_distance),
                    "threshold_px": int(args.pre_click_adjust_threshold),
                },
            ),
        }
        write_json(out_dir / "left_blank_takeoff_attempt.json", result)
        print(f"left_blank_takeoff_attempt={out_dir / 'left_blank_takeoff_attempt.json'}")
        return 4

    pre_attempt_delay_s = max(0.0, int(args.pre_attempt_visible_delay_ms) / 1000.0)
    if pre_attempt_delay_s > 0.0:
        time.sleep(pre_attempt_delay_s)

    pre_click_source = verify_payload if isinstance(verify_payload, dict) and verify_payload else payload
    stroke_points: List[Dict[str, int]] = []
    if args.attempt_style == "polyline4":
        gb = _bbox_global_from_candidate(pre_click_source, left_target_candidate)
        gx, gy, gw, gh = gb["x"], gb["y"], gb["w"], gb["h"]
        if gw > 48 and gh > 48:
            # Start on a clear 90-degree corner and trace axis-aligned points.
            inset = max(2, int(min(gw, gh) * 0.03))
            p1 = {"x": int(gx + inset), "y": int(gy + inset)}  # top-left 90-degree corner
            p2 = {"x": int(gx + gw - inset), "y": int(gy + inset)}
            p3 = {"x": int(gx + gw - inset), "y": int(gy + gh - inset)}
            p4 = {"x": int(gx + inset), "y": int(gy + gh - inset)}
            click_xy(p1["x"], p1["y"])
            time.sleep(0.34)
            click_xy(p2["x"], p2["y"])
            time.sleep(0.34)
            click_xy(p3["x"], p3["y"])
            time.sleep(0.34)
            click_xy(p4["x"], p4["y"], double=True)
            stroke_points = [p1, p2, p3, p4]
        else:
            click_xy(left_target_x, left_target_y)
            time.sleep(0.55)
            click_xy(left_target_x, left_target_y, double=True)
            stroke_points = [{"x": left_target_x, "y": left_target_y}]
    elif args.attempt_style == "polyline2":
        gb = _bbox_global_from_candidate(pre_click_source, left_target_candidate)
        gx, gy, gw, gh = gb["x"], gb["y"], gb["w"], gb["h"]
        if gw > 40 and gh > 40:
            p1x = int(gx + (gw * 0.32))
            p1y = int(gy + (gh * 0.38))
            p2x = int(gx + (gw * 0.70))
            p2y = int(gy + (gh * 0.72))
            click_xy(p1x, p1y)
            time.sleep(0.55)
            click_xy(p2x, p2y, double=True)
            stroke_points = [{"x": p1x, "y": p1y}, {"x": p2x, "y": p2y}]
        else:
            click_xy(left_target_x, left_target_y)
            time.sleep(0.8)
            click_xy(left_target_x, left_target_y, double=True)
            stroke_points = [{"x": left_target_x, "y": left_target_y}]
    else:
        click_xy(left_target_x, left_target_y)
        time.sleep(0.8)
        click_xy(left_target_x, left_target_y, double=True)
        stroke_points = [{"x": left_target_x, "y": left_target_y}]
    time.sleep(0.6)

    screenshot_monitor(int(args.monitor_index), out_dir / "after_left_blank_click.png")

    post_out = out_dir / "grouping_after_attempt.json"
    post_proc = subprocess.run(
        [
            "python",
            "scripts/ost_grouping_selector.py",
            "--monitor-index",
            str(args.monitor_index),
            "--output",
            str(post_out),
        ],
        capture_output=True,
        text=True,
    )
    post_payload = read_json(post_out)
    probe_point = stroke_points[-1] if stroke_points else {"x": left_target_x, "y": left_target_y}
    post_candidate = _nearest_candidate_to_point(
        post_payload, int(probe_point.get("x", 0)), int(probe_point.get("y", 0))
    )
    post_score = float((post_candidate.get("score", 0.0) if isinstance(post_candidate, dict) else 0.0) or 0.0)
    post_classifier_out = out_dir / "post_item_classification.json"
    post_classifier = run_item_type_classifier(
        project_id=str(args.project_id),
        monitor_index=int(args.monitor_index),
        item_db_root=str(args.item_db_root),
        output_path=post_classifier_out,
        context_label="left_blank_post_attempt",
    )
    post_classifier_conf = float(
        ((post_classifier.get("summary", {}) if isinstance(post_classifier, dict) else {}).get("top_confidence", 0.0) or 0.0)
    )
    post_item_type = _top_item_type(post_classifier)
    expected_item_type = str(args.expected_item_type or "").strip().lower()
    expected_item_type_match = True
    if expected_item_type:
        expected_item_type_match = post_item_type.lower() == expected_item_type
    is_match = (post_score >= float(args.match_score_threshold)) and (
        post_classifier_conf >= float(args.classifier_confidence_threshold)
    ) and bool(expected_item_type_match)
    bad_work = not is_match
    cleanup_actions: List[Dict[str, Any]] = []
    if bad_work and (not bool(args.no_cleanup_bad_work)):
        cleanup_actions = undo_bad_work(int(args.cleanup_undo_count))
        screenshot_monitor(int(args.monitor_index), out_dir / "after_cleanup.png")

    result = {
        "ok": True,
        "timestamp": now_tag(),
        "focused_window": focused,
        "condition_row": args.condition_row,
        "row_anchor_name": row_anchor_name,
        "row_anchor_click": {"x": int(row_anchor.get("x", 0)), "y": int(row_anchor.get("y", 0))},
        "condition_selection": condition_selection,
        "condition_selection_attempts": condition_selection_attempts,
        "condition_verification": condition_verification,
        "condition_preferred_keywords": preferred_keywords,
        "pre_unblock": {
            "enabled": True,
            "actions": pre_unblock_actions,
        },
        "pre_clear": {
            "enabled": bool(int(args.pre_clear_count) > 0),
            "count": int(args.pre_clear_count),
            "actions": pre_clear_actions,
        },
        "pre_attempt_screenshot": str(out_dir / "before_attempt.png"),
        "pre_item_classification": pre_classifier,
        "grouping_stdout": proc.stdout.strip(),
        "grouping_stderr": proc.stderr.strip(),
        "post_grouping_stdout": post_proc.stdout.strip(),
        "post_grouping_stderr": post_proc.stderr.strip(),
        "pre_click_verify_screenshot": str(pre_click_verify_screenshot),
        "pre_click_verify_stdout": verify_proc.stdout.strip(),
        "pre_click_verify_stderr": verify_proc.stderr.strip(),
        "pre_click_verify_payload": verify_payload,
        "pre_click_adjustment": {
            "adjusted": pre_click_adjusted,
            "distance_px": int(pre_click_distance),
            "threshold_px": int(args.pre_click_adjust_threshold),
            "expected_target_applied": bool(expected_target_applied),
            "expected_target_distance_px": int(expected_target_distance),
            "expected_target_threshold_px": int(expected_target_threshold),
            "final_click": {"x": int(left_target_x), "y": int(left_target_y)},
        },
        "ocr_telemetry": {
            "condition": (
                (condition_selection.get("selection", {}) if isinstance(condition_selection.get("selection", {}), dict) else {})
                .get("active_detection", {})
                .get("ocr_diagnostics", {})
            ),
            "grouping_before": _extract_ocr_diag(payload),
            "grouping_verify": _extract_ocr_diag(verify_payload),
            "grouping_after": _extract_ocr_diag(post_payload),
        },
        "post_item_classification": post_classifier,
        "selected_target": target,
        "left_target_method": target_method,
        "left_target_candidate": left_target_candidate,
        "left_blank_click": {"x": left_target_x, "y": left_target_y},
        "pre_attempt_visible_delay_ms": int(args.pre_attempt_visible_delay_ms),
        "attempt_style": args.attempt_style,
        "stroke_points": stroke_points,
        "post_attempt_probe_point": probe_point,
        "post_attempt_nearest_candidate": post_candidate,
        "match_assessment": {
            "score": post_score,
            "threshold": float(args.match_score_threshold),
            "classifier_top_confidence": post_classifier_conf,
            "classifier_threshold": float(args.classifier_confidence_threshold),
            "post_item_type": post_item_type,
            "expected_item_type": str(args.expected_item_type or ""),
            "expected_item_type_match": bool(expected_item_type_match),
            "is_match": is_match,
            "bad_work": bad_work,
        },
        "self_review": build_self_review(
            reason=("ok" if is_match else "quality_gate_failed"),
            condition_verification=condition_verification,
            pre_click_adjustment={
                "adjusted": pre_click_adjusted,
                "distance_px": int(pre_click_distance),
                "threshold_px": int(args.pre_click_adjust_threshold),
            },
            match_assessment={
                "score": post_score,
                "threshold": float(args.match_score_threshold),
                "classifier_top_confidence": post_classifier_conf,
                "classifier_threshold": float(args.classifier_confidence_threshold),
                "expected_item_type_match": bool(expected_item_type_match),
            },
            cleanup_ran=bool(cleanup_actions),
        ),
        "cleanup": {
            "enabled": not bool(args.no_cleanup_bad_work),
            "undo_count": int(args.cleanup_undo_count),
            "ran": bool(cleanup_actions),
            "actions": cleanup_actions,
        },
        "evidence_screenshot": str(out_dir / "after_left_blank_click.png"),
    }
    write_json(out_dir / "left_blank_takeoff_attempt.json", result)
    print(f"left_blank_takeoff_attempt={out_dir / 'left_blank_takeoff_attempt.json'}")
    return 0


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    raise SystemExit(main())
