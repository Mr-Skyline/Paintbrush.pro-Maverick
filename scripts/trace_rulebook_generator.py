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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


FAILURE_RESULTS = frozenset({"failure", "error", "cancelled"})

# Rows without a non-empty string sessionId are grouped under this internal key.
NO_SESSION_KEY = "__no_session__"

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


def _session_key(obj: dict[str, Any]) -> str:
    sid = obj.get("sessionId")
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    return NO_SESSION_KEY


def _session_heading(key: str) -> str:
    if key == NO_SESSION_KEY:
        return "(no sessionId)"
    return f"`{key}`"


def _parse_event_filter_csv(raw: str | None) -> frozenset[str] | None:
    if raw is None:
        return None
    parts = [p.strip() for p in raw.split(",")]
    names = [p for p in parts if p]
    return frozenset(names)


def _filter_rows_by_events(
    rows: list[dict[str, Any]],
    include: frozenset[str] | None,
    exclude: frozenset[str] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        name = str(r["event"]).strip()
        if include is not None and name not in include:
            continue
        if exclude is not None and name in exclude:
            continue
        out.append(r)
    return out


def _filter_rows_by_session(
    rows: list[dict[str, Any]], session_id: str | None
) -> list[dict[str, Any]]:
    if session_id is None:
        return rows
    want = session_id.strip()
    if not want:
        return rows
    return [r for r in rows if _session_key(r) == want]


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


def _session_order(keys: list[str]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    for k in keys:
        if k not in seen:
            seen.add(k)
            order.append(k)
    return order


@dataclass(frozen=True)
class TraceAnalysis:
    n_events: int
    result_counts: Counter[str]
    success_n: int
    failure_n: int
    cancelled_n: int
    error_rate: float
    error_heavy: bool
    top_success: list[tuple[tuple[str, ...], int]]
    deterministic: list[tuple[tuple[str, ...], int]]
    failure_top: list[tuple[tuple[str, ...], int]]


def _analyze_trace(
    names: list[str],
    results: list[str],
    categories: list[str],
    min_frequency: int,
    max_rules: int,
) -> TraceAnalysis:
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

    return TraceAnalysis(
        n_events=n_events,
        result_counts=result_counts,
        success_n=success_n,
        failure_n=failure_n,
        cancelled_n=cancelled_n,
        error_rate=error_rate,
        error_heavy=error_heavy,
        top_success=top_success,
        deterministic=deterministic,
        failure_top=failure_top,
    )


def _unique_event_count(names: list[str]) -> int:
    return len(set(names))


def _format_mini_summary_lines(
    analysis: TraceAnalysis,
    names: list[str],
    *,
    bullet_prefix: str = "",
) -> list[str]:
    rc = analysis.result_counts
    return [
        f"{bullet_prefix}- **Events in scope:** {analysis.n_events}",
        f"{bullet_prefix}- **Unique event names:** {_unique_event_count(names)}",
        (
            f"{bullet_prefix}- **Result tallies:** success={analysis.success_n}, "
            f"failure={analysis.failure_n}, cancelled={analysis.cancelled_n}, "
            f"skipped={rc.get('skipped', 0)}, pending={rc.get('pending', 0)}, "
            f"unknown={rc.get('unknown', 0)}"
        ),
    ]


def _format_pattern_block(
    lines: list[str],
    analysis: TraceAnalysis,
    *,
    success_title: str,
    deterministic_title: str,
    failure_title: str,
    min_frequency: int,
    heading_prefix: str = "##",
) -> None:
    hp = heading_prefix
    lines.append(f"{hp} {success_title}")
    lines.append("")
    lines.append(
        "Frequent **bigrams** and **trigrams** of `event` names where the **last** "
        "step has result `success` (or legacy `ok`). Sorted by count, then length, "
        "then workflow salience."
    )
    lines.append("")
    if not analysis.top_success:
        lines.append("_No patterns met the frequency threshold._")
        lines.append("")
    else:
        for rank, (chain, freq) in enumerate(analysis.top_success, start=1):
            lines.append(f"{rank}. `{_format_chain(chain)}` -- count **{freq}**")
        lines.append("")

    lines.append(f"{hp} {deterministic_title}")
    lines.append("")
    lines.append(
        "Subsequences where every event name is one of: "
        + ", ".join(f"`{x}`" for x in sorted(REPLAY_EVENT_NAMES))
        + ". Same success-ending filter and frequency threshold as above."
    )
    lines.append("")
    if not analysis.deterministic:
        lines.append("_No qualifying replay-only chains met the threshold._")
        lines.append("")
    else:
        for rank, (chain, freq) in enumerate(analysis.deterministic, start=1):
            lines.append(f"{rank}. `{_format_chain(chain)}` -- count **{freq}**")
        lines.append("")

    lines.append(f"{hp} {failure_title}")
    lines.append("")
    if not analysis.error_heavy:
        lines.append(
            "Omitted: trace is not **error-heavy** "
            "(failure+cancelled rate below 15% or fewer than 3 such outcomes)."
        )
        lines.append("")
    else:
        lines.append(
            f"Trace looks **error-heavy** (~{analysis.error_rate * 100:.1f}% of "
            "success+failure+cancelled outcomes are failure or cancelled). "
            "Frequent **bigrams/trigrams whose last step is failure, error, or cancelled** "
            f"(min frequency {min_frequency}):"
        )
        lines.append("")
        if not analysis.failure_top:
            lines.append("_No failure-ending patterns met the frequency threshold._")
            lines.append("")
        else:
            for rank, (chain, freq) in enumerate(analysis.failure_top, start=1):
                lines.append(f"{rank}. `{_format_chain(chain)}` -- count **{freq}**")
            lines.append("")


def _filter_description_lines(
    include_events: frozenset[str] | None,
    exclude_events: frozenset[str] | None,
    session_id: str | None = None,
) -> list[str]:
    out: list[str] = []
    if include_events is not None:
        listed = ", ".join(f"`{x}`" for x in sorted(include_events))
        out.append(f"- **Event include filter:** {listed}")
    if exclude_events is not None:
        listed = ", ".join(f"`{x}`" for x in sorted(exclude_events))
        out.append(f"- **Event exclude filter:** {listed}")
    if session_id is not None and session_id.strip():
        out.append(f"- **sessionId filter:** `{session_id.strip()}`")
    return out


def generate_markdown(
    path: Path,
    min_frequency: int,
    max_rules: int,
    input_display: str,
    *,
    by_session: bool = False,
    include_events: frozenset[str] | None = None,
    exclude_events: frozenset[str] | None = None,
    session_id: str | None = None,
) -> str:
    all_rows, malformed_lines = _load_trace(path)
    rows_after_events = _filter_rows_by_events(
        all_rows, include_events, exclude_events
    )
    rows = _filter_rows_by_session(rows_after_events, session_id)

    lines: list[str] = [
        "# Trace-derived rulebook (draft)",
        "",
    ]

    if by_session:
        lines.append("## Per-session breakdown")
        lines.append("")
        keys_in_order = _session_order([_session_key(r) for r in rows])
        all_no_session = bool(keys_in_order) and all(
            k == NO_SESSION_KEY for k in keys_in_order
        )
        if not rows:
            lines.append("_No valid rows after event filters; nothing to split._")
            lines.append("")
        elif all_no_session:
            lines.append(
                "_No non-empty `sessionId` on any row; per-session pattern lists "
                "would duplicate the global sections below, so only global output follows._"
            )
            lines.append("")
        else:
            for sk in keys_in_order:
                sess_rows = [r for r in rows if _session_key(r) == sk]
                names_s, results_s, categories_s = _rows_to_parallel(sess_rows)
                an = _analyze_trace(
                    names_s, results_s, categories_s, min_frequency, max_rules
                )
                lines.append(f"### Session {_session_heading(sk)}")
                lines.append("")
                lines.append("#### Summary")
                lines.append("")
                lines.extend(_format_mini_summary_lines(an, names_s))
                lines.append("")
                _format_pattern_block(
                    lines,
                    an,
                    success_title="Top successful patterns",
                    deterministic_title="Candidate deterministic replay patterns",
                    failure_title="Low-confidence / needs-human patterns",
                    min_frequency=min_frequency,
                    heading_prefix="####",
                )

    names, results, categories = _rows_to_parallel(rows)
    analysis = _analyze_trace(names, results, categories, min_frequency, max_rules)

    lines.append("## Summary stats")
    lines.append("")
    lines.append(f"- **Source:** `{input_display}`")
    lines.append(f"- **Valid JSON rows (file):** {len(all_rows)}")
    lines.append(f"- **Rows after event filters:** {len(rows_after_events)}")
    if session_id is not None and session_id.strip():
        lines.append(f"- **Rows after sessionId filter:** {len(rows)}")
    lines.append(f"- **Malformed lines skipped:** {malformed_lines}")
    lines.extend(
        _filter_description_lines(include_events, exclude_events, session_id)
    )
    lines.append(f"- **Unique event names (after filters):** {_unique_event_count(names)}")
    lines.append(
        f"- **Result tallies (after filters):** success={analysis.success_n}, "
        f"failure={analysis.failure_n}, cancelled={analysis.cancelled_n}, "
        f"skipped={analysis.result_counts.get('skipped', 0)}, "
        f"pending={analysis.result_counts.get('pending', 0)}, "
        f"unknown={analysis.result_counts.get('unknown', 0)}"
    )
    lines.append(f"- **Min frequency threshold:** {min_frequency}")
    lines.append(f"- **Max rules (cap):** {max_rules}")
    lines.append(
        "- **N-gram sizes:** bigrams and trigrams (terminal step filters per section below)"
    )
    if by_session:
        lines.append(
            "- **Per-session mode:** enabled (`--by-session`); see sections above "
            "for per-session summaries and patterns where `sessionId` differs."
        )
    lines.append("")

    _format_pattern_block(
        lines,
        analysis,
        success_title="Top successful patterns",
        deterministic_title="Candidate deterministic replay patterns",
        failure_title="Low-confidence / needs-human patterns",
        min_frequency=min_frequency,
        heading_prefix="##",
    )

    lines.append("---")
    lines.append("")
    footer_bits = [
        "Draft only: edit before treating as policy.",
    ]
    if by_session and rows and not all(
        _session_key(r) == NO_SESSION_KEY for r in rows
    ):
        footer_bits.append(
            "Global sections aggregate all rows after event filters (all sessions)."
        )
    else:
        footer_bits.append(
            "Counts are over the whole file order after event filters "
            "(not split by session id)."
        )
    lines.append(" ".join(footer_bits))
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
    parser.add_argument(
        "--by-session",
        action="store_true",
        help=(
            "Emit per-session summaries and pattern sections (by non-empty sessionId) "
            "before the global summary; global sections still include all filtered rows."
        ),
    )
    parser.add_argument(
        "--include-events",
        metavar="NAMES",
        help="Comma-separated event names: only these events are used for mining and stats.",
    )
    parser.add_argument(
        "--exclude-events",
        metavar="NAMES",
        help="Comma-separated event names: drop these events before mining and stats.",
    )
    parser.add_argument(
        "--session-id",
        metavar="ID",
        help=(
            "If set, only rows whose sessionId matches this string (after trim) are used; "
            "rows with empty sessionId are excluded."
        ),
    )
    args = parser.parse_args()
    if args.min_frequency < 1:
        print("--min-frequency must be at least 1", file=sys.stderr)
        return 2
    if args.max_rules < 1:
        print("--max-rules must be at least 1", file=sys.stderr)
        return 2
    include_set = _parse_event_filter_csv(args.include_events)
    exclude_set = _parse_event_filter_csv(args.exclude_events)
    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1
    md = generate_markdown(
        args.input,
        args.min_frequency,
        args.max_rules,
        str(args.input.resolve()),
        by_session=args.by_session,
        include_events=include_set,
        exclude_events=exclude_set,
        session_id=args.session_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md, encoding="utf-8")
    print(f"Wrote {args.output} ({len(md)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
