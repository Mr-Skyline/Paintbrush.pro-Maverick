from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .fresh_start import initialize_fresh_dataset


PDF_EXTENSIONS = {".pdf"}
WORD_EXTENSIONS = {".doc", ".docx"}
ALLOWED_EXTENSIONS = PDF_EXTENSIONS | WORD_EXTENSIONS


@dataclass(slots=True)
class IngestSummary:
    source_dir: Path
    dataset_root: Path
    split: str
    scanned_files: int
    scanned_pdf_files: int
    scanned_word_files: int
    processed_files: int
    processed_pdf_files: int
    processed_word_files: int
    skipped_files: int
    pages_written: int
    documents_copied: int
    failed_files: int
    state_path: Path
    manifest_path: Path
    failures: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_dir"] = str(self.source_dir)
        payload["dataset_root"] = str(self.dataset_root)
        payload["state_path"] = str(self.state_path)
        payload["manifest_path"] = str(self.manifest_path)
        return payload


@dataclass(slots=True)
class IngestWatchIteration:
    run_index: int
    started_at_utc: str
    completed_at_utc: str
    duration_seconds: float
    summary: IngestSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_index": self.run_index,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "duration_seconds": self.duration_seconds,
            "summary": self.summary.to_dict(),
        }


@dataclass(slots=True)
class IngestWatchSummary:
    source_dir: Path
    dataset_root: Path
    split: str
    interval_seconds: int
    max_runs: int
    started_at_utc: str
    completed_at_utc: str
    total_duration_seconds: float
    runs_executed: int
    total_scanned_files: int
    total_processed_files: int
    total_skipped_files: int
    total_pages_written: int
    total_documents_copied: int
    total_failed_files: int
    iterations: list[IngestWatchIteration]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_dir": str(self.source_dir),
            "dataset_root": str(self.dataset_root),
            "split": self.split,
            "interval_seconds": self.interval_seconds,
            "max_runs": self.max_runs,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "total_duration_seconds": self.total_duration_seconds,
            "runs_executed": self.runs_executed,
            "total_scanned_files": self.total_scanned_files,
            "total_processed_files": self.total_processed_files,
            "total_skipped_files": self.total_skipped_files,
            "total_pages_written": self.total_pages_written,
            "total_documents_copied": self.total_documents_copied,
            "total_failed_files": self.total_failed_files,
            "iterations": [iteration.to_dict() for iteration in self.iterations],
        }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return text.lower() or "file"


def _pdf_signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _signature_tag(signature: str) -> str:
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12]


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    if not isinstance(payload, dict):
        return default
    return payload


def _scan_source_files(source_dir: Path, recursive: bool, limit: int) -> list[Path]:
    iterator = source_dir.rglob("*") if recursive else source_dir.glob("*")
    files = sorted(
        [
            p.resolve()
            for p in iterator
            if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
        ]
    )
    if limit > 0:
        files = files[:limit]
    return files


def _load_pdf_pages(path: Path, dpi: int) -> list[np.ndarray]:
    try:
        from pdf2image import convert_from_path  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "pdf2image is required for PDF ingestion. "
            "Install dependencies from takeoff_agent/requirements.txt."
        ) from exc

    import cv2

    pages = convert_from_path(str(path), dpi=dpi)
    images: list[np.ndarray] = []
    for page in pages:
        rgb = np.array(page)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        images.append(bgr)
    return images


