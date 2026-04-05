from __future__ import annotations

import json
import os
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def log_runtime_event(
    output_dir: Path,
    *,
    event_type: str,
    payload: dict[str, Any],
    config: dict[str, Any],
) -> None:
    runtime_cfg = config.get("runtime", {})
    if not bool(runtime_cfg.get("log_to_jsonl", True)):
        return
    file_name = str(runtime_cfg.get("log_file_name", "takeoff-runtime.jsonl"))
    path = output_dir / "logs" / file_name
    append_jsonl(
        path,
        {
            "timestamp_utc": _now_iso(),
            "event_type": event_type,
            **payload,
        },
    )


def log_exception(
    stage: str,
    exc: Exception,
    *,
    output_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> None:
    message = str(exc)
    max_chars = 1000
    if config:
        max_chars = int(config.get("runtime", {}).get("max_error_preview_chars", 1000))
    trace = traceback.format_exc()
    payload = {
        "stage": stage,
        "error_type": exc.__class__.__name__,
        "message": message[:max_chars],
        "traceback": trace[: max_chars * 3],
    }
    if output_dir and config:
        log_runtime_event(output_dir, event_type="error", payload=payload, config=config)
    else:
        # Last-resort stderr output for failures before output/config init.
        print(f"[takeoff_agent:{stage}] {payload['error_type']}: {payload['message']}")


def maybe_emit_supabase_handoff(
    *,
    payload: dict[str, Any],
    output_dir: Path,
    project_id: str,
) -> Path | None:
    """
    Optional Supabase handoff artifact generator.

    This function intentionally avoids hard-failing when credentials or SDK are unavailable.
    It always writes a local handoff JSON payload. If Supabase env vars + SDK are present,
    it attempts best-effort insert + storage upload metadata.
    """
    handoff_dir = output_dir / "handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = handoff_dir / f"{project_id}-supabase-handoff.json"

    handoff_payload: dict[str, Any] = {
        "project_id": project_id,
        "created_at_utc": _now_iso(),
        "totals": payload.get("totals", {}),
        "pages_processed": payload.get("pages_processed", 0),
        "json_path": str((output_dir / "takeoff-results.json").resolve()),
        "csv_path": str((output_dir / "takeoff-results.csv").resolve()),
        "annotated_images": [
            p.get("overlay_image")
            for p in payload.get("pages", [])
            if p.get("overlay_image")
        ],
        "supabase": {
            "attempted": False,
            "insert_ok": False,
            "storage_ok": False,
            "reason": "",
        },
    }

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip() or os.getenv(
        "SUPABASE_ANON_KEY", ""
    ).strip()
    bucket = os.getenv("SUPABASE_TAKEOFF_BUCKET", "takeoffs").strip()
    table = os.getenv("SUPABASE_TAKEOFF_TABLE", "estimates").strip()

    if not url or not key:
        handoff_payload["supabase"]["reason"] = (
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_ANON_KEY not set."
        )
        handoff_path.write_text(json.dumps(handoff_payload, indent=2), encoding="utf-8")
        return handoff_path

    try:
        from supabase import Client, create_client  # type: ignore

        client: Client = create_client(url, key)
        handoff_payload["supabase"]["attempted"] = True

        row = {
            "project_id": project_id,
            "walls_ea": payload.get("totals", {}).get("walls_lf", 0),
            "ceilings_sf": payload.get("totals", {}).get("rooms_sf", 0),
            "polygons": payload.get("pages", []),
            "meta": {
                "source_input": payload.get("source_input", ""),
                "pages_processed": payload.get("pages_processed", 0),
            },
        }
        try:
            client.table(table).insert(row).execute()
            handoff_payload["supabase"]["insert_ok"] = True
        except Exception as insert_exc:
            handoff_payload["supabase"]["reason"] = f"table insert failed: {insert_exc}"

        # Best-effort upload of annotated images if they exist.
        try:
            for img_path in handoff_payload["annotated_images"]:
                if not img_path:
                    continue
                p = Path(img_path)
                if not p.exists():
                    continue
                with p.open("rb") as handle:
                    client.storage.from_(bucket).upload(
                        path=f"{project_id}/{p.name}",
                        file=handle.read(),
                        file_options={"content-type": "image/png", "upsert": "true"},
                    )
            handoff_payload["supabase"]["storage_ok"] = True
        except Exception as storage_exc:
            reason = handoff_payload["supabase"].get("reason", "")
            extra = f"storage upload failed: {storage_exc}"
            handoff_payload["supabase"]["reason"] = (
                f"{reason} | {extra}" if reason else extra
            )
    except Exception as exc:
        handoff_payload["supabase"]["reason"] = f"client init failed: {exc}"

    handoff_path.write_text(json.dumps(handoff_payload, indent=2), encoding="utf-8")
    return handoff_path
