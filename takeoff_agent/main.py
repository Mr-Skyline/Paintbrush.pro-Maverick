from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from detection import detect_blueprint_geometry
from postprocess import build_takeoff_result
from preprocess import decode_input_to_image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("takeoff-agent")

APP_VERSION = "0.1.0"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


class TakeoffRequest(BaseModel):
    project_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    mime_type: str = "application/octet-stream"
    file_base64: str = Field(min_length=1)


def _load_config() -> dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


CONFIG = _load_config()
app = FastAPI(title="Paintbrush CV Service", version=APP_VERSION)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "paintbrush-takeoff-cv",
        "version": APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/v1/takeoff/process")
def process_takeoff(payload: TakeoffRequest) -> dict[str, Any]:
    try:
        img = decode_input_to_image(payload.file_base64, payload.mime_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    detections = detect_blueprint_geometry(img, CONFIG)
    result = build_takeoff_result(
        project_id=payload.project_id,
        source_name=payload.source_name,
        detections=detections,
        config=CONFIG,
    )
    return {"result": result}


@app.post("/api/v1/chat/reply")
def chat_reply(body: dict[str, Any]) -> dict[str, str]:
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="message required")
    # Lightweight deterministic fallback reply for sidekick integrations.
    return {"reply": f"Received: {message[:200]} | Takeoff agent is active."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
