from __future__ import annotations

import math
from typing import Any


def _normalize_angle_deg(p1: list[int], p2: list[int]) -> float:
    dx = float(p2[0] - p1[0])
    dy = float(p2[1] - p1[1])
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return 0.0
    angle = abs(math.degrees(math.atan2(dy, dx)))
    if angle > 180:
        angle %= 180
    if angle > 90:
        angle = 180 - angle
    return angle


def _snap_wall_axis(
    start: list[int], end: list[int], angle_threshold_deg: float = 10.0
) -> tuple[list[int], list[int]]:
    angle = _normalize_angle_deg(start, end)
    sx, sy = start
    ex, ey = end
    if angle <= angle_threshold_deg:
        ey = sy
    elif abs(angle - 90.0) <= angle_threshold_deg:
        ex = sx
    return [sx, sy], [ex, ey]


def _wall_signature(
    start: list[int], end: list[int], quant: int = 4
) -> tuple[int, int, int, int]:
    s = [int(round(start[0] / quant) * quant), int(round(start[1] / quant) * quant)]
    e = [int(round(end[0] / quant) * quant), int(round(end[1] / quant) * quant)]
    return tuple(s + e) if s <= e else tuple(e + s)


def _poly_area_px(points: list[list[int]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        area += float(x1 * y2 - x2 * y1)
    return abs(area) / 2.0


def _snap_axis_aligned(point: list[int], anchor: list[int], tolerance: int = 4) -> list[int]:
    x, y = point
    ax, ay = anchor
    if abs(x - ax) <= tolerance:
        x = ax
    if abs(y - ay) <= tolerance:
        y = ay
    return [x, y]


def _cleanup_room_polygon(points: list[list[int]]) -> list[list[int]]:
    if not points:
        return points
    cleaned = [points[0]]
    for point in points[1:]:
        cleaned.append(_snap_axis_aligned(point, cleaned[-1], tolerance=4))
    return cleaned


def finalize_page_results(
    page: Any,
    raw_detection: Any,
    config: dict[str, Any],
) -> dict[str, Any]:
    min_conf = float(config.get("postprocess", {}).get("min_confidence", 0.9))
    px_per_foot = 1.0 / max(page.scale_ft_per_px, 1e-9)

    walls: list[dict[str, Any]] = []
    total_walls_lf = 0.0
    seen_wall_keys: set[tuple[int, int, int, int]] = set()
    for wall in raw_detection.walls:
        start, end = _snap_wall_axis(wall["start_px"], wall["end_px"])
        wall_key = _wall_signature(start, end, quant=4)
        if wall_key in seen_wall_keys:
            continue
        seen_wall_keys.add(wall_key)
        length_ft = float(wall["length_px"]) / px_per_foot
        total_walls_lf += length_ft
        walls.append(
            {
                "start_px": start,
                "end_px": end,
                "classification": wall.get("classification", "wall"),
                "length_ft": round(length_ft, 2),
                "confidence": float(wall.get("confidence", 0.0)),
            }
        )

    rooms: list[dict[str, Any]] = []
    total_rooms_sf = 0.0
    min_area_ft = 0.25
    for room in raw_detection.rooms:
        poly = _cleanup_room_polygon(room["polygon_px"])
        area_px = _poly_area_px(poly)
        area_sf = area_px / max(px_per_foot * px_per_foot, 1e-9)
        if area_sf < min_area_ft:
            continue
        total_rooms_sf += area_sf
        rooms.append(
            {
                "name": room["room"],
                "polygon_px": poly,
                "sf": round(area_sf, 2),
                "confidence": float(room.get("confidence", 0.0)),
            }
        )

    counts = [
        {"name": "Doors", "quantity": int(raw_detection.counts.get("Doors", 0))},
        {"name": "Windows", "quantity": int(raw_detection.counts.get("Windows", 0))},
        {"name": "Fixtures", "quantity": int(raw_detection.counts.get("Fixtures", 0))},
    ]

    return {
        "page_index": page.page_index,
        "source_name": page.source_name,
        "detection_source": getattr(raw_detection, "detection_source", "unknown"),
        "retries_used": int(getattr(raw_detection, "retries_used", 0)),
        "scale": {
            "ft_per_px": page.scale_ft_per_px,
            "px_per_ft": round(px_per_foot, 4),
        },
        "confidence": float(raw_detection.confidence),
        "needs_review": float(raw_detection.confidence) < min_conf,
        "walls": walls,
        "rooms": rooms,
        "counts": counts,
        "page_totals": {
            "walls_lf": round(total_walls_lf, 2),
            "rooms_sf": round(total_rooms_sf, 2),
            "doors_ea": int(raw_detection.counts.get("Doors", 0)),
            "windows_ea": int(raw_detection.counts.get("Windows", 0)),
            "fixtures_ea": int(raw_detection.counts.get("Fixtures", 0)),
        },
    }


def aggregate_quantities(page_results: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "walls_lf": 0.0,
        "rooms_sf": 0.0,
        "doors_ea": 0,
        "windows_ea": 0,
        "fixtures_ea": 0,
        "pages_below_confidence_threshold": 0,
    }
    for page in page_results:
        page_totals = page.get("page_totals", {})
        totals["walls_lf"] += float(page_totals.get("walls_lf", 0.0))
        totals["rooms_sf"] += float(page_totals.get("rooms_sf", 0.0))
        totals["doors_ea"] += int(page_totals.get("doors_ea", 0))
        totals["windows_ea"] += int(page_totals.get("windows_ea", 0))
        totals["fixtures_ea"] += int(page_totals.get("fixtures_ea", 0))
        if page.get("needs_review"):
            totals["pages_below_confidence_threshold"] += 1

    totals["walls_lf"] = round(totals["walls_lf"], 2)
    totals["rooms_sf"] = round(totals["rooms_sf"], 2)
    return totals
