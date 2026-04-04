#!/usr/bin/env python3
"""
Build a local symbol knowledge index from labeled blueprint symbol images.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
from collections import defaultdict
from typing import Any, Dict, List

from ost_symbol_knowledge import (
    append_jsonl,
    compute_symbol_embedding,
    now_tag,
    write_json,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest symbol dataset into local index")
    p.add_argument("--dataset-root", required=True, help="Path to dataset root")
    p.add_argument("--dataset-name", default="custom", help="Dataset name label")
    p.add_argument("--project-id", default="TP-0001", help="Project id for output path")
    p.add_argument("--output-root", default="", help="Override output root")
    p.add_argument("--limit", type=int, default=0, help="Max images to ingest (0=no limit)")
    p.add_argument("--min-per-class", type=int, default=3, help="Minimum examples to keep class prototype")
    p.add_argument("--max-file-size-mb", type=int, default=50)
    p.add_argument("--scan-max-files", type=int, default=0)
    p.add_argument("--allow-warnings", action="store_true")
    p.add_argument("--skip-safety-scan", action="store_true")
    p.add_argument("--quarantine-dir", default="", help="Optional quarantine root override")
    return p.parse_args()


def _is_image(path: pathlib.Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def _class_from_path(dataset_root: pathlib.Path, image_path: pathlib.Path) -> str:
    rel = image_path.relative_to(dataset_root)
    parts = list(rel.parts)
    if len(parts) >= 2:
        return str(parts[0]).strip().lower().replace(" ", "_")
    return "unknown"


def _safe_copy(src: pathlib.Path, dst: pathlib.Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _run_safety_scan(
    dataset_root: pathlib.Path,
    output_root: pathlib.Path,
    max_file_size_mb: int,
    max_files: int,
) -> Dict[str, Any]:
    report_json = output_root / f"safety_report_{now_tag()}.json"
    cmd = [
        "python",
        "scripts/ost_dataset_safety_scan.py",
        "--dataset-root",
        str(dataset_root),
        "--report-json",
        str(report_json),
        "--max-file-size-mb",
        str(int(max_file_size_mb)),
        "--max-files",
        str(int(max_files)),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in (0, 4):
        return {
            "ok": False,
            "scan_invoked": True,
            "scan_exit_code": int(proc.returncode),
            "scan_stdout": proc.stdout.strip(),
            "scan_stderr": proc.stderr.strip(),
            "report_json": str(report_json),
            "report": {},
        }
    report: Dict[str, Any] = {}
    try:
        report = json.loads(report_json.read_text(encoding="utf-8"))
    except Exception:
        report = {}
    return {
        "ok": bool(proc.returncode == 0),
        "scan_invoked": True,
        "scan_exit_code": int(proc.returncode),
        "scan_stdout": proc.stdout.strip(),
        "scan_stderr": proc.stderr.strip(),
        "report_json": str(report_json),
        "report": report,
    }


def main() -> int:
    args = parse_args()
    dataset_root = pathlib.Path(args.dataset_root).expanduser().resolve()
    if not dataset_root.exists():
        print("ERROR: dataset_root_not_found")
        return 2

    if args.output_root.strip():
        output_root = pathlib.Path(args.output_root).expanduser().resolve()
    else:
        output_root = pathlib.Path("output") / "ost-training-lab" / "symbol_knowledge" / str(args.project_id)
    output_root.mkdir(parents=True, exist_ok=True)
    quarantine_root = (
        pathlib.Path(args.quarantine_dir).expanduser().resolve()
        if str(args.quarantine_dir).strip()
        else (output_root / "quarantine")
    )
    quarantine_root.mkdir(parents=True, exist_ok=True)

    tag = now_tag()
    embeddings_jsonl = output_root / f"embeddings_{args.dataset_name}_{tag}.jsonl"
    index_json = output_root / f"symbol_index_{args.dataset_name}_{tag}.json"
    latest_json = output_root / "symbol_index_latest.json"
    manifest_json = output_root / f"ingest_manifest_{args.dataset_name}_{tag}.json"

    safety = {"ok": True, "scan_invoked": False}
    if not bool(args.skip_safety_scan):
        safety = _run_safety_scan(
            dataset_root=dataset_root,
            output_root=output_root,
            max_file_size_mb=int(args.max_file_size_mb),
            max_files=int(args.scan_max_files),
        )
        if not safety.get("scan_invoked"):
            print("ERROR: safety_scan_not_invoked")
            return 4
        report = safety.get("report", {}) if isinstance(safety.get("report", {}), dict) else {}
        warn_count = int(((report.get("counts", {}) if isinstance(report.get("counts", {}), dict) else {}).get("warn_files", 0) or 0))
        if not bool(safety.get("ok", False)):
            print("ERROR: safety_scan_blocked")
            return 5
        if warn_count > 0 and not bool(args.allow_warnings):
            print("ERROR: safety_scan_has_warnings_use_allow_warnings")
            return 6

    all_images = [p for p in dataset_root.rglob("*") if p.is_file() and _is_image(p)]
    all_images.sort()
    if args.limit > 0:
        all_images = all_images[: int(args.limit)]
    if not all_images:
        print("ERROR: no_images_found")
        return 3

    safe_images: List[pathlib.Path] = []
    for img in all_images:
        rel = img.relative_to(dataset_root)
        qpath = quarantine_root / args.dataset_name / rel
        _safe_copy(img, qpath)
        safe_images.append(qpath)

    class_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    bad_rows: List[Dict[str, Any]] = []
    for i, img_path in enumerate(safe_images, start=1):
        cls = _class_from_path(quarantine_root / args.dataset_name, img_path)
        row = compute_symbol_embedding(img_path)
        row["dataset_name"] = str(args.dataset_name)
        row["symbol_class"] = cls
        row["source_root"] = str(dataset_root)
        row["quarantine_root"] = str(quarantine_root / args.dataset_name)
        if row.get("ok"):
            append_jsonl(embeddings_jsonl, row)
            class_rows[cls].append(row)
        else:
            bad_rows.append(row)
        if i % 200 == 0:
            print(f"progress: {i}/{len(all_images)}")

    prototypes: Dict[str, Any] = {}
    for cls, rows in class_rows.items():
        if len(rows) < int(args.min_per_class):
            continue
        emb_len = len(rows[0].get("embedding", []))
        vec = [0.0] * emb_len
        for r in rows:
            emb = r.get("embedding", [])
            if not isinstance(emb, list) or len(emb) != emb_len:
                continue
            for idx, val in enumerate(emb):
                vec[idx] += float(val)
        denom = float(max(1, len(rows)))
        proto = [round(v / denom, 6) for v in vec]
        examples = [str(r.get("path", "")) for r in rows[:12]]
        prototypes[cls] = {
            "count": int(len(rows)),
            "prototype_embedding": proto,
            "example_paths": examples,
        }

    payload = {
        "ok": True,
        "dataset_name": str(args.dataset_name),
        "project_id": str(args.project_id),
        "dataset_root": str(dataset_root),
        "quarantine_root": str(quarantine_root / args.dataset_name),
        "ingested_images": int(len(all_images)),
        "valid_embeddings": int(sum(len(v) for v in class_rows.values())),
        "invalid_embeddings": int(len(bad_rows)),
        "class_count": int(len(class_rows)),
        "prototype_class_count": int(len(prototypes)),
        "prototypes": prototypes,
        "embeddings_jsonl": str(embeddings_jsonl),
        "safety_scan": safety,
    }
    manifest = {
        "ok": True,
        "created_at": now_tag(),
        "dataset_name": str(args.dataset_name),
        "dataset_root": str(dataset_root),
        "quarantine_root": str(quarantine_root / args.dataset_name),
        "project_id": str(args.project_id),
        "source_image_count": int(len(all_images)),
        "quarantined_image_count": int(len(safe_images)),
        "safety_scan_report_json": str((safety.get("report_json", "") if isinstance(safety, dict) else "") or ""),
        "safety_scan_ok": bool((safety.get("ok", True) if isinstance(safety, dict) else True)),
        "embeddings_jsonl": str(embeddings_jsonl),
        "index_json": str(index_json),
    }
    write_json(manifest_json, manifest)
    write_json(index_json, payload)
    write_json(latest_json, payload)
    print(str(index_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

