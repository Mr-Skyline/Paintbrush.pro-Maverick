"""CLI entry point for the standalone Paintbrush takeoff agent."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from .detection import run_detection
from .postprocess import aggregate_quantities, finalize_page_results
from .preprocess import denoise_and_threshold, load_config, load_plan_pages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process blueprint files and export takeoff JSON/CSV."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Blueprint input path (PDF or image).",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("config.yaml")),
        help="Path to takeoff agent config.yaml.",
    )
    parser.add_argument(
        "--out",
        default="output/takeoff-agent",
        help="Output folder for JSON and CSV exports.",
    )
    parser.add_argument(
        "--save-debug-images",
        action="store_true",
        help="Save preprocessed threshold images for each page.",
    )
    parser.add_argument(
        "--project-id",
        default="local-dev-project",
        help="Project id used in exported metadata.",
    )
    return parser.parse_args()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        rows = [{"kind": "", "name": "", "quantity": "", "unit": "", "page_index": ""}]
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    pages = load_plan_pages(args.input, config)
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = output_dir / "debug"
    if args.save_debug_images:
        debug_dir.mkdir(parents=True, exist_ok=True)

    per_page: list[dict[str, Any]] = []
    for page in pages:
        _, binary = denoise_and_threshold(page.image_bgr)
        detection_cfg = config.get("detection", {})
        raw = run_detection(binary, detection_cfg, source_image=page.image_bgr)
        processed = finalize_page_results(page, raw, config)
        per_page.append(processed)

        if args.save_debug_images:
            import cv2

            debug_path = debug_dir / f"page-{page.page_index:03d}-threshold.png"
            cv2.imwrite(str(debug_path), binary)

    totals = aggregate_quantities(per_page)
    payload = {
        "project_id": args.project_id,
        "source_input": str(Path(args.input).resolve()),
        "pages_processed": len(per_page),
        "totals": totals,
        "pages": per_page,
    }

    export_rows: list[dict[str, Any]] = []
    for page in per_page:
        page_idx = page["page_index"]
        for wall in page["walls"]:
            export_rows.append(
                {
                    "kind": "wall",
                    "name": wall["classification"],
                    "quantity": wall["length_ft"],
                    "unit": "LF",
                    "page_index": page_idx,
                }
            )
        for room in page["rooms"]:
            export_rows.append(
                {
                    "kind": "room",
                    "name": room["name"],
                    "quantity": room["sf"],
                    "unit": "SF",
                    "page_index": page_idx,
                }
            )
        for count in page["counts"]:
            export_rows.append(
                {
                    "kind": "count",
                    "name": count["name"],
                    "quantity": count["quantity"],
                    "unit": "EA",
                    "page_index": page_idx,
                }
            )

    json_path = output_dir / "takeoff-results.json"
    csv_path = output_dir / "takeoff-results.csv"
    write_json(json_path, payload)
    write_csv(csv_path, export_rows)

    print(f"Pages processed: {len(per_page)}")
    print(f"Total wall LF: {totals['walls_lf']}")
    print(f"Total room SF: {totals['rooms_sf']}")
    print(f"Total doors EA: {totals['doors_ea']}")
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
