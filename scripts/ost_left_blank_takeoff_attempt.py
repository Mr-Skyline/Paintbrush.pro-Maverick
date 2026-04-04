#!/usr/bin/env python3
"""
Attempt takeoff on blank drawing left of selected grouping.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import math
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

import cv2
import mss
import numpy as np
import pyautogui

from mouse_takeover_guard import install_pyautogui_takeover_guard
from ocr_engine import create_ocr_engine

try:
    import pygetwindow as gw  # type: ignore
except Exception:  # pragma: no cover
    gw = None

install_pyautogui_takeover_guard(pyautogui)
ACTIVE_OST_WINDOW_RECT: Dict[str, int] = {}


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def infer_finish_context(
    condition_name: str,
    condition_style: str,
    taxonomy_path: str,
    finish_index_json: str,
) -> Dict[str, Any]:
    low = f"{condition_name or ''}".lower()
    taxonomy = read_json(pathlib.Path(taxonomy_path)) if str(taxonomy_path or "").strip() else {}
    trades = taxonomy.get("trades", {}) if isinstance(taxonomy, dict) else {}
    match_rows: List[Dict[str, Any]] = []
    for trade, row in trades.items():
        aliases = row.get("aliases", []) if isinstance(row, dict) else []
        aliases = [str(a).lower() for a in aliases if str(a).strip()]
        hit_count = sum(1 for a in aliases if a and a in low)
        if hit_count > 0:
            conf = min(0.95, 0.45 + (0.1 * hit_count))
            match_rows.append({"trade": str(trade), "confidence": round(conf, 3), "hits": hit_count})
    match_rows.sort(key=lambda r: float(r.get("confidence", 0.0)), reverse=True)

    design_set = {"best": "unknown", "confidence": 0.0}
    if str(finish_index_json or "").strip():
        idx = read_json(pathlib.Path(finish_index_json))
        ds = idx.get("design_set_signature_index", {}) if isinstance(idx, dict) else {}
        if isinstance(ds, dict) and ds:
            best_key = ""
            best_val = -1.0
            for k, v in ds.items():
                score = float((v.get("avg_score", 0.0) if isinstance(v, dict) else 0.0) or 0.0)
                if score > best_val:
                    best_key = str(k)
                    best_val = score
            if best_key:
                design_set = {"best": best_key, "confidence": round(best_val, 3)}

    inferred_trade = match_rows[0]["trade"] if match_rows else "unknown"
    base_conf = float(match_rows[0]["confidence"]) if match_rows else 0.35
    if condition_style == "count" and inferred_trade in {"doors", "door_frames"}:
        base_conf = min(0.98, base_conf + 0.12)
    if condition_style == "area" and inferred_trade in {"painting", "wallcovering", "drywall", "ceilings"}:
        base_conf = min(0.98, base_conf + 0.08)
    if condition_style == "linear" and inferred_trade in {"trim", "wood_base"}:
        base_conf = min(0.98, base_conf + 0.08)
    return {
        "inferred_trade": inferred_trade,
        "confidence": round(base_conf, 3),
        "trade_candidates": match_rows[:5],
        "design_set_signature": design_set,
        "condition_name": condition_name,
        "condition_style": condition_style,
    }


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


def get_window_rect(title_contains: str) -> Dict[str, int]:
    if gw is None:
        return {}
    try:
        wins = gw.getWindowsWithTitle(title_contains)
        if not wins:
            return {}
        w = wins[0]
        return {
            "left": int(getattr(w, "left", 0) or 0),
            "top": int(getattr(w, "top", 0) or 0),
            "width": max(0, int(getattr(w, "width", 0) or 0)),
            "height": max(0, int(getattr(w, "height", 0) or 0)),
        }
    except Exception:
        return {}


def _clamp_point_to_ost_window(x: int, y: int, margin_px: int = 10) -> Tuple[int, int, bool]:
    rect = ACTIVE_OST_WINDOW_RECT if isinstance(ACTIVE_OST_WINDOW_RECT, dict) else {}
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


def screenshot_monitor(monitor_index: int, out_file: pathlib.Path) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}")
        shot = sct.grab(mons[monitor_index])
        mss.tools.to_png(shot.rgb, shot.size, output=str(out_file))


def screenshot_monitor_np(monitor_index: int) -> np.ndarray:
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}")
        shot = sct.grab(mons[monitor_index])
        return np.array(shot)[:, :, :3].copy()


def click_xy(x: int, y: int, double: bool = False) -> None:
    tx, ty, adjusted = _clamp_point_to_ost_window(int(x), int(y))
    if adjusted:
        print(f"ost_window_clamp from=({int(x)},{int(y)}) to=({tx},{ty})")
    pyautogui.moveTo(tx, ty, duration=0.15)
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
    target_row_index: int = -1,
    selection_mode: str = "active_qty_non_unassigned",
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
        str(selection_mode),
        "--monitor-index",
        str(monitor_index),
        "--window-title-contains",
        str(window_title_contains),
        "--prefer-contains",
        str(prefer_contains),
        "--output-json",
        str(out_json),
    ]
    if int(target_row_index) >= 0:
        cmd.extend(["--target-row-index", str(int(target_row_index))])
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


def inspect_condition_style(
    x: int,
    y: int,
    monitor_index: int,
    out_dir: pathlib.Path,
    window_title_contains: str,
) -> Dict[str, Any]:
    out_json = out_dir / "condition_style_inspection.json"
    cmd = [
        "python",
        "scripts/ost_condition_style_inspector.py",
        "--x",
        str(int(x)),
        "--y",
        str(int(y)),
        "--monitor-index",
        str(int(monitor_index)),
        "--window-title-contains",
        str(window_title_contains),
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
        "inspection": payload,
    }


def evaluate_condition_selection(
    selection_result: Dict[str, Any],
    min_qty: float,
    preferred_keywords: List[str] | None = None,
    expected_row_index: int = -1,
) -> Dict[str, Any]:
    sel = selection_result.get("selection", {}) if isinstance(selection_result, dict) else {}
    active = sel.get("active_detection", {}) if isinstance(sel, dict) else {}
    selected = active.get("selected", {}) if isinstance(active, dict) else {}
    selected_by = str(sel.get("selected_by", "") or "")
    selection_mode = str(sel.get("selection_mode", "") or "")
    text = str(sel.get("selected_condition_text", "") or "")
    qty = float(sel.get("selected_condition_qty", 0.0) or 0.0)
    click = sel.get("click_point", {}) if isinstance(sel, dict) else {}
    safe_adj = sel.get("taskbar_safe_adjustment", {}) if isinstance(sel, dict) else {}
    click_ok = isinstance(click, dict) and int(click.get("x", 0) or 0) > 0 and int(click.get("y", 0) or 0) > 0
    unassigned = "unassigned" in text.lower()
    preferred_keywords = preferred_keywords or []
    keyword = str(sel.get("selected_condition_keyword", "") or "").lower()
    lock_conf = float(sel.get("selected_condition_confidence", 0.0) or 0.0)
    candidate_count = int(sel.get("active_candidate_count", 0) or 0)
    prefer_hit = (not preferred_keywords) or bool(keyword and keyword in preferred_keywords)
    selected_row_y = int(selected.get("y_center_global", 0) or 0)
    selected_row_index_raw = selected.get("row_index", -1) if isinstance(selected, dict) else -1
    selected_row_index = int(selected_row_index_raw if selected_row_index_raw is not None else -1)
    click_y = int(click.get("y", 0) or 0) if isinstance(click, dict) else 0
    safe_applied = bool((safe_adj or {}).get("applied", False)) if isinstance(safe_adj, dict) else False
    y_aligned = selected_row_y <= 0 or click_y <= 0 or abs(selected_row_y - click_y) <= 120 or safe_applied
    row_index_match = expected_row_index < 0 or selected_row_index == int(expected_row_index)
    if selected_by == "locked_row_by_name" or selection_mode == "locked_row_by_name":
        is_verified = (
            bool(keyword in {"ceiling", "gwb"})
            and (not unassigned)
            and prefer_hit
            and click_ok
            and y_aligned
            and row_index_match
            and lock_conf >= 0.90
            and candidate_count >= 1
        )
    else:
        is_verified = (
            selected_by == "active_qty_non_unassigned"
            and qty >= float(min_qty)
            and (not unassigned)
            and prefer_hit
            and click_ok
            and y_aligned
            and row_index_match
            and lock_conf >= 0.92
            and candidate_count >= 1
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
        "selected_row_index": selected_row_index,
        "expected_row_index": int(expected_row_index),
        "row_index_match": bool(row_index_match),
        "click_y": click_y,
        "taskbar_safe_adjusted": safe_applied,
        "selected_keyword": keyword,
        "preferred_keywords": preferred_keywords,
        "preferred_keyword_hit": bool(prefer_hit),
        "lock_confidence": lock_conf,
        "active_candidate_count": candidate_count,
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


def _monitor_origin(payload: Dict[str, Any]) -> Tuple[int, int]:
    analysis = payload.get("analysis", {}) if isinstance(payload, dict) else {}
    mon = analysis.get("monitor", {}) if isinstance(analysis, dict) else {}
    return int(mon.get("left", 0)), int(mon.get("top", 0))


def _run_glm_plan_preread(
    image_bgr: np.ndarray,
    payload: Dict[str, Any],
    ocr_config_path: str,
    condition_name: str,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        eng = create_ocr_engine(config_path=str(ocr_config_path))
    except Exception as exc:
        return {"ok": False, "reason": "ocr_engine_init_failed", "error": str(exc), "duration_ms": int((time.perf_counter() - t0) * 1000)}

    analysis = payload.get("analysis", {}) if isinstance(payload, dict) else {}
    canvas = analysis.get("canvas_region", {}) if isinstance(analysis, dict) else {}
    mon_left, mon_top = _monitor_origin(payload)
    x0 = int(canvas.get("x0", 0))
    y0 = int(canvas.get("y0", 0))
    x1 = int(canvas.get("x1", 0))
    y1 = int(canvas.get("y1", 0))
    if x1 <= x0 or y1 <= y0:
        h, w = image_bgr.shape[:2]
        x0, y0, x1, y1 = int(w * 0.2), int(h * 0.12), int(w * 0.92), int(h * 0.95)
        mon_left, mon_top = 0, 0
    roi = image_bgr[max(0, y0 - mon_top):max(0, y1 - mon_top), max(0, x0 - mon_left):max(0, x1 - mon_left)]
    if roi.size == 0:
        return {"ok": False, "reason": "empty_roi", "duration_ms": int((time.perf_counter() - t0) * 1000)}

    ctx = (
        "Read blueprint plan text cues for area takeoff. "
        "Extract concise tokens for room labels, ceiling boundaries, dimensions, AFF/CLG marks, and boundary hints. "
        f"Active condition: {condition_name}."
    )
    ocr = eng.ocr_text(roi, context=ctx, psm=6)
    text = str(ocr.get("text", "") or "")
    low = text.lower()
    cue_tokens = ["room", "ceiling", "clg", "aff", "typ", "dim", "elev", "corridor", "office", "unit"]
    hits = [t for t in cue_tokens if t in low]
    confidence = min(0.95, 0.3 + (0.08 * len(hits)) + (0.12 if bool(ocr.get("ok", False)) else 0.0))
    return {
        "ok": bool(ocr.get("ok", False)),
        "engine_used": str(ocr.get("engine_used", "")),
        "fallback_used": bool(ocr.get("fallback_used", False)),
        "confidence": round(confidence, 3),
        "cue_hits": hits,
        "text_preview": " ".join(text.split())[:600],
        "roi": {"x": int(x0), "y": int(y0), "w": int(max(0, x1 - x0)), "h": int(max(0, y1 - y0))},
        "duration_ms": int((time.perf_counter() - t0) * 1000),
        "diagnostics": eng.get_diagnostics(),
    }


def _order_clockwise(points: List[Dict[str, int]]) -> List[Dict[str, int]]:
    if len(points) < 3:
        return points
    cx = sum(int(p["x"]) for p in points) / max(1, len(points))
    cy = sum(int(p["y"]) for p in points) / max(1, len(points))
    ordered = sorted(points, key=lambda p: math.atan2(float(p["y"] - cy), float(p["x"] - cx)))
    # Ensure clockwise winding for deterministic click order.
    if _poly_signed_area(ordered) > 0:
        ordered = list(reversed(ordered))
    return ordered


def _plan_area_polygon_v2(
    image_bgr: np.ndarray,
    payload: Dict[str, Any],
    candidate: Dict[str, Any],
    preread_confidence: float,
) -> Dict[str, Any]:
    if not isinstance(candidate, dict) or not candidate:
        return {"ok": False, "reason": "missing_candidate"}
    gb = _bbox_global_from_candidate(payload, candidate)
    mon_left, mon_top = _monitor_origin(payload)
    x, y, w, h = int(gb["x"] - mon_left), int(gb["y"] - mon_top), int(gb["w"]), int(gb["h"])
    if w < 36 or h < 36:
        return {"ok": False, "reason": "candidate_too_small"}
    h_img, w_img = image_bgr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w_img, x + w), min(h_img, y + h)
    roi = image_bgr[y0:y1, x0:x1]
    if roi.size == 0:
        return {"ok": False, "reason": "empty_candidate_roi"}
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 70, 160)
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return {"ok": False, "reason": "no_contours"}
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)
    best = None
    for c in cnts:
        area = float(cv2.contourArea(c))
        if area >= float(w * h) * 0.08:
            best = c
            break
    if best is None:
        return {"ok": False, "reason": "no_usable_contour"}
    peri = float(cv2.arcLength(best, True))
    approx = cv2.approxPolyDP(best, 0.025 * peri, True)
    pts = []
    for p in approx:
        px, py = int(p[0][0]), int(p[0][1])
        pts.append({"x": int(px + x0 + mon_left), "y": int(py + y0 + mon_top)})
    if len(pts) < 4:
        return {"ok": False, "reason": "contour_polygon_too_few_points"}
    if len(pts) > 10:
        step = max(1, int(len(pts) / 8))
        pts = [pts[i] for i in range(0, len(pts), step)][:8]
    pts = _order_clockwise(pts)
    # Rotate start to strongest 90-degree-like corner.
    def corner_score(idx: int) -> float:
        a = pts[idx - 1]
        b = pts[idx]
        c = pts[(idx + 1) % len(pts)]
        v1 = (a["x"] - b["x"], a["y"] - b["y"])
        v2 = (c["x"] - b["x"], c["y"] - b["y"])
        n1 = math.hypot(v1[0], v1[1]) or 1.0
        n2 = math.hypot(v2[0], v2[1]) or 1.0
        cosv = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        ang = abs(math.degrees(math.acos(cosv)))
        return abs(90.0 - ang)
    start_idx = min(range(len(pts)), key=corner_score)
    pts = pts[start_idx:] + pts[:start_idx]
    conf = min(0.95, 0.45 + (0.03 * len(pts)) + (0.2 * min(1.0, preread_confidence)))
    return {"ok": True, "ordered_points": pts, "confidence": round(conf, 3), "point_count": len(pts)}


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


def _load_teacher_targets(path: str) -> List[Dict[str, Any]]:
    raw = str(path or "").strip()
    if not raw:
        return []
    p = pathlib.Path(raw)
    if not p.exists() or p.is_dir():
        return []
    payload = read_json(p)
    targets = payload.get("teacher_targets", []) if isinstance(payload, dict) else []
    return targets if isinstance(targets, list) else []


def _distance(a: Dict[str, int], b: Dict[str, int]) -> float:
    return math.hypot(float(a.get("x", 0) - b.get("x", 0)), float(a.get("y", 0) - b.get("y", 0)))


def _poly_area(points: List[Dict[str, int]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i in range(len(points)):
        x1, y1 = float(points[i].get("x", 0)), float(points[i].get("y", 0))
        x2, y2 = float(points[(i + 1) % len(points)].get("x", 0)), float(points[(i + 1) % len(points)].get("y", 0))
        total += (x1 * y2) - (x2 * y1)
    return abs(total) * 0.5


def _poly_signed_area(points: List[Dict[str, int]]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i in range(len(points)):
        x1, y1 = float(points[i].get("x", 0)), float(points[i].get("y", 0))
        x2, y2 = float(points[(i + 1) % len(points)].get("x", 0)), float(points[(i + 1) % len(points)].get("y", 0))
        total += (x1 * y2) - (x2 * y1)
    return total * 0.5


def _hausdorff(a_points: List[Dict[str, int]], b_points: List[Dict[str, int]]) -> float:
    if not a_points or not b_points:
        return 1e9
    def _directed(u: List[Dict[str, int]], v: List[Dict[str, int]]) -> float:
        mx = 0.0
        for p in u:
            mn = min(_distance(p, q) for q in v)
            mx = max(mx, mn)
        return mx
    return max(_directed(a_points, b_points), _directed(b_points, a_points))


def _segments_intersect(a1: Dict[str, int], a2: Dict[str, int], b1: Dict[str, int], b2: Dict[str, int]) -> bool:
    def _ccw(p1: Dict[str, int], p2: Dict[str, int], p3: Dict[str, int]) -> bool:
        return (p3["y"] - p1["y"]) * (p2["x"] - p1["x"]) > (p2["y"] - p1["y"]) * (p3["x"] - p1["x"])
    return _ccw(a1, b1, b2) != _ccw(a2, b1, b2) and _ccw(a1, a2, b1) != _ccw(a1, a2, b2)


def _self_intersects(points: List[Dict[str, int]]) -> bool:
    if len(points) < 4:
        return False
    edges = [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
    for i, (a1, a2) in enumerate(edges):
        for j, (b1, b2) in enumerate(edges):
            if abs(i - j) <= 1 or (i == 0 and j == len(edges) - 1) or (j == 0 and i == len(edges) - 1):
                continue
            if _segments_intersect(a1, a2, b1, b2):
                return True
    return False


def _plan_teacher_path_from_start(
    user_start: Dict[str, int],
    teacher_targets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not teacher_targets:
        return {"ok": False, "reason": "no_teacher_targets"}
    chosen: Dict[str, Any] = {}
    best_dist = 1e18
    for t in teacher_targets:
        center = t.get("center_global", {}) if isinstance(t, dict) else {}
        if not isinstance(center, dict):
            continue
        d = _distance(user_start, {"x": int(center.get("x", 0) or 0), "y": int(center.get("y", 0) or 0)})
        if d < best_dist:
            best_dist = d
            chosen = t
    if not chosen:
        return {"ok": False, "reason": "no_nearest_teacher_target"}
    polygon = chosen.get("polygon_points", []) if isinstance(chosen.get("polygon_points", []), list) else []
    if len(polygon) < 3:
        return {"ok": False, "reason": "teacher_polygon_missing"}
    # Rotate to nearest vertex from user-provided start.
    nearest_idx = 0
    nearest_dist = 1e18
    for i, p in enumerate(polygon):
        if not isinstance(p, dict):
            continue
        d = _distance(user_start, {"x": int(p.get("x", 0)), "y": int(p.get("y", 0))})
        if d < nearest_dist:
            nearest_dist = d
            nearest_idx = i
    ordered = []
    for k in range(len(polygon)):
        ordered.append(polygon[(nearest_idx + k) % len(polygon)])
    signed = _poly_signed_area(ordered)
    winding = "clockwise" if signed < 0 else "counterclockwise"
    return {
        "ok": True,
        "teacher_target_id": str(chosen.get("id", "")),
        "ordered_points": [{"x": int(p.get("x", 0)), "y": int(p.get("y", 0))} for p in ordered],
        "start_vertex_index": int(nearest_idx),
        "winding": winding,
        "start_distance_px": round(float(nearest_dist), 3),
    }


def _compute_geometry_match(stroke_points: List[Dict[str, int]], teacher_targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not stroke_points or not teacher_targets:
        return {
            "score": 0.0,
            "ok": False,
            "reason": "missing_stroke_or_teacher_targets",
            "teacher_target_id": "",
        }
    probe = stroke_points[-1]
    chosen: Dict[str, Any] = {}
    chosen_dist = 1e18
    for t in teacher_targets:
        center = t.get("center_global", {}) if isinstance(t, dict) else {}
        if not isinstance(center, dict):
            continue
        d = _distance(probe, {"x": int(center.get("x", 0) or 0), "y": int(center.get("y", 0) or 0)})
        if d < chosen_dist:
            chosen_dist = d
            chosen = t
    if not chosen:
        return {"score": 0.0, "ok": False, "reason": "no_teacher_target_selected", "teacher_target_id": ""}
    polygon = chosen.get("polygon_points", []) if isinstance(chosen.get("polygon_points", []), list) else []
    if not polygon:
        return {"score": 0.0, "ok": False, "reason": "teacher_target_missing_polygon", "teacher_target_id": str(chosen.get("id", ""))}
    stroke_min = []
    normalized_stroke = [{"x": int(p.get("x", 0)), "y": int(p.get("y", 0))} for p in stroke_points]
    normalized_poly = [{"x": int(p.get("x", 0)), "y": int(p.get("y", 0))} for p in polygon if isinstance(p, dict)]
    for sp in normalized_stroke:
        best = 1e18
        for pp in normalized_poly:
            best = min(best, _distance(sp, pp))
        if best < 1e18:
            stroke_min.append(best)
    avg_min = float(sum(stroke_min) / max(1, len(stroke_min))) if stroke_min else 1e9
    bbox = chosen.get("bbox_global", {}) if isinstance(chosen.get("bbox_global", {}), dict) else {}
    bw = max(1.0, float(bbox.get("w", 1) or 1))
    bh = max(1.0, float(bbox.get("h", 1) or 1))
    diag = math.hypot(bw, bh)
    norm = avg_min / max(1.0, diag)
    hausdorff = _hausdorff(normalized_stroke, normalized_poly) / max(1.0, diag)
    stroke_area = _poly_area(normalized_stroke)
    target_area = _poly_area(normalized_poly)
    area_delta = abs(stroke_area - target_area) / max(1.0, target_area)
    stroke_winding = "clockwise" if _poly_signed_area(normalized_stroke) < 0 else "counterclockwise"
    target_winding = "clockwise" if _poly_signed_area(normalized_poly) < 0 else "counterclockwise"
    winding_mismatch = stroke_winding != target_winding
    self_intersection = _self_intersects(normalized_stroke)
    score = max(0.0, min(1.0, 1.0 - ((0.45 * norm) + (0.4 * hausdorff) + (0.15 * min(1.0, area_delta)))))
    fail_reason = "ok"
    if self_intersection:
        fail_reason = "self_intersecting"
    elif winding_mismatch:
        fail_reason = "winding_wrong"
    elif area_delta > 0.03:
        fail_reason = "area_delta_gt_3pct"
    elif hausdorff > 0.45:
        fail_reason = "vertex_drift"
    elif score < 0.55:
        fail_reason = "geometry_below_threshold"
    return {
        "score": round(float(score), 4),
        "ok": bool(score >= 0.55 and fail_reason == "ok"),
        "reason": fail_reason,
        "teacher_target_id": str(chosen.get("id", "")),
        "teacher_target": chosen,
        "avg_min_distance_px": round(avg_min, 3),
        "diag_px": round(diag, 3),
        "hausdorff_norm": round(float(hausdorff), 4),
        "area_delta": round(float(area_delta), 4),
        "stroke_winding": stroke_winding,
        "target_winding": target_winding,
        "self_intersecting": bool(self_intersection),
    }


def _write_evidence_pack(
    out_dir: pathlib.Path,
    teacher_targets: List[Dict[str, Any]],
    stroke_points: List[Dict[str, int]],
    geometry: Dict[str, Any],
    phase_timeline: List[Dict[str, Any]] | None = None,
) -> Dict[str, str]:
    ev_dir = out_dir / "evidence_pack"
    ev_dir.mkdir(parents=True, exist_ok=True)
    before = out_dir / "before_attempt.png"
    after = out_dir / "after_left_blank_click.png"
    selected_condition_proof = ev_dir / "selected_condition_proof.png"
    if before.exists():
        selected_condition_proof.write_bytes(before.read_bytes())
    teacher_overlay = ev_dir / "boost_teacher_overlay.png"
    attempt_overlay = ev_dir / "attempt_overlay.png"
    mismatch_overlay = ev_dir / "mismatch_overlay.png"
    mismatch_heatmap = ev_dir / "mismatch_heatmap.png"
    phase_timeline_json = ev_dir / "phase_timeline.json"
    if before.exists():
        img = cv2.imread(str(before))
        if img is not None:
            for t in teacher_targets:
                poly = t.get("polygon_points", []) if isinstance(t, dict) else []
                pts = np.array([[int(p.get("x", 0)), int(p.get("y", 0))] for p in poly if isinstance(p, dict)], dtype=np.int32)
                if len(pts) >= 3:
                    cv2.polylines(img, [pts], isClosed=True, color=(0, 200, 255), thickness=2)
            cv2.imwrite(str(teacher_overlay), img)
    if after.exists():
        img2 = cv2.imread(str(after))
        if img2 is not None:
            if stroke_points:
                pts2 = np.array([[int(p.get("x", 0)), int(p.get("y", 0))] for p in stroke_points], dtype=np.int32)
                if len(pts2) >= 2:
                    cv2.polylines(img2, [pts2], isClosed=False, color=(0, 255, 0), thickness=2)
                for p in stroke_points:
                    cv2.circle(img2, (int(p.get("x", 0)), int(p.get("y", 0))), 4, (0, 255, 0), -1)
            cv2.imwrite(str(attempt_overlay), img2)
            if not bool(geometry.get("ok", False)):
                cv2.putText(
                    img2,
                    f"geometry_fail score={float(geometry.get('score', 0.0)):.3f}",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.imwrite(str(mismatch_overlay), img2)
    if teacher_overlay.exists() and attempt_overlay.exists():
        timg = cv2.imread(str(teacher_overlay), cv2.IMREAD_COLOR)
        aimg = cv2.imread(str(attempt_overlay), cv2.IMREAD_COLOR)
        if timg is not None and aimg is not None:
            if timg.shape != aimg.shape:
                aimg = cv2.resize(aimg, (timg.shape[1], timg.shape[0]), interpolation=cv2.INTER_LINEAR)
            diff = cv2.absdiff(timg, aimg)
            heat = cv2.applyColorMap(cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY), cv2.COLORMAP_JET)
            cv2.imwrite(str(mismatch_heatmap), heat)
    write_json(phase_timeline_json, {"phases": phase_timeline or []})
    return {
        "selected_condition_proof": str(selected_condition_proof),
        "boost_teacher_overlay": str(teacher_overlay),
        "attempt_overlay": str(attempt_overlay),
        "mismatch_overlay": str(mismatch_overlay),
        "mismatch_heatmap": str(mismatch_heatmap),
        "phase_timeline_json": str(phase_timeline_json),
    }


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
        default="ceiling,gwb",
        help="Preferred condition keywords (comma-separated).",
    )
    parser.add_argument(
        "--expected-condition-row-index",
        type=int,
        default=-1,
        help="If set >=0, require selected condition row index to match Boost-used row index.",
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
    parser.add_argument("--teacher-targets-json", default="")
    parser.add_argument("--geometry-score-threshold", type=float, default=0.55)
    parser.add_argument("--user-start-x", type=int, default=0, help="Optional user-provided start point x.")
    parser.add_argument("--user-start-y", type=int, default=0, help="Optional user-provided start point y.")
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
    parser.add_argument("--finish-taxonomy-json", default="scripts/ost_finish_taxonomy.json")
    parser.add_argument("--finish-index-json", default="")
    parser.add_argument("--ocr-config", default="scripts/ocr_engine.config.json")
    parser.add_argument("--enforce-area-style", action="store_true")
    parser.add_argument("--enforce-condition-names", default="ceiling,gwb")
    parser.add_argument("--balanced-latency-budget-ms", type=int, default=28000)
    args = parser.parse_args()

    out_dir = pathlib.Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    phase_timeline: List[Dict[str, Any]] = []
    t_run_start = time.perf_counter()
    t_phase_last = t_run_start

    def mark_phase(phase: str, **extra: Any) -> None:
        nonlocal t_phase_last
        now = time.perf_counter()
        row = {
            "phase": phase,
            "ts": now_tag(),
            "elapsed_ms": int((now - t_run_start) * 1000),
            "delta_ms": int((now - t_phase_last) * 1000),
        }
        if extra:
            row.update(extra)
        phase_timeline.append(row)
        t_phase_last = now

    mark_phase("start")
    setup_cfg = read_json(pathlib.Path(args.setup_config))
    anchors = setup_cfg.get("anchors", {}) if isinstance(setup_cfg, dict) else {}
    row_anchor_name = "conditions_first_row" if args.condition_row == "first" else "conditions_second_row"
    row_anchor = anchors.get(row_anchor_name, {})
    if not row_anchor:
        print(f"missing_anchor={row_anchor_name}")
        return 2

    global ACTIVE_OST_WINDOW_RECT
    focused = focus_window(str(args.window_title_contains))
    ACTIVE_OST_WINDOW_RECT = get_window_rect(str(args.window_title_contains))
    time.sleep(0.2)
    pre_unblock_actions = unblock_ui_state()
    pre_clear_actions = undo_bad_work(max(0, int(args.pre_clear_count)))
    mark_phase("pre_clear_done", actions=len(pre_clear_actions))
    screenshot_monitor(int(args.monitor_index), out_dir / "before_attempt.png")
    teacher_targets = _load_teacher_targets(str(args.teacher_targets_json))
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
        selection_mode = (
            "locked_row_by_name"
            if (bool(args.enforce_area_style) or int(args.expected_condition_row_index) >= 0)
            else "active_qty_non_unassigned"
        )
        sel = run_condition_selector(
            setup_config=str(args.setup_config),
            condition_row=str(args.condition_row),
            monitor_index=int(args.monitor_index),
            out_dir=out_dir,
            window_title_contains=str(args.window_title_contains),
            prefer_contains=str(args.condition_prefer_contains),
            target_row_index=int(args.expected_condition_row_index),
            selection_mode=selection_mode,
        )
        verdict = evaluate_condition_selection(
            sel,
            min_qty=float(args.condition_min_qty),
            preferred_keywords=preferred_keywords,
            expected_row_index=int(args.expected_condition_row_index),
        )
        if (
            not bool(verdict.get("verified", False))
            and selection_mode == "locked_row_by_name"
            and str((sel.get("selection", {}) if isinstance(sel.get("selection", {}), dict) else {}).get("reason", "") or "")
            == "no_locked_ceiling_or_gwb_row"
        ):
            # Fallback to active-qty lock when name-lock OCR is too noisy.
            sel_fallback = run_condition_selector(
                setup_config=str(args.setup_config),
                condition_row=str(args.condition_row),
                monitor_index=int(args.monitor_index),
                out_dir=out_dir,
                window_title_contains=str(args.window_title_contains),
                prefer_contains=str(args.condition_prefer_contains),
                target_row_index=int(args.expected_condition_row_index),
                selection_mode="active_qty_non_unassigned",
            )
            verdict_fallback = evaluate_condition_selection(
                sel_fallback,
                min_qty=float(args.condition_min_qty),
                preferred_keywords=preferred_keywords,
                expected_row_index=int(args.expected_condition_row_index),
            )
            condition_selection_attempts.append(
                {
                    "selection_mode": "active_qty_non_unassigned_fallback",
                    "selection": sel_fallback,
                    "verification": verdict_fallback,
                }
            )
            if bool(verdict_fallback.get("verified", False)):
                sel = sel_fallback
                verdict = verdict_fallback
        condition_selection_attempts.append({"selection": sel, "verification": verdict})
        condition_selection = sel
        condition_verification = verdict
        if bool(verdict.get("verified", False)):
            break
        time.sleep(0.45)
    mark_phase("condition_lock_done", verified=bool(condition_verification.get("verified", False)))
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
    click_pt = (
        (condition_selection.get("selection", {}) if isinstance(condition_selection.get("selection", {}), dict) else {})
        .get("click_point", {})
    )
    cx = int(click_pt.get("x", 0) or 0) if isinstance(click_pt, dict) else 0
    cy = int(click_pt.get("y", 0) or 0) if isinstance(click_pt, dict) else 0
    condition_style_info: Dict[str, Any] = {}
    condition_style = ""
    if cx > 0 and cy > 0:
        condition_style_info = inspect_condition_style(
            x=cx,
            y=cy,
            monitor_index=int(args.monitor_index),
            out_dir=out_dir,
            window_title_contains=str(args.window_title_contains),
        )
        condition_style = str(
            (
                condition_style_info.get("inspection", {})
                if isinstance(condition_style_info.get("inspection", {}), dict)
                else {}
            ).get("style", "")
            or ""
        ).strip().lower()
    if condition_style not in {"area", "linear", "count"}:
        condition_style = "area"
    selection_payload = (
        condition_selection.get("selection", {})
        if isinstance(condition_selection.get("selection", {}), dict)
        else {}
    )
    active_condition_name = str(selection_payload.get("active_condition_name", "") or "").strip()
    if not active_condition_name:
        active_condition_name = str(selection_payload.get("selected_condition_keyword", "") or "").strip()
    if not active_condition_name:
        active_condition_name = str(selection_payload.get("selected_condition_text", "") or "").strip()
    finish_inference = infer_finish_context(
        condition_name=active_condition_name,
        condition_style=condition_style,
        taxonomy_path=str(args.finish_taxonomy_json),
        finish_index_json=str(args.finish_index_json),
    )
    low_conf_fallback = bool(float(finish_inference.get("confidence", 0.0) or 0.0) < 0.45)
    style_inspection_ok = bool(
        (
            (
                condition_style_info.get("inspection", {})
                if isinstance(condition_style_info.get("inspection", {}), dict)
                else {}
            ).get("ok", False)
        )
    )
    allowed_conditions = [t.strip().lower() for t in str(args.enforce_condition_names or "").split(",") if t.strip()]
    active_low = active_condition_name.lower()
    condition_allowed = bool(any(k in active_low for k in allowed_conditions)) if allowed_conditions else True
    # If style dialog OCR fails but condition lock is strong and name is allowed,
    # allow the normalized fallback style ("area") to proceed.
    allow_style_fallback = bool(
        bool(args.enforce_area_style)
        and (not style_inspection_ok)
        and str(condition_style).lower() == "area"
        and condition_allowed
        and bool(condition_verification.get("verified", False))
        and float(condition_verification.get("lock_confidence", 0.0) or 0.0) >= 0.8
    )
    if bool(args.enforce_area_style) and (not allow_style_fallback) and (
        not style_inspection_ok or str(condition_style).lower() != "area"
    ):
        result = {
            "ok": False,
            "timestamp": now_tag(),
            "focused_window": focused,
            "condition_row": args.condition_row,
            "condition_selection": condition_selection,
            "condition_verification": condition_verification,
            "condition_style": condition_style,
            "style_inspection_ok": style_inspection_ok,
            "style_fallback_applied": allow_style_fallback,
            "active_condition_name": active_condition_name,
            "reason": "style_not_area_enforced",
        }
        write_json(out_dir / "left_blank_takeoff_attempt.json", result)
        print(f"left_blank_takeoff_attempt={out_dir / 'left_blank_takeoff_attempt.json'}")
        return 4
    if not condition_allowed:
        result = {
            "ok": False,
            "timestamp": now_tag(),
            "focused_window": focused,
            "condition_row": args.condition_row,
            "condition_selection": condition_selection,
            "condition_verification": condition_verification,
            "condition_style": condition_style,
            "active_condition_name": active_condition_name,
            "allowed_conditions": allowed_conditions,
            "reason": "condition_name_not_allowed",
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
    mark_phase("grouping_before_done")
    monitor_img = screenshot_monitor_np(int(args.monitor_index))
    plan_preread = _run_glm_plan_preread(
        image_bgr=monitor_img,
        payload=payload,
        ocr_config_path=str(args.ocr_config),
        condition_name=active_condition_name,
    )
    mark_phase(
        "glm_preread_done",
        ocr_duration_ms=int(plan_preread.get("duration_ms", 0) or 0),
        ocr_ok=bool(plan_preread.get("ok", False)),
        ocr_engine=str(plan_preread.get("engine_used", "")),
        preread_confidence=float(plan_preread.get("confidence", 0.0) or 0.0),
    )
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
    mark_phase("grouping_verify_done")
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
    mark_phase("attempt_start")

    pre_click_source = verify_payload if isinstance(verify_payload, dict) and verify_payload else payload
    stroke_points: List[Dict[str, int]] = []
    planned_path: Dict[str, Any] = {}
    user_start_point = {"x": int(args.user_start_x), "y": int(args.user_start_y)}
    if int(args.user_start_x) > 0 and int(args.user_start_y) > 0 and teacher_targets:
        planned_path = _plan_teacher_path_from_start(user_start=user_start_point, teacher_targets=teacher_targets)
        if bool(planned_path.get("ok", False)):
            planned_points = planned_path.get("ordered_points", []) if isinstance(planned_path.get("ordered_points", []), list) else []
            click_points = [{"x": int(p.get("x", 0)), "y": int(p.get("y", 0))} for p in planned_points if isinstance(p, dict)]
            if len(click_points) >= 2:
                for i, p in enumerate(click_points):
                    click_xy(int(p["x"]), int(p["y"]), double=(i == len(click_points) - 1))
                    time.sleep(0.25)
                stroke_points = click_points
    if not stroke_points:
        behavior_style = condition_style
        # Confidence-gated fallback keeps behavior conservative when finish inference is weak.
        if low_conf_fallback and behavior_style == "count":
            behavior_style = "linear"
        if args.attempt_style == "polyline2":
            behavior_style = "linear"
        elif args.attempt_style == "point":
            behavior_style = "count"
        if behavior_style == "area":
            elapsed_ms = int((time.perf_counter() - t_run_start) * 1000)
            conservative_mode = bool(elapsed_ms > int(args.balanced_latency_budget_ms))
            planner = (
                {"ok": False, "reason": "conservative_mode"}
                if conservative_mode
                else _plan_area_polygon_v2(
                    image_bgr=monitor_img,
                    payload=pre_click_source,
                    candidate=left_target_candidate,
                    preread_confidence=float(plan_preread.get("confidence", 0.0) or 0.0),
                )
            )
            if bool(planner.get("ok", False)):
                poly_points = planner.get("ordered_points", []) if isinstance(planner.get("ordered_points", []), list) else []
                for i, p in enumerate(poly_points):
                    if not isinstance(p, dict):
                        continue
                    click_xy(int(p.get("x", 0)), int(p.get("y", 0)), double=(i == len(poly_points) - 1))
                    time.sleep(0.24)
                stroke_points = [{"x": int(p.get("x", 0)), "y": int(p.get("y", 0))} for p in poly_points if isinstance(p, dict)]
            else:
                gb = _bbox_global_from_candidate(pre_click_source, left_target_candidate)
                gx, gy, gw, gh = gb["x"], gb["y"], gb["w"], gb["h"]
                if gw > 48 and gh > 48:
                    inset = max(2, int(min(gw, gh) * 0.03))
                    p1 = {"x": int(gx + inset), "y": int(gy + inset)}
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
        elif behavior_style == "linear":
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
    mark_phase("attempt_clicks_done", points=len(stroke_points))

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
    mark_phase("grouping_after_done")
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
    geometry_match = _compute_geometry_match(stroke_points=stroke_points, teacher_targets=teacher_targets)
    geometry_ok = bool(geometry_match.get("score", 0.0) >= float(args.geometry_score_threshold))
    is_match = (post_score >= float(args.match_score_threshold)) and (
        post_classifier_conf >= float(args.classifier_confidence_threshold)
    ) and bool(expected_item_type_match) and bool(geometry_ok)
    bad_work = not is_match
    cleanup_actions: List[Dict[str, Any]] = []
    if bad_work and (not bool(args.no_cleanup_bad_work)):
        cleanup_actions = undo_bad_work(int(args.cleanup_undo_count))
        screenshot_monitor(int(args.monitor_index), out_dir / "after_cleanup.png")
    mark_phase("cleanup_done", cleanup_ran=bool(cleanup_actions))
    evidence_pack = _write_evidence_pack(
        out_dir=out_dir,
        teacher_targets=teacher_targets,
        stroke_points=stroke_points,
        geometry=geometry_match,
        phase_timeline=phase_timeline,
    )

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
        "condition_style": condition_style,
        "condition_style_inspection": condition_style_info,
        "condition_style_enforced_area": bool(args.enforce_area_style),
        "condition_name_allowed": bool(condition_allowed),
        "active_condition_name": active_condition_name,
        "allowed_condition_names": allowed_conditions,
        "finish_inference": finish_inference,
        "finish_inference_fallback": {
            "applied": low_conf_fallback,
            "threshold": 0.45,
        },
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
            "plan_preread": plan_preread,
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
            "geometry_score": float(geometry_match.get("score", 0.0) or 0.0),
            "geometry_threshold": float(args.geometry_score_threshold),
            "geometry_ok": bool(geometry_ok),
            "geometry_reason": str(geometry_match.get("reason", "") or ""),
            "teacher_target_id": str(geometry_match.get("teacher_target_id", "") or ""),
            "finish_trade": str(finish_inference.get("inferred_trade", "") or ""),
            "finish_confidence": float(finish_inference.get("confidence", 0.0) or 0.0),
            "is_match": is_match,
            "bad_work": bad_work,
        },
        "geometry_match": geometry_match,
        "teacher_targets_json": str(args.teacher_targets_json or ""),
        "teacher_targets_count": len(teacher_targets),
        "planned_path": planned_path,
        "user_start_point": user_start_point,
        "phase_timeline": phase_timeline,
        "runtime_ms": int((time.perf_counter() - t_run_start) * 1000),
        "balanced_policy": {
            "latency_budget_ms": int(args.balanced_latency_budget_ms),
            "conservative_mode": bool(int((time.perf_counter() - t_run_start) * 1000) > int(args.balanced_latency_budget_ms)),
        },
        "evidence_pack": evidence_pack,
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
