#!/usr/bin/env python3
"""
Build a markdown rulebook from an exported agent trace JSONL file.

Each line is one JSON object. Expected keys align with AgentTraceEvent:
id, ts, event, category, result, optional context. Malformed lines are skipped
and counted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


FAILURE_RESULTS = frozenset({"failure", "error", "cancelled"})

# Events with replay handlers in src/lib/agentTrace.ts (replayAgentTraceSequence).
REPLAY_EVENT_NAMES = frozenset(
    {
        "tool_selected",
        "sheet_selected",
        "run_ai_takeoff_started",
        "review_approve_all",
        "export_paintbrush_csv",
    }
)


def _parse_row(line: str) -> dict[str, Any] | None:
    s = line.strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    ev = obj.get("event")
    if not isinstance(ev, str) or not ev.strip():
        return None
    return obj


def _norm_result(obj: dict[str, Any]) -> str:
    r = obj.get("result", "unknown")
    if not isinstance(r, str):
        return "unknown"
    r = r.strip().lower()
    if r == "ok":
        return "success"
    if r in ("success", "failure", "cancelled", "skipped", "pending", "unknown"):
        return r
    if r == "error":
        return "failure"
    return "unknown"


def _category(obj: dict[str, Any]) -> str:
    c = obj.get("category", "")
    return c if isinstance(c, str) else ""


def _iter_ngrams(
    names: list[str], n: int
) -> Iterable[tuple[tuple[str, ...], int]]:
    """Yield (ngram_tuple, index_of_last_event) for each window of length n."""
    if len(names) < n:
        return
    for i in range(len(names) - n + 1):
        yield (tuple(names[i : i + n]), i + n - 1)


def _interesting_bonus(chain: tuple[str, ...], categories: list[str]) -> int:
    """Higher score = more workflow-salient (used as tie-breaker)."""
    score = 0
    for name in chain:
        low = name.lower()
        if "upload" in low:
            score += 2
        if "sheet" in low or low == "tool_selected":
            score += 1
        if "takeoff" in low or "boost" in low or "ai" in low:
            score += 1
        if "review" in low:
            score += 1
        if "export" in low or "download" in low:
            score += 1
    for i, _name in enumerate(chain):
        if i < len(categories):
            cat = categories[i].lower()
            if cat in ("sheet", "tool", "ai", "review", "export"):
                score += 1
    return score


def _format_chain(chain: tuple[str, ...]) -> str:
    return " -> ".join(chain)


def _load_trace(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Return (valid rows in order, malformed_line_count)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    malformed = 0
    for line in raw.splitlines():
        row = _parse_row(line)
        if row is None:
            if line.strip():
                malformed += 1
            continue
        rows.append(row)
    return rows, malformed


def _rows_to_parallel(
    rows: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    names: list[str] = []
    results: list[str] = []
    categories: list[str] = []
    for r in rows:
        names.append(str(r["event"]).strip())
        results.append(_norm_result(r))
        categories.append(_category(r))
    return names, results, categories


def generate_markdown(
    path: Path,
    min_frequency: int,
    max_rules: int,
    input_display: str,
) -> str:
    rows, malformed_lines = _load_trace(path)
    names, results, categories = _rows_to_parallel(rows)

    n_events = len(names)
    result_counts: Counter[str] = Counter(results)
    success_n = result_counts.get("success", 0)
    failure_n = result_counts.get("failure", 0)
    cancelled_n = result_counts.get("cancelled", 0)

    terminal_fail_or_cancel = failure_n + cancelled_n
    denom_for_error_rate = success_n + terminal_fail_or_cancel
    error_rate = (
        (terminal_fail_or_cancel / denom_for_error_rate)
        if denom_for_error_rate
        else 0.0
    )
    error_heavy = error_rate >= 0.15 and terminal_fail_or_cancel >= 3

    success_patterns: Counter[tuple[str, ...]] = Counter()
    for n in (2, 3):
        for chain, last_idx in _iter_ngrams(names, n):
            if results[last_idx] == "success":
                success_patterns[chain] += 1

    success_filtered = [
        (c, f) for c, f in success_patterns.items() if f >= min_frequency
    ]

    def cats_for_chain(chain: tuple[str, ...]) -> list[str]:
        """Categories for one occurrence of chain (prefer last window in file)."""
        L = len(chain)
        for i in range(len(names) - L, -1, -1):
            if tuple(names[i : i + L]) == chain:
                return categories[i : i + L]
        return [""] * L

    success_filtered.sort(
        key=lambda cf: (
            -cf[1],
            -len(cf[0]),
            -_interesting_bonus(cf[0], cats_for_chain(cf[0])),
            cf[0],
        )
    )

    top_success = success_filtered[:max_rules]

    deterministic: list[tuple[tuple[str, ...], int]] = []
    for chain, freq in success_filtered:
        if all(e in REPLAY_EVENT_NAMES for e in chain):
            deterministic.append((chain, freq))
    deterministic = deterministic[:max_rules]

    failure_patterns: Counter[tuple[str, ...]] = Counter()
    for n in (2, 3):
        for chain, last_idx in _iter_ngrams(names, n):
            if results[last_idx] in FAILURE_RESULTS:
                failure_patterns[chain] += 1
    failure_filtered = [
        (c, f) for c, f in failure_patterns.items() if f >= min_frequency
    ]
    failure_filtered.sort(key=lambda cf: (-cf[1], -len(cf[0]), cf[0]))
    failure_top = failure_filtered[:max_rules]

    lines: list[str] = [
        "# Trace-derived rulebook (draft)",
        "",
        "## Summary stats",
        "",
        f"- **Source:** `{input_display}`",
        f"- **Valid JSON rows:** {n_events}",
        f"- **Malformed lines skipped:** {malformed_lines}",
        f"- **Unique event names:** {len(set(names))}",
        f"- **Result tallies:** success={success_n}, failure={failure_n}, "
        f"cancelled={cancelled_n}, skipped={result_counts.get('skipped', 0)}, "
        f"pending={result_counts.get('pending', 0)}, unknown={result_counts.get('unknown', 0)}",
        f"- **Min frequency threshold:** {min_frequency}",
        f"- **Max rules (cap):** {max_rules}",
        "- **N-gram sizes:** bigrams and trigrams (terminal step filters per section below)",
        "",
    ]

    lines.append("## Top successful patterns")
    lines.append("")
    lines.append(
        "Frequent **bigrams** and **trigrams** of `event` names where the **last** "
        "step has result `success` (or legacy `ok`). Sorted by count, then length, "
        "then workflow salience."
    )
    lines.append("")
    if not top_success:
        lines.append("_No patterns met the frequency threshold._")
        lines.append("")
    else:
        for rank, (chain, freq) in enumerate(top_success, start=1):
            lines.append(f"{rank}. `{_format_chain(chain)}` -- count **{freq}**")
        lines.append("")

    lines.append("## Candidate deterministic replay patterns")
    lines.append("")
    lines.append(
        "Subsequences where every event name is one of: "
        + ", ".join(f"`{x}`" for x in sorted(REPLAY_EVENT_NAMES))
        + ". Same success-ending filter and frequency threshold as above."
    )
    lines.append("")
    if not deterministic:
        lines.append("_No qualifying replay-only chains met the threshold._")
        lines.append("")
    else:
        for rank, (chain, freq) in enumerate(deterministic, start=1):
            lines.append(f"{rank}. `{_format_chain(chain)}` -- count **{freq}**")
        lines.append("")

    lines.append("## Low-confidence / needs-human patterns")
    lines.append("")
    if not error_heavy:
        lines.append(
            "Omitted: trace is not **error-heavy** "
            "(failure+cancelled rate below 15% or fewer than 3 such outcomes)."
        )
        lines.append("")
    else:
        lines.append(
            f"Trace looks **error-heavy** (~{error_rate * 100:.1f}% of "
            "success+failure+cancelled outcomes are failure or cancelled). "
            "Frequent **bigrams/trigrams whose last step is failure, error, or cancelled** "
            f"(min frequency {min_frequency}):"
        )
        lines.append("")
        if not failure_top:
            lines.append("_No failure-ending patterns met the frequency threshold._")
            lines.append("")
        else:
            for rank, (chain, freq) in enumerate(failure_top, start=1):
                lines.append(f"{rank}. `{_format_chain(chain)}` -- count **{freq}**")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Draft only: edit before treating as policy. "
        "Counts are over the whole file order (not split by session id)."
    )
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize frequent event-name n-grams from trace JSONL into a markdown rulebook."
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
        help="Path to write markdown output.",
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=2,
        metavar="N",
        help="Minimum count for an n-gram to be listed (default: 2).",
    )
    parser.add_argument(
        "--max-rules",
        type=int,
        default=50,
        metavar="N",
        help="Max items in the main pattern lists (default: 50).",
    )
    args = parser.parse_args()
    if args.min_frequency < 1:
        print("--min-frequency must be at least 1", file=sys.stderr)
        return 2
    if args.max_rules < 1:
        print("--max-rules must be at least 1", file=sys.stderr)
        return 2
    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1
    md = generate_markdown(
        args.input,
        args.min_frequency,
        args.max_rules,
        str(args.input.resolve()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md, encoding="utf-8")
    print(f"Wrote {args.output} ({len(md)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
