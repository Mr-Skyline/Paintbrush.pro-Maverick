from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(slots=True)
class DetectionOutput:
    """Structured raw detections for post-processing."""

    walls: list[dict[str, Any]]
    rooms: list[dict[str, Any]]
    counts: dict[str, int]
    confidence: float
    detection_source: str
    retries_used: int


def _line_length(p1: tuple[int, int], p2: tuple[int, int]) -> float:
    return float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))


def _line_angle_bucket(
    p1: tuple[int, int], p2: tuple[int, int], bucket_degrees: float = 5.0
) -> int:
    dx = float(p2[0] - p1[0])
    dy = float(p2[1] - p1[1])
    angle = np.degrees(np.arctan2(dy, dx)) % 180.0
    bucket = max(1.0, float(bucket_degrees))
    return int(round(angle / bucket) * bucket)


def _classify_wall_by_color(
    source_image: np.ndarray | None, p1: tuple[int, int], p2: tuple[int, int]
) -> str:
    """
    Heuristic wall type classification from midpoint color.

    - red dominant  -> exterior
    - blue dominant -> interior
    - otherwise     -> wall
    """
    if source_image is None:
        return "wall"
    h, w = source_image.shape[:2]
    mx = max(0, min(w - 1, int((p1[0] + p2[0]) / 2)))
    my = max(0, min(h - 1, int((p1[1] + p2[1]) / 2)))
    b, g, r = source_image[my, mx].tolist()
    if r > b + 20 and r > g + 20:
        return "exterior_wall"
    if b > r + 20 and b > g + 20:
        return "interior_wall"
    return "wall"


def _dedupe_walls(
    walls: list[dict[str, Any]],
    endpoint_tolerance_px: int = 6,
    angle_bucket_degrees: float = 5.0,
) -> list[dict[str, Any]]:
    """
    Merge likely duplicate line detections from Hough output.
    """
    if not walls:
        return walls

    grouped: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    for wall in walls:
        sx, sy = wall["start_px"]
        ex, ey = wall["end_px"]
        p1 = (int(sx), int(sy))
        p2 = (int(ex), int(ey))
        if p2 < p1:
            p1, p2 = p2, p1
        bucket = (
            int(round(p1[0] / endpoint_tolerance_px)),
            int(round(p1[1] / endpoint_tolerance_px)),
            int(round(p2[0] / endpoint_tolerance_px)),
            int(round(p2[1] / endpoint_tolerance_px)),
        )
        angle_bucket = _line_angle_bucket(p1, p2, angle_bucket_degrees)
        key = bucket + (angle_bucket,)

        best = grouped.get(key)
        if best is None or float(wall["length_px"]) > float(best["length_px"]):
            grouped[key] = wall
    return list(grouped.values())


def _detect_walls_with_yolo(
    source_image: np.ndarray,
    model_path: str,
    confidence_threshold: float,
    source_fallback_classification: bool = True,
) -> list[dict[str, Any]]:
    """
    Optional YOLO-based wall detection.

    Expected model output:
      boxes where each box centerline is treated as a wall segment.
    """
    try:
        from ultralytics import YOLO  # type: ignore
    except Exception:
        return []

    try:
        model = YOLO(model_path)
        result = model.predict(source=source_image, conf=confidence_threshold, verbose=False)[
            0
        ]
    except Exception:
        return []

    boxes = getattr(result, "boxes", None)
    if boxes is None or boxes.xyxy is None:
        return []

    walls: list[dict[str, Any]] = []
    xyxy = boxes.xyxy.cpu().numpy().tolist()
    confs = boxes.conf.cpu().numpy().tolist() if boxes.conf is not None else []
    for idx, box in enumerate(xyxy):
        x1, y1, x2, y2 = [int(v) for v in box]
        p1 = (x1, int((y1 + y2) / 2))
        p2 = (x2, int((y1 + y2) / 2))
        length = _line_length(p1, p2)
        if length <= 0:
            continue
        conf = float(confs[idx]) if idx < len(confs) else 0.7
        classification = (
            _classify_wall_by_color(source_image, p1, p2)
            if source_fallback_classification
            else "wall"
        )
        walls.append(
            {
                "start_px": [p1[0], p1[1]],
                "end_px": [p2[0], p2[1]],
                "length_px": float(length),
                "classification": classification,
                "confidence": conf,
            }
        )
    return _dedupe_walls(walls)


