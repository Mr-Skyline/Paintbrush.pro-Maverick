from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class PromoteSummary:
    source_weights: Path
    promoted_weights: Path
    config_path: Path
    yolo_enabled: bool
    model_path_written: str


def promote_wall_model(
    *,
    weights_path: Path,
    model_store_dir: Path,
    config_path: Path,
    promoted_name: str = "wall_detector.pt",
    enable_yolo: bool = True,
) -> PromoteSummary:
    src = weights_path.resolve()
    if not src.exists():
        raise FileNotFoundError(f"Weights path not found: {src}")

    model_store_dir = model_store_dir.resolve()
    model_store_dir.mkdir(parents=True, exist_ok=True)
    dst = (model_store_dir / promoted_name).resolve()
    shutil.copy2(src, dst)

    cfg_path = config_path.resolve()
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config path not found: {cfg_path}")
    cfg: dict[str, Any] = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    detection = cfg.setdefault("detection", {})
    walls = detection.setdefault("walls", {})
    yolo_cfg = walls.setdefault("yolo", {})
    yolo_cfg["enabled"] = bool(enable_yolo)
    yolo_cfg["model_path"] = str(dst)
    if "confidence_threshold" not in yolo_cfg:
        yolo_cfg["confidence_threshold"] = 0.25

    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    return PromoteSummary(
        source_weights=src,
        promoted_weights=dst,
        config_path=cfg_path,
        yolo_enabled=bool(enable_yolo),
        model_path_written=str(dst),
    )

