from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _first_present(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def _bool_value(raw: dict[str, Any], keys: tuple[str, ...], default: bool) -> bool:
    value = _first_present(raw, keys)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def _load_items(queue_path: Path) -> list[BatchItem]:
    payload = json.loads(queue_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if "items" in payload:
            raw_items = payload["items"]
        elif "jobs" in payload:
            raw_items = payload["jobs"]
        elif "queue" in payload:
            raw_items = payload["queue"]
        elif any(k in payload for k in ("input", "input_path", "source")):
            raw_items = [payload]
        else:
            raise ValueError(
                "Queue object must contain one of: items, jobs, queue, "
                "or a single job shape with input/input_path/source."
            )
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raise ValueError("Queue file must be a JSON object or array.")

    if not isinstance(raw_items, list):
        raise ValueError("Queue jobs/items value must be a JSON array.")
    if not raw_items:
        raise ValueError("Queue file contains zero jobs.")

    seen_ids: set[str] = set()
    items: list[BatchItem] = []
    for idx, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(f"Queue entry at index {idx} must be an object.")
        item_id = str(raw.get("id") or f"job-{idx + 1}")
        if item_id in seen_ids:
            raise ValueError(f"Duplicate job id '{item_id}' found in queue.")
        seen_ids.add(item_id)
        input_value = _first_present(raw, ("input", "input_path", "source"))
        out_value = _first_present(raw, ("out", "output", "output_dir"))
        if input_value is None:
            raise ValueError(
                f"Queue job '{item_id}' is missing input. "
                "Expected one of: input, input_path, source."
            )
        if out_value is None:
            raise ValueError(
                f"Queue job '{item_id}' is missing output directory. "
                "Expected one of: out, output, output_dir."
            )
        config_value = _first_present(raw, ("config", "config_path")) or "takeoff_agent/config.yaml"
        project_id_value = _first_present(raw, ("project_id", "project", "projectId")) or item_id
        items.append(
            BatchItem(
                id=item_id,
                project_id=str(project_id_value),
                input_path=Path(str(input_value)).resolve(),
                output_dir=Path(str(out_value)).resolve(),
                config_path=Path(str(config_value)).resolve(),
                save_overlays=_bool_value(raw, ("save_overlays", "saveOverlays"), True),
                save_debug_images=_bool_value(
                    raw, ("save_debug_images", "saveDebugImages"), False
                ),
                enable_supabase_handoff=_bool_value(
                    raw, ("enable_supabase_handoff", "enableSupabaseHandoff"), True
                ),
            )
        )
    return items


def _write_status(status_path: Path, payload: dict[str, Any]) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_item(item: BatchItem, *, env: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    started_utc = _now_iso()
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
    duration_seconds = round(time.perf_counter() - started, 3)
    completed_utc = _now_iso()
    return {
        "id": item.id,
        "project_id": item.project_id,
        "input": str(item.input_path),
        "out": str(item.output_dir),
        "config": str(item.config_path),
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "started_at_utc": started_utc,
        "completed_at_utc": completed_utc,
        "duration_seconds": duration_seconds,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run queued takeoff jobs."
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
        help="Maximum concurrent jobs to run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queue_path = Path(args.queue).resolve()
    status_path = Path(args.status_out).resolve()
    if not queue_path.exists():
        raise FileNotFoundError(f"Queue file not found: {queue_path}")

    items = _load_items(queue_path)
    started = time.perf_counter()
    started_utc = _now_iso()
    env = os.environ.copy()
    results: list[dict[str, Any]] = []
    max_concurrent = max(1, int(args.max_concurrent))
    if max_concurrent == 1:
        for item in items:
            results.append(_run_item(item, env=env))
    else:
        with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
            future_map = {pool.submit(_run_item, item, env=env): item for item in items}
            for future in as_completed(future_map):
                results.append(future.result())

    ordered = sorted(results, key=lambda r: str(r.get("id", "")))
    duration_seconds = round(time.perf_counter() - started, 3)
    job_durations = [float(r.get("duration_seconds", 0.0)) for r in ordered]
    average_duration = round(sum(job_durations) / len(job_durations), 3) if job_durations else 0.0
    throughput_jobs_per_min = (
        round((len(ordered) / duration_seconds) * 60, 3) if duration_seconds > 0 else 0.0
    )
    failed_job_ids = [str(r.get("id", "")) for r in ordered if not bool(r.get("ok"))]
    summary_status = "ok" if not failed_job_ids else "failed"
    for result in ordered:
        result["status"] = "ok" if result.get("ok") else "failed"

    payload = {
        "queue_path": str(queue_path),
        "started_at_utc": started_utc,
        "completed_at_utc": _now_iso(),
        "duration_seconds": duration_seconds,
        "average_job_duration_seconds": average_duration,
        "fastest_job_seconds": min(job_durations) if job_durations else 0.0,
        "slowest_job_seconds": max(job_durations) if job_durations else 0.0,
        "throughput_jobs_per_min": throughput_jobs_per_min,
        "max_concurrent": max_concurrent,
        "execution_mode": "parallel" if max_concurrent > 1 else "sequential",
        "status": summary_status,
        "jobs_total": len(items),
        "jobs_ok": sum(1 for r in ordered if r["ok"]),
        "jobs_failed": sum(1 for r in ordered if not r["ok"]),
        "failed_job_ids": failed_job_ids,
        "results": ordered,
    }
    _write_status(status_path, payload)
    print(json.dumps(payload, indent=2))
    return 0 if payload["jobs_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
