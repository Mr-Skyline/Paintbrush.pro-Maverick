from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class FreshDatasetLayout:
    root: Path
    images_train: Path
    images_val: Path
    images_test: Path
    labels_train: Path
    labels_val: Path
    labels_test: Path
    labels_template: Path
    manifest_path: Path


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def initialize_fresh_dataset(root: Path, *, project_name: str) -> FreshDatasetLayout:
    """
    Create a brand-new, empty dataset scaffold for Roboflow/YOLO workflows.

    This intentionally does not import historical output runs. It creates
    directories + template metadata only.
    """
    root = root.resolve()
    images_train = root / "images" / "train"
    images_val = root / "images" / "val"
    images_test = root / "images" / "test"
    labels_train = root / "labels" / "train"
    labels_val = root / "labels" / "val"
    labels_test = root / "labels" / "test"
    labels_template = root / "labels_template.txt"
    manifest_path = root / "manifest.json"

    for path in [
        images_train,
        images_val,
        images_test,
        labels_train,
        labels_val,
        labels_test,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    if not labels_template.exists():
        labels_template.write_text(
            "\n".join(
                [
                    "# YOLO label format per line:",
                    "# <class_id> <x_center> <y_center> <width> <height>",
                    "# values are normalized 0..1",
                    "# class ids:",
                    "# 0 exterior_wall",
                    "# 1 interior_wall",
                    "# 2 door",
                    "# 3 window",
                    "# 4 fixture",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    if not manifest_path.exists():
        manifest_path.write_text(
            json.dumps(
                {
                    "project_name": project_name,
                    "created_at_utc": _now_iso(),
                    "notes": "Fresh-start dataset scaffold. Add files manually or via uploader.",
                    "classes": [
                        "exterior_wall",
                        "interior_wall",
                        "door",
                        "window",
                        "fixture",
                    ],
                    "samples": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return FreshDatasetLayout(
        root=root,
        images_train=images_train,
        images_val=images_val,
        images_test=images_test,
        labels_train=labels_train,
        labels_val=labels_val,
        labels_test=labels_test,
        labels_template=labels_template,
        manifest_path=manifest_path,
    )


def add_image_to_split(
    dataset_root: Path,
    *,
    image_path: Path,
    split: str,
    class_names: list[str] | None = None,
) -> Path:
    """
    Copy one image into the dataset split and create an empty label file.
    """
    split_norm = split.strip().lower()
    if split_norm not in {"train", "val", "test"}:
        raise ValueError("split must be one of: train, val, test")
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    images_dir = dataset_root / "images" / split_norm
    labels_dir = dataset_root / "labels" / split_norm
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    target_image = images_dir / image_path.name
    target_image.write_bytes(image_path.read_bytes())

    target_label = labels_dir / f"{image_path.stem}.txt"
    if not target_label.exists():
        target_label.write_text("", encoding="utf-8")

    manifest_path = dataset_root / "manifest.json"
    if manifest_path.exists():
        payload: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        samples = payload.setdefault("samples", [])
        samples.append(
            {
                "added_at_utc": _now_iso(),
                "file_name": image_path.name,
                "split": split_norm,
                "label_path": f"labels/{split_norm}/{image_path.stem}.txt",
                "image_path": f"images/{split_norm}/{image_path.name}",
                "classes_hint": class_names
                if class_names
                else ["exterior_wall", "interior_wall", "door", "window", "fixture"],
            }
        )
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return target_image

