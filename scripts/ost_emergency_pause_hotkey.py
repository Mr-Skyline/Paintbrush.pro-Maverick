#!/usr/bin/env python3
"""
Global emergency pause hotkey for Maverick/OST automation.

Trigger: press SPACE 3 times quickly (within --window-ms).
Action: write pause flag + terminate active workspace automation processes.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import pathlib
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List


VK_SPACE = 0x20
DEFAULT_PAUSE_FLAG_REL = pathlib.Path("output/maverick/emergency_pause.flag")


def now_iso() -> str:
    return datetime.now().isoformat()


def workspace_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def pause_flag_path(root: pathlib.Path | None = None) -> pathlib.Path:
    raw = str(os.environ.get("MAVERICK_EMERGENCY_PAUSE_FLAG", "") or "").strip()
    if raw:
        p = pathlib.Path(raw)
        return p if p.is_absolute() else (root or workspace_root()) / p
    return (root or workspace_root()) / DEFAULT_PAUSE_FLAG_REL


def write_pause_flag(reason: str, root: pathlib.Path | None = None) -> pathlib.Path:
    flag = pause_flag_path(root)
    flag.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": now_iso(),
        "reason": reason,
        "by": "triple_space_hotkey",
    }
    flag.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return flag


def clear_pause_flag(root: pathlib.Path | None = None) -> bool:
    flag = pause_flag_path(root)
    if flag.exists():
        flag.unlink(missing_ok=True)
        return True
    return False


def _list_workspace_python_processes(root: pathlib.Path) -> Dict[str, Any]:
    root_token = str(root).replace("'", "''")
    # Match either absolute workspace path OR known automation script tokens.
    cmd = (
        "Get-CimInstance Win32_Process "
        "| Where-Object { "
        "  ($_.Name -match '^python(\\.exe|w\\.exe)?$') "
        "  -and ("
        f"    ($_.CommandLine -like '*{root_token}*') "
        "    -or ($_.CommandLine -match 'scripts[\\\\/](ost_|maverick_)') "
        "    -or ($_.CommandLine -match 'ost_.*\\.py') "
        "    -or ($_.CommandLine -match 'maverick_.*\\.py') "
        "  ) "
        "} "
        "| Select-Object ProcessId, Name, CommandLine "
        "| ConvertTo-Json -Depth 4 -Compress"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if int(proc.returncode or 0) != 0:
        return {"ok": False, "processes": [], "stderr": str(proc.stderr or "").strip()}
    raw = (proc.stdout or "").strip()
    if not raw:
        return {"ok": True, "processes": []}
    try:
        data = json.loads(raw)
    except Exception:
        return {"ok": False, "processes": [], "stderr": "process_list_json_parse_failed"}
    if isinstance(data, dict):
        return {"ok": True, "processes": [data]}
    if isinstance(data, list):
        return {"ok": True, "processes": [x for x in data if isinstance(x, dict)]}
    return {"ok": False, "processes": [], "stderr": "process_list_payload_invalid"}


def _taskkill_pid(pid: int, retries: int = 2) -> bool:
    for _ in range(max(1, int(retries))):
        tk = subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if int(tk.returncode or 1) == 0:
            return True
        time.sleep(0.12)
    return False


def pause_everything(root: pathlib.Path, reason: str = "triple_space") -> Dict[str, Any]:
    this_pid = os.getpid()
    flag = write_pause_flag(reason, root=root)
    scan = _list_workspace_python_processes(root)
    procs = scan.get("processes", []) if isinstance(scan.get("processes", []), list) else []
    killed: List[int] = []
    failed: List[int] = []
    skipped: List[int] = []
    scanned = 0

    for row in procs:
        scanned += 1
        pid = int(row.get("ProcessId", 0) or 0)
        cmdline = str(row.get("CommandLine", "") or "")
        if pid <= 0 or pid == this_pid:
            if pid > 0:
                skipped.append(pid)
            continue
        if "ost_emergency_pause_hotkey.py" in cmdline:
            skipped.append(pid)
            continue
        if _taskkill_pid(pid, retries=3):
            killed.append(pid)
        else:
            failed.append(pid)

    still_failed: List[int] = []
    if failed:
        # One more sweep for flaky process states.
        time.sleep(0.15)
        for pid in failed:
            if _taskkill_pid(pid, retries=2):
                killed.append(pid)
            else:
                still_failed.append(pid)

    return {
        "ok": bool(len(still_failed) == 0),
        "reason": reason,
        "workspace_root": str(root),
        "pause_flag": str(flag),
        "killed_pids": killed,
        "failed_pids": still_failed,
        "skipped_pids": skipped,
        "scan_ok": bool(scan.get("ok", False)),
        "scan_stderr": str(scan.get("stderr", "") or ""),
        "scanned_process_count": int(scanned),
    }


def watch_triple_space(window_ms: int, poll_ms: int, cooldown_ms: int) -> int:
    user32 = ctypes.windll.user32
    space_down = False
    press_times: List[float] = []
    cooldown_until = 0.0
    root = workspace_root()

    print(
        json.dumps(
            {
                "ok": True,
                "mode": "watch",
                "trigger": "space_x3",
                "window_ms": int(window_ms),
                "poll_ms": int(poll_ms),
                "cooldown_ms": int(cooldown_ms),
                "workspace": str(root),
            }
        )
    )

    while True:
        now = time.monotonic()
        key_down = bool(user32.GetAsyncKeyState(VK_SPACE) & 0x8000)

        if key_down and not space_down:
            # Rising edge = one key press.
            press_times.append(now)
            threshold = now - (float(window_ms) / 1000.0)
            press_times = [t for t in press_times if t >= threshold]
            if len(press_times) >= 3 and now >= cooldown_until:
                res = pause_everything(root, reason="triple_space")
                res["triggered_at"] = now_iso()
                print(json.dumps(res))
                press_times.clear()
                cooldown_until = now + (float(cooldown_ms) / 1000.0)

        space_down = key_down
        time.sleep(max(0.01, float(poll_ms) / 1000.0))


def main() -> int:
    parser = argparse.ArgumentParser(description="Emergency triple-space pause hotkey")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_watch = sub.add_parser("watch", help="Watch global triple-space trigger")
    p_watch.add_argument("--window-ms", type=int, default=1200)
    p_watch.add_argument("--poll-ms", type=int, default=30)
    p_watch.add_argument("--cooldown-ms", type=int, default=1800)

    sub.add_parser("pause-now", help="Pause everything immediately")
    sub.add_parser("clear", help="Clear emergency pause flag")
    args = parser.parse_args()

    if args.cmd == "watch":
        return watch_triple_space(
            window_ms=max(250, int(args.window_ms)),
            poll_ms=max(10, int(args.poll_ms)),
            cooldown_ms=max(300, int(args.cooldown_ms)),
        )
    if args.cmd == "pause-now":
        print(json.dumps(pause_everything(workspace_root(), reason="pause_now_cli"), indent=2))
        return 0
    if args.cmd == "clear":
        root = workspace_root()
        print(
            json.dumps(
                {"ok": True, "cleared": clear_pause_flag(root=root), "pause_flag": str(pause_flag_path(root=root))},
                indent=2,
            )
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

