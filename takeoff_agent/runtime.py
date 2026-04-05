from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RuntimeArtifacts:
    output_dir: Path
    logs_dir: Path
    errors_path: Path


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_runtime_dirs(output_dir: Path) -> RuntimeArtifacts:
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    errors_path = logs_dir / "errors.jsonl"
    return RuntimeArtifacts(output_dir=output_dir, logs_dir=logs_dir, errors_path=errors_path)


def configure_logger(artifacts: RuntimeArtifacts) -> logging.Logger:
    logger = logging.getLogger("takeoff_agent")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    file_handler = logging.FileHandler(artifacts.logs_dir / "run.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def append_error_log(
    artifacts: RuntimeArtifacts,
    *,
    project_id: str,
    page_index: int,
    error_type: str,
    stage: str,
    message: str,
    confidence: float | None = None,
) -> None:
    payload: dict[str, Any] = {
        "timestamp_utc": _now_iso(),
        "project_id": project_id,
        "page_index": page_index,
        "stage": stage,
        "error_type": error_type,
        "message": message,
    }
    if confidence is not None:
        payload["confidence"] = confidence

    with artifacts.errors_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def maybe_emit_supabase_handoff(
    *,
    payload: dict[str, Any],
    output_dir: Path,
    project_id: str,
    logger: logging.Logger | None = None,
) -> Path:
    """
    Optional Supabase handoff artifact generator.

    This path must never block local runs. It always writes local handoff JSON.
    If env vars + SDK are available, it also performs best-effort inserts/uploads.
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
        if logger:
            logger.info("supabase handoff skipped: missing env vars")
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
    if logger:
        logger.info("supabase handoff artifact written: %s", handoff_path)
    return handoff_path