def _merge_manifest_entries(
    dataset_root: Path,
    *,
    source_pdf: Path,
    split: str,
    image_rel_paths: list[str],
    document_rel_paths: list[str] | None = None,
) -> Path:
    manifest_path = dataset_root / "manifest.json"
    payload = _load_json(
        manifest_path,
        default={
            "project_name": "Paintbrush.pro",
            "created_at_utc": _now_iso(),
            "notes": "Generated dataset manifest.",
            "classes": [
                "exterior_wall",
                "interior_wall",
                "door",
                "window",
                "fixture",
            ],
            "samples": [],
            "documents": [],
        },
    )
    samples = payload.setdefault("samples", [])
    if not isinstance(samples, list):
        samples = []
        payload["samples"] = samples

    documents = payload.setdefault("documents", [])
    if not isinstance(documents, list):
        documents = []
        payload["documents"] = documents

    existing_images = set()
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        image_path = sample.get("image_path")
        if isinstance(image_path, str):
            existing_images.add(image_path)

    for image_rel in image_rel_paths:
        if image_rel in existing_images:
            continue
        image_name = Path(image_rel).name
        samples.append(
            {
                "added_at_utc": _now_iso(),
                "file_name": image_name,
                "split": split,
                "label_path": f"labels/{split}/{Path(image_name).stem}.txt",
                "image_path": image_rel,
                "source_pdf": str(source_pdf),
                "classes_hint": [
                    "exterior_wall",
                    "interior_wall",
                    "door",
                    "window",
                    "fixture",
                ],
            }
        )
        existing_images.add(image_rel)

    if document_rel_paths:
        existing_docs = set()
        for doc in documents:
            if isinstance(doc, dict) and isinstance(doc.get("document_path"), str):
                existing_docs.add(str(doc["document_path"]))
        for document_rel in document_rel_paths:
            if document_rel in existing_docs:
                continue
            doc_name = Path(document_rel).name
            documents.append(
                {
                    "added_at_utc": _now_iso(),
                    "file_name": doc_name,
                    "split": split,
                    "document_path": document_rel,
                    "source_document": str(source_pdf),
                }
            )
            existing_docs.add(document_rel)

    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def _remove_old_outputs(
    *,
    dataset_root: Path,
    previous_images: list[str],
    previous_documents: list[str],
    keep_images: set[str] | None = None,
    keep_documents: set[str] | None = None,
) -> None:
    keep_images = keep_images or set()
    keep_documents = keep_documents or set()
    for rel_path in previous_images:
        if not isinstance(rel_path, str):
            continue
        if rel_path in keep_images:
            continue
        image_path = dataset_root / rel_path
        if image_path.exists():
            image_path.unlink()
        label_path = (
            dataset_root
            / "labels"
            / image_path.parent.name
            / f"{image_path.stem}.txt"
        )
        if label_path.exists():
            label_path.unlink()
    for rel_path in previous_documents:
        if not isinstance(rel_path, str):
            continue
        if rel_path in keep_documents:
            continue
        document_path = dataset_root / rel_path
        if document_path.exists():
            document_path.unlink()


