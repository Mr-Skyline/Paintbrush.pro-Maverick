"""CLI entry point for the standalone Paintbrush takeoff agent."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .detection import run_detection
from .postprocess import aggregate_quantities, finalize_page_results
from .preprocess import denoise_and_threshold, load_config, load_plan_pages
from .runtime import (
    RuntimeArtifacts,
    append_error_log,
    configure_logger,
    ensure_runtime_dirs,
    maybe_emit_supabase_handoff,
)


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
        "--save-overlays",
        action="store_true",
        help="Save annotated page overlay images.",
    )
    parser.add_argument(
        "--project-id",
        default="local-dev-project",
        help="Project id used in exported metadata.",
    )
    parser.add_argument(
        "--enable-supabase-handoff",
        action="store_true",
        help=(
            "Write optional handoff files for Supabase ingestion. "
            "No network calls are made unless env vars are configured."
        ),
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


def _draw_overlays(image_bgr: Any, page_result: dict[str, Any], out_path: Path) -> None:
    overlay = image_bgr.copy()

    # Red lines for walls.
    for wall in page_result.get("walls", []):
        p1 = tuple(wall.get("start_px", [0, 0]))
        p2 = tuple(wall.get("end_px", [0, 0]))
        cv2.line(overlay, p1, p2, (0, 0, 255), 2, lineType=cv2.LINE_AA)

    # Green polygons for rooms.
    for room in page_result.get("rooms", []):
        points = room.get("polygon_px", [])
        if len(points) < 3:
            continue
        contour = np.array(points, dtype=np.int32).reshape((-1, 1, 2))
        contour = cv2.convexHull(contour)
        cv2.polylines(overlay, [contour], True, (0, 255, 0), 2, lineType=cv2.LINE_AA)

    # Yellow markers for detected counts (rough indicator only).
    count_y = 24
    for item in page_result.get("counts", []):
        label = f"{item.get('name', '?')}: {item.get('quantity', 0)}"
        cv2.putText(
            overlay,
            label,
            (16, count_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 220, 255),
            2,
            cv2.LINE_AA,
        )
        count_y += 22

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), overlay)


def _default_error_payload(
    *,
    page_index: int,
    source_name: str,
    confidence: float = 0.0,
    retry_applied: bool = False,
) -> dict[str, Any]:
    return {
        "page_index": page_index,
        "source_name": source_name,
        "scale": {"ft_per_px": 0.0, "px_per_ft": 0.0},
        "confidence": confidence,
        "needs_review": True,
        "retry_applied": retry_applied,
        "walls": [],
        "rooms": [],
        "counts": [
            {"name": "Doors", "quantity": 0},
            {"name": "Windows", "quantity": 0},
            {"name": "Fixtures", "quantity": 0},
        ],
        "page_totals": {
            "walls_lf": 0.0,
            "rooms_sf": 0.0,
            "doors_ea": 0,
            "windows_ea": 0,
            "fixtures_ea": 0,
        },
    }


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    pages = load_plan_pages(args.input, config)
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts: RuntimeArtifacts = ensure_runtime_dirs(output_dir)
    logger = configure_logger(artifacts)

    debug_dir = output_dir / "debug"
    if args.save_debug_images:
        debug_dir.mkdir(parents=True, exist_ok=True)

    detection_cfg = config.get("detection", {})
    retry_cfg = config.get("retry", {})
    min_conf = float(retry_cfg.get("min_confidence", 0.8))
    downscale_factor = float(retry_cfg.get("downscale_factor", 2.0))
    enable_retry = bool(retry_cfg.get("enable", True))

    per_page: list[dict[str, Any]] = []
    for page in pages:
        processed: dict[str, Any] | None = None
        try:
            _, binary = denoise_and_threshold(page.image_bgr)
            raw = run_detection(
                binary, detection_cfg, source_image=page.image_bgr, retry_index=0
            )
            processed = finalize_page_results(page, raw, config)

            # Auto-retry path for low-confidence pages.
            if enable_retry and float(processed.get("confidence", 0.0)) < min_conf:
                new_w = max(64, int(page.image_bgr.shape[1] / max(downscale_factor, 1.0)))
                new_h = max(64, int(page.image_bgr.shape[0] / max(downscale_factor, 1.0)))
                resized = cv2.resize(
                    page.image_bgr,
                    dsize=(new_w, new_h),
                    interpolation=cv2.INTER_AREA,
                )
                _, binary_retry = denoise_and_threshold(resized)
                raw_retry = run_detection(
                    binary_retry, detection_cfg, source_image=resized, retry_index=1
                )
                if raw_retry.confidence > raw.confidence:
                    retry_scale_x = float(page.image_bgr.shape[1]) / float(new_w)
                    retry_scale_y = float(page.image_bgr.shape[0]) / float(new_h)
                    retry_scale = max(retry_scale_x, retry_scale_y)

                    # Reproject retry detections back to original image coordinates
                    # so quantity calculations remain on the original plan scale.
                    for wall in raw_retry.walls:
                        sx, sy = wall["start_px"]
                        ex, ey = wall["end_px"]
                        wall["start_px"] = [
                            int(round(sx * retry_scale_x)),
                            int(round(sy * retry_scale_y)),
                        ]
                        wall["end_px"] = [
                            int(round(ex * retry_scale_x)),
                            int(round(ey * retry_scale_y)),
                        ]
                        wall["length_px"] = float(wall["length_px"]) * retry_scale

                    for room in raw_retry.rooms:
                        room["polygon_px"] = [
                            [
                                int(round(pt[0] * retry_scale_x)),
                                int(round(pt[1] * retry_scale_y)),
                            ]
                            for pt in room.get("polygon_px", [])
                        ]
                        room["area_px"] = float(room.get("area_px", 0.0)) * (
                            retry_scale_x * retry_scale_y
                        )

                    processed = finalize_page_results(page, raw_retry, config)
                    processed["retry_applied"] = True
                    logger.info(
                        "page=%s retry applied confidence %.3f -> %.3f",
                        page.page_index,
                        raw.confidence,
                        raw_retry.confidence,
                    )
                else:
                    processed["retry_applied"] = False

            if args.save_overlays:
                overlay_path = output_dir / "annotated" / f"page-{page.page_index:03d}.png"
                _draw_overlays(page.image_bgr, processed, overlay_path)
                processed["overlay_image"] = str(overlay_path)

            if args.save_debug_images:
                debug_path = debug_dir / f"page-{page.page_index:03d}-threshold.png"
                cv2.imwrite(str(debug_path), binary)

            logger.info(
                "page=%s walls=%s rooms=%s confidence=%.3f needs_review=%s",
                page.page_index,
                len(processed.get("walls", [])),
                len(processed.get("rooms", [])),
                float(processed.get("confidence", 0.0)),
                bool(processed.get("needs_review", True)),
            )
            per_page.append(processed)
        except Exception as exc:
            append_error_log(
                artifacts,
                project_id=args.project_id,
                page_index=page.page_index,
                error_type=type(exc).__name__,
                stage="page_processing",
                message=str(exc),
            )
            logger.exception("page=%s failed", page.page_index)
            failed = processed or _default_error_payload(
                page_index=page.page_index,
                source_name=page.source_name,
            )
            failed["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            per_page.append(failed)
            continue

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

    if args.enable_supabase_handoff:
        maybe_emit_supabase_handoff(
            payload=payload,
            output_dir=output_dir,
            project_id=args.project_id,
            logger=logger,
        )

    logger.info(
        "completed pages=%s walls_lf=%.2f rooms_sf=%.2f doors=%s",
        len(per_page),
        float(totals["walls_lf"]),
        float(totals["rooms_sf"]),
        int(totals["doors_ea"]),
    )
    print(f"Pages processed: {len(per_page)}")
    print(f"Total wall LF: {totals['walls_lf']}")
    print(f"Total room SF: {totals['rooms_sf']}")
    print(f"Total doors EA: {totals['doors_ea']}")
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