def detect_walls(
    binary_image: np.ndarray,
    min_length_px: int = 40,
    max_line_gap: int = 8,
    hough_threshold: int = 110,
    source_image: np.ndarray | None = None,
    dedupe_distance_px: int = 6,
    dedupe_angle_deg: float = 5.0,
) -> list[dict[str, Any]]:
    """
    Baseline wall detector using probabilistic Hough transform.

    This is intentionally modular so it can be swapped with YOLO keypoint outputs.
    """
    lines = cv2.HoughLinesP(
        binary_image,
        rho=1,
        theta=np.pi / 180,
        threshold=hough_threshold,
        minLineLength=min_length_px,
        maxLineGap=max_line_gap,
    )
    if lines is None:
        return []

    walls: list[dict[str, Any]] = []
    for line in lines:
        x1, y1, x2, y2 = line[0].tolist()
        p1, p2 = (int(x1), int(y1)), (int(x2), int(y2))
        length = _line_length(p1, p2)
        if length < min_length_px:
            continue
        walls.append(
            {
                "start_px": [p1[0], p1[1]],
                "end_px": [p2[0], p2[1]],
                "length_px": length,
                "classification": _classify_wall_by_color(source_image, p1, p2),
                "confidence": 0.78,
            }
        )
    return _dedupe_walls(
        walls,
        endpoint_tolerance_px=max(1, int(dedupe_distance_px)),
        angle_bucket_degrees=max(1.0, float(dedupe_angle_deg)),
    )


def detect_rooms(binary_image: np.ndarray, min_area_px: float = 2000) -> list[dict[str, Any]]:
    """
    Baseline room extraction from contours.

    Intended as a pluggable fallback before ML segmentation is attached.
    """
    contours, _ = cv2.findContours(binary_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rooms: list[dict[str, Any]] = []
    room_index = 1
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area_px:
            continue
        epsilon = 0.01 * cv2.arcLength(contour, True)
        poly = cv2.approxPolyDP(contour, epsilon, True)
        points = [[int(pt[0][0]), int(pt[0][1])] for pt in poly]
        if len(points) < 3:
            continue
        rooms.append(
            {
                "room": f"Room {room_index}",
                "polygon_px": points,
                "area_px": float(area),
                "confidence": 0.74,
            }
        )
        room_index += 1
    return rooms


def detect_symbol_counts(
    binary_image: np.ndarray, min_area_px: int = 20
) -> dict[str, int]:
    """
    Baseline count extraction from connected components.

    This is a deterministic placeholder until trained symbol detection is attached.
    """
    component_count, _labels, stats, _ = cv2.connectedComponentsWithStats(binary_image, 8)
    doors = 0
    windows = 0
    fixtures = 0
    for i in range(1, component_count):
        area = int(stats[i, cv2.CC_STAT_AREA])
        width = int(stats[i, cv2.CC_STAT_WIDTH])
        height = int(stats[i, cv2.CC_STAT_HEIGHT])
        if area < min_area_px:
            continue
        aspect = width / max(1.0, float(height))
        if 0.7 <= aspect <= 1.3:
            doors += 1
        elif aspect > 1.3:
            windows += 1
        else:
            fixtures += 1
    return {"Doors": doors, "Windows": windows, "Fixtures": fixtures}


def run_detection(
    binary_image: np.ndarray,
    config: dict[str, Any],
    source_image: np.ndarray | None = None,
    retry_index: int = 0,
) -> DetectionOutput:
    walls_cfg = config.get("walls", {})
    rooms_cfg = config.get("rooms", {})
    counts_cfg = config.get("counts", {})

    yolo_cfg = config.get("yolo", walls_cfg.get("yolo", {}))
    # Accept both old and new key names to avoid config drift.
    yolo_model_path = str(
        yolo_cfg.get("model_path") or yolo_cfg.get("wall_model_path") or ""
    ).strip()
    yolo_conf = float(
        yolo_cfg.get("confidence_threshold", yolo_cfg.get("confidence", 0.25))
    )
    prefer_yolo = bool(yolo_cfg.get("enabled", False))

    walls: list[dict[str, Any]] = []
    detection_source = "hough"
    if prefer_yolo and source_image is not None and yolo_model_path:
        walls = _detect_walls_with_yolo(
            source_image=source_image,
            model_path=yolo_model_path,
            confidence_threshold=yolo_conf,
        )
        if walls:
            detection_source = "yolo"

    if not walls:
        walls = detect_walls(
            binary_image,
            min_length_px=int(walls_cfg.get("min_length_px", 40)),
            max_line_gap=int(walls_cfg.get("max_line_gap", 8)),
            hough_threshold=int(walls_cfg.get("hough_threshold", 110)),
            source_image=source_image,
            dedupe_distance_px=int(walls_cfg.get("dedupe_distance_px", 6)),
            dedupe_angle_deg=float(walls_cfg.get("dedupe_angle_deg", 5.0)),
        )
        detection_source = "hough"
    rooms = detect_rooms(binary_image, float(rooms_cfg.get("min_area_px", 2000)))
    counts = detect_symbol_counts(binary_image, int(counts_cfg.get("min_area_px", 20)))

    confidences = [w.get("confidence", 0.0) for w in walls] + [
        r.get("confidence", 0.0) for r in rooms
    ]
    pipeline_conf = float(np.mean(confidences)) if confidences else 0.0
    return DetectionOutput(
        walls=walls,
        rooms=rooms,
        counts=counts,
        confidence=pipeline_conf,
        detection_source=detection_source,
        retries_used=retry_index,
    )

