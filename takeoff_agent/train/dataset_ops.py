from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DataYamlSummary:
    data_yaml_path: Path
    classes: list[str]
    train_count: int
    val_count: int
    test_count: int


def _count_images(images_dir: Path) -> int:
    return len(
        [
            p
            for p in images_dir.glob("*")
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
    )


def _extract_classes_from_manifest(dataset_root: Path) -> list[str]:
    manifest = dataset_root / "manifest.json"
    if not manifest.exists():
        return [
            "exterior_wall",
            "interior_wall",
            "door",
            "window",
            "fixture",
        ]
    payload: dict[str, Any] = json.loads(manifest.read_text(encoding="utf-8"))
    classes = payload.get("classes", [])
    if not isinstance(classes, list) or not classes:
        return [
            "exterior_wall",
            "interior_wall",
            "door",
            "window",
            "fixture",
        ]
    return [str(c) for c in classes]


def generate_yolo_data_yaml(
    dataset_root: Path,
    *,
    output_path: Path | None = None,
    class_names: list[str] | None = None,
) -> DataYamlSummary:
    """
    Generate a YOLO-compatible data.yaml from fresh dataset folders.
    """
    dataset_root = dataset_root.resolve()
    images_root = dataset_root / "images"
    train_dir = images_root / "train"
    val_dir = images_root / "val"
    test_dir = images_root / "test"
    for p in [train_dir, val_dir, test_dir]:
        p.mkdir(parents=True, exist_ok=True)

    names = class_names if class_names else _extract_classes_from_manifest(dataset_root)
    out = output_path.resolve() if output_path else (dataset_root / "data.yaml")

    yaml_lines = [
        f"path: {dataset_root.as_posix()}",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        "",
        f"nc: {len(names)}",
        "names:",
    ]
    for idx, name in enumerate(names):
        yaml_lines.append(f"  {idx}: {name}")
    out.write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

    return DataYamlSummary(
        data_yaml_path=out,
        classes=names,
        train_count=_count_images(train_dir),
        val_count=_count_images(val_dir),
        test_count=_count_images(test_dir),
    )

