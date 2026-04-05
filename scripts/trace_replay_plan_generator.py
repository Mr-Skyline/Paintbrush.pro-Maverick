#!/usr/bin/env python3
"""
Generate a JSON replay plan from an exported agent trace JSONL file.

Each line is one JSON object. Malformed lines are skipped and counted.
Maps trace events to replay actions consistent with src/lib/agentReplay.ts.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRACE_EVENT_TO_ACTION: dict[str, str] = {
    "tool_selected": "set_tool",
    "sheet_selected": "set_page",
    "run_ai_takeoff_started": "run_ai_takeoff",
    "review_approve_all": "approve_review",
    "export_paintbrush_csv": "export_outputs",
}


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


def _load_trace(path: Path) -> tuple[list[dict[str, Any]], int, int]:
    """Return (valid rows in file order, malformed_line_count, total_rows).

    total_rows counts non-empty lines (each is one attempted JSON record).
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    rows: list[dict[str, Any]] = []
    malformed = 0
    total_rows = 0
    for line in lines:
        if not line.strip():
            continue
        total_rows += 1
        row = _parse_row(line)
        if row is None:
            malformed += 1
            continue
        rows.append(row)
    return rows, malformed, total_rows


def _parse_include_events_csv(raw: str | None) -> frozenset[str] | None:
    if raw is None:
        return None
    parts = [p.strip() for p in raw.split(",")]
    names = [p for p in parts if p]
    # Empty / whitespace-only list means no filter (same as omitting the flag).
    return frozenset(names) if names else None


def _session_key(obj: dict[str, Any]) -> str:
    sid = obj.get("sessionId")
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    return ""


def _filter_session(rows: list[dict[str, Any]], session_id: str | None) -> list[dict[str, Any]]:
    if session_id is None:
        return rows
    want = session_id.strip()
    if not want:
        return rows
    return [r for r in rows if _session_key(r) == want]


def _filter_events(
    rows: list[dict[str, Any]], include: frozenset[str] | None
) -> list[dict[str, Any]]:
    if include is None:
        return rows
    out: list[dict[str, Any]] = []
    for r in rows:
        name = str(r["event"]).strip()
        if name in include:
            out.append(r)
    return out


def _context(obj: dict[str, Any]) -> dict[str, Any] | None:
    c = obj.get("context")
    if c is not None and isinstance(c, dict):
        return c
    return None


def _read_string(ctx: dict[str, Any] | None, key: str) -> str | None:
    if ctx is None:
        return None
    v = ctx.get(key)
    return v if isinstance(v, str) and len(v) > 0 else None


def _read_optional_page(ctx: dict[str, Any] | None) -> int | None:
    if ctx is None:
        return None
    v = ctx.get("page")
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        if not f == f or not f.is_integer():  # NaN or non-integer float
            return None
        p = int(f)
        return p if p >= 1 else None
    return None


def _ts_value(obj: dict[str, Any]) -> float:
    t = obj.get("ts")
    if isinstance(t, bool):
        return 0.0
    if isinstance(t, (int, float)):
        if isinstance(t, float) and not t == t:  # NaN
            return 0.0
        return float(t)
    return 0.0


def _sort_key(row: dict[str, Any], appearance: int) -> tuple[float, str, int]:
    tid = row.get("id")
    sid = tid if isinstance(tid, str) else ""
    return (_ts_value(row), sid, appearance)


def _bump_skipped(
    agg: dict[tuple[str, str], int], event: str, reason: str
) -> None:
    key = (event, reason)
    agg[key] = agg.get(key, 0) + 1


