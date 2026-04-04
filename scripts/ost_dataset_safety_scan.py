#!/usr/bin/env python3
"""
Safety scanner for external blueprint datasets before ingestion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from datetime import datetime
from typing import Any, Dict, List


SAFE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
SAFE_META_EXTS = {".txt", ".csv", ".json", ".xml", ".yml", ".yaml", ".md"}
ARCHIVE_EXTS = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz"}
EXECUTABLE_EXTS = {
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".js",
    ".jar",
    ".msi",
    ".scr",
    ".com",
    ".pif",
    ".reg",
    ".hta",
    ".wsf",
    ".lnk",
}


def now_iso() -> str:
    return datetime.now().isoformat()


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Safety scan for dataset root")
    p.add_argument("--dataset-root", required=True)
    p.add_argument("--report-json", required=True)
    p.add_argument("--max-file-size-mb", type=int, default=50)
    p.add_argument("--max-files", type=int, default=0, help="0 means no cap")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    dataset_root = pathlib.Path(args.dataset_root).expanduser().resolve()
    report_json = pathlib.Path(args.report_json).expanduser().resolve()
    max_file_size = int(args.max_file_size_mb) * 1024 * 1024
    max_files = int(args.max_files)
    if not dataset_root.exists() or not dataset_root.is_dir():
        print("ERROR: dataset_root_not_found")
        return 2

    rows: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    all_files = [p for p in dataset_root.rglob("*") if p.is_file()]
    all_files.sort()
    if max_files > 0:
        all_files = all_files[:max_files]

    for p in all_files:
        rel = str(p.relative_to(dataset_root))
        ext = p.suffix.lower()
        size = int(p.stat().st_size)
        row = {
            "path": rel,
            "ext": ext,
            "size_bytes": size,
            "sha256": "",
            "classification": "unknown",
            "status": "allow",
            "reason": "",
        }
        if ext in EXECUTABLE_EXTS:
            row["classification"] = "executable"
            row["status"] = "block"
            row["reason"] = "executable_extension"
        elif ext in ARCHIVE_EXTS:
            row["classification"] = "archive"
            row["status"] = "warn"
            row["reason"] = "archive_requires_manual_unpack_review"
        elif ext in SAFE_IMAGE_EXTS:
            row["classification"] = "image"
        elif ext in SAFE_META_EXTS:
            row["classification"] = "metadata"
        else:
            row["classification"] = "unknown"
            row["status"] = "warn"
            row["reason"] = "unknown_extension"

        if size > max_file_size:
            row["status"] = "warn" if row["status"] != "block" else row["status"]
            if row["reason"]:
                row["reason"] += ";"
            row["reason"] += "oversized_file"

        try:
            row["sha256"] = sha256_file(p)
        except Exception:
            row["status"] = "warn" if row["status"] != "block" else row["status"]
            if row["reason"]:
                row["reason"] += ";"
            row["reason"] += "hash_failed"

        rows.append(row)
        if row["status"] == "block":
            blocked.append(row)
        elif row["status"] == "warn":
            warnings.append(row)

    payload = {
        "ok": len(blocked) == 0,
        "dataset_root": str(dataset_root),
        "scanned_at": now_iso(),
        "limits": {
            "max_file_size_mb": int(args.max_file_size_mb),
            "max_files": int(args.max_files),
        },
        "counts": {
            "scanned_files": len(rows),
            "blocked_files": len(blocked),
            "warn_files": len(warnings),
        },
        "blocked": blocked[:200],
        "warnings": warnings[:500],
        "rows_jsonl_hint": "Use rows for full provenance ledger.",
        "rows": rows,
    }
    write_json(report_json, payload)
    print(str(report_json))
    return 0 if payload["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())

