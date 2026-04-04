#!/usr/bin/env python3
"""
Accuracy-focused ingestion pipeline.

Builds a merged accuracy index across:
- conditions/quantities
- finish taxonomy
- symbol knowledge
- height notations
- design signatures
- OCR correction glossary
"""

from __future__ import annotations

import argparse
import difflib
import json
import pathlib
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Set, Tuple


WORKSPACE_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_ROOT = WORKSPACE_ROOT / "output" / "ost-training-lab"


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


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


def write_md(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run accuracy-only ingestion pipeline")
    p.add_argument("--project-id", default="TP-0001")
    p.add_argument("--registry", default="scripts/ost_training_registry.json")
    p.add_argument("--attempt-glob", default="output/ost-training-lab/attempt_ATT-*.json")
    p.add_argument("--training-notes-glob", default="output/ost-training-lab/training_notes_ANL-*.json")
    p.add_argument("--finish-taxonomy-json", default="scripts/ost_finish_taxonomy.json")
    p.add_argument("--output-root", default="output/ost-training-lab/accuracy_knowledge")
    p.add_argument("--min-condition-support", type=int, default=5)
    p.add_argument("--min-symbol-support", type=int, default=5)
    p.add_argument("--min-ocr-pair-support", type=int, default=2)
    p.add_argument("--max-ocr-suggestions", type=int, default=120)
    p.add_argument("--symbol-dataset-root", default="", help="Optional dataset root to run fresh symbol ingestion")
    p.add_argument("--symbol-dataset-name", default="accuracy_ingest")
    return p.parse_args()


def _run_cmd(cmd: List[str], timeout_s: int = 300) -> Dict[str, Any]:
    proc = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=timeout_s)
    return {
        "ok": bool(proc.returncode == 0),
        "exit_code": int(proc.returncode),
        "stdout": str(proc.stdout or "").strip(),
        "stderr": str(proc.stderr or "").strip(),
        "command": cmd,
    }


def _run_cmd_with_retry(cmd: List[str], timeout_s: int = 300, retries: int = 1, backoff_s: float = 1.25) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for i in range(max(1, int(retries) + 1)):
        res = _run_cmd(cmd, timeout_s=timeout_s)
        attempts.append(res)
        if bool(res.get("ok", False)):
            out = dict(res)
            out["attempts"] = attempts
            return out
        if i < int(retries):
            time.sleep(max(0.0, float(backoff_s) * float(i + 1)))
    out = dict(attempts[-1] if attempts else {"ok": False, "exit_code": 1, "stdout": "", "stderr": "", "command": cmd})
    out["attempts"] = attempts
    return out


