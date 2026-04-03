#!/usr/bin/env python3
"""
OST Project Scope Report

Scans a project folder for relevant documents and builds:
- scope-of-work summary
- painting / wallcover / high-performance product callouts
- finish schedule insights
- inferred unit matrix
- conflicting information flags
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Tuple


TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".rtf"}
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}

PRODUCT_PATTERNS = {
    "sherwin_williams": [r"\bsherwin[\s\-]*williams\b", r"\bpro[\s\-]?mar\b", r"\bduration\b", r"\bemerald\b"],
    "benjamin_moore": [r"\bbenjamin\s+moore\b", r"\baura\b", r"\bscuff[\s\-]*x\b"],
    "ppg": [r"\bppg\b", r"\bpitt[\s\-]*tech\b", r"\bbreak[\s\-]*through\b"],
    "behr": [r"\bbehr\b", r"\bultra\b", r"\bmarquee\b"],
    "wallcovering": [r"\bwallcover(ing)?\b", r"\bvinyl\s+wallcovering\b", r"\btype\s+ii\b", r"\btype\s+iii\b"],
    "high_performance": [
        r"\bepoxy\b",
        r"\burethane\b",
        r"\bintumescent\b",
        r"\banti[\s\-]*microbial\b",
        r"\bchemical[\s\-]*resistant\b",
        r"\bhigh[\s\-]*performance\b",
    ],
}

PAINT_BRAND_FAMILIES = {"sherwin_williams", "benjamin_moore", "ppg", "behr"}

SCOPE_PATTERNS = {
    "paint_walls": [r"\bpaint(ed|ing)?\s+walls?\b", r"\bwall\s+paint\b"],
    "paint_ceilings": [r"\bpaint(ed|ing)?\s+ceilings?\b", r"\bceiling\s+paint\b"],
    "paint_doors_frames": [r"\bdoors?\b", r"\bframes?\b", r"\bdoor\s+frame\b"],
    "wallcover_install": [r"\binstall\b.*\bwallcover", r"\bwallcover.*\binstall\b"],
    "surface_prep": [r"\bsurface\s+prep\b", r"\bprepare\s+surfaces?\b", r"\bpatch(ing)?\b", r"\bskim\s+coat\b"],
}


def read_text_file(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def read_csv_file(path: pathlib.Path) -> str:
    rows = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            r = csv.reader(f)
            for i, row in enumerate(r):
                if i > 3000:
                    break
                rows.append(" | ".join(row))
    except Exception:
        return ""
    return "\n".join(rows)


def read_json_file(path: pathlib.Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return json.dumps(data)[:400000]
    except Exception:
        return ""


def read_pdf_file(path: pathlib.Path, max_pages: int = 80) -> str:
    reader = None
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(str(path))
        except Exception:
            return ""
    out = []
    n = min(len(reader.pages), max_pages)
    for i in range(n):
        try:
            out.append(reader.pages[i].extract_text() or "")
        except Exception:
            pass
    return "\n".join(out)


def read_docx_file(path: pathlib.Path) -> str:
    # Dependency-free minimal docx extraction.
    try:
        with zipfile.ZipFile(path) as zf:
            with zf.open("word/document.xml") as f:
                xml = f.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<[^>]+>", " ", xml)
    xml = re.sub(r"\s+", " ", xml)
    return xml


def gather_documents(folder: pathlib.Path, max_files: int = 160) -> List[pathlib.Path]:
    files = []
    for p in folder.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in TEXT_EXTS or ext in PDF_EXTS or ext in DOCX_EXTS:
            files.append(p)
    files = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)
    return files[:max_files]


def extract_finish_codes(text: str) -> List[str]:
    codes = set()
    for m in re.findall(r"\bF[\s\-]*([0-9]{1,3})\b", text, flags=re.IGNORECASE):
        codes.add(f"F-{m}")
    for m in re.findall(r"\bFINISH[\s\-]*([0-9]{1,3})\b", text, flags=re.IGNORECASE):
        codes.add(f"F-{m}")
    return sorted(codes)


def extract_unit_tokens(text: str) -> List[str]:
    units = set()
    for m in re.findall(r"\bUNIT[\s:._-]*([A-Z0-9\-]{1,6})\b", text, flags=re.IGNORECASE):
        units.add(f"UNIT-{m.upper()}")
    return sorted(units)


def count_patterns(text: str, patterns: Dict[str, List[str]]) -> Dict[str, int]:
    t = text.lower()
    out: Dict[str, int] = {}
    for key, ps in patterns.items():
        c = 0
        for p in ps:
            c += len(re.findall(p, t))
        out[key] = c
    return out


def analyze_folder(folder: pathlib.Path, max_files: int = 160, max_pdf_pages: int = 80) -> Dict[str, Any]:
    docs = gather_documents(folder, max_files=max_files)
    doc_summaries = []
    product_counter: Counter[str] = Counter()
    scope_counter: Counter[str] = Counter()
    finish_to_products: Dict[str, Counter[str]] = defaultdict(Counter)
    finish_family_doc_support: Dict[str, Dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    unit_finish_counter: Dict[str, Counter[str]] = defaultdict(Counter)
    finish_occurrence: Counter[str] = Counter()
    role_counter: Counter[str] = Counter()
    conflicts: List[Dict[str, Any]] = []

    for d in docs:
        ext = d.suffix.lower()
        text = ""
        if ext in {".txt", ".md", ".log", ".rtf"}:
            text = read_text_file(d)
        elif ext == ".csv":
            text = read_csv_file(d)
        elif ext == ".json":
            text = read_json_file(d)
        elif ext in PDF_EXTS:
            text = read_pdf_file(d, max_pages=max_pdf_pages)
        elif ext in DOCX_EXTS:
            text = read_docx_file(d)

        text = text[:600000]
        if not text.strip():
            continue

        finish_codes = extract_finish_codes(text)
        units = extract_unit_tokens(text)
        prod_hits = count_patterns(text, PRODUCT_PATTERNS)
        scope_hits = count_patterns(text, SCOPE_PATTERNS)

        for k, v in prod_hits.items():
            if v > 0:
                product_counter[k] += v
        for k, v in scope_hits.items():
            if v > 0:
                scope_counter[k] += v
        for f in finish_codes:
            finish_occurrence[f] += 1

        # role hints
        lt = text.lower()
        if "finish schedule" in lt:
            role_counter["finish_schedule_docs"] += 1
        if "specification" in lt or "section 09" in lt:
            role_counter["spec_docs"] += 1
        if "reflected ceiling plan" in lt or re.search(r"\brcp\b", lt):
            role_counter["rcp_docs"] += 1

        present_product_families = [k for k, v in prod_hits.items() if v > 0]
        doc_signature = str(d).lower()
        for f in finish_codes:
            for pf in present_product_families:
                finish_to_products[f][pf] += 1
                finish_family_doc_support[f][pf].add(doc_signature)
        for u in units:
            for f in finish_codes:
                unit_finish_counter[u][f] += 1

        doc_summaries.append(
            {
                "path": str(d),
                "ext": ext,
                "chars": len(text),
                "finish_codes": finish_codes,
                "unit_tokens": units,
                "product_hits": {k: v for k, v in prod_hits.items() if v > 0},
                "scope_hits": {k: v for k, v in scope_hits.items() if v > 0},
            }
        )

    def confidence_label(score: float) -> str:
        if score >= 0.75:
            return "high"
        if score >= 0.45:
            return "medium"
        return "low"

    # conflicts: finish code tied to incompatible product families.
    # Use confidence gates to reduce false positives from noisy OCR/doc spillover.
    for finish, fam_counter in finish_to_products.items():
        fams = [k for k, v in fam_counter.items() if v > 0]
        strong_fams = [k for k, v in fam_counter.items() if v >= 2]
        strong_total = sum(v for v in fam_counter.values() if v >= 2)
        support_counts = {
            fam: len(finish_family_doc_support.get(finish, {}).get(fam, set()))
            for fam in strong_fams
        }
        strong_support = [fam for fam, c in support_counts.items() if c >= 2]
        paint_brand_count = sum(1 for k in strong_fams if k in PAINT_BRAND_FAMILIES)
        has_wallcover = "wallcovering" in strong_fams
        has_hpf = "high_performance" in strong_fams
        coverage_component = min(1.0, strong_total / 10.0)
        doc_support_component = min(1.0, sum(support_counts.values()) / 8.0)
        confidence_score = round((0.6 * coverage_component) + (0.4 * doc_support_component), 3)
        confidence = confidence_label(confidence_score)
        # Critical when competing paint brands are both strongly indicated for same finish code.
        # Otherwise keep as warning if mixed domains are strongly indicated.
        if paint_brand_count >= 2 and strong_total >= 4 and len(strong_support) >= 2:
            conflicts.append(
                {
                    "kind": "finish_product_conflict",
                    "finish_code": finish,
                    "severity": "critical",
                    "families": sorted(strong_fams),
                    "support_doc_counts": support_counts,
                    "confidence": confidence,
                    "confidence_score": confidence_score,
                    "details": dict(fam_counter),
                }
            )
        elif (
            ((has_wallcover and paint_brand_count >= 1) or (has_hpf and paint_brand_count >= 1))
            and strong_total >= 3
            and len(strong_support) >= 2
        ):
            conflicts.append(
                {
                    "kind": "finish_product_conflict",
                    "finish_code": finish,
                    "severity": "warn",
                    "families": sorted(strong_fams),
                    "support_doc_counts": support_counts,
                    "confidence": confidence,
                    "confidence_score": confidence_score,
                    "details": dict(fam_counter),
                }
            )

    # conflict: same unit token mapped to many finish codes (potentially inconsistent matrix)
    for unit, fc in unit_finish_counter.items():
        if len(fc.keys()) >= 6:
            conflicts.append(
                {
                    "kind": "unit_finish_matrix_complexity",
                    "unit": unit,
                    "severity": "warn",
                    "confidence": "medium" if len(fc.keys()) >= 8 else "low",
                    "confidence_score": 0.6 if len(fc.keys()) >= 8 else 0.35,
                    "finish_count": len(fc.keys()),
                    "details": dict(fc),
                }
            )

    # Dedupe repeated conflicts and keep highest-confidence variant.
    deduped: Dict[str, Dict[str, Any]] = {}
    for c in conflicts:
        if c.get("kind") == "finish_product_conflict":
            fams = ",".join(sorted(c.get("families") or []))
            key = f"{c.get('kind')}::{c.get('finish_code')}::{c.get('severity')}::{fams}"
        elif c.get("kind") == "unit_finish_matrix_complexity":
            key = f"{c.get('kind')}::{c.get('unit')}"
        else:
            key = json.dumps(c, sort_keys=True)
        prev = deduped.get(key)
        if prev is None:
            deduped[key] = c
        else:
            prev_score = float(prev.get("confidence_score", 0.0) or 0.0)
            new_score = float(c.get("confidence_score", 0.0) or 0.0)
            if new_score > prev_score:
                deduped[key] = c
    conflicts = list(deduped.values())

    # inferred unit matrix
    unit_matrix = []
    for unit, fc in sorted(unit_finish_counter.items()):
        row = {"unit": unit, "finish_codes": sorted(fc.keys()), "counts": dict(fc)}
        unit_matrix.append(row)

    conflict_summary = {
        "total": len(conflicts),
        "critical": sum(1 for c in conflicts if c.get("severity") == "critical"),
        "warn": sum(1 for c in conflicts if c.get("severity") == "warn"),
        "high_confidence": sum(1 for c in conflicts if c.get("confidence") == "high"),
        "medium_confidence": sum(1 for c in conflicts if c.get("confidence") == "medium"),
        "low_confidence": sum(1 for c in conflicts if c.get("confidence") == "low"),
        "actionable": sum(
            1
            for c in conflicts
            if c.get("severity") == "critical" or c.get("confidence") in {"high", "medium"}
        ),
        "informational": sum(
            1
            for c in conflicts
            if c.get("severity") != "critical" and c.get("confidence") == "low"
        ),
    }

    return {
        "ts": datetime.now().isoformat(),
        "project_folder": str(folder),
        "document_count": len(doc_summaries),
        "documents": doc_summaries,
        "scope_signals": dict(scope_counter),
        "product_signals": dict(product_counter),
        "finish_codes": dict(finish_occurrence),
        "role_signals": dict(role_counter),
        "unit_matrix": unit_matrix,
        "conflicts": conflicts,
        "conflict_summary": conflict_summary,
    }


def to_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Project Scope Intelligence Report")
    lines.append("")
    lines.append(f"- Generated: `{report.get('ts')}`")
    lines.append(f"- Project folder: `{report.get('project_folder')}`")
    lines.append(f"- Documents analyzed: `{report.get('document_count')}`")
    lines.append("")
    lines.append("## Scope Signals")
    for k, v in sorted((report.get("scope_signals") or {}).items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Product Signals")
    for k, v in sorted((report.get("product_signals") or {}).items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Finish Codes")
    for k, v in sorted((report.get("finish_codes") or {}).items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Conflicts")
    conflicts = report.get("conflicts") or []
    conflict_summary = report.get("conflict_summary") or {}
    if conflict_summary:
        lines.append(
            f"- Summary: total={conflict_summary.get('total', 0)} "
            f"critical={conflict_summary.get('critical', 0)} "
            f"warn={conflict_summary.get('warn', 0)} "
            f"actionable={conflict_summary.get('actionable', 0)} "
            f"informational={conflict_summary.get('informational', 0)}"
        )
    if not conflicts:
        lines.append("- None detected by current heuristics")
    else:
        for c in conflicts:
            lines.append(f"- {c.get('kind')}: {json.dumps(c)}")
    lines.append("")
    lines.append("## Unit Matrix (Inferred)")
    for row in report.get("unit_matrix") or []:
        lines.append(f"- {row.get('unit')}: {', '.join(row.get('finish_codes') or [])}")
    lines.append("")
    lines.append("## Next Actions")
    lines.append("- Validate conflicts against finish schedule sheets and Division 09 specs.")
    lines.append("- Confirm high-performance requirements (epoxy/urethane/intumescent) by space type.")
    lines.append("- Use this report as context for Boost + grouping selection.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build project scope intelligence report")
    parser.add_argument("--project-folder", required=True, help="Project folder path")
    parser.add_argument(
        "--output-json",
        default="output/ost-project-scope/latest.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--output-md",
        default="output/ost-project-scope/latest.md",
        help="Output Markdown report path",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=160,
        help="Max number of docs to analyze",
    )
    parser.add_argument(
        "--max-pdf-pages",
        type=int,
        default=80,
        help="Max pages to read per PDF",
    )
    args = parser.parse_args()

    folder = pathlib.Path(args.project_folder)
    if not folder.exists() or not folder.is_dir():
        print(f"Invalid project folder: {folder}")
        return 2

    report = analyze_folder(
        folder,
        max_files=max(10, int(args.max_files)),
        max_pdf_pages=max(10, int(args.max_pdf_pages)),
    )
    out_json = pathlib.Path(args.output_json)
    out_md = pathlib.Path(args.output_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    out_md.write_text(to_markdown(report), encoding="utf-8")
    print(f"scope_intel_json={out_json}")
    print(f"scope_intel_md={out_md}")
    print(f"documents={report.get('document_count')} conflicts={len(report.get('conflicts') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
