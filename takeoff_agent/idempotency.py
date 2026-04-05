from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def config_fingerprint(config: dict[str, Any]) -> str:
    """
    Build a stable digest for config-driven behavior.
    """
    payload = {
        "preprocess": config.get("preprocess", {}),
        "scale": config.get("scale", {}),
        "detection": config.get("detection", {}),
        "retry": config.get("retry", {}),
        "postprocess": config.get("postprocess", {}),
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def build_idempotency_key(
    *,
    project_id: str,
    input_path: str | Path,
    config: dict[str, Any],
    agent_version: str = "dev",
) -> str:
    resolved_input = str(Path(input_path).resolve())
    cfg_hash = config_fingerprint(config)
    material = "\0".join([project_id, resolved_input, cfg_hash, agent_version])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()