def _latest_glob(pattern: str) -> pathlib.Path | None:
    rows = sorted(pathlib.Path(".").glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return rows[0] if rows else None


def _collect_strings(node: Any) -> Iterable[str]:
    if isinstance(node, str):
        s = " ".join(node.split()).strip()
        if s:
            yield s
        return
    if isinstance(node, dict):
        for v in node.values():
            yield from _collect_strings(v)
        return
    if isinstance(node, list):
        for v in node:
            yield from _collect_strings(v)


def _tokenize_text_for_ocr(s: str) -> Iterable[str]:
    # Keep OCR-like words, short phrases, and numeric+notation tokens.
    raw_tokens = re.findall(r"[A-Za-z0-9\.\-'/]{3,}", str(s or ""))
    for tok in raw_tokens:
        t = tok.strip().lower().strip(".,;:()[]{}")
        if t:
            yield t


def _blueprint_noise_tokens() -> Set[str]:
    return {
        "python",
        "scripts",
        "output",
        "json",
        "jsonl",
        "stdout",
        "stderr",
        "command",
        "project",
        "training",
        "attempt",
        "attempts",
        "selection",
        "conditions",
        "condition",
        "classifier",
        "fastscan",
        "tesseract",
        "glmocr",
        "takeoff",
        "no-boost",
        "tp-0001",
        "cleanup",
        "unknown",
        "pattern",
        "blank",
        "drawing",
        "batch",
        "gates",
        "strict",
        "complete",
        "sequence",
        "proof",
        "artifacts",
        "active",
        "primary",
        "common",
        "cannot",
        "confirm",
        "evidence",
    }


def _is_noise_token(tok: str) -> bool:
    t = str(tok or "").strip().lower()
    if not t:
        return True
    if t in _blueprint_noise_tokens():
        return True
    if t.startswith("--"):
        return True
    if "/" in t or "\\" in t:
        return True
    if re.fullmatch(r"\d{6,}", t):
        return True
    if re.fullmatch(r"[0-9a-f]{16,}", t):
        return True
    return False


def _attempt_text_corpus(row: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if not isinstance(row, dict):
        return out

    # Keep fields likely to contain plan text/labels, skip command/trace noise.
    for key in ("project_name", "module_goal"):
        v = str(row.get(key, "") or "").strip()
        if v:
            out.append(v)

    snap = row.get("finish_learning_snapshot", {})
    if isinstance(snap, dict):
        for key in (
            "condition_name",
            "condition_style",
            "inferred_trade",
            "ceiling_type_hint",
        ):
            v = str(snap.get(key, "") or "").strip()
            if v:
                out.append(v)
        for key in ("height_samples", "height_notation_hits", "design_set_hints"):
            vals = snap.get(key, [])
            if isinstance(vals, list):
                out.extend([str(x).strip() for x in vals if str(x).strip()])

    takeoff = row.get("takeoff_copy_summary", {})
    if isinstance(takeoff, dict):
        result = takeoff.get("result", {}) if isinstance(takeoff.get("result", {}), dict) else {}
        for key in ("active_condition_name", "condition_style", "reason"):
            v = str(result.get(key, "") or "").strip()
            if v:
                out.append(v)
        for item in result.get("allowed_condition_names", []) if isinstance(result.get("allowed_condition_names", []), list) else []:
            s = str(item).strip()
            if s:
                out.append(s)

        ocr_tel = result.get("ocr_telemetry", {}) if isinstance(result.get("ocr_telemetry", {}), dict) else {}
        plan = ocr_tel.get("plan_preread", {}) if isinstance(ocr_tel.get("plan_preread", {}), dict) else {}
        for key in ("text", "ocr_preview"):
            v = str(plan.get(key, "") or "").strip()
            if v:
                out.append(v)
        cue_hits = plan.get("cue_hits", []) if isinstance(plan.get("cue_hits", []), list) else []
        out.extend([str(x).strip() for x in cue_hits if str(x).strip()])

    # Include evidence text snippets from notes if present.
    evidence = row.get("evidence_samples", [])
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                for key in ("condition", "room_or_location", "text"):
                    v = str(item.get(key, "") or "").strip()
                    if v:
                        out.append(v)
    return out


def _notes_text_corpus(notes_payload: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if not isinstance(notes_payload, dict):
        return out
    for key in ("observations", "reasoning"):
        vals = notes_payload.get(key, [])
        if isinstance(vals, list):
            out.extend([str(x).strip() for x in vals if str(x).strip()])
    for row in notes_payload.get("top_active_conditions", []) if isinstance(notes_payload.get("top_active_conditions", []), list) else []:
        if isinstance(row, dict):
            for key in ("condition", "sample_room"):
                s = str(row.get(key, "") or "").strip()
                if s:
                    out.append(s)
    for row in notes_payload.get("evidence_samples", []) if isinstance(notes_payload.get("evidence_samples", []), list) else []:
        if isinstance(row, dict):
            for key in ("condition", "room_or_location", "text"):
                s = str(row.get(key, "") or "").strip()
                if s:
                    out.append(s)
    return out


def _resolve_symbol_dataset_root(arg_root: str) -> Tuple[str, Dict[str, Any]]:
    requested = str(arg_root or "").strip()
    if requested:
        p = pathlib.Path(requested).expanduser()
        if p.exists() and p.is_dir():
            return str(p), {"ok": True, "mode": "explicit", "path": str(p)}
        return "", {"ok": False, "mode": "explicit", "reason": "missing_or_not_dir", "path": str(p)}

    # Try common local roots automatically.
    candidates = [
        OUT_ROOT / "symbol_seed_dataset",
        OUT_ROOT / "symbol_dataset",
        WORKSPACE_ROOT / "datasets" / "symbols",
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return str(p), {"ok": True, "mode": "auto", "path": str(p)}
    return "", {"ok": False, "mode": "auto", "reason": "no_symbol_dataset_found"}


def _canonical_vocab(finish_taxonomy: Dict[str, Any]) -> List[str]:
    vocab = {"ceiling", "gwb", "gypsum", "wallboard", "door", "frame", "trim", "base", "paint"}
    trades = finish_taxonomy.get("trades", {}) if isinstance(finish_taxonomy, dict) else {}
    if isinstance(trades, dict):
        for trade, row in trades.items():
            vocab.add(str(trade).strip().lower())
            if isinstance(row, dict):
                for a in row.get("aliases", []) or []:
                    vocab.add(str(a).strip().lower().replace(" ", "_"))
                for s in row.get("subtypes", []) or []:
                    vocab.add(str(s).strip().lower())
    return sorted(vocab)


def _best_vocab_match(tok: str, vocab: List[str], min_ratio: float = 0.76) -> Tuple[str, float]:
    best = ""
    best_ratio = 0.0
    for v in vocab:
        r = difflib.SequenceMatcher(a=tok, b=v).ratio()
        if r > best_ratio:
            best_ratio = r
            best = v
    if best_ratio < min_ratio:
        return "", 0.0
    return best, best_ratio


def _extract_height_tokens(texts: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    pat_words = ["aff", "a.f.f.", "clg", "ceiling", "typ", "varies", "elev", "el."]
    for t in texts:
        low = t.lower()
        for w in pat_words:
            if w in low:
                counts[w] += 1
        for m in re.findall(r"\b\d{1,2}'(?:-\d{1,2})?\"?\b", low):
            counts[m] += 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def _design_signature_scores(texts: Iterable[str]) -> Dict[str, Any]:
    sig = {
        "autocad_like": ["a-", "xref", "layer", "ctb", "stb"],
        "revit_like": ["level", "sheet", "view", "detail", "room tag"],
        "vectorworks_like": ["class", "design layer", "sheet layer"],
    }
    texts_list = [x for x in texts if isinstance(x, str) and x.strip()]
    all_text = " ".join([x.lower() for x in texts_list])
    out: Dict[str, Any] = {}
    for k, pats in sig.items():
        hits = sum(1 for p in pats if p in all_text)
        out[k] = {"hits": int(hits), "avg_score": round(float(hits) / max(1, len(pats)), 3), "samples": len(texts_list)}
    return out


def build_accuracy_index(args: argparse.Namespace) -> Dict[str, Any]:
    run_events: List[Dict[str, Any]] = []
    blockers: List[Dict[str, Any]] = []

    # 1) Conditions/quantities baseline from DB notes
    notes_cmd = _run_cmd_with_retry(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "analyze-training-notes",
            "--project-id",
            str(args.project_id),
            "--registry",
            str(args.registry),
        ],
        timeout_s=180,
        retries=1,
    )
    run_events.append({"step": "training_notes", **notes_cmd})
    if not bool(notes_cmd.get("ok", False)):
        blockers.append(
            {
                "id": "training_notes_failed",
                "severity": "high",
                "auto_action": "retry_once",
                "status": "open",
                "details": str(notes_cmd.get("stderr", "") or notes_cmd.get("stdout", "")).strip()[:500],
            }
        )
    latest_notes = _latest_glob(str(args.training_notes_glob))
    notes_payload = read_json(latest_notes, {}) if latest_notes else {}

    # 2) Optional fresh symbols ingestion
    symbol_root, symbol_root_status = _resolve_symbol_dataset_root(str(args.symbol_dataset_root or ""))
    run_events.append({"step": "resolve_symbol_dataset_root", **symbol_root_status})
    if symbol_root_status.get("ok") is False and str(args.symbol_dataset_root or "").strip():
        blockers.append(
            {
                "id": "symbol_dataset_missing",
                "severity": "medium",
                "auto_action": "skip_symbol_ingest_continue",
                "status": "mitigated",
                "details": f"Requested dataset root not available: {symbol_root_status.get('path', '')}",
            }
        )
    if symbol_root:
        scan_report = OUT_ROOT / "symbol_ingest_reports" / f"safety_scan_{args.project_id}_{now_tag()}.json"
        scan_cmd = _run_cmd_with_retry(
            [
                sys.executable,
                "scripts/ost_orchestrator.py",
                "dataset-safety-scan",
                "--dataset-root",
                str(symbol_root),
                "--report-json",
                str(scan_report),
                "--max-file-size-mb",
                "50",
            ],
            timeout_s=240,
            retries=1,
        )
        run_events.append({"step": "dataset_safety_scan", **scan_cmd, "report_json": str(scan_report)})
        if not bool(scan_cmd.get("ok", False)):
            blockers.append(
                {
                    "id": "dataset_safety_scan_failed",
                    "severity": "medium",
                    "auto_action": "skip_symbol_ingest_continue",
                    "status": "mitigated",
                    "details": str(scan_cmd.get("stderr", "") or scan_cmd.get("stdout", "")).strip()[:500],
                }
            )
        ingest_cmd = _run_cmd_with_retry(
            [
                sys.executable,
                "scripts/ost_orchestrator.py",
                "symbol-knowledge-ingest",
                "--project-id",
                str(args.project_id),
                "--dataset-root",
                str(symbol_root),
                "--dataset-name",
                str(args.symbol_dataset_name),
                "--min-per-class",
                "3",
                "--max-file-size-mb",
                "50",
            ],
            timeout_s=600,
            retries=1,
        )
        run_events.append({"step": "symbol_knowledge_ingest", **ingest_cmd})
        if not bool(ingest_cmd.get("ok", False)):
            blockers.append(
                {
                    "id": "symbol_ingest_failed",
                    "severity": "medium",
                    "auto_action": "continue_with_latest_symbol_index",
                    "status": "mitigated",
                    "details": str(ingest_cmd.get("stderr", "") or ingest_cmd.get("stdout", "")).strip()[:500],
                }
            )

    # 3) Rebuild finish index (includes symbols+attempt telemetry snapshots)
    finish_cmd = _run_cmd_with_retry(
        [
            sys.executable,
            "scripts/ost_orchestrator.py",
            "finish-knowledge-index-build",
            "--project-id",
            str(args.project_id),
        ],
        timeout_s=300,
        retries=1,
    )
    run_events.append({"step": "finish_knowledge_index_build", **finish_cmd})
    if not bool(finish_cmd.get("ok", False)):
        blockers.append(
            {
                "id": "finish_index_build_failed",
                "severity": "high",
                "auto_action": "continue_with_latest_snapshot_if_present",
                "status": "open",
                "details": str(finish_cmd.get("stderr", "") or finish_cmd.get("stdout", "")).strip()[:500],
            }
        )
    latest_finish = _latest_glob(f"output/ost-training-lab/finish_knowledge/{args.project_id}/finish_knowledge_index_*.json")
    finish_payload = read_json(latest_finish, {}) if latest_finish else {}
    latest_symbol = _latest_glob(f"output/ost-training-lab/symbol_knowledge/{args.project_id}/symbol_index_*.json")
    symbol_payload = read_json(latest_symbol, {}) if latest_symbol else {}
    finish_taxonomy = read_json(pathlib.Path(args.finish_taxonomy_json), {})
    if not latest_finish:
        blockers.append(
            {
                "id": "missing_finish_index_artifact",
                "severity": "high",
                "auto_action": "keep_pipeline_running_with_empty_finish_payload",
                "status": "open",
                "details": "No finish knowledge artifact found for project",
            }
        )
    if not latest_symbol:
        blockers.append(
            {
                "id": "missing_symbol_index_artifact",
                "severity": "low",
                "auto_action": "continue_without_symbol_domain_enrichment",
                "status": "mitigated",
                "details": "No symbol knowledge artifact found for project",
            }
        )

    # 4) Attempt corpus for OCR/height/design enrichments
    attempt_paths = sorted(pathlib.Path(".").glob(str(args.attempt_glob)))
    corpus_texts: List[str] = []
    for p in attempt_paths:
        row = read_json(p, {})
        if isinstance(row, dict):
            corpus_texts.extend(_attempt_text_corpus(row))
    corpus_texts.extend(_notes_text_corpus(notes_payload))
    if len(attempt_paths) == 0:
        blockers.append(
            {
                "id": "no_attempt_files",
                "severity": "medium",
                "auto_action": "fallback_to_notes_and_taxonomy_only",
                "status": "mitigated",
                "details": f"Attempt glob returned no files: {args.attempt_glob}",
            }
        )

    # OCR glossary generation
    vocab = _canonical_vocab(finish_taxonomy)
    pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    pair_conf_sum: Dict[Tuple[str, str], float] = defaultdict(float)
    unresolved_counts: Dict[str, int] = defaultdict(int)
    for text in corpus_texts:
        for tok in _tokenize_text_for_ocr(text):
            if _is_noise_token(tok):
                continue
            match, conf = _best_vocab_match(tok, vocab, min_ratio=0.78)
            if match and tok != match:
                k = (tok, match)
                pair_counts[k] += 1
                pair_conf_sum[k] += float(conf)
            elif not match and len(tok) >= 5 and not _is_noise_token(tok):
                unresolved_counts[tok] += 1

    ocr_pairs: List[Dict[str, Any]] = []
    for (raw, canonical), cnt in sorted(pair_counts.items(), key=lambda kv: kv[1], reverse=True):
        if cnt < int(args.min_ocr_pair_support):
            continue
        conf = pair_conf_sum[(raw, canonical)] / max(1, cnt)
        ocr_pairs.append(
            {
                "raw": raw,
                "canonical": canonical,
                "support_count": int(cnt),
                "confidence": round(float(conf), 4),
            }
        )
    ocr_pairs = ocr_pairs[: max(10, int(args.max_ocr_suggestions))]
    unresolved = [
        {"token": k, "support_count": int(v)}
        for k, v in sorted(unresolved_counts.items(), key=lambda kv: kv[1], reverse=True)[:120]
    ]

    # Domain projections
    category_hits = notes_payload.get("category_hits", {}) if isinstance(notes_payload.get("category_hits", {}), dict) else {}
    top_conditions = notes_payload.get("top_active_conditions", []) if isinstance(notes_payload.get("top_active_conditions", []), list) else []
    symbol_index = finish_payload.get("symbol_index", {}) if isinstance(finish_payload.get("symbol_index", {}), dict) else {}
    finish_trade_index = finish_payload.get("finish_trade_index", {}) if isinstance(finish_payload.get("finish_trade_index", {}), dict) else {}
    height_index = finish_payload.get("height_notation_index", {}) if isinstance(finish_payload.get("height_notation_index", {}), dict) else {}
    design_index = finish_payload.get("design_set_signature_index", {}) if isinstance(finish_payload.get("design_set_signature_index", {}), dict) else {}

    extra_height_tokens = _extract_height_tokens(corpus_texts)
    design_from_corpus = _design_signature_scores(corpus_texts)

    contracts = {
        "version": 1,
        "domains": {
            "conditions_quantities": {
                "required_keys": ["rows_scanned", "active_rows", "category_hits", "top_active_conditions"],
            },
            "finish_taxonomy": {
                "required_keys": ["trades", "height_notation_patterns", "design_set_signatures"],
            },
            "symbol_knowledge": {
                "required_keys": ["symbol_classes", "support_counts", "quality_status"],
            },
            "height_notations": {
                "required_keys": ["tokens", "patterns", "source_counts"],
            },
            "design_signatures": {
                "required_keys": ["autocad_like", "revit_like", "vectorworks_like"],
            },
            "ocr_glossary": {
                "required_keys": ["corrections", "unresolved_tokens", "min_support"],
            },
        },
    }

    domains = {
        "conditions_quantities": {
            "rows_scanned": int(notes_payload.get("rows_scanned", 0) or 0),
            "active_rows": int(notes_payload.get("active_rows", 0) or 0),
            "category_hits": category_hits,
            "top_active_conditions": top_conditions[:20],
            "condition_label_map_size": int(notes_payload.get("condition_label_map_size", 0) or 0),
        },
        "finish_taxonomy": {
            "version": int(finish_taxonomy.get("version", 0) or 0),
            "trades": finish_taxonomy.get("trades", {}) if isinstance(finish_taxonomy.get("trades", {}), dict) else {},
            "height_notation_patterns": finish_taxonomy.get("height_notation_patterns", []) if isinstance(finish_taxonomy.get("height_notation_patterns", []), list) else [],
            "design_set_signatures": finish_taxonomy.get("design_set_signatures", {}) if isinstance(finish_taxonomy.get("design_set_signatures", {}), dict) else {},
            "observed_finish_trades": finish_trade_index,
        },
        "symbol_knowledge": {
            "symbol_classes": sorted(symbol_index.keys()),
            "support_counts": {k: int((v.get("support_count", 0) if isinstance(v, dict) else 0) or 0) for k, v in symbol_index.items()},
            "quality_status": {k: str((v.get("quality_status", "warn") if isinstance(v, dict) else "warn") or "warn") for k, v in symbol_index.items()},
            "latest_symbol_source": str(latest_symbol) if latest_symbol else "",
            "latest_finish_source": str(latest_finish) if latest_finish else "",
            "symbol_index_raw_ok": bool(symbol_payload.get("ok", False)),
        },
        "height_notations": {
            "tokens": height_index.get("tokens", {}) if isinstance(height_index.get("tokens", {}), dict) else {},
            "patterns": height_index.get("patterns", {}) if isinstance(height_index.get("patterns", {}), dict) else {},
            "extra_tokens_from_corpus": extra_height_tokens,
            "source_counts": {
                "attempt_files": len(attempt_paths),
                "corpus_text_items": len(corpus_texts),
            },
        },
        "design_signatures": {
            "from_finish_index": design_index,
            "from_corpus": design_from_corpus,
        },
        "ocr_glossary": {
            "corrections": ocr_pairs,
            "unresolved_tokens": unresolved,
            "min_support": int(args.min_ocr_pair_support),
            "corpus_text_items": len(corpus_texts),
            "vocabulary_size": len(vocab),
        },
    }

    # Balanced quality gates and review queue candidates
    quality_checks: List[Dict[str, Any]] = []
    review_items: List[Dict[str, Any]] = []

    cond_ok = int(domains["conditions_quantities"]["active_rows"]) >= int(args.min_condition_support)
    quality_checks.append({"domain": "conditions_quantities", "ok": cond_ok, "value": int(domains["conditions_quantities"]["active_rows"])})
    if not cond_ok:
        review_items.append({"domain": "conditions_quantities", "reason": "low_active_rows", "value": int(domains["conditions_quantities"]["active_rows"])})

    symbol_support_total = sum(domains["symbol_knowledge"]["support_counts"].values())
    symbol_ok = symbol_support_total >= int(args.min_symbol_support)
    quality_checks.append({"domain": "symbol_knowledge", "ok": symbol_ok, "value": int(symbol_support_total)})
    if not symbol_ok:
        review_items.append({"domain": "symbol_knowledge", "reason": "low_symbol_support", "value": int(symbol_support_total)})

    low_signal_corpus = len(corpus_texts) < 180
    ocr_ok = (len(ocr_pairs) > 0) or low_signal_corpus
    quality_checks.append({"domain": "ocr_glossary", "ok": ocr_ok, "value": len(ocr_pairs)})
    if not ocr_ok:
        review_items.append({"domain": "ocr_glossary", "reason": "no_high_confidence_pairs", "value": 0})

    height_signal = (
        len(domains["height_notations"]["tokens"])
        + len(domains["height_notations"]["extra_tokens_from_corpus"])
        + len(domains["finish_taxonomy"]["height_notation_patterns"])
    )
    height_ok = height_signal > 0
    quality_checks.append({"domain": "height_notations", "ok": height_ok, "value": len(domains["height_notations"]["extra_tokens_from_corpus"])})
    if not height_ok:
        review_items.append({"domain": "height_notations", "reason": "no_tokens_detected", "value": 0})

    payload: Dict[str, Any] = {
        "ok": True,
        "project_id": str(args.project_id),
        "created_at": datetime.now().isoformat(),
        "contracts": contracts,
        "sources": {
            "latest_training_notes_json": str(latest_notes) if latest_notes else "",
            "latest_finish_knowledge_json": str(latest_finish) if latest_finish else "",
            "latest_symbol_knowledge_json": str(latest_symbol) if latest_symbol else "",
            "attempt_file_count": len(attempt_paths),
        },
        "domains": domains,
        "quality": {
            "profile": "balanced",
            "checks": quality_checks,
            "review_queue_pending": len(review_items),
            "overall_ok": bool(all(bool(x.get("ok", False)) for x in quality_checks)),
        },
        "blockers": {
            "count": len(blockers),
            "open": [x for x in blockers if str(x.get("status", "")) == "open"],
            "mitigated": [x for x in blockers if str(x.get("status", "")) != "open"],
        },
        "run_events": run_events,
    }

    out_root = pathlib.Path(args.output_root).expanduser().resolve() / str(args.project_id)
    tag = now_tag()
    out_json = out_root / f"accuracy_index_{tag}.json"
    latest_json = out_root / "accuracy_index_latest.json"
    report_json = out_root / f"accuracy_ingestion_report_{tag}.json"
    report_md = out_root / f"accuracy_ingestion_report_{tag}.md"
    review_queue_path = OUT_ROOT / "review_queue" / "accuracy_ingestion_review_queue.json"

    report_payload = {
        "ok": True,
        "project_id": str(args.project_id),
        "created_at": datetime.now().isoformat(),
        "overall_ok": bool(payload["quality"]["overall_ok"]),
        "checks": quality_checks,
        "review_items": review_items,
        "blocker_summary": {
            "count": len(blockers),
            "open_count": len([x for x in blockers if str(x.get("status", "")) == "open"]),
        },
        "artifact_paths": {
            "accuracy_index_json": str(out_json),
            "accuracy_index_latest_json": str(latest_json),
            "report_json": str(report_json),
            "report_md": str(report_md),
        },
    }
    md = [
        f"# Accuracy Ingestion Report - {tag}",
        "",
        f"- project_id: `{args.project_id}`",
        f"- overall_ok: `{str(report_payload['overall_ok']).lower()}`",
        "",
        "## Domain Checks",
    ]
    for row in quality_checks:
        md.append(
            f"- {row['domain']}: ok={str(bool(row['ok'])).lower()} value={row['value']}"
        )
    md.append("")
    md.append("## Review Queue")
    if review_items:
        for item in review_items:
            md.append(f"- {item['domain']}: {item['reason']} (value={item['value']})")
    else:
        md.append("- none")
    md.append("")
    md.append("## Blockers")
    if blockers:
        for b in blockers:
            md.append(
                f"- {b['id']}: severity={b['severity']} status={b['status']} action={b['auto_action']}"
            )
    else:
        md.append("- none")

    # Update review queue (append newest run)
    queue = read_json(review_queue_path, {"updated_at": "", "items": []})
    items = queue.get("items", []) if isinstance(queue.get("items", []), list) else []
    items.append(
        {
            "ts": datetime.now().isoformat(),
            "project_id": str(args.project_id),
            "review_items": review_items,
            "report_json": str(report_json),
        }
    )
    queue["items"] = items[-500:]
    queue["updated_at"] = datetime.now().isoformat()

    write_json(out_json, payload)
    write_json(latest_json, payload)
    write_json(report_json, report_payload)
    write_md(report_md, "\n".join(md) + "\n")
    write_json(review_queue_path, queue)
    print(str(out_json))
    return payload


def main() -> int:
    args = parse_args()
    payload = build_accuracy_index(args)
    return 0 if bool(payload.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())

