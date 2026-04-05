#!/usr/bin/env python3
"""
Build a JSON replay plan from trace JSONL: frequent success-ending n-grams whose
events are all in the replay-capable set (aligned with trace_rulebook_generator).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from trace_rulebook_generator import (
    REPLAY_EVENT_NAMES,
    _analyze_trace,
    _filter_rows_by_events,
    _filter_rows_by_session,
    _load_trace,
    _parse_event_filter_csv,
    _rows_to_parallel,
)


def _build_plan(
    path: Path,
    *,
    min_frequency: int,
    max_rules: int,
    max_steps: int,
    include_events: frozenset[str] | None,
    exclude_events: frozenset[str] | None,
    session_id: str | None,
) -> dict[str, Any]:
    all_rows, malformed_lines = _load_trace(path)
    rows = _filter_rows_by_events(all_rows, include_events, exclude_events)
    rows = _filter_rows_by_session(rows, session_id)
    if max_steps >= 1:
        rows = rows[:max_steps]
    names, results, categories = _rows_to_parallel(rows)
    analysis = _analyze_trace(names, results, categories, min_frequency, max_rules)
    patterns = [
        {"events": list(chain), "frequency": freq}
        for chain, freq in analysis.deterministic
    ]
    return {
        "version": 1,
        "source": str(path.resolve()),
        "replay_event_names": sorted(REPLAY_EVENT_NAMES),
        "malformed_lines_skipped": malformed_lines,
        "rows_used": len(rows),
        "parameters": {
            "min_frequency": min_frequency,
            "max_rules": max_rules,
            "max_steps": max_steps,
            "session_id": session_id.strip() if session_id and session_id.strip() else None,
            "include_events": sorted(include_events) if include_events else None,
            "exclude_events": sorted(exclude_events) if exclude_events else None,
        },
        "patterns": patterns,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract candidate deterministic replay patterns from trace JSONL "
            "(success-ending bigrams/trigrams using only replay-handled event names)."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to trace JSONL (one JSON object per line).",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write JSON output.",
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=2,
        metavar="N",
        help="Minimum count for a pattern (default: 2).",
    )
    parser.add_argument(
        "--max-rules",
        type=int,
        default=50,
        metavar="N",
        help="Max patterns to emit (default: 50).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=80,
        metavar="N",
        help="Consider at most this many rows after filters, in file order (default: 80).",
    )
    parser.add_argument(
        "--session-id",
        metavar="ID",
        help="Only use rows with this sessionId (non-empty match).",
    )
    parser.add_argument(
        "--include-events",
        metavar="NAMES",
        help="Comma-separated event names: only these rows are used.",
    )
    parser.add_argument(
        "--exclude-events",
        metavar="NAMES",
        help="Comma-separated event names to drop before analysis.",
    )
    args = parser.parse_args()
    if args.min_frequency < 1:
        print("--min-frequency must be at least 1", file=sys.stderr)
        return 2
    if args.max_rules < 1:
        print("--max-rules must be at least 1", file=sys.stderr)
        return 2
    if args.max_steps < 1:
        print("--max-steps must be at least 1", file=sys.stderr)
        return 2
    include_set = _parse_event_filter_csv(args.include_events)
    exclude_set = _parse_event_filter_csv(args.exclude_events)
    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1
    plan = _build_plan(
        args.input,
        min_frequency=args.min_frequency,
        max_rules=args.max_rules,
        max_steps=args.max_steps,
        include_events=include_set,
        exclude_events=exclude_set,
        session_id=args.session_id,
    )
    text = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"Wrote {args.output} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
