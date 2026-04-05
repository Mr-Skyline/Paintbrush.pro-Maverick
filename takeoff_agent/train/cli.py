from __future__ import annotations

import argparse
import json
from pathlib import Path

from .eval import evaluate_runs_root
from .fresh_start import initialize_fresh_dataset
from .dataset_ops import generate_yolo_data_yaml
from .roboflow_client import upload_images


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fresh-start training dataset tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser(
        "init-fresh-dataset",
        help="Initialize a brand-new local dataset scaffold for Roboflow.",
    )
    init_cmd.add_argument(
        "--dataset-root",
        default="takeoff_agent/train/datasets/fresh_start",
        help="Destination dataset root.",
    )
    init_cmd.add_argument(
        "--project-name",
        default="Paintbrush.pro",
        help="Human-readable project name for metadata.",
    )

    upload_cmd = sub.add_parser(
        "upload-images",
        help="Upload images from fresh_start/images to Roboflow.",
    )
    upload_cmd.add_argument(
        "--images-dir",
        default="takeoff_agent/train/datasets/fresh_start/images",
        help="Directory containing source images to upload.",
    )
    upload_cmd.add_argument(
        "--workspace",
        default="",
        help="Roboflow workspace slug (or set ROBOFLOW_WORKSPACE).",
    )
    upload_cmd.add_argument(
        "--project",
        default="",
        help="Roboflow project slug (or set ROBOFLOW_PROJECT).",
    )
    upload_cmd.add_argument(
        "--api-key",
        default="",
        help="Roboflow API key (or set ROBOFLOW_API_KEY).",
    )
    upload_cmd.add_argument(
        "--split",
        default="train",
        choices=["train", "valid", "test"],
        help="Dataset split tag for uploads.",
    )
    upload_cmd.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum images to upload (0 = all).",
    )
    upload_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would upload without making API calls.",
    )

    yolo_cmd = sub.add_parser(
        "write-yolo-config",
        help="Generate YOLO data.yaml from a fresh dataset root.",
    )
    yolo_cmd.add_argument(
        "--dataset-root",
        default="takeoff_agent/train/datasets/fresh_start",
        help="Dataset root containing images/ and labels/.",
    )
    yolo_cmd.add_argument(
        "--out",
        default="takeoff_agent/train/datasets/fresh_start/data.yaml",
        help="Output YOLO data.yaml path.",
    )
    yolo_cmd.add_argument(
        "--class-names",
        default="exterior_wall,interior_wall,door,window,fixture",
        help="Comma-separated class names in index order.",
    )

    eval_cmd = sub.add_parser(
        "evaluate-runs",
        help="Build a local quality report from takeoff output runs.",
    )
    eval_cmd.add_argument(
        "--runs-root",
        default="output",
        help="Root folder containing run output subfolders.",
    )
    eval_cmd.add_argument(
        "--out-dir",
        default="takeoff_agent/train/eval/latest",
        help="Folder to write eval report artifacts.",
    )
    eval_cmd.add_argument(
        "--min-confidence",
        type=float,
        default=0.9,
        help="Confidence threshold used for bad-run classification in the report.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "init-fresh-dataset":
        root = Path(args.dataset_root).resolve()
        summary = initialize_fresh_dataset(root, project_name=args.project_name)
        print(f"Initialized fresh dataset at: {summary.root}")
        print(f"Manifest: {summary.manifest_path}")
        print(
            "How-to: copy images into images/{train,val,test} and create matching labels/*.txt files"
        )
        return 0

    if args.command == "upload-images":
        result = upload_images(
            images_dir=Path(args.images_dir).resolve(),
            workspace=args.workspace,
            project=args.project,
            api_key=args.api_key,
            split=args.split,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        print(f"Found: {result.found}")
        print(f"Uploaded: {result.uploaded}")
        print(f"Failed: {result.failed}")
        print(f"Manifest: {result.manifest_path}")
        return 0

    if args.command == "write-yolo-config":
        class_names = [c.strip() for c in args.class_names.split(",") if c.strip()]
        if not class_names:
            raise ValueError("At least one class name is required.")
        summary = generate_yolo_data_yaml(
            dataset_root=Path(args.dataset_root).resolve(),
            output_path=Path(args.out).resolve(),
            class_names=class_names,
        )
        print(f"Wrote YOLO config: {summary.data_yaml_path}")
        print(
            f"Image counts train/val/test: {summary.train_count}/{summary.val_count}/{summary.test_count}"
        )
        return 0

    if args.command == "evaluate-runs":
        summary = evaluate_runs_root(
            runs_root=Path(args.runs_root).resolve(),
            out_dir=Path(args.out_dir).resolve(),
            min_confidence=float(args.min_confidence),
        )
        print(json.dumps(summary, indent=2))
        return 0

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
