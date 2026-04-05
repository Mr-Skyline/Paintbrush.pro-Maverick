#!/usr/bin/env python3
"""
Build a markdown rulebook template from an exported agent trace JSONL file.

Each line should be a JSON object with at least `event` (string). Optional
fields `category`, `result`, `ts` match the app's AgentTraceEvent shape.
Only events with successful `result` are used when forming subsequences.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SUCCESS_RESULTS = frozenset({"success", "ok"})

# Categories / name hints for "workflow-critical" steps (Lane D prioritization).
def _event_is_interesting(event: str, category: str) -> bool:
    ev = event.lower()
    cat = category.lower()
    if "upload" in ev:
        return True
    if cat == "sheet" or "sheet" in ev:
        return True
    if cat == "tool" or ev == "tool_selected" or ("tool" in ev and "trace" not in ev):
        return True
    if cat == "ai" or "boost" in ev or "takeoff" in ev or "ai_takeoff" in ev:
        return True
    if cat == "review" or "review" in ev:
        return True
    if cat == "export" or "export" in ev or ("download" in ev and "zip" in ev):
        return True
    return False


def _parse_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    event = obj.get("event")
    if not isinstance(event, str) or not event.strip():
        return None
    return obj


def _is_success(obj: dict[str, Any]) -> bool:
    r = obj.get("result", "success")
    return isinstance(r, str) and r in SUCCESS_RESULTS


def _load_success_events(path: Path) -> list[tuple[str, str]]:
    """Return list of (event_name, category) for successful trace rows."""
    out: list[tuple[str, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        row = _parse_line(line)
        if row is None:
            continue
        if not _is_success(row):
            continue
        cat = row.get("category", "")
        if not isinstance(cat, str):
            cat = str(cat)
        out.append((row["event"], cat))
    return out


def _sliding_windows(
    items: list[tuple[str, str]], min_len: int, max_len: int
) -> Iterable[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Yield (event_chain, category_chain) for each window."""
    n = len(items)
    if n < min_len:
        return
    events = [t[0] for t in items]
    cats = [t[1] for t in items]
    for i in range(n):
        for length in range(min_len, max_len + 1):
            j = i + length
            if j > n:
                break
            yield (tuple(events[i:j]), tuple(cats[i:j]))


def _rule_id(chain: tuple[str, ...]) -> str:
    h = hashlib.sha256(" | ".join(chain).encode("utf-8")).hexdigest()[:8]
    return f"RB-{h}"


_INTENT_OVERRIDES: dict[str, str] = {
    "session_start": "start a trace session",
    "session_end": "end a trace session",
    "workspace_pdf_upload_started": "start uploading plan PDFs",
    "workspace_pdf_upload_completed": "finish uploading plan PDFs",
    "workspace_pdf_upload_failed": "hit an upload failure",
    "sheet_selected": "select a plan sheet",
    "tool_selected": "select a markup tool",
    "open_ai_takeoff_dialog": "open the AI takeoff dialog",
    "workspace_run_boost_started": "start an AI boost run",
    "workspace_run_boost_success": "complete an AI boost run successfully",
    "workspace_run_boost_failed": "see an AI boost run fail",
    "review_approve_all": "approve all items in review",
    "review_approve_all_outcome": "finish bulk review approval",
    "review_add_conditions_only": "add reviewed conditions only",
    "review_add_conditions_only_outcome": "finish add-conditions-only review action",
    "review_dismiss": "dismiss the review panel",
    "export_paintbrush_csv": "export Paintbrush CSV",
    "export_project_zip": "export a project ZIP",
    "workspace_export_paintbrush": "export Paintbrush data from the workspace",
    "workspace_download_zip_started": "start downloading a project ZIP",
    "workspace_download_zip": "download a project ZIP",
    "workspace_save_manual": "save the project manually",
    "workspace_sync_disk": "sync the project to disk",
    "workspace_page_nav": "navigate to another plan page",
    "trace_cleared": "clear the agent trace",
    "save_project": "save the project",
    "sync_project_to_disk": "sync the project to disk",
}


def _phrase_for_event(name: str) -> str:
    if name in _INTENT_OVERRIDES:
        return _INTENT_OVERRIDES[name]
    base = name
    if base.startswith("workspace_"):
        base = base[len("workspace_") :]
    base = base.replace("_", " ")
    base = re.sub(r"\s+", " ", base).strip()
    return base or name


def infer_intent(chain: tuple[str, ...]) -> str:
    if not chain:
        return "No events in chain."
    phrases = [_phrase_for_event(e) for e in chain]
    if len(phrases) == 1:
        return f"The user likely intended to {phrases[0]}."
    joined = ", then ".join(phrases[:-1]) + f", then {phrases[-1]}"
    return f"The user likely intended to {joined}."


def _chain_priority(chain: tuple[str, ...], cats: tuple[str, ...]) -> int:
    score = 0
    for ev, cat in zip(chain, cats):
        if _event_is_interesting(ev, cat):
            score += 1
    return score


def generate_markdown(
    path: Path,
    min_frequency: int,
    input_display: str,
) -> str:
    items = _load_success_events(path)
    counts: Counter[tuple[str, ...]] = Counter()
    cat_by_chain: dict[tuple[str, ...], tuple[str, ...]] = {}

    for ev_chain, cat_chain in _sliding_windows(items, 3, 6):
        counts[ev_chain] += 1
        cat_by_chain[ev_chain] = cat_chain

    filtered = [(c, f) for c, f in counts.items() if f >= min_frequency]
    # Sort: more "interesting" events in chain, then higher frequency, then longer (more specific).
    filtered.sort(
        key=lambda cf: (
            -_chain_priority(cf[0], cat_by_chain[cf[0]]),
            -cf[1],
            -len(cf[0]),
            cf[0],
        )
    )

    lines: list[str] = [
        "# Trace-derived rulebook (draft)",
        "",
        f"Source: `{input_display}`",
        f"Successful events considered: **{len(items)}** · Minimum sequence frequency: **{min_frequency}**",
        "",
        "Subsequences are **3–6** consecutive successful events (sliding window). "
        "Rules that touch upload, sheet, tool, AI/boost/takeoff, review, or export-style "
        "steps are listed first.",
        "",
        "## Rules",
        "",
    ]

    if not filtered:
        lines.append("_No subsequences met the frequency threshold._")
        lines.append("")
        return "\n".join(lines)

    for chain, freq in filtered:
        rid = _rule_id(chain)
        chain_md = " → ".join(f"`{e}`" for e in chain)
        intent = infer_intent(chain)
        lines.append(f"### {rid} — frequency {freq}")
        lines.append("")
        lines.append(f"- **Event chain:** {chain_md}")
        lines.append(f"- **Inferred intent:** {intent}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize frequent successful event sequences from trace JSONL into a markdown rulebook template."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to exported trace JSONL (one JSON object per line).",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write markdown output.",
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=2,
        metavar="N",
        help="Minimum times a subsequence must appear (default: 2).",
    )
    args = parser.parse_args()
    if args.min_frequency < 1:
        print("--min-frequency must be at least 1", file=sys.stderr)
        return 2
    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1
    md = generate_markdown(args.input, args.min_frequency, str(args.input.resolve()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md, encoding="utf-8")
    print(f"Wrote {args.output} ({len(md)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
