from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shapely.geometry import Polygon


def build_takeoff_result(
    project_id: str, source_name: str, detections: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    px_per_ft = float(config.get("pixels_per_foot_default", 48))
    room_sf_total = 0.0
    rooms = []
    for room in detections.get("rooms", []):
        pts = room.get("points", [])
        if len(pts) < 3:
            continue
        poly = Polygon([(p["x"], p["y"]) for p in pts])
        if poly.area <= 0:
            continue
        sf = float(poly.area / (px_per_ft**2))
        room_sf_total += sf
        rooms.append(
            {
                "id": room["id"],
                "label": room.get("label", "Room"),
                "points": pts,
                "sf": round(sf, 2),
                "confidence": room.get("confidence", 0.8),
            }
        )

    walls = []
    lf_total = 0.0
    for wall in detections.get("walls", []):
        lf = float(wall.get("length_px", 0.0) / px_per_ft)
        lf_total += lf
        walls.append(
            {
                "id": wall["id"],
                "kind": wall.get("kind", "interior"),
                "x1": wall["x1"],
                "y1": wall["y1"],
                "x2": wall["x2"],
                "y2": wall["y2"],
                "lf": round(lf, 2),
                "confidence": wall.get("confidence", 0.8),
            }
        )

    confidence = float(detections.get("confidence", 0.8))
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return {
        "projectId": project_id,
        "sourceName": source_name,
        "page": 1,
        "confidence": round(confidence, 3),
        "scaleLabel": config.get("scale_label_default", '1/8" = 1\'-0"'),
        "walls": walls,
        "rooms": rooms,
        "counts": detections.get("counts", {"doors": 0, "windows": 0, "fixtures": 0}),
        "quantities": {
            "wallsLf": round(lf_total, 2),
            "roomsSf": round(room_sf_total, 2),
        },
        "needsReview": confidence < float(config.get("manual_review_threshold", 0.9)),
        "auditId": f"audit_{project_id}_{now}",
    }
