#!/usr/bin/env python3
"""
Run the non-UI trace intelligence steps in order: rulebook markdown, then replay plan JSON.

Does not touch UI lock scripts (npm run ui:lock:*). Does not start the app or replay in a browser.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run trace_rulebook_generator.py and trace_replay_plan_generator.py "
            "on the same JSONL input."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to trace JSONL (one JSON object per line).",
    )
    parser.add_argument(
        "--rulebook-output",
        type=Path,
        default=None,
        help="Markdown path for the rulebook (default: <input-stem>-trace-rulebook.md next to input).",
    )
    parser.add_argument(
        "--replay-plan-output",
        type=Path,
        default=None,
        help="JSON path for the replay plan (default: <input-stem>-trace-replay-plan.json next to input).",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter to use for sub-scripts (default: current interpreter).",
    )
    args = parser.parse_args()
    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    base = args.input.parent
    stem = args.input.stem
    rulebook_out = args.rulebook_output or (base / f"{stem}-trace-rulebook.md")
    replay_out = args.replay_plan_output or (base / f"{stem}-trace-replay-plan.json")

    here = Path(__file__).resolve().parent
    rulebook_script = here / "trace_rulebook_generator.py"
    replay_script = here / "trace_replay_plan_generator.py"

    for script in (rulebook_script, replay_script):
        if not script.is_file():
            print(f"Missing script: {script}", file=sys.stderr)
            return 1

    py = args.python
    rc1 = subprocess.run(
        [
            py,
            str(rulebook_script),
            "--input",
            str(args.input),
            "--output",
            str(rulebook_out),
        ],
        check=False,
    )
    if rc1.returncode != 0:
        return rc1.returncode

    rc2 = subprocess.run(
        [
            py,
            str(replay_script),
            "--input",
            str(args.input),
            "--output",
            str(replay_out),
        ],
        check=False,
    )
    return rc2.returncode


if __name__ == "__main__":
    raise SystemExit(main())
