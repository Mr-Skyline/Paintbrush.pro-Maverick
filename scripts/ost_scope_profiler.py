#!/usr/bin/env python3
"""
OST Scope Profiler

Builds a project scope context pack from a PDF plan set:
- page role hints (plan / RCP / finish / schedules / elevations)
- inferred takeoff work packages
- repeated unit patterns
- Boost guidance priorities
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Tuple


def extract_pdf_text(pdf_path: pathlib.Path, max_pages: int = 400) -> List[str]:
    # Try pypdf first, then PyPDF2.
    reader = None
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(pdf_path))
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(str(pdf_path))
        except Exception as exc:
            raise RuntimeError(
                "No PDF text reader available. Install with: pip install pypdf"
            ) from exc

    texts: List[str] = []
    n = min(len(reader.pages), max_pages)
    for i in range(n):
        try:
            txt = reader.pages[i].extract_text() or ""
        except Exception:
            txt = ""
        texts.append(txt)
    return texts


ROLE_PATTERNS: Dict[str, List[str]] = {
    "plan_view": [
        r"\bfloor\s+plan\b",
        r"\bunit\s+[a-z0-9\-]+\s+plan\b",
        r"\barchitectural\s+plan\b",
    ],
    "rcp_view": [
        r"\breflected\s+ceiling\s+plan\b",
        r"\brcp\b",
        r"\bceiling\s+plan\b",
    ],
    "finish_floor_view": [
        r"\bfinish\s+floor\s+plan\b",
        r"\bfloor\s+finish\b",
    ],
    "finish_schedule": [
        r"\bfinish\s+schedule\b",
        r"\bmaterial\s+schedule\b",
    ],
    "door_schedule": [
        r"\bdoor\s+schedule\b",
    ],
    "window_schedule": [
        r"\bwindow\s+schedule\b",
    ],
    "wall_types": [
        r"\bwall\s+type",
        r"\bpartition\s+type",
    ],
    "elevations": [
        r"\belevation(s)?\b",
        r"\binterior\s+elevation\b",
        r"\bexterior\s+elevation\b",
    ],
    "notes_specs": [
        r"\bgeneral\s+notes\b",
        r"\bkeynotes?\b",
        r"\bspecification(s)?\b",
    ],
}


def page_roles(page_text: str) -> Dict[str, int]:
    t = page_text.lower()
    out: Dict[str, int] = {}
    for role, patterns in ROLE_PATTERNS.items():
        hits = 0
        for p in patterns:
            hits += len(re.findall(p, t))
        if hits > 0:
            out[role] = hits
    return out


def detect_unit_tokens(text: str) -> List[str]:
    tokens = re.findall(r"\bunit[\s:._-]*([a-z0-9]{1,6})\b", text.lower())
    return [f"unit-{x}" for x in tokens]


def infer_work_packages(role_counts: Dict[str, int]) -> List[str]:
    wp: List[str] = []
    if role_counts.get("plan_view", 0) > 0:
        wp.append("walls-linear")
        wp.append("room-area")
    if role_counts.get("rcp_view", 0) > 0:
        wp.append("ceiling-area")
    if role_counts.get("finish_floor_view", 0) > 0:
        wp.append("floor-finish-area")
    if role_counts.get("door_schedule", 0) > 0:
        wp.append("doors-count")
    if role_counts.get("window_schedule", 0) > 0:
        wp.append("windows-count")
    if role_counts.get("elevations", 0) > 0:
        wp.append("elevation-wall-area")
    if role_counts.get("finish_schedule", 0) > 0:
        wp.append("finish-validation")
    return sorted(set(wp))


def build_scope_profile(pdf_path: pathlib.Path, max_pages: int = 120) -> Dict[str, Any]:
    texts = extract_pdf_text(pdf_path, max_pages=max_pages)
    per_page_roles: List[Dict[str, Any]] = []
    role_totals: Counter[str] = Counter()
    unit_counter: Counter[str] = Counter()
    role_to_pages: Dict[str, List[int]] = defaultdict(list)

    for idx, txt in enumerate(texts):
        roles = page_roles(txt)
        per_page_roles.append({"page_index": idx, "roles": roles, "text_len": len(txt)})
        for role, count in roles.items():
            role_totals[role] += count
            role_to_pages[role].append(idx)
        for u in detect_unit_tokens(txt):
            unit_counter[u] += 1

    role_totals_dict = dict(role_totals)
    repeated_units = {u: c for u, c in unit_counter.items() if c >= 2}
    unique_units = sorted(unit_counter.keys())

    work_packages = infer_work_packages(role_totals_dict)
    boost_priorities = []
    if "ceiling-area" in work_packages:
        boost_priorities.append("prioritize-rcp-for-ceiling-takeoff")
    if "walls-linear" in work_packages:
        boost_priorities.append("prioritize-plan-for-wall-runs")
    if "floor-finish-area" in work_packages:
        boost_priorities.append("prioritize-finish-floor-plan")
    if "doors-count" in work_packages or "windows-count" in work_packages:
        boost_priorities.append("cross-check-counts-with-schedules")

    # Page grouping guidance: do not depend on unit labels.
    grouping_guidance = {
        "strategy": "scope-first",
        "primary_dimensions": [
            "sheet_role(plan/rcp/finish/schedule)",
            "drawing_completeness",
            "markup_density",
            "detail_level",
        ],
        "note": "Select best candidate per sheet role first, then per repeated unit geometry.",
    }

    return {
        "ts": datetime.now().isoformat(),
        "pdf_path": str(pdf_path),
        "page_count": len(texts),
        "role_totals": role_totals_dict,
        "role_to_pages": {k: sorted(set(v)) for k, v in role_to_pages.items()},
        "work_packages": work_packages,
        "repeated_units": repeated_units,
        "unique_unit_tokens": unique_units,
        "boost_priorities": boost_priorities,
        "grouping_guidance": grouping_guidance,
        "per_page_roles": per_page_roles,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile plan-set scope from PDF")
    parser.add_argument("--pdf", required=True, help="Path to PDF plan set")
    parser.add_argument(
        "--output",
        default="output/ost-scope-profiler/latest.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=120,
        help="Max number of pages to analyze",
    )
    args = parser.parse_args()

    pdf_path = pathlib.Path(args.pdf)
    if not pdf_path.exists():
        print(f"Missing PDF: {pdf_path}")
        return 2

    profile = build_scope_profile(pdf_path, max_pages=max(10, int(args.max_pages)))
    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(f"scope_profile_saved={out_path}")
    print(f"page_count={profile['page_count']} work_packages={len(profile['work_packages'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
