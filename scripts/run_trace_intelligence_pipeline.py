#!/usr/bin/env python3
"""
Run trace intelligence scripts in sequence: rulebook markdown, replay plan JSON, summary.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def _run_step(
    name: str,
    argv: list[str],
    *,
    cwd: Path,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "name": name,
        "command": argv,
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "error": None,
    }
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["returncode"] = -1
        return rec
    rec["returncode"] = proc.returncode
    rec["stdout"] = proc.stdout or ""
    rec["stderr"] = proc.stderr or ""
    return rec


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate trace_rulebook.md and trace_replay_plan.json from JSONL; "
            "writes pipeline_summary.json with per-step status."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to trace JSONL (one JSON object per line).",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Directory for trace_rulebook.md, trace_replay_plan.json, pipeline_summary.json.",
    )
    parser.add_argument(
        "--session-id",
        metavar="ID",
        help="Pass through to both generators: restrict to this sessionId.",
    )
    parser.add_argument(
        "--include-events",
        metavar="NAMES",
        help="Comma-separated event names passed to both generators.",
    )
    parser.add_argument(
        "--exclude-events",
        metavar="NAMES",
        help="Comma-separated event names passed to both generators.",
    )
    parser.add_argument(
        "--max-rules",
        type=int,
        default=50,
        metavar="N",
        help="Passed to both generators (default: 50).",
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=2,
        metavar="N",
        help="Passed to both generators (default: 2).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=80,
        metavar="N",
        help="Passed to trace_replay_plan_generator only (default: 80).",
    )
    args = parser.parse_args()

    repo_root = _scripts_dir().parent
    py = sys.executable
    rulebook_script = _scripts_dir() / "trace_rulebook_generator.py"
    replay_script = _scripts_dir() / "trace_replay_plan_generator.py"

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    rulebook_path = out_dir / "trace_rulebook.md"
    replay_path = out_dir / "trace_replay_plan.json"
    summary_path = out_dir / "pipeline_summary.json"

    common: list[str] = [
        "--input",
        str(args.input.resolve()),
        "--min-frequency",
        str(args.min_frequency),
        "--max-rules",
        str(args.max_rules),
    ]
    if args.session_id is not None:
        common.extend(["--session-id", args.session_id])
    if args.include_events is not None:
        common.extend(["--include-events", args.include_events])
    if args.exclude_events is not None:
        common.extend(["--exclude-events", args.exclude_events])

    rulebook_argv = [
        py,
        str(rulebook_script),
        *common,
        "--output",
        str(rulebook_path.resolve()),
    ]
    replay_argv = [
        py,
        str(replay_script),
        *common,
        "--max-steps",
        str(args.max_steps),
        "--output",
        str(replay_path.resolve()),
    ]

    steps: list[dict[str, Any]] = []
    steps.append(
        _run_step(
            "trace_rulebook_generator",
            rulebook_argv,
            cwd=repo_root,
        )
    )
    steps[-1]["output_path"] = str(rulebook_path.resolve())

    steps.append(
        _run_step(
            "trace_replay_plan_generator",
            replay_argv,
            cwd=repo_root,
        )
    )
    steps[-1]["output_path"] = str(replay_path.resolve())

    ok = all(s.get("returncode") == 0 and s.get("error") is None for s in steps)

    summary: dict[str, Any] = {
        "ok": ok,
        "input": str(args.input.resolve()),
        "out_dir": str(out_dir.resolve()),
        "parameters": {
            "session_id": args.session_id,
            "include_events": args.include_events,
            "exclude_events": args.exclude_events,
            "max_rules": args.max_rules,
            "min_frequency": args.min_frequency,
            "max_steps": args.max_steps,
        },
        "outputs": {
            "trace_rulebook": str(rulebook_path.resolve()),
            "trace_replay_plan": str(replay_path.resolve()),
            "pipeline_summary": str(summary_path.resolve()),
        },
        "steps": steps,
    }

    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for s in steps:
        label = s["name"]
        rc = s.get("returncode")
        if s.get("error"):
            print(f"{label}: failed to start ({s['error']})", file=sys.stderr)
        else:
            print(f"{label}: exit {rc}")
        if s.get("stdout"):
            sys.stdout.write(s["stdout"])
        if s.get("stderr"):
            sys.stderr.write(s["stderr"])

    print(f"Wrote {summary_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