def _plan_step(
    row: dict[str, Any],
    event_name: str,
    action: str,
    ctx: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    """
    Returns (step_dict, skip_key) where skip_key is (event, reason) if skipped.
    """
    if action == "set_tool":
        tool = _read_string(ctx, "tool")
        if not tool:
            return None, (event_name, "missing required context: tool")
        args: dict[str, Any] = {"tool": tool}
        return {
            "ts": _ts_value(row),
            "event": event_name,
            "action": action,
            "args": args,
            "confidence": 0.95,
            "reason": "required context.tool present",
        }, None

    if action == "set_page":
        document_id = _read_string(ctx, "documentId")
        if not document_id:
            return None, (event_name, "missing required context: documentId")
        page = _read_optional_page(ctx)
        args = {"documentId": document_id}
        if page is not None:
            args["page"] = page
        if page is not None:
            conf = 0.95
            rsn = "documentId and page present"
        else:
            conf = 0.65
            rsn = "documentId present; optional page omitted or invalid"
        return {
            "ts": _ts_value(row),
            "event": event_name,
            "action": action,
            "args": args,
            "confidence": conf,
            "reason": rsn,
        }, None

    if action == "run_ai_takeoff":
        args: dict[str, Any] = {}
        scope = _read_string(ctx, "scope") if ctx else None
        if scope is not None:
            args["scope"] = scope
            conf = 0.95
            rsn = "optional context.scope present"
        else:
            conf = 0.65
            rsn = "action valid without scope"
        return {
            "ts": _ts_value(row),
            "event": event_name,
            "action": action,
            "args": args,
            "confidence": conf,
            "reason": rsn,
        }, None

    if action in ("approve_review", "export_outputs"):
        return {
            "ts": _ts_value(row),
            "event": event_name,
            "action": action,
            "args": {},
            "confidence": 0.95,
            "reason": "no required context for this action",
        }, None

    return None, (event_name, "unknown action")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Build a JSON replay plan from a trace JSONL export."
    )
    p.add_argument("--input", required=True, type=Path, help="Input JSONL trace path")
    p.add_argument("--output", required=True, type=Path, help="Output JSON path")
    p.add_argument(
        "--max-steps",
        type=int,
        default=80,
        help="Maximum number of plan steps to emit (default: 80)",
    )
    p.add_argument(
        "--session-only",
        default=None,
        metavar="SESSION_ID",
        help="Only include rows with this sessionId",
    )
    p.add_argument(
        "--include-events",
        default=None,
        help="Comma-separated event names to include (default: all events)",
    )
    args_ns = p.parse_args()
    inp: Path = args_ns.input
    out: Path = args_ns.output
    max_steps: int = args_ns.max_steps
    session_only: str | None = args_ns.session_only
    include_raw: str | None = args_ns.include_events

    if max_steps < 0:
        print("error: --max-steps must be >= 0", file=sys.stderr)
        return 2

    if not inp.is_file():
        print(f"error: input not found: {inp}", file=sys.stderr)
        return 2

    include_events = _parse_include_events_csv(include_raw)

    rows, malformed, total_rows = _load_trace(inp)
    after_session = _filter_session(rows, session_only)
    selected = _filter_events(after_session, include_events)

    decorated = [(r, i) for i, r in enumerate(selected)]
    decorated.sort(key=lambda pair: _sort_key(pair[0], pair[1]))

    skipped_agg: dict[tuple[str, str], int] = {}
    step_candidates: list[dict[str, Any]] = []

    for row, appearance in decorated:
        event_name = str(row["event"]).strip()
        action = TRACE_EVENT_TO_ACTION.get(event_name)
        if action is None:
            _bump_skipped(skipped_agg, event_name, "event type has no replay mapping")
            continue
        ctx = _context(row)
        step, skip = _plan_step(row, event_name, action, ctx)
        if skip is not None:
            _bump_skipped(skipped_agg, skip[0], skip[1])
            continue
        assert step is not None
        step_candidates.append(step)

    limited = step_candidates[:max_steps] if max_steps else []
    steps_out: list[dict[str, Any]] = []
    for idx, s in enumerate(limited):
        entry = {"index": idx, **s}
        steps_out.append(entry)

    skipped_list = [
        {"event": ev, "reason": reason, "count": count}
        for (ev, reason), count in sorted(skipped_agg.items(), key=lambda x: (x[0][0], x[0][1]))
    ]

    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    meta: dict[str, Any] = {
        "source": str(inp.resolve()),
        "total_rows": total_rows,
        "malformed_rows": malformed,
        "selected_rows": len(selected),
        "generated_steps": len(steps_out),
        "generated_at": generated_at,
        "filters": {
            "session_only": session_only,
            "include_events": sorted(include_events) if include_events is not None else None,
            "max_steps": max_steps,
        },
    }

    doc = {"meta": meta, "steps": steps_out, "skipped": skipped_list}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
