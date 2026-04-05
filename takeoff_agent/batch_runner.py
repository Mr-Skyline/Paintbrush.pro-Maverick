from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BatchItem:
    id: str
    project_id: str
    input_path: Path
    output_dir: Path
    config_path: Path
    save_overlays: bool
    save_debug_images: bool
    enable_supabase_handoff: bool


def _load_items(queue_path: Path) -> list[BatchItem]:
    payload = json.loads(queue_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_items = payload.get("items", payload.get("jobs", []))
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raise ValueError("Queue file must be a JSON object or array.")

    items: list[BatchItem] = []
    for idx, raw in enumerate(raw_items):
        item_id = str(raw.get("id") or f"job-{idx + 1}")
        items.append(
            BatchItem(
                id=item_id,
                project_id=str(raw.get("project_id") or item_id),
                input_path=Path(str(raw["input"])).resolve(),
                output_dir=Path(str(raw["out"])).resolve(),
                config_path=Path(str(raw.get("config") or "takeoff_agent/config.yaml")).resolve(),
                save_overlays=bool(raw.get("save_overlays", True)),
                save_debug_images=bool(raw.get("save_debug_images", False)),
                enable_supabase_handoff=bool(raw.get("enable_supabase_handoff", True)),
            )
        )
    return items


def _write_status(status_path: Path, payload: dict[str, Any]) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_item(item: BatchItem, *, env: dict[str, str]) -> dict[str, Any]:
    cmd = [
        "python3",
        "-m",
        "takeoff_agent.main",
        "--input",
        str(item.input_path),
        "--config",
        str(item.config_path),
        "--out",
        str(item.output_dir),
        "--project-id",
        item.project_id,
    ]
    if item.save_overlays:
        cmd.append("--save-overlays")
    if item.save_debug_images:
        cmd.append("--save-debug-images")
    if item.enable_supabase_handoff:
        cmd.append("--enable-supabase-handoff")

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return {
        "id": item.id,
        "project_id": item.project_id,
        "input": str(item.input_path),
        "out": str(item.output_dir),
        "config": str(item.config_path),
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run queued takeoff jobs (sequential runner)."
    )
    parser.add_argument("--queue", required=True, help="Path to queue JSON file.")
    parser.add_argument(
        "--status-out",
        default="output/takeoff-batch/latest-status.json",
        help="Path for batch status JSON output.",
    )
    # Accepted for compatibility with future parallel runner mode.
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=1,
        help="Compatibility flag; current runner executes sequentially.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queue_path = Path(args.queue).resolve()
    status_path = Path(args.status_out).resolve()
    if not queue_path.exists():
        raise FileNotFoundError(f"Queue file not found: {queue_path}")

    items = _load_items(queue_path)
    env = os.environ.copy()
    results: list[dict[str, Any]] = []
    if int(args.max_concurrent) > 1:
        print(
            json.dumps(
                {
                    "warning": "Current batch runner is sequential; max-concurrent is ignored.",
                    "max_concurrent": int(args.max_concurrent),
                }
            )
        )
    for item in items:
        result = _run_item(item, env=env)
        results.append(result)

    payload = {
        "queue_path": str(queue_path),
        "jobs_total": len(items),
        "jobs_ok": sum(1 for r in results if r["ok"]),
        "jobs_failed": sum(1 for r in results if not r["ok"]),
        "results": results,
    }
    _write_status(status_path, payload)
    print(json.dumps(payload, indent=2))
    return 0 if payload["jobs_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
