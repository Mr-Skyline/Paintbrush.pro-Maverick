from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


ROBOFLOW_UPLOAD_ENDPOINT = "https://api.roboflow.com/dataset/{project}/upload"


@dataclass(slots=True)
class RoboflowProjectConfig:
    api_key: str
    project: str
    workspace: str | None = None


@dataclass(slots=True)
class UploadSummary:
    found: int
    uploaded: int
    failed: int
    manifest_path: Path


def load_roboflow_config(
    *, api_key: str | None = None, project: str | None = None, workspace: str | None = None
) -> RoboflowProjectConfig:
    resolved_api_key = (api_key or os.getenv("ROBOFLOW_API_KEY", "")).strip()
    resolved_project = (project or os.getenv("ROBOFLOW_PROJECT", "")).strip()
    resolved_workspace = (workspace or os.getenv("ROBOFLOW_WORKSPACE", "")).strip() or None
    if not resolved_api_key:
        raise ValueError("Missing ROBOFLOW_API_KEY.")
    if not resolved_project:
        raise ValueError("Missing ROBOFLOW_PROJECT (slug).")
    return RoboflowProjectConfig(
        api_key=resolved_api_key, project=resolved_project, workspace=resolved_workspace
    )


def upload_image(
    *,
    image_path: Path,
    cfg: RoboflowProjectConfig,
    split: str,
    batch: str,
    annotation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    params: dict[str, Any] = {
        "api_key": cfg.api_key,
        "name": image_path.stem,
        "split": split,
        "batch": batch,
    }
    if annotation is not None:
        params["annotation"] = json.dumps(annotation)
        params["annotation_type"] = "coco"

    with image_path.open("rb") as handle:
        response = requests.post(
            ROBOFLOW_UPLOAD_ENDPOINT.format(project=cfg.project),
            params=params,
            files={"file": (image_path.name, handle, "image/png")},
            timeout=120,
        )
    response.raise_for_status()
    return response.json()


def upload_images(
    *,
    images_dir: Path,
    workspace: str = "",
    project: str = "",
    api_key: str = "",
    split: str = "train",
    limit: int = 0,
    dry_run: bool = False,
) -> UploadSummary:
    images = sorted(
        [
            p
            for p in images_dir.glob("*")
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
    )
    if limit > 0:
        images = images[:limit]

    manifest_path = images_dir / "roboflow-upload-manifest.jsonl"
    found = len(images)
    uploaded = 0
    failed = 0

    if dry_run:
        for image in images:
            with manifest_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "image": str(image),
                            "status": "dry_run",
                            "split": split,
                        }
                    )
                    + "\n"
                )
        return UploadSummary(
            found=found, uploaded=0, failed=0, manifest_path=manifest_path
        )

    cfg = load_roboflow_config(api_key=api_key, project=project, workspace=workspace)
    batch = images_dir.name
    for image in images:
        try:
            response = upload_image(
                image_path=image,
                cfg=cfg,
                split=split,
                batch=batch,
                annotation=None,
            )
            uploaded += 1
            record = {
                "image": str(image),
                "status": "uploaded",
                "response": response,
            }
        except Exception as exc:
            failed += 1
            record = {
                "image": str(image),
                "status": "failed",
                "error": str(exc),
            }
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    return UploadSummary(
        found=found, uploaded=uploaded, failed=failed, manifest_path=manifest_path
    )
