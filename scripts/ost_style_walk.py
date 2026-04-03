#!/usr/bin/env python3
"""
Maverick Style Walk

Guided capture mode for learning operator takeoff patterns while the user
scrolls through sheets in live OST.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
from datetime import datetime
from typing import Any, Dict, List

try:
    import cv2
    import mss
    import mss.tools
    import numpy as np
    import pygetwindow as gw
    import pytesseract
except Exception as exc:  # pragma: no cover
    print(
        "Missing dependencies. Install with:\n"
        "  pip install pygetwindow mss opencv-python pytesseract numpy\n"
        f"Import error: {exc}"
    )
    raise


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_jsonl(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")


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


def monitor_rect(monitor_index: int) -> Dict[str, int]:
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index < 1 or monitor_index >= len(monitors):
            raise ValueError(f"monitor_index={monitor_index} invalid; available 1..{len(monitors)-1}")
        m = monitors[monitor_index]
        return {
            "left": int(m["left"]),
            "top": int(m["top"]),
            "width": int(m["width"]),
            "height": int(m["height"]),
        }


def screenshot_monitor(monitor_index: int, out_file: pathlib.Path) -> pathlib.Path:
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index < 1 or monitor_index >= len(monitors):
            raise ValueError(f"monitor_index={monitor_index} invalid; available 1..{len(monitors)-1}")
        shot = sct.grab(monitors[monitor_index])
        out_file.parent.mkdir(parents=True, exist_ok=True)
        mss.tools.to_png(shot.rgb, shot.size, output=str(out_file))
    return out_file


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
    return float(cv2.absdiff(a, b).mean())


def extract_text(image_path: pathlib.Path) -> str:
    try:
        return pytesseract.image_to_string(str(image_path)).strip()
    except Exception:
        return ""


def condense_text(s: str, max_len: int = 220) -> str:
    x = " ".join((s or "").split())
    return x[:max_len]


def run_style_walk(
    project_id: str,
    monitor_index: int,
    duration_seconds: int,
    interval_seconds: float,
    window_title_contains: str,
    change_threshold: float,
    output_root: pathlib.Path,
) -> Dict[str, Any]:
    if not focus_ost_window(window_title_contains):
        return {
            "ok": False,
            "reason": "window_not_found_or_focus_failed",
            "window_title_contains": window_title_contains,
        }

    session_id = f"stylewalk-{now_tag()}"
    walk_dir = output_root / session_id
    shots_dir = walk_dir / "screens"
    events_path = walk_dir / "events.jsonl"
    summary_json = walk_dir / "summary.json"
    summary_md = walk_dir / "summary.md"

    start_ts = time.time()
    deadline = start_ts + max(5, duration_seconds)
    idx = 0
    prev_file: pathlib.Path | None = None
    prev_text = ""
    changed_frames = 0
    event_count = 0
    screen_paths: List[str] = []
    page_clues: List[str] = []

    append_jsonl(
        events_path,
        {
            "ts": datetime.now().isoformat(),
            "event": "style_walk_started",
            "project_id": project_id,
            "monitor_index": monitor_index,
            "duration_seconds": duration_seconds,
            "interval_seconds": interval_seconds,
            "change_threshold": change_threshold,
        },
    )

    while time.time() < deadline:
        idx += 1
        shot_file = shots_dir / f"frame_{idx:04d}.png"
        screenshot_monitor(monitor_index, shot_file)
        screen_paths.append(str(shot_file))
        text = condense_text(extract_text(shot_file))
        diff = 0.0
        text_changed = False
        visual_changed = False
        if prev_file is not None:
            diff = mean_abs_diff(prev_file, shot_file)
            visual_changed = diff >= change_threshold
            text_changed = text != prev_text and bool(text)
        page_changed = bool(prev_file is None or visual_changed or text_changed)
        if page_changed:
            changed_frames += 1
            clue = text[:120] if text else f"frame_{idx}"
            if clue and clue not in page_clues:
                page_clues.append(clue)
            append_jsonl(
                events_path,
                {
                    "ts": datetime.now().isoformat(),
                    "event": "page_change_detected",
                    "frame": idx,
                    "image": str(shot_file),
                    "visual_diff": round(diff, 4),
                    "visual_changed": visual_changed,
                    "text_changed": text_changed,
                    "ocr_preview": text,
                },
            )
            event_count += 1
        prev_file = shot_file
        prev_text = text
        time.sleep(max(0.2, interval_seconds))

    elapsed = round(time.time() - start_ts, 2)
    summary = {
        "ok": True,
        "session_id": session_id,
        "project_id": project_id,
        "monitor_index": monitor_index,
        "duration_seconds": duration_seconds,
        "interval_seconds": interval_seconds,
        "change_threshold": change_threshold,
        "elapsed_seconds": elapsed,
        "frames_captured": idx,
        "page_change_events": changed_frames,
        "events_logged": event_count,
        "walk_dir": str(walk_dir),
        "events_jsonl": str(events_path),
        "screens_dir": str(shots_dir),
        "top_page_clues": page_clues[:15],
    }
    write_json(summary_json, summary)

    md_lines = [
        f"# Maverick Style Walk Summary - {session_id}",
        "",
        f"- project_id: {project_id}",
        f"- elapsed_seconds: {elapsed}",
        f"- frames_captured: {idx}",
        f"- page_change_events: {changed_frames}",
        f"- monitor_index: {monitor_index}",
        f"- events_jsonl: {events_path}",
        "",
        "## What Maverick Saw",
        "- This capture records how you navigate sheets and where condition/takeoff text changes while you scroll.",
        "- Use this with training notes to coach 'why' and preferred edits/reassignments per page context.",
        "",
        "## Top OCR Page Clues",
    ]
    if page_clues:
        for clue in page_clues[:15]:
            md_lines.append(f"- {clue}")
    else:
        md_lines.append("- No OCR clues detected.")
    summary_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a live OST style-walk session")
    parser.add_argument("--project-id", default="TP-0001")
    parser.add_argument("--monitor-index", type=int, default=1)
    parser.add_argument("--duration-seconds", type=int, default=90)
    parser.add_argument("--interval-seconds", type=float, default=1.8)
    parser.add_argument("--window-title-contains", default="On-Screen Takeoff")
    parser.add_argument("--change-threshold", type=float, default=0.75)
    parser.add_argument("--output-root", default="output/ost-training-lab/style_walks")
    args = parser.parse_args()

    result = run_style_walk(
        project_id=str(args.project_id),
        monitor_index=int(args.monitor_index),
        duration_seconds=int(args.duration_seconds),
        interval_seconds=float(args.interval_seconds),
        window_title_contains=str(args.window_title_contains),
        change_threshold=float(args.change_threshold),
        output_root=pathlib.Path(str(args.output_root)),
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

