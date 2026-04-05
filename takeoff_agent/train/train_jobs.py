from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

@dataclass(slots=True)
class TrainJobSummary:
    run_dir: Path
    mode: str
    ok: bool
    best_weights: Path | None
    results_path: Path | None
    metrics: dict[str, Any]
    note: str


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _count_images(data_yaml_path: Path) -> int:
    import yaml

    payload = yaml.safe_load(data_yaml_path.read_text(encoding="utf-8")) or {}
    base = Path(str(payload.get("path", "."))).resolve()
    total = 0
    for split in ("train", "val", "test"):
        rel = str(payload.get(split, "")).strip()
        if not rel:
            continue
        folder = (base / rel).resolve()
        if not folder.exists():
            continue
        total += len(
            [
                p
                for p in folder.glob("*")
                if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            ]
        )
    return total


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_yolo_train_job(
    *,
    data_yaml: Path,
    out_root: Path,
    model: str = "yolov8n.pt",
    epochs: int = 20,
    imgsz: int = 1024,
    batch: int = 8,
    device: str = "cpu",
    workers: int = 2,
) -> TrainJobSummary:
    """
    Run a YOLO training job if dataset size is viable, else create a dry-run artifact.

    This keeps autonomous workflow unblocked even before sufficient labeled data exists.
    """
    data_yaml = data_yaml.resolve()
    out_root = out_root.resolve()
    run_dir = out_root / f"train_{_now_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    image_count = _count_images(data_yaml)
    if image_count < 5:
        summary = {
            "mode": "dry_run",
            "ok": True,
            "reason": "insufficient_images_for_training",
            "image_count": image_count,
            "min_required": 5,
            "data_yaml": str(data_yaml),
            "recommendation": (
                "Add at least 5 labeled images before real YOLO training. "
                "Keep adding to train/val/test and rerun train-yolo."
            ),
        }
        _write_json(run_dir / "summary.json", summary)
        return TrainJobSummary(
            run_dir=run_dir,
            mode="dry_run",
            ok=True,
            best_weights=None,
            results_path=run_dir / "summary.json",
            metrics={"image_count": image_count},
            note="Dry-run generated due to low image count.",
        )

    try:
        from ultralytics import YOLO  # type: ignore
    except Exception as exc:
        summary = {
            "mode": "train_failed",
            "ok": False,
            "reason": "ultralytics_import_error",
            "error": str(exc),
            "data_yaml": str(data_yaml),
        }
        _write_json(run_dir / "summary.json", summary)
        return TrainJobSummary(
            run_dir=run_dir,
            mode="train_failed",
            ok=False,
            best_weights=None,
            results_path=run_dir / "summary.json",
            metrics={},
            note=f"Ultralytics import failed: {exc}",
        )

    model_obj = YOLO(model)
    results = model_obj.train(
        data=str(data_yaml),
        epochs=int(epochs),
        imgsz=int(imgsz),
        batch=int(batch),
        device=device,
        workers=int(workers),
        project=str(out_root),
        name=run_dir.name,
        verbose=False,
    )

    # Ultralytics writes under project/name; ensure we point there.
    realized_run_dir = Path(getattr(results, "save_dir", run_dir)).resolve()
    weights_best = realized_run_dir / "weights" / "best.pt"
    results_csv = realized_run_dir / "results.csv"
    summary = {
        "mode": "train",
        "ok": weights_best.exists(),
        "data_yaml": str(data_yaml),
        "weights_best": str(weights_best) if weights_best.exists() else "",
        "results_csv": str(results_csv) if results_csv.exists() else "",
        "image_count": image_count,
    }
    _write_json(realized_run_dir / "summary.json", summary)

    return TrainJobSummary(
        run_dir=realized_run_dir,
        mode="train",
        ok=bool(summary["ok"]),
        best_weights=weights_best if weights_best.exists() else None,
        results_path=results_csv if results_csv.exists() else (realized_run_dir / "summary.json"),
        metrics={"image_count": image_count},
        note="YOLO training completed." if summary["ok"] else "YOLO training finished without best.pt",
    )


def run_yolo_training_job(
    *,
    data_yaml: Path,
    model_name: str,
    epochs: int,
    imgsz: int,
    batch: int,
    device: str,
    project_dir: Path,
    run_name: str,
    dry_run: bool,
) -> dict[str, Any]:
    """
    CLI-friendly wrapper returning JSON-serializable output.
    """
    out_root = project_dir / run_name
    if dry_run:
        out_root.mkdir(parents=True, exist_ok=True)
        summary_path = out_root / "summary.json"
        _write_json(
            summary_path,
            {
                "mode": "dry_run",
                "ok": True,
                "data_yaml": str(data_yaml.resolve()),
                "model": model_name,
                "epochs": epochs,
                "imgsz": imgsz,
                "batch": batch,
                "device": device,
            },
        )
        return {
            "run_dir": str(out_root),
            "mode": "dry_run",
            "ok": True,
            "best_weights": "",
            "results_path": str(summary_path),
            "metrics": {},
            "note": "Dry-run metadata created.",
        }

    summary = run_yolo_train_job(
        data_yaml=data_yaml,
        out_root=project_dir,
        model=model_name,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
    )
    return {
        "run_dir": str(summary.run_dir),
        "mode": summary.mode,
        "ok": summary.ok,
        "best_weights": str(summary.best_weights) if summary.best_weights else "",
        "results_path": str(summary.results_path) if summary.results_path else "",
        "metrics": summary.metrics,
        "note": summary.note,
    }


def promote_model_weights(
    *,
    weights_path: Path,
    target_dir: Path,
    config_path: Path,
    target_filename: str,
    enable_yolo: bool,
) -> dict[str, Any]:
    src = weights_path.resolve()
    if not src.exists():
        raise FileNotFoundError(f"Weights file not found: {src}")

    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = (target_dir / target_filename).resolve()
    dst.write_bytes(src.read_bytes())

    cfg_path = config_path.resolve()
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config path not found: {cfg_path}")
    cfg: dict[str, Any] = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    detection = cfg.setdefault("detection", {})
    walls = detection.setdefault("walls", {})
    yolo_cfg = walls.setdefault("yolo", {})
    yolo_cfg["model_path"] = str(dst)
    yolo_cfg["wall_model_path"] = str(dst)
    yolo_cfg.setdefault("confidence_threshold", 0.25)
    yolo_cfg.setdefault("confidence", yolo_cfg["confidence_threshold"])
    if enable_yolo:
        yolo_cfg["enabled"] = True
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    summary = {
        "source_weights": str(src),
        "promoted_weights": str(dst),
        "config_path": str(cfg_path),
        "yolo_enabled": bool(yolo_cfg.get("enabled", False)),
        "model_path_written": str(dst),
    }
    _write_json(target_dir / "last_promotion.json", summary)
    return summary
