from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class EvalSummary:
    report_path: Path
    csv_path: Path
    scanned_runs: int
    low_conf_runs: int
    errored_runs: int
    avg_confidence: float


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def evaluate_output_runs(
    *,
    runs_root: Path,
    out_dir: Path,
    confidence_threshold: float = 0.9,
) -> EvalSummary:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.json"
    csv_path = out_dir / "summary.csv"

    rows: list[dict[str, Any]] = []
    scanned_runs = 0
    low_conf_runs = 0
    errored_runs = 0
    conf_sum = 0.0
    conf_count = 0

    for run_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        payload = _safe_read_json(run_dir / "takeoff-results.json")
        if payload is None:
            continue
        scanned_runs += 1

        pages = payload.get("pages", [])
        page_confidences = [float(p.get("confidence", 0.0)) for p in pages]
        mean_conf = sum(page_confidences) / max(1, len(page_confidences))
        min_conf = min(page_confidences) if page_confidences else 0.0
        has_error = any("error" in p for p in pages)
        needs_review = bool(payload.get("totals", {}).get("pages_below_confidence_threshold", 0))

        if has_error:
            errored_runs += 1
        if min_conf <= confidence_threshold or needs_review:
            low_conf_runs += 1

        conf_sum += sum(page_confidences)
        conf_count += len(page_confidences)

        rows.append(
            {
                "run_dir": str(run_dir),
                "project_id": payload.get("project_id", run_dir.name),
                "pages_processed": int(payload.get("pages_processed", 0)),
                "mean_page_confidence": round(mean_conf, 4),
                "min_page_confidence": round(min_conf, 4),
                "needs_review": needs_review,
                "has_page_error": has_error,
                "walls_lf": float(payload.get("totals", {}).get("walls_lf", 0.0)),
                "rooms_sf": float(payload.get("totals", {}).get("rooms_sf", 0.0)),
                "doors_ea": int(payload.get("totals", {}).get("doors_ea", 0)),
            }
        )

    avg_confidence = (conf_sum / conf_count) if conf_count else 0.0

    report = {
        "generated_at_utc": _now_iso(),
        "runs_root": str(runs_root),
        "confidence_threshold": confidence_threshold,
        "scanned_runs": scanned_runs,
        "low_conf_runs": low_conf_runs,
        "errored_runs": errored_runs,
        "avg_confidence": round(avg_confidence, 4),
        "rows": rows,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "run_dir",
            "project_id",
            "pages_processed",
            "mean_page_confidence",
            "min_page_confidence",
            "needs_review",
            "has_page_error",
            "walls_lf",
            "rooms_sf",
            "doors_ea",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return EvalSummary(
        report_path=report_path,
        csv_path=csv_path,
        scanned_runs=scanned_runs,
        low_conf_runs=low_conf_runs,
        errored_runs=errored_runs,
        avg_confidence=round(avg_confidence, 4),
    )


def evaluate_runs_root(
    *,
    runs_root: Path,
    out_dir: Path,
    min_confidence: float,
) -> dict[str, Any]:
    summary = evaluate_output_runs(
        runs_root=runs_root,
        out_dir=out_dir,
        confidence_threshold=min_confidence,
    )
    return {
        "report_path": str(summary.report_path),
        "csv_path": str(summary.csv_path),
        "scanned_runs": summary.scanned_runs,
        "low_conf_runs": summary.low_conf_runs,
        "errored_runs": summary.errored_runs,
        "avg_confidence": summary.avg_confidence,
    }