def _clean_removed_sources(
    *,
    dataset_root: Path,
    state: dict[str, Any],
    current_sources: set[str],
) -> None:
    files_state = state.get("files", {})
    if not isinstance(files_state, dict):
        return
    removed_keys = [key for key in files_state.keys() if key not in current_sources]
    if not removed_keys:
        return

    manifest_path = dataset_root / "manifest.json"
    manifest = _load_json(manifest_path, default={"samples": [], "documents": []})
    samples = manifest.get("samples", [])
    documents = manifest.get("documents", [])
    if not isinstance(samples, list):
        samples = []
    if not isinstance(documents, list):
        documents = []

    removed_image_paths: set[str] = set()
    removed_document_paths: set[str] = set()
    for key in removed_keys:
        payload = files_state.pop(key, {})
        if not isinstance(payload, dict):
            continue
        previous_images = payload.get("images", [])
        previous_documents = payload.get("documents", [])
        _remove_old_outputs(
            dataset_root=dataset_root,
            previous_images=previous_images if isinstance(previous_images, list) else [],
            previous_documents=(
                previous_documents if isinstance(previous_documents, list) else []
            ),
        )
        for rel in previous_images:
            if isinstance(rel, str):
                removed_image_paths.add(rel)
        for rel in previous_documents:
            if isinstance(rel, str):
                removed_document_paths.add(rel)

    manifest["samples"] = [
        row
        for row in samples
        if not (
            isinstance(row, dict)
            and isinstance(row.get("image_path"), str)
            and row["image_path"] in removed_image_paths
        )
    ]
    manifest["documents"] = [
        row
        for row in documents
        if not (
            isinstance(row, dict)
            and isinstance(row.get("document_path"), str)
            and row["document_path"] in removed_document_paths
        )
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def ingest_pdf_folder(
    *,
    source_dir: Path,
    dataset_root: Path,
    split: str,
    dpi: int = 220,
    recursive: bool = True,
    limit_pdfs: int = 0,
    force: bool = False,
    clean_removed: bool = False,
    write_label_stubs: bool = True,
) -> IngestSummary:
    split_norm = split.strip().lower()
    if split_norm not in {"train", "val", "test"}:
        raise ValueError("split must be one of: train, val, test")

    source_dir = source_dir.resolve()
    dataset_root = dataset_root.resolve()
    if not source_dir.exists():
        raise FileNotFoundError(f"Source folder does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise ValueError(f"Source path must be a folder: {source_dir}")

    # Guarantee the dataset scaffold exists before writing images/labels.
    initialize_fresh_dataset(dataset_root, project_name="Paintbrush.pro")
    images_dir = dataset_root / "images" / split_norm
    labels_dir = dataset_root / "labels" / split_norm
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    state_path = dataset_root / "ingestion_state.json"
    state = _load_json(state_path, default={"files": {}})
    files_state = state.setdefault("files", {})
    if not isinstance(files_state, dict):
        files_state = {}
        state["files"] = files_state

    source_files = _scan_source_files(source_dir, recursive=recursive, limit=limit_pdfs)
    scanned_files = len(source_files)
    scanned_pdf_files = sum(1 for path in source_files if path.suffix.lower() in PDF_EXTENSIONS)
    scanned_word_files = sum(
        1 for path in source_files if path.suffix.lower() in WORD_EXTENSIONS
    )
    processed_files = 0
    processed_pdf_files = 0
    processed_word_files = 0
    skipped_files = 0
    pages_written = 0
    documents_copied = 0
    failed_files = 0
    failures: list[dict[str, str]] = []
    current_source_keys = {str(path) for path in source_files}
    if clean_removed:
        _clean_removed_sources(
            dataset_root=dataset_root,
            state=state,
            current_sources=current_source_keys,
        )

    for source_path in source_files:
        key = str(source_path)
        signature = _pdf_signature(source_path)
        prev = files_state.get(key, {})
        prev_signature = prev.get("signature") if isinstance(prev, dict) else None
        prev_outputs = prev.get("images", []) if isinstance(prev, dict) else []
        prev_documents = prev.get("documents", []) if isinstance(prev, dict) else []
        prev_output_ok = isinstance(prev_outputs, list) and all(
            (dataset_root / rel).exists() for rel in prev_outputs if isinstance(rel, str)
        )
        prev_documents_ok = isinstance(prev_documents, list) and all(
            (dataset_root / rel).exists() for rel in prev_documents if isinstance(rel, str)
        )
        has_previous_output = bool(prev_outputs) or bool(prev_documents)

        if (
            not force
            and prev_signature == signature
            and prev_output_ok
            and prev_documents_ok
            and has_previous_output
        ):
            skipped_files += 1
            continue

        try:
            if source_path.suffix.lower() in PDF_EXTENSIONS:
                pages = _load_pdf_pages(source_path, dpi=dpi)
                if not pages:
                    raise RuntimeError("No pages rendered from PDF.")
                rel_outputs: list[str] = []
                source_slug = _slug(source_path.stem)
                source_tag = _signature_tag(signature)
                for page_index, image_bgr in enumerate(pages, start=1):
                    image_name = f"{source_slug}-{source_tag}-p{page_index:03d}.png"
                    image_path = images_dir / image_name

                    import cv2

                    ok = cv2.imwrite(str(image_path), image_bgr)
                    if not ok:
                        raise RuntimeError(f"Failed writing image: {image_path}")

                    if write_label_stubs:
                        label_path = labels_dir / f"{image_path.stem}.txt"
                        if not label_path.exists():
                            label_path.write_text("", encoding="utf-8")

                    rel_outputs.append(f"images/{split_norm}/{image_name}")
                    pages_written += 1

                _remove_old_outputs(
                    dataset_root=dataset_root,
                    previous_images=prev_outputs if isinstance(prev_outputs, list) else [],
                    previous_documents=(
                        prev_documents if isinstance(prev_documents, list) else []
                    ),
                    keep_images=set(rel_outputs),
                )
                _merge_manifest_entries(
                    dataset_root,
                    source_pdf=source_path,
                    split=split_norm,
                    image_rel_paths=rel_outputs,
                    document_rel_paths=[],
                )
                processed_pdf_files += 1
                files_state[key] = {
                    "signature": signature,
                    "kind": "pdf",
                    "updated_at_utc": _now_iso(),
                    "split": split_norm,
                    "images": rel_outputs,
                    "documents": [],
                }
            else:
                docs_dir = dataset_root / "documents" / split_norm
                docs_dir.mkdir(parents=True, exist_ok=True)
                source_slug = _slug(source_path.stem)
                source_tag = _signature_tag(signature)
                target_name = f"{source_slug}-{source_tag}{source_path.suffix.lower()}"
                target_path = docs_dir / target_name
                shutil.copy2(source_path, target_path)
                rel_document = f"documents/{split_norm}/{target_name}"
                _remove_old_outputs(
                    dataset_root=dataset_root,
                    previous_images=prev_outputs if isinstance(prev_outputs, list) else [],
                    previous_documents=(
                        prev_documents if isinstance(prev_documents, list) else []
                    ),
                    keep_documents={rel_document},
                )
                _merge_manifest_entries(
                    dataset_root,
                    source_pdf=source_path,
                    split=split_norm,
                    image_rel_paths=[],
                    document_rel_paths=[rel_document],
                )
                documents_copied += 1
                processed_word_files += 1
                files_state[key] = {
                    "signature": signature,
                    "kind": "word",
                    "updated_at_utc": _now_iso(),
                    "split": split_norm,
                    "images": [],
                    "documents": [rel_document],
                }
            processed_files += 1
        except Exception as exc:
            failed_files += 1
            failures.append({"source": str(source_path), "error": str(exc)})
            continue

    state["last_run_utc"] = _now_iso()
    state["source_dir"] = str(source_dir)
    state["dataset_root"] = str(dataset_root)
    state["split"] = split_norm
    state["allowed_extensions"] = sorted(ALLOWED_EXTENSIONS)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    manifest_path = dataset_root / "manifest.json"
    return IngestSummary(
        source_dir=source_dir,
        dataset_root=dataset_root,
        split=split_norm,
        scanned_files=scanned_files,
        scanned_pdf_files=scanned_pdf_files,
        scanned_word_files=scanned_word_files,
        processed_files=processed_files,
        processed_pdf_files=processed_pdf_files,
        processed_word_files=processed_word_files,
        skipped_files=skipped_files,
        pages_written=pages_written,
        documents_copied=documents_copied,
        failed_files=failed_files,
        state_path=state_path,
        manifest_path=manifest_path,
        failures=failures,
    )


def watch_ingest_folder(
    *,
    source_dir: Path,
    dataset_root: Path,
    split: str,
    interval_seconds: int = 30,
    max_runs: int = 0,
    dpi: int = 220,
    recursive: bool = True,
    limit_files: int = 0,
    force: bool = False,
    clean_removed: bool = False,
    write_label_stubs: bool = True,
) -> IngestWatchSummary:
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be >= 1")
    if max_runs < 0:
        raise ValueError("max_runs must be >= 0")

    run_limit = max_runs if max_runs > 0 else 10**9
    iterations: list[IngestWatchIteration] = []
    started_at_utc = _now_iso()
    started = time.perf_counter()

    for run_index in range(1, run_limit + 1):
        run_started_utc = _now_iso()
        run_started = time.perf_counter()
        summary = ingest_pdf_folder(
            source_dir=source_dir,
            dataset_root=dataset_root,
            split=split,
            dpi=dpi,
            recursive=recursive,
            limit_pdfs=limit_files,
            force=force,
            clean_removed=clean_removed,
            write_label_stubs=write_label_stubs,
        )
        run_duration = round(time.perf_counter() - run_started, 3)
        iterations.append(
            IngestWatchIteration(
                run_index=run_index,
                started_at_utc=run_started_utc,
                completed_at_utc=_now_iso(),
                duration_seconds=run_duration,
                summary=summary,
            )
        )

        if run_index >= run_limit:
            break
        time.sleep(interval_seconds)

    completed_at_utc = _now_iso()
    total_duration_seconds = round(time.perf_counter() - started, 3)
    return IngestWatchSummary(
        source_dir=source_dir.resolve(),
        dataset_root=dataset_root.resolve(),
        split=split.strip().lower(),
        interval_seconds=interval_seconds,
        max_runs=max_runs,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        total_duration_seconds=total_duration_seconds,
        runs_executed=len(iterations),
        total_scanned_files=sum(it.summary.scanned_files for it in iterations),
        total_processed_files=sum(it.summary.processed_files for it in iterations),
        total_skipped_files=sum(it.summary.skipped_files for it in iterations),
        total_pages_written=sum(it.summary.pages_written for it in iterations),
        total_documents_copied=sum(it.summary.documents_copied for it in iterations),
        total_failed_files=sum(it.summary.failed_files for it in iterations),
        iterations=iterations,
    )

