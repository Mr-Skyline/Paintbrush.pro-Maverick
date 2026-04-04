#!/usr/bin/env python3
"""
Select an OST condition row, with OCR-based active-condition detection.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import time
from typing import Any, Dict, List, Tuple

import mss
import numpy as np
import pyautogui
import pytesseract
import cv2

from mouse_takeover_guard import install_pyautogui_takeover_guard
from ocr_engine import create_ocr_engine, OcrEngine
from ost_window_guard import (
    clamp_point_to_active_window,
    set_active_window_rect,
)

try:
    import pygetwindow as gw  # type: ignore
except Exception:  # pragma: no cover
    gw = None

install_pyautogui_takeover_guard(pyautogui)


def read_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def monitor_rect(monitor_index: int) -> Dict[str, int]:
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}.")
        mon = mons[monitor_index]
        return {
            "left": int(mon["left"]),
            "top": int(mon["top"]),
            "width": int(mon["width"]),
            "height": int(mon["height"]),
        }


def clamp_point_to_safe_monitor_zone(
    x: int,
    y: int,
    monitor: Dict[str, int],
    bottom_margin_px: int = 120,
    side_margin_px: int = 8,
) -> Tuple[int, int, bool]:
    left = int(monitor["left"])
    top = int(monitor["top"])
    right = left + int(monitor["width"])
    bottom = top + int(monitor["height"])
    safe_x = max(left + side_margin_px, min(int(x), right - side_margin_px))
    safe_y = max(top + side_margin_px, min(int(y), bottom - max(40, bottom_margin_px)))
    changed = (safe_x != int(x)) or (safe_y != int(y))
    return safe_x, safe_y, changed


def screenshot_monitor_np(monitor_index: int) -> np.ndarray:
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 1 or monitor_index >= len(mons):
            raise ValueError(f"Invalid monitor index {monitor_index}.")
        shot = sct.grab(mons[monitor_index])
        return np.array(shot)[:, :, :3]


def _safe_float(token: str) -> float:
    raw = str(token or "").strip().replace(",", "")
    try:
        return float(raw)
    except Exception:
        return 0.0


def _qty_positive(text: str) -> Tuple[bool, float]:
    nums = re.findall(r"\d+(?:\.\d+)?", text or "")
    vals = [_safe_float(n) for n in nums]
    vals = [v for v in vals if v > 0.0]
    if not vals:
        return False, 0.0
    return True, max(vals)


def _best_qty_from_texts(texts: List[str]) -> Tuple[bool, float, str]:
    best_val = 0.0
    best_txt = ""
    found = False
    for t in texts:
        ok, val = _qty_positive(t)
        if ok and val > best_val:
            best_val = val
            best_txt = str(t or "")
            found = True
    return found, best_val, best_txt


def _parse_preferred_keywords(raw: str) -> List[str]:
    toks = [t.strip().lower() for t in str(raw or "").split(",")]
    return [t for t in toks if t]


def _canonical_condition_name(text: str) -> str:
    norm = _normalize_for_match(text)
    if not norm:
        return ""
    # Keep mapping constrained to the two allowed conditions only.
    if norm in {"ceiling", "ceilings", "ceillin", "cei1ing", "ce1ling", "ceiling1"}:
        return "ceiling"
    if "ceiling" in norm or "celing" in norm or "celings" in norm or "ceilng" in norm:
        return "ceiling"
    if norm in {"gwb", "gypsumwallboard", "gypsumboard", "gypboard"}:
        return "gwb"
    if "gwb" in norm or "gypsum" in norm:
        return "gwb"
    # Exact token fallback (no fuzzy unrelated matching).
    low = str(text or "").lower()
    if re.search(r"\bceil(?:ing|ings)\b", low):
        return "ceiling"
    if re.search(r"\b(gwb|gypsum\s*wall\s*board|gypsum\s*board)\b", low):
        return "gwb"
    return ""


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _find_keyword(text: str, preferred_keywords: List[str]) -> str:
    if not preferred_keywords:
        return ""
    canonical = _canonical_condition_name(text)
    if canonical and canonical in preferred_keywords:
        return canonical
    norm = _normalize_for_match(text)
    for kw in preferred_keywords:
        nkw = _normalize_for_match(kw)
        if nkw and nkw in norm:
            return kw
    return ""


def _looks_like_folder_or_header_row(text: str) -> bool:
    low = str(text or "").lower()
    if not low:
        return True
    # Guard against clicking the "Condition/Vertical Groups" container/header row.
    header_tokens = ("vertical group", "vertical groups", "group folder", "condition folder")
    return any(tok in low for tok in header_tokens)


def _choose_best_name_text(candidates: List[str], preferred_keywords: List[str]) -> Tuple[str, str]:
    best_txt = ""
    best_kw = ""
    best_score = -1e9
    for txt in candidates:
        t = str(txt or "").strip()
        if not t:
            continue
        kw = _find_keyword(t, preferred_keywords)
        alpha = len(re.findall(r"[A-Za-z]", t))
        score = float(alpha + (300 if kw else 0))
        if score > best_score:
            best_score = score
            best_txt = t
            best_kw = kw
    return best_txt, best_kw


def detect_active_condition_row(
    cfg: Dict[str, Any],
    monitor_index: int,
    ocr: OcrEngine,
    preferred_keywords: List[str] | None = None,
) -> Dict[str, Any]:
    anchors = cfg.get("anchors", {}) if isinstance(cfg, dict) else {}
    a1 = anchors.get("conditions_first_row", {}) if isinstance(anchors, dict) else {}
    a2 = anchors.get("conditions_second_row", {}) if isinstance(anchors, dict) else {}
    if not (isinstance(a1, dict) and isinstance(a2, dict) and "x" in a1 and "y" in a1 and "x" in a2 and "y" in a2):
        return {"ok": False, "reason": "missing_condition_anchors"}

    mon = monitor_rect(monitor_index)
    img = screenshot_monitor_np(monitor_index)
    ax = int(a1["x"])
    ay = int(a1["y"])
    by = int(a2["y"])
    row_h = max(18, abs(by - ay))
    lx = ax - mon["left"]
    ly = ay - mon["top"]
    x0 = max(0, lx - 70)
    x1 = min(mon["width"], lx + 1120)
    y0 = max(0, ly - int(row_h * 0.45))
    y1 = min(mon["height"], ly + (row_h * 18))
    if x1 <= x0 or y1 <= y0:
        return {"ok": False, "reason": "invalid_conditions_roi"}

    roi = img[y0:y1, x0:x1]
    candidates: List[Dict[str, Any]] = []
    debug_rows: List[Dict[str, Any]] = []
    preferred_keywords = preferred_keywords or []
    ocr_calls: List[Dict[str, Any]] = []
    fastscan_tesseract = str(os.environ.get("MAVERICK_OCR_FASTSCAN_TESSERACT", "1")).strip().lower() not in {"0", "false", "no"}
    glmo_name_assist = str(os.environ.get("MAVERICK_CONDITION_NAME_GLM_ASSIST", "1")).strip().lower() not in {"0", "false", "no"}
    # Scan expected row bands and OCR name + quantity columns separately.
    panel_w = x1 - x0
    name_col_x0 = 0
    name_col_x1 = max(name_col_x0 + 60, panel_w - 260)
    for ridx in range(0, 16):
        ry0 = int(ridx * row_h)
        ry1 = min(roi.shape[0], int((ridx + 1) * row_h))
        if ry1 <= ry0 + 8:
            continue
        row_img = roi[ry0:ry1, :]
        gray = cv2.cvtColor(row_img, cv2.COLOR_BGR2GRAY)
        name_img = gray[:, name_col_x0:name_col_x1]
        qty_variants = []
        for span in (220, 300, 380):
            qx0 = max(0, panel_w - span)
            qx1 = panel_w
            qty_variants.append(gray[:, qx0:qx1])

        name_thr = cv2.adaptiveThreshold(name_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
        qty_texts: List[str] = []
        for qimg in qty_variants:
            qthr = cv2.adaptiveThreshold(qimg, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
            if fastscan_tesseract:
                qtxt = pytesseract.image_to_string(
                    qthr,
                    config="--psm 7 -c tessedit_char_whitelist=0123456789.,",
                ).strip()
                ocr_calls.append({"field": "qty", "engine_used": "tesseract_fastscan", "fallback_used": False})
            else:
                qty_res = ocr.ocr_text(
                    qthr,
                    context="OST conditions quantity OCR",
                    psm=7,
                    whitelist="0123456789.,",
                )
                qtxt = str(qty_res.get("text", "") or "").strip()
                ocr_calls.append(
                    {
                        "field": "qty",
                        "engine_used": str(qty_res.get("engine_used", "")),
                        "fallback_used": bool(qty_res.get("fallback_used", False)),
                    }
                )
            if qtxt:
                qty_texts.append(qtxt)
        has_qty, qty, qty_txt = _best_qty_from_texts(qty_texts)
        if not has_qty or qty <= 0.0:
            continue
        name_text_candidates: List[str] = []
        if fastscan_tesseract:
            try:
                name_text_candidates.append(pytesseract.image_to_string(name_img, config="--psm 6").strip())
                name_text_candidates.append(pytesseract.image_to_string(name_thr, config="--psm 6").strip())
                up = cv2.resize(name_thr, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC)
                name_text_candidates.append(pytesseract.image_to_string(up, config="--psm 7").strip())
            except Exception:
                pass
            ocr_calls.append({"field": "name", "engine_used": "tesseract_fastscan_multi", "fallback_used": False})
        else:
            name_res = ocr.ocr_text(name_thr, context="OST conditions row name OCR", psm=6)
            name_text_candidates.append(str(name_res.get("text", "") or "").strip())
            ocr_calls.append(
                {
                    "field": "name",
                    "engine_used": str(name_res.get("engine_used", "")),
                    "fallback_used": bool(name_res.get("fallback_used", False)),
                }
            )
        name_txt, matched_keyword = _choose_best_name_text(name_text_candidates, preferred_keywords)
        if glmo_name_assist and preferred_keywords and not matched_keyword:
            name_res2 = ocr.ocr_text(
                row_img,
                context="Read only the condition name from this row. Return exact text.",
                psm=6,
            )
            name_txt2 = str(name_res2.get("text", "") or "").strip()
            ocr_calls.append(
                {
                    "field": "name_assist",
                    "engine_used": str(name_res2.get("engine_used", "")),
                    "fallback_used": bool(name_res2.get("fallback_used", False)),
                }
            )
            name_txt, matched_keyword = _choose_best_name_text([name_txt, name_txt2], preferred_keywords)
        lower = name_txt.lower()
        if ridx == 0 and _looks_like_folder_or_header_row(lower):
            continue
        if "unassigned" in lower or "(unassigned)" in lower:
            continue
        alpha_count = len(re.findall(r"[A-Za-z]", name_txt))
        if alpha_count < 2:
            continue
        y_center = int((ry0 + ry1) / 2.0)
        # Prefer rows near top when multiple conditions are active.
        if preferred_keywords and not matched_keyword:
            continue
        row_position_score = max(0.0, 1.0 - (float(ridx) / 16.0))
        qty_score = min(1.0, float(qty) / 100.0)
        keyword_score = 1.0 if matched_keyword in {"ceiling", "gwb"} else 0.0
        confidence = (0.62 * keyword_score) + (0.23 * qty_score) + (0.15 * row_position_score)
        score = float((1000 - ridx) + (qty * 0.01) + (2200 if matched_keyword else 0))
        candidates.append(
            {
                "row_index": ridx,
                "text": name_txt,
                "qty_text": qty_txt,
                "qty": round(qty, 3),
                "matched_keyword": matched_keyword,
                "canonical_name": _canonical_condition_name(name_txt),
                "confidence": round(float(confidence), 4),
                "score": round(score, 3),
                "y_center_local": y_center,
                "y_center_global": int(mon["top"] + y0 + y_center),
            }
        )

    if not candidates:
        return {
            "ok": False,
            "reason": "no_active_condition_detected",
            "ocr_diagnostics": {
                "engine": ocr.get_diagnostics(),
                "call_samples": ocr_calls[:60],
            },
            "roi_global": {
                "x": int(mon["left"] + x0),
                "y": int(mon["top"] + y0),
                "w": int(x1 - x0),
                "h": int(y1 - y0),
            },
        }
    candidates.sort(key=lambda c: float(c.get("score", 0.0)), reverse=True)
    best = candidates[0]
    best_conf = float(best.get("confidence", 0.0) or 0.0)
    second_conf = 0.0
    if len(candidates) > 1:
        second_conf = float(candidates[1].get("confidence", 0.0) or 0.0)
    ambiguous = bool((best_conf - second_conf) < 0.08 and second_conf > 0.4)
    if ambiguous or best_conf < 0.92:
        return {
            "ok": False,
            "reason": "ambiguous_or_low_confidence_condition_lock",
            "selected_candidate": best,
            "candidate_count": len(candidates),
            "confidence": {
                "best": round(best_conf, 4),
                "second": round(second_conf, 4),
                "delta": round(best_conf - second_conf, 4),
            },
            "candidates": candidates[:12],
            "ocr_diagnostics": {
                "engine": ocr.get_diagnostics(),
                "call_samples": ocr_calls[:60],
            },
            "roi_global": {
                "x": int(mon["left"] + x0),
                "y": int(mon["top"] + y0),
                "w": int(x1 - x0),
                "h": int(y1 - y0),
            },
        }
    return {
        "ok": True,
        "selected": best,
        "candidates": candidates[:12],
        "candidate_count": len(candidates),
        "lock_confidence": round(best_conf, 4),
        "ocr_diagnostics": {
            "engine": ocr.get_diagnostics(),
            "call_samples": ocr_calls[:60],
        },
        "roi_global": {
            "x": int(mon["left"] + x0),
            "y": int(mon["top"] + y0),
            "w": int(x1 - x0),
            "h": int(y1 - y0),
        },
    }


def detect_condition_row_by_name(
    cfg: Dict[str, Any],
    monitor_index: int,
    ocr: OcrEngine,
    preferred_keywords: List[str] | None = None,
    target_row_index: int = -1,
) -> Dict[str, Any]:
    anchors = cfg.get("anchors", {}) if isinstance(cfg, dict) else {}
    a1 = anchors.get("conditions_first_row", {}) if isinstance(anchors, dict) else {}
    a2 = anchors.get("conditions_second_row", {}) if isinstance(anchors, dict) else {}
    if not (isinstance(a1, dict) and isinstance(a2, dict) and "x" in a1 and "y" in a1 and "x" in a2 and "y" in a2):
        return {"ok": False, "reason": "missing_condition_anchors"}
    mon = monitor_rect(monitor_index)
    img = screenshot_monitor_np(monitor_index)
    ax = int(a1["x"])
    ay = int(a1["y"])
    by = int(a2["y"])
    row_h = max(18, abs(by - ay))
    lx = ax - mon["left"]
    ly = ay - mon["top"]
    x0 = max(0, lx - 70)
    x1 = min(mon["width"], lx + 1120)
    y0 = max(0, ly - int(row_h * 0.45))
    y1 = min(mon["height"], ly + (row_h * 18))
    if x1 <= x0 or y1 <= y0:
        return {"ok": False, "reason": "invalid_conditions_roi"}
    roi = img[y0:y1, x0:x1]
    preferred_keywords = preferred_keywords or []
    panel_w = x1 - x0
    name_col_x0 = 0
    name_col_x1 = max(name_col_x0 + 60, panel_w - 260)
    candidates: List[Dict[str, Any]] = []
    debug_rows: List[Dict[str, Any]] = []
    for ridx in range(0, 16):
        if target_row_index >= 0 and ridx != int(target_row_index):
            continue
        ry0 = int(ridx * row_h)
        ry1 = min(roi.shape[0], int((ridx + 1) * row_h))
        if ry1 <= ry0 + 8:
            continue
        row_img = roi[ry0:ry1, :]
        gray = cv2.cvtColor(row_img, cv2.COLOR_BGR2GRAY)
        name_img = gray[:, name_col_x0:name_col_x1]
        name_thr = cv2.adaptiveThreshold(name_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
        t1 = pytesseract.image_to_string(name_img, config="--psm 6").strip()
        t2 = pytesseract.image_to_string(name_thr, config="--psm 6").strip()
        up = cv2.resize(name_thr, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC)
        t3 = pytesseract.image_to_string(up, config="--psm 7").strip()
        txt, kw = _choose_best_name_text([t1, t2, t3], preferred_keywords)
        if txt:
            debug_rows.append({"row_index": ridx, "text": txt[:160], "matched_keyword": kw})
        if not txt:
            continue
        lower = txt.lower()
        if ridx == 0 and _looks_like_folder_or_header_row(lower):
            continue
        if "unassigned" in lower:
            continue
        if preferred_keywords and kw not in {"ceiling", "gwb"}:
            continue
        alpha_count = len(re.findall(r"[A-Za-z]", txt))
        if alpha_count < 2:
            continue
        y_center = int((ry0 + ry1) / 2.0)
        conf = 0.95 if kw in {"ceiling", "gwb"} else 0.0
        candidates.append(
            {
                "row_index": ridx,
                "text": txt,
                "matched_keyword": kw,
                "canonical_name": _canonical_condition_name(txt),
                "confidence": conf,
                "score": float((1000 - ridx) + (2200 if kw else 0)),
                "y_center_local": y_center,
                "y_center_global": int(mon["top"] + y0 + y_center),
            }
        )
    if not candidates:
        return {
            "ok": False,
            "reason": "no_name_locked_condition_detected",
            "debug_rows": debug_rows[:12],
            "roi_global": {"x": int(mon["left"] + x0), "y": int(mon["top"] + y0), "w": int(x1 - x0), "h": int(y1 - y0)},
        }
    candidates.sort(key=lambda c: float(c.get("score", 0.0)), reverse=True)
    best = candidates[0]
    return {
        "ok": True,
        "selected": best,
        "candidates": candidates[:12],
        "candidate_count": len(candidates),
        "lock_confidence": float(best.get("confidence", 0.0) or 0.0),
        "roi_global": {"x": int(mon["left"] + x0), "y": int(mon["top"] + y0), "w": int(x1 - x0), "h": int(y1 - y0)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Select condition row in OST (anchor or OCR active-qty mode)")
    parser.add_argument("--setup-config", default="scripts/ost_project_setup_agent.config.json")
    parser.add_argument("--condition-row", choices=["first", "second"], default="first")
    parser.add_argument(
        "--selection-mode",
        choices=["anchor_row", "active_qty_non_unassigned", "locked_row_by_name"],
        default="active_qty_non_unassigned",
    )
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--window-title-contains", default="On-Screen Takeoff")
    parser.add_argument("--click-delay-ms", type=int, default=450)
    parser.add_argument("--taskbar-safe-margin-px", type=int, default=120)
    parser.add_argument(
        "--prefer-contains",
        default="ceiling,gwb",
        help="Comma-separated preferred condition keywords.",
    )
    parser.add_argument(
        "--target-row-index",
        type=int,
        default=-1,
        help="If >=0, force click this detected row index.",
    )
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()

    cfg = read_json(pathlib.Path(args.setup_config))
    ocr = create_ocr_engine()
    anchors = cfg.get("anchors", {}) if isinstance(cfg, dict) else {}
    focused = focus_window(str(args.window_title_contains))
    set_active_window_rect(str(args.window_title_contains))
    key = "conditions_first_row" if args.condition_row == "first" else "conditions_second_row"
    pt = anchors.get(key, {}) if isinstance(anchors, dict) else {}
    if not isinstance(pt, dict) or "x" not in pt or "y" not in pt:
        print(f"missing_anchor={key}")
        return 2

    selection: Dict[str, Any] = {
        "ok": True,
        "selection_mode": args.selection_mode,
        "focused": focused,
        "fallback_anchor": {"name": key, "x": int(pt["x"]), "y": int(pt["y"])},
    }
    x, y = int(pt["x"]), int(pt["y"])
    mon = monitor_rect(max(1, int(args.monitor_index)))
    if args.selection_mode == "active_qty_non_unassigned":
        preferred = _parse_preferred_keywords(str(args.prefer_contains))
        selection["preferred_keywords"] = preferred
        detected = detect_active_condition_row(
            cfg=cfg,
            monitor_index=max(1, int(args.monitor_index)),
            ocr=ocr,
            preferred_keywords=preferred,
        )
        selection["active_detection"] = detected
        if bool(detected.get("ok", False)):
            sel = detected.get("selected", {})
            if isinstance(sel, dict):
                target_row_idx = int(args.target_row_index)
                if target_row_idx >= 0:
                    forced_found = False
                    for cand in detected.get("candidates", []) if isinstance(detected.get("candidates", []), list) else []:
                        if isinstance(cand, dict) and int(cand.get("row_index", -1) or -1) == target_row_idx:
                            sel = cand
                            forced_found = True
                            break
                    if not forced_found:
                        selection["selected_by"] = "target_row_index_not_found"
                        selection["active_detection"] = detected
                        write_json(pathlib.Path(args.output_json), selection)
                        print(f"condition_selection={args.output_json}")
                        return 4
                y = int(sel.get("y_center_global", y))
                selection["selected_condition_text"] = str(sel.get("text", ""))
                selection["selected_condition_qty"] = float(sel.get("qty", 0.0) or 0.0)
                selection["selected_condition_keyword"] = str(sel.get("matched_keyword", "") or "")
                row_idx_raw = sel.get("row_index", -1)
                selection["selected_condition_row_index"] = int(row_idx_raw if row_idx_raw is not None else -1)
                selection["selected_condition_confidence"] = float(sel.get("confidence", 0.0) or 0.0)
                selection["active_candidate_count"] = int(detected.get("candidate_count", 0) or 0)
                selection["selected_by"] = "active_qty_non_unassigned"
        else:
            selection["ok"] = False
            selection["selected_by"] = "no_valid_active_keyword_row"
            selection["reason"] = "no_active_ceiling_or_gwb_with_qty"
            if str(args.output_json or "").strip():
                write_json(pathlib.Path(str(args.output_json)), selection)
            print(f"condition_selection={args.output_json}")
            return 5
    elif args.selection_mode == "locked_row_by_name":
        preferred = _parse_preferred_keywords(str(args.prefer_contains))
        selection["preferred_keywords"] = preferred
        detected = detect_condition_row_by_name(
            cfg=cfg,
            monitor_index=max(1, int(args.monitor_index)),
            ocr=ocr,
            preferred_keywords=preferred,
            target_row_index=int(args.target_row_index),
        )
        selection["active_detection"] = detected
        if bool(detected.get("ok", False)):
            sel = detected.get("selected", {})
            if isinstance(sel, dict):
                y = int(sel.get("y_center_global", y))
                selection["selected_condition_text"] = str(sel.get("text", ""))
                selection["selected_condition_qty"] = float(sel.get("qty", 0.0) or 0.0)
                selection["selected_condition_keyword"] = str(sel.get("matched_keyword", "") or "")
                row_idx_raw = sel.get("row_index", -1)
                selection["selected_condition_row_index"] = int(row_idx_raw if row_idx_raw is not None else -1)
                selection["selected_condition_confidence"] = float(sel.get("confidence", 0.0) or 0.0)
                selection["active_candidate_count"] = int(detected.get("candidate_count", 0) or 0)
                selection["selected_by"] = "locked_row_by_name"
        else:
            # Deterministic fallback: click first usable row under header band.
            fallback_y = int(pt["y"]) + 24 if args.condition_row == "first" else int(pt["y"])
            y = int(fallback_y)
            inferred_kw = preferred[0] if preferred else ""
            selection["selected_condition_text"] = str(inferred_kw)
            selection["selected_condition_qty"] = 0.0
            selection["selected_condition_keyword"] = str(inferred_kw)
            selection["selected_condition_row_index"] = 0 if args.condition_row == "first" else 1
            selection["selected_condition_confidence"] = 0.5
            selection["active_candidate_count"] = 0
            selection["selected_by"] = "locked_row_header_guard_fallback"
            selection["name_lock_fallback"] = {
                "applied": True,
                "reason": "no_locked_ceiling_or_gwb_row",
                "fallback_y": int(fallback_y),
            }
    else:
        selection["selected_by"] = "anchor_row"

    # Hard guard: first-row clicks must land below the folder/header line.
    if args.condition_row == "first":
        min_first_row_y = int(pt["y"]) + 24
        if int(y) < min_first_row_y:
            selection["header_row_guard"] = {
                "applied": True,
                "from_y": int(y),
                "to_y": int(min_first_row_y),
            }
            y = int(min_first_row_y)
        else:
            selection["header_row_guard"] = {"applied": False}

    if args.selection_mode == "active_qty_non_unassigned" and selection.get("selected_by") != "active_qty_non_unassigned":
        selection["ok"] = False
        selection["reason"] = "active_condition_not_locked"
        if str(args.output_json or "").strip():
            write_json(pathlib.Path(str(args.output_json)), selection)
        print(f"condition_selection={args.output_json}")
        return 6
    if args.selection_mode == "locked_row_by_name" and selection.get("selected_by") not in {
        "locked_row_by_name",
        "locked_row_header_guard_fallback",
    }:
        selection["ok"] = False
        selection["reason"] = "name_locked_condition_not_found"
        if str(args.output_json or "").strip():
            write_json(pathlib.Path(str(args.output_json)), selection)
        print(f"condition_selection={args.output_json}")
        return 8

    safe_x, safe_y, adjusted = clamp_point_to_safe_monitor_zone(
        x=x,
        y=y,
        monitor=mon,
        bottom_margin_px=max(40, int(args.taskbar_safe_margin_px)),
    )
    if adjusted:
        selection["taskbar_safe_adjustment"] = {
            "applied": True,
            "from": {"x": x, "y": y},
            "to": {"x": safe_x, "y": safe_y},
            "bottom_margin_px": max(40, int(args.taskbar_safe_margin_px)),
        }
    else:
        selection["taskbar_safe_adjustment"] = {"applied": False}

    win_x, win_y, win_adjusted = clamp_point_to_active_window(safe_x, safe_y, margin_px=10)
    if win_adjusted:
        selection["window_safe_adjustment"] = {
            "applied": True,
            "from": {"x": safe_x, "y": safe_y},
            "to": {"x": win_x, "y": win_y},
        }
    else:
        selection["window_safe_adjustment"] = {"applied": False}
    pyautogui.click(x=win_x, y=win_y)
    time.sleep(max(0.15, int(args.click_delay_ms) / 1000.0))
    selection["click_point"] = {"x": win_x, "y": win_y}
    if str(args.output_json or "").strip():
        write_json(pathlib.Path(str(args.output_json)), selection)
    print(
        f"selected_condition_row={args.condition_row} mode={args.selection_mode} "
        f"selected_by={selection.get('selected_by')} focused={focused} point=({x},{y})"
    )
    return 0


if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.04
    raise SystemExit(main())
