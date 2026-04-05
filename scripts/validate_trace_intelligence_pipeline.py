#!/usr/bin/env python3
"""
Validate the trace → rulebook / replay-plan tooling using a bundled JSONL fixture.

Runs (under a fresh directory in output/trace-intel-validation/):
  1. trace_rulebook_generator (full markdown)
  2. trace_rulebook_generator (--include-events replay subset)
  3. Replay-plan JSON derived from the fixture (replay-eligible events only)
  4. Pipeline summary JSON (counts + output paths)

Stdlib only; exits non-zero if any step fails or expected artifacts are missing/empty.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
FIXTURE = SCRIPTS / "fixtures" / "sample_agent_trace.jsonl"
RULEBOOK_GEN = SCRIPTS / "trace_rulebook_generator.py"

# Keep in sync with scripts/trace_rulebook_generator.py and src/lib/agentReplay.ts
REPLAY_EVENTS = frozenset(
    {
        "tool_selected",
        "sheet_selected",
        "run_ai_takeoff_started",
        "review_approve_all",
        "export_paintbrush_csv",
    }
)

TRACE_EVENT_TO_ACTION: dict[str, str] = {
    "tool_selected": "set_tool",
    "sheet_selected": "set_page",
    "run_ai_takeoff_started": "run_ai_takeoff",
    "review_approve_all": "approve_review",
    "export_paintbrush_csv": "export_outputs",
}


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"PASS: {msg}")


def _parse_trace_line(line: str) -> dict[str, Any] | None:
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


def _load_fixture_stats(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    valid: list[dict[str, Any]] = []
    malformed = 0
    for line in raw.splitlines():
        row = _parse_trace_line(line)
        if row is None:
            if line.strip():
                malformed += 1
            continue
        valid.append(row)
    replay_rows = [r for r in valid if str(r["event"]).strip() in REPLAY_EVENTS]
    events = Counter(str(r["event"]).strip() for r in valid)
    return {
        "valid_rows": len(valid),
        "malformed_lines": malformed,
        "replay_eligible_rows": len(replay_rows),
        "event_counts": dict(events),
    }


def _generate_replay_plan(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    order = 0
    for r in rows:
        name = str(r["event"]).strip()
        if name not in REPLAY_EVENTS:
            continue
        order += 1
        action = TRACE_EVENT_TO_ACTION.get(name)
        plan.append(
            {
                "order": order,
                "trace_event": name,
                "replay_action": action,
                "id": r.get("id"),
                "ts": r.get("ts"),
                "sessionId": r.get("sessionId"),
                "result": r.get("result"),
                "context": r.get("context") if isinstance(r.get("context"), dict) else {},
            }
        )
    return plan


def _run_python_script(
    script: Path, args: list[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _require_nonempty_file(path: Path, label: str) -> bool:
    if not path.is_file():
        _fail(f"missing {label}: {path}")
        return False
    if path.stat().st_size == 0:
        _fail(f"empty {label}: {path}")
        return False
    return True


def main() -> int:
    if not FIXTURE.is_file():
        _fail(f"fixture not found: {FIXTURE}")
        return 1
    if not RULEBOOK_GEN.is_file():
        _fail(f"rulebook generator not found: {RULEBOOK_GEN}")
        return 1

    base_out = REPO_ROOT / "output" / "trace-intel-validation"
    base_out.mkdir(parents=True, exist_ok=True)

    failures = 0
    with tempfile.TemporaryDirectory(
        prefix="run-", dir=str(base_out)
    ) as tmp:
        out = Path(tmp)
        rulebook_md = out / "trace-rulebook.md"
        rulebook_replay_md = out / "trace-rulebook-replay.md"
        replay_plan_json = out / "replay_plan.json"
        pipeline_report_json = out / "pipeline_report.json"

        # --- Rulebook (full) ---
        p1 = _run_python_script(
            RULEBOOK_GEN,
            [
                "--input",
                str(FIXTURE),
                "--output",
                str(rulebook_md),
                "--min-frequency",
                "2",
                "--max-rules",
                "20",
            ],
            cwd=REPO_ROOT,
        )
        if p1.returncode != 0:
            failures += 1
            _fail(
                f"rulebook generator (full) exit {p1.returncode}: "
                f"{p1.stderr.strip() or p1.stdout.strip()}"
            )
        else:
            _ok("rulebook generator (full) exited 0")

        replay_csv = ",".join(sorted(REPLAY_EVENTS))
        p2 = _run_python_script(
            RULEBOOK_GEN,
            [
                "--input",
                str(FIXTURE),
                "--output",
                str(rulebook_replay_md),
                "--min-frequency",
                "2",
                "--max-rules",
                "20",
                "--include-events",
                replay_csv,
            ],
            cwd=REPO_ROOT,
        )
        if p2.returncode != 0:
            failures += 1
            _fail(
                f"rulebook generator (replay filter) exit {p2.returncode}: "
                f"{p2.stderr.strip() or p2.stdout.strip()}"
            )
        else:
            _ok("rulebook generator (replay filter) exited 0")

        # --- Replay plan (generator pass) ---
        raw = FIXTURE.read_text(encoding="utf-8", errors="replace")
        valid_rows: list[dict[str, Any]] = []
        for line in raw.splitlines():
            row = _parse_trace_line(line)
            if row is not None:
                valid_rows.append(row)
        plan = _generate_replay_plan(valid_rows)
        replay_plan_json.write_text(
            json.dumps(plan, indent=2) + "\n", encoding="utf-8"
        )
        if not plan:
            failures += 1
            _fail("replay plan has no steps")
        else:
            _ok(f"replay plan wrote {len(plan)} step(s)")

        # --- Pipeline runner (summary artifact) ---
        stats = _load_fixture_stats(FIXTURE)
        report = {
            "fixture": str(FIXTURE.resolve()),
            "output_dir": str(out.resolve()),
            "steps_completed": [
                "trace_rulebook_generator_full",
                "trace_rulebook_generator_replay_subset",
                "replay_plan_generator",
                "pipeline_runner",
            ],
            "stats": stats,
            "artifacts": {
                "trace_rulebook_md": str(rulebook_md.name),
                "trace_rulebook_replay_md": str(rulebook_replay_md.name),
                "replay_plan_json": str(replay_plan_json.name),
            },
        }
        pipeline_report_json.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        _ok("pipeline report written")

        required = [
            (rulebook_md, "trace-rulebook.md"),
            (rulebook_replay_md, "trace-rulebook-replay.md"),
            (replay_plan_json, "replay_plan.json"),
            (pipeline_report_json, "pipeline_report.json"),
        ]
        for path, label in required:
            if not _require_nonempty_file(path, label):
                failures += 1

        # Sanity: rulebook should mention skipped malformed count
        rb_text = rulebook_md.read_text(encoding="utf-8")
        if "Malformed lines skipped" not in rb_text and "malformed" not in rb_text.lower():
            failures += 1
            _fail("rulebook markdown missing malformed-line signal")
        else:
            _ok("rulebook mentions malformed / skip stats")

    print("")
    if failures:
        print(f"SUMMARY: FAIL ({failures} check(s) failed)")
        return 1
    print("SUMMARY: PASS (trace intelligence pipeline validation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
