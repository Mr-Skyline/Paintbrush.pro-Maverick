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


def _line_length(p1: tuple[int, int], p2: tuple[int, int]) -> float:
    return float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))


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


def detect_walls(
    binary_image: np.ndarray,
    min_length_px: int = 40,
    max_line_gap: int = 8,
    hough_threshold: int = 110,
    source_image: np.ndarray | None = None,
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
    return walls


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
) -> DetectionOutput:
    walls_cfg = config.get("walls", {})
    rooms_cfg = config.get("rooms", {})
    counts_cfg = config.get("counts", {})

    walls = detect_walls(
        binary_image,
        min_length_px=int(walls_cfg.get("min_length_px", 40)),
        max_line_gap=int(walls_cfg.get("max_line_gap", 8)),
        hough_threshold=int(walls_cfg.get("hough_threshold", 110)),
        source_image=source_image,
    )
    rooms = detect_rooms(binary_image, float(rooms_cfg.get("min_area_px", 2000)))
    counts = detect_symbol_counts(binary_image, int(counts_cfg.get("min_area_px", 20)))

    confidences = [w.get("confidence", 0.0) for w in walls] + [
        r.get("confidence", 0.0) for r in rooms
    ]
    pipeline_conf = float(np.mean(confidences)) if confidences else 0.0
    return DetectionOutput(walls=walls, rooms=rooms, counts=counts, confidence=pipeline_conf)

