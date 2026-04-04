#!/usr/bin/env python3
"""
Continuously mirror a Cursor transcript into this GitHub repo.

Outputs:
  - docs/live_conversation.md
  - docs/live_conversation.json

Optional:
  - Auto-commit + auto-push to origin/main whenever content changes.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List


REDACT_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9]{16,})"),
    re.compile(r"(xai-[A-Za-z0-9_-]{16,})"),
    re.compile(r"((?:api[_ -]?key|token)\s*[:=]\s*[A-Za-z0-9._-]{8,})", re.IGNORECASE),
]


def _redact(text: str) -> str:
    out = text
    for pat in REDACT_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def _flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
            elif isinstance(item, str) and item.strip():
                parts.append(item)
        return "\n".join(parts).strip()
    return ""


def parse_transcript(path: pathlib.Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = str(event.get("role", "")).strip().lower()
        msg = event.get("message", {})
        if not isinstance(msg, dict):
            continue
        content = _flatten_content(msg.get("content"))
        if not content:
            continue
        rows.append({"role": role or "unknown", "text": _redact(content)})
    return rows


def build_markdown(rows: List[Dict[str, str]], source_path: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out: List[str] = [
        "# Live Conversation Bridge",
        "",
        f"- Updated: `{now}`",
        f"- Source: `{source_path}`",
        f"- Messages: `{len(rows)}`",
        "",
        "## Conversation",
        "",
    ]
    for i, row in enumerate(rows, start=1):
        role = row["role"].upper()
        text = row["text"].strip()
        out.append(f"### {i}. {role}")
        out.append("")
        out.append(text)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _run_git(repo_root: pathlib.Path, args: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )


def maybe_commit_and_push(repo_root: pathlib.Path, files: List[pathlib.Path], commit_prefix: str) -> None:
    rel_files = [str(p.relative_to(repo_root)).replace("\\", "/") for p in files]
    add = _run_git(repo_root, ["add", *rel_files])
    if add.returncode != 0:
        print(f"sync_git_add_failed: {add.stderr.strip()}")
        return

    status = _run_git(repo_root, ["status", "--porcelain", "--", *rel_files])
    if status.returncode != 0 or not status.stdout.strip():
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"{commit_prefix}: {ts}"
    commit = _run_git(repo_root, ["commit", "-m", msg])
    if commit.returncode != 0:
        print(f"sync_git_commit_failed: {commit.stderr.strip()}")
        return
    push = _run_git(repo_root, ["push", "origin", "main"])
    if push.returncode != 0:
        print(f"sync_git_push_failed: {push.stderr.strip()}")
        return
    print("sync_pushed: origin/main")


def write_outputs(repo_root: pathlib.Path, transcript_path: pathlib.Path, rows: List[Dict[str, str]]) -> List[pathlib.Path]:
    docs_dir = repo_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    md_path = docs_dir / "live_conversation.md"
    json_path = docs_dir / "live_conversation.json"
    md_path.write_text(build_markdown(rows, str(transcript_path)), encoding="utf-8")
    payload = {
        "updated_at": datetime.now().isoformat(),
        "source": str(transcript_path),
        "message_count": len(rows),
        "messages": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return [md_path, json_path]


def main() -> int:
    parser = argparse.ArgumentParser(description="Live transcript -> GitHub sync bridge")
    parser.add_argument("--transcript", required=True, help="Path to transcript .jsonl")
    parser.add_argument("--repo-root", default=".", help="Repo root path")
    parser.add_argument("--watch", action="store_true", help="Run continuously")
    parser.add_argument("--interval-s", type=float, default=2.0, help="Watch poll interval")
    parser.add_argument("--auto-push", action="store_true", help="Auto commit+push updates")
    parser.add_argument("--commit-prefix", default="sync(conversation)", help="Commit message prefix")
    args = parser.parse_args()

    repo_root = pathlib.Path(args.repo_root).resolve()
    transcript_path = pathlib.Path(args.transcript).resolve()

    last_sig = ""
    while True:
        try:
            rows = parse_transcript(transcript_path)
            sig = f"{len(rows)}:{hash(rows[-1]['text']) if rows else 0}"
            if sig != last_sig:
                files = write_outputs(repo_root, transcript_path, rows)
                print(f"sync_updated messages={len(rows)}")
                if args.auto_push:
                    maybe_commit_and_push(repo_root, files, args.commit_prefix)
                last_sig = sig
        except KeyboardInterrupt:
            print("sync_stopped")
            return 0
        except Exception as exc:
            print(f"sync_error: {exc}")

        if not args.watch:
            return 0
        time.sleep(max(0.5, float(args.interval_s)))


if __name__ == "__main__":
    raise SystemExit(main())

