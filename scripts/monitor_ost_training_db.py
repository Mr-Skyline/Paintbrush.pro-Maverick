#!/usr/bin/env python3
"""
Monitor a target file and emit change events.

Default target:
  C:\\OCS Documents\\OST\\Training Playground.mdb
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
from datetime import datetime, timezone
from typing import Any, Dict


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stat_snapshot(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    st = path.stat()
    return {
        "exists": True,
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
    }


def append_jsonl(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor OST training MDB for changes")
    parser.add_argument(
        "--file",
        default=r"C:\OCS Documents\OST\Training Playground.mdb",
        help="File path to monitor",
    )
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=2000,
        help="Polling interval in milliseconds",
    )
    parser.add_argument(
        "--log",
        default="output/ost-training-db-monitor.jsonl",
        help="Output JSONL log path",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=int,
        default=60,
        help="Emit heartbeat event every N seconds",
    )
    args = parser.parse_args()

    file_path = pathlib.Path(args.file)
    log_path = pathlib.Path(args.log)
    interval_s = max(0.2, args.interval_ms / 1000.0)
    heartbeat_s = max(5, args.heartbeat_seconds)

    prev = stat_snapshot(file_path)
    started = {
        "ts": iso_now(),
        "event": "monitor_started",
        "file": str(file_path),
        "interval_ms": int(interval_s * 1000),
        "initial": prev,
    }
    append_jsonl(log_path, started)
    print(f"[monitor] started file={file_path}")

    last_heartbeat = time.time()
    while True:
        current = stat_snapshot(file_path)
        if current != prev:
            evt = {
                "ts": iso_now(),
                "event": "file_changed",
                "file": str(file_path),
                "previous": prev,
                "current": current,
            }
            append_jsonl(log_path, evt)
            print(
                "[monitor] change detected "
                f"exists={current.get('exists')} size={current.get('size')} mtime_ns={current.get('mtime_ns')}"
            )
            prev = current

        now = time.time()
        if now - last_heartbeat >= heartbeat_s:
            hb = {
                "ts": iso_now(),
                "event": "heartbeat",
                "file": str(file_path),
                "state": current,
            }
            append_jsonl(log_path, hb)
            print("[monitor] heartbeat")
            last_heartbeat = now
        time.sleep(interval_s)


if __name__ == "__main__":
    raise SystemExit(main())
