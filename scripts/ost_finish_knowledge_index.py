#!/usr/bin/env python3
"""
Build a merged finish knowledge index from symbol indexes and attempt telemetry.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Tuple


def read_json(path: pathlib.Path, fallback: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return fallback


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build merged finish knowledge index")
    p.add_argument("--project-id", default="TP-0001")
    p.add_argument("--symbol-index-glob", default="output/ost-training-lab/symbol_knowledge/*/symbol_index_*.json")
    p.add_argument("--attempt-glob", default="output/ost-training-lab/attempt_ATT-*.json")
    p.add_argument("--output-root", default="output/ost-training-lab/finish_knowledge")
    p.add_argument("--min-class-support", type=int, default=5)
    p.add_argument("--max-example-paths", type=int, default=20)
    return p.parse_args()


def _merge_embeddings(rows: List[Tuple[List[float], int]]) -> List[float]:
    if not rows:
        return []
    dim = len(rows[0][0])
    out = [0.0] * dim
    total_w = 0.0
    for emb, w in rows:
        if len(emb) != dim:
            continue
        wf = float(max(1, int(w)))
        total_w += wf
        for i, v in enumerate(emb):
            out[i] += float(v) * wf
    if total_w <= 0:
        return []
    return [round(v / total_w, 6) for v in out]


def _detect_design_set_hints(text: str) -> Dict[str, float]:
    low = str(text or "").lower()
    signatures = {
        "autocad_like": ["a-", "xref", "layer", "ctb", "stb"],
        "revit_like": ["sheet", "view", "level", "room tag", "detail"],
        "vectorworks_like": ["class", "design layer", "sheet layer"],
    }
    out: Dict[str, float] = {}
    for key, pats in signatures.items():
        hits = sum(1 for p in pats if p in low)
        out[key] = round(hits / max(1, len(pats)), 3)
    return out


def main() -> int:
    args = parse_args()
    output_root = pathlib.Path(args.output_root).expanduser().resolve() / str(args.project_id)
    output_root.mkdir(parents=True, exist_ok=True)

    symbol_paths = sorted(pathlib.Path(".").glob(str(args.symbol_index_glob)))
    attempt_paths = sorted(pathlib.Path(".").glob(str(args.attempt_glob)))

    class_buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"rows": [], "examples": []})
    dedupe_guard = set()
    for sp in symbol_paths:
        idx = read_json(sp, {})
        protos = idx.get("prototypes", {}) if isinstance(idx, dict) else {}
        for cls, row in protos.items():
            if not isinstance(row, dict):
                continue
            emb = row.get("prototype_embedding", [])
            cnt = int(row.get("count", 0) or 0)
            if not isinstance(emb, list) or not emb:
                continue
            emb_key = f"{cls}|{','.join([str(round(float(x), 6)) for x in emb[:16]])}"
            if emb_key in dedupe_guard:
                continue
            dedupe_guard.add(emb_key)
            class_buckets[cls]["rows"].append(([float(x) for x in emb], max(1, cnt)))
            class_buckets[cls]["examples"].extend([str(x) for x in (row.get("example_paths", []) or [])])

    symbol_index: Dict[str, Any] = {}
    for cls, bucket in class_buckets.items():
        merged = _merge_embeddings(bucket["rows"])
        support = int(sum(w for _, w in bucket["rows"]))
        quality = "pass" if support >= int(args.min_class_support) else "warn"
        symbol_index[cls] = {
            "support_count": support,
            "prototype_embedding": merged,
            "quality_status": quality,
            "example_paths": list(dict.fromkeys(bucket["examples"]))[: int(args.max_example_paths)],
        }

    height_patterns: Dict[str, int] = defaultdict(int)
    notation_tokens: Dict[str, int] = defaultdict(int)
    design_scores: Dict[str, List[float]] = defaultdict(list)
    finish_trade_counts: Dict[str, int] = defaultdict(int)

    for ap in attempt_paths:
        row = read_json(ap, {})
        if not isinstance(row, dict):
            continue
        snap = row.get("finish_learning_snapshot", {})
        if not isinstance(snap, dict):
            continue
        trade = str(snap.get("inferred_trade", "") or "").strip().lower()
        if trade:
            finish_trade_counts[trade] += 1
        for token in (snap.get("height_notation_hits", []) or []):
            notation_tokens[str(token).lower()] += 1
        for h in (snap.get("height_samples", []) or []):
            height_patterns[str(h)] += 1
        source_text = " ".join(
            [
                str(snap.get("condition_name", "")),
                str(row.get("project_name", "")),
                str((row.get("module_goal", "") if isinstance(row.get("module_goal", ""), str) else "")),
            ]
        )
        ds = _detect_design_set_hints(source_text)
        for k, v in ds.items():
            design_scores[k].append(float(v))

    design_set_signature_index = {
        k: {
            "avg_score": round(sum(vals) / max(1, len(vals)), 3),
            "samples": len(vals),
        }
        for k, vals in design_scores.items()
    }
    height_notation_index = {
        "tokens": dict(sorted(notation_tokens.items(), key=lambda kv: kv[1], reverse=True)),
        "patterns": dict(sorted(height_patterns.items(), key=lambda kv: kv[1], reverse=True)),
    }
    finish_trade_index = dict(sorted(finish_trade_counts.items(), key=lambda kv: kv[1], reverse=True))

    payload = {
        "ok": True,
        "project_id": str(args.project_id),
        "created_at": datetime.now().isoformat(),
        "source_counts": {
            "symbol_index_files": len(symbol_paths),
            "attempt_files": len(attempt_paths),
        },
        "quality_thresholds": {"min_class_support": int(args.min_class_support)},
        "symbol_index": symbol_index,
        "height_notation_index": height_notation_index,
        "design_set_signature_index": design_set_signature_index,
        "finish_trade_index": finish_trade_index,
    }
    out_json = output_root / f"finish_knowledge_index_{now_tag()}.json"
    latest_json = output_root / "finish_knowledge_index_latest.json"
    write_json(out_json, payload)
    write_json(latest_json, payload)
    print(str(out_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

