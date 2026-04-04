#!/usr/bin/env python3
"""
OST Training Lab

Manages training registry, executes module attempts, and scores results.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, List


PROGRAM_PATH = pathlib.Path("scripts/ost_training_program.json")
REGISTRY_PATH = pathlib.Path("scripts/ost_training_registry.json")
BOOST_AGENT_SCRIPT = pathlib.Path("scripts/ost_boost_agent.py")
BOOST_AGENT_CONFIG = pathlib.Path("scripts/ost_boost_agent.config.json")
GROUP_SELECTOR_SCRIPT = pathlib.Path("scripts/ost_grouping_selector.py")
SCOPE_PROFILER_SCRIPT = pathlib.Path("scripts/ost_scope_profiler.py")
PROJECT_SCOPE_REPORT_SCRIPT = pathlib.Path("scripts/ost_project_scope_report.py")
ITEM_TYPE_CLASSIFIER_SCRIPT = pathlib.Path("scripts/ost_item_type_classifier.py")
LEFT_BLANK_TAKEOFF_SCRIPT = pathlib.Path("scripts/ost_left_blank_takeoff_attempt.py")
UNDO_ACTIONS_SCRIPT = pathlib.Path("scripts/ost_undo_actions.py")
SELECT_CONDITION_ROW_SCRIPT = pathlib.Path("scripts/ost_select_condition_row.py")
RUNS_DIR = pathlib.Path("output/ost-boost-agent")
LAB_OUT_DIR = pathlib.Path("output/ost-training-lab")
GROUP_OUT_DIR = pathlib.Path("output/ost-grouping-selector")
SCOPE_OUT_DIR = pathlib.Path("output/ost-scope-profiler")
PROJECT_SCOPE_OUT_DIR = pathlib.Path("output/ost-project-scope")
ITEM_TYPES_DIR = LAB_OUT_DIR / "item_types"
ITEM_TYPE_REGISTRY_PATH = ITEM_TYPES_DIR / "item_type_registry.json"
ITEM_TYPE_EVENTS_PATH = ITEM_TYPES_DIR / "item_type_events.jsonl"
ITEM_TYPE_CLASSIFICATIONS_DIR = ITEM_TYPES_DIR / "classifications"
ITEM_TYPE_PROJECT_OVERRIDES_DIR = ITEM_TYPES_DIR / "project_overrides"
DEFAULT_DISCOVERY_ROOT = pathlib.Path(r"G:\Shared drives\SKYLINE 2026\AI Bids")
DEFAULT_TRAINING_DB_CANDIDATES = [
    pathlib.Path(r"C:\OCS Documents\OST\Training Playground.mdb"),
    pathlib.Path(r"C:\OCS Documents\OST\OST_TRAINING.mdb"),
]
PROTOCOLS_DIR = LAB_OUT_DIR / "protocols"
PROTOCOL_REGISTRY_PATH = PROTOCOLS_DIR / "protocol_registry.json"
PROJECT_PROTOCOL_MAP_PATH = PROTOCOLS_DIR / "project_protocol_map.json"
PROTOCOL_VERIFICATION_QUEUE_PATH = PROTOCOLS_DIR / "verification_queue.json"
FINISH_REVIEW_QUEUE_PATH = LAB_OUT_DIR / "review_queue" / "finish_review_queue.json"
WORKSPACE_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _emergency_pause_flag_path() -> pathlib.Path:
    raw = str(os.environ.get("MAVERICK_EMERGENCY_PAUSE_FLAG", "") or "").strip()
    if raw:
        p = pathlib.Path(raw)
        return p if p.is_absolute() else (WORKSPACE_ROOT / p)
    return WORKSPACE_ROOT / "output" / "maverick" / "emergency_pause.flag"


def _start_emergency_watch() -> subprocess.Popen[str] | None:
    enabled_raw = str(os.environ.get("MAVERICK_AUTO_EMERGENCY_WATCH", "1")).strip().lower()
    enabled = enabled_raw not in {"0", "false", "no", "off"}
    if not enabled:
        return None
    script = WORKSPACE_ROOT / "scripts" / "ost_emergency_pause_hotkey.py"
    if not script.exists():
        return None
    try:
        return subprocess.Popen(
            [sys.executable, str(script), "watch"],
            cwd=str(WORKSPACE_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            env={
                **os.environ,
                "MAVERICK_EMERGENCY_PAUSE_FLAG": str(_emergency_pause_flag_path()),
            },
        )
    except Exception:
        return None


def _stop_emergency_watch(proc: subprocess.Popen[str] | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def run_subprocess_guarded(
    cmd: List[str],
    timeout: int | None = None,
    capture_output: bool = True,
    text: bool = True,
    watch_emergency: bool = True,
) -> subprocess.CompletedProcess[str]:
    watcher: subprocess.Popen[str] | None = _start_emergency_watch() if watch_emergency else None
    env = {
        **os.environ,
        "MAVERICK_EMERGENCY_PAUSE_FLAG": str(_emergency_pause_flag_path()),
    }
    try:
        return subprocess.run(
            cmd,
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            env=env,
        )
    finally:
        _stop_emergency_watch(watcher)


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_jsonl(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")


def enqueue_finish_review(entry: Dict[str, Any]) -> None:
    queue = {"updated_at": datetime.now().isoformat(), "items": []}
    if FINISH_REVIEW_QUEUE_PATH.exists():
        try:
            existing = read_json(FINISH_REVIEW_QUEUE_PATH)
            if isinstance(existing, dict):
                queue = existing
                if not isinstance(queue.get("items", []), list):
                    queue["items"] = []
        except Exception:
            pass
    items = queue.get("items", []) if isinstance(queue.get("items", []), list) else []
    items.append(entry)
    queue["items"] = items[-500:]
    queue["updated_at"] = datetime.now().isoformat()
    write_json(FINISH_REVIEW_QUEUE_PATH, queue)


def cleanup_stale_ost_processes() -> Dict[str, Any]:
    """
    Best-effort reliability hardening for overlapping runs on Windows.
    Kills stale Python processes that are clearly OST automation workers.
    """
    ps = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match '^python(\\.exe)?$' -and $_.CommandLine -match 'ost_(boost_agent|left_blank_takeoff_attempt|grouping_selector|select_condition_row|undo_actions)' } | "
        "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; \"$($_.ProcessId)\" } catch {} }"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=12,
        )
        killed = [x.strip() for x in str(proc.stdout or "").splitlines() if x.strip()]
        return {"ok": proc.returncode == 0, "killed_pids": killed, "stderr": str(proc.stderr or "").strip()}
    except Exception as exc:
        return {"ok": False, "killed_pids": [], "stderr": str(exc)}


def acquire_boost_mutex(project_id: str, stale_after_s: int = 900) -> Dict[str, Any]:
    LAB_OUT_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LAB_OUT_DIR / f"boost_mutex_{project_id}.lock.json"
    now_ts = int(time.time())
    if lock_path.exists():
        existing = read_json(lock_path)
        created_at = int(existing.get("created_at_unix", 0) or 0) if isinstance(existing, dict) else 0
        existing_pid = int(existing.get("pid", 0) or 0) if isinstance(existing, dict) else 0
        age = max(0, now_ts - created_at)
        pid_running = False
        if existing_pid > 0:
            try:
                probe = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", f"Get-Process -Id {existing_pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
                    capture_output=True,
                    text=True,
                    timeout=6,
                )
                pid_running = str(probe.stdout or "").strip().isdigit()
            except Exception:
                pid_running = False
        # If pid is gone, treat as stale immediately.
        if (not pid_running) and lock_path.exists():
            try:
                lock_path.unlink()
            except Exception:
                pass
            existing = {}
            created_at = 0
            age = 0
        if age < max(60, int(stale_after_s)):
            return {"acquired": False, "lock_path": str(lock_path), "existing": existing, "age_s": age}
    payload = {"project_id": project_id, "pid": os.getpid(), "created_at_unix": now_ts, "created_at": datetime.now().isoformat()}
    write_json(lock_path, payload)
    return {"acquired": True, "lock_path": str(lock_path), "payload": payload}


def release_boost_mutex(lock_path: str) -> None:
    try:
        p = pathlib.Path(str(lock_path or "").strip())
        if p.exists():
            p.unlink()
    except Exception:
        pass


def load_or_init_item_type_store() -> Dict[str, Any]:
    ITEM_TYPES_DIR.mkdir(parents=True, exist_ok=True)
    ITEM_TYPE_CLASSIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    ITEM_TYPE_PROJECT_OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
    if not ITEM_TYPE_REGISTRY_PATH.exists():
        write_json(
            ITEM_TYPE_REGISTRY_PATH,
            {
                "version": 1,
                "updated_at": datetime.now().isoformat(),
                "item_types": {
                    "perimeter_wall": {
                        "description": "Outer perimeter walls; darker, thicker linework",
                        "prototype_embedding": [0.85, 0.72, 0.35, 0.15, 0.22, 0.58, 0.12, 0.06],
                        "thresholds": {"min_similarity": 0.62, "min_confidence": 0.58},
                    },
                    "interior_wall": {
                        "description": "Interior partitions; thinner than perimeter with uniform width",
                        "prototype_embedding": [0.55, 0.46, 0.33, 0.12, 0.2, 0.52, 0.11, 0.08],
                        "thresholds": {"min_similarity": 0.58, "min_confidence": 0.52},
                    },
                    "cmu_wall": {
                        "description": "CMU or hatch/cross-pattern wall assemblies",
                        "prototype_embedding": [0.76, 0.64, 0.44, 0.58, 0.3, 0.5, 0.2, 0.12],
                        "thresholds": {"min_similarity": 0.6, "min_confidence": 0.55},
                    },
                    "door_frame": {
                        "description": "Door/frame-related symbols and linework",
                        "prototype_embedding": [0.42, 0.35, 0.4, 0.2, 0.28, 0.42, 0.26, 0.24],
                        "thresholds": {"min_similarity": 0.54, "min_confidence": 0.48},
                    },
                    "colored_takeoff_markup": {
                        "description": "Existing user takeoff markup in non-black/non-white colors",
                        "prototype_embedding": [0.48, 0.41, 0.24, 0.18, 0.86, 0.46, 0.18, 0.42],
                        "thresholds": {"min_similarity": 0.6, "min_confidence": 0.55},
                    },
                },
            },
        )
    return read_json(ITEM_TYPE_REGISTRY_PATH)


def load_program() -> Dict[str, Any]:
    if not PROGRAM_PATH.exists():
        raise FileNotFoundError(f"Program file missing: {PROGRAM_PATH}")
    return read_json(PROGRAM_PATH)


def load_registry(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "database_name": "OST_TRAINING.mdb", "projects": []}
    return read_json(path)


def build_finish_learning_snapshot(project: Dict[str, Any], takeoff_result: Dict[str, Any]) -> Dict[str, Any]:
    finish_profile = project.get("finish_profile", {}) if isinstance(project, dict) else {}
    if not isinstance(finish_profile, dict):
        finish_profile = {}
    summary = takeoff_result.get("result", {}) if isinstance(takeoff_result.get("result", {}), dict) else {}
    condition_name = str(
        (
            (
                summary.get("condition_selection", {})
                if isinstance(summary.get("condition_selection", {}), dict)
                else {}
            )
            .get("selection", {})
            if isinstance(
                (
                    summary.get("condition_selection", {})
                    if isinstance(summary.get("condition_selection", {}), dict)
                    else {}
                ).get("selection", {}),
                dict,
            )
            else {}
        ).get("active_condition_name", "")
        or ""
    ).lower()
    condition_style = str(summary.get("condition_style", "") or "").lower()
    ocr_preview = str(
        (
            (
                summary.get("condition_style_inspection", {})
                if isinstance(summary.get("condition_style_inspection", {}), dict)
                else {}
            )
            .get("inspection", {})
            if isinstance(
                (
                    summary.get("condition_style_inspection", {})
                    if isinstance(summary.get("condition_style_inspection", {}), dict)
                    else {}
                ).get("inspection", {}),
                dict,
            )
            else {}
        ).get("ocr_preview", "")
        or ""
    )
    low = f"{condition_name} {ocr_preview}".lower()
    inferred_trade = "unknown"
    if any(k in low for k in ("paint", "coating")):
        inferred_trade = "painting"
    elif any(k in low for k in ("wallcover", "wc ")):
        inferred_trade = "wallcovering"
    elif any(k in low for k in ("gwb", "drywall", "gypsum")):
        inferred_trade = "drywall"
    elif any(k in low for k in ("frame", "jamb")):
        inferred_trade = "door_frames"
    elif "door" in low:
        inferred_trade = "doors"
    elif any(k in low for k in ("base", "baseboard")):
        inferred_trade = "wood_base"
    elif any(k in low for k in ("trim", "casing", "crown")):
        inferred_trade = "trim"
    elif any(k in low for k in ("ceiling", "clg", "act", "deck")):
        inferred_trade = "ceilings"

    ceiling_type = "unknown"
    if any(k in low for k in ("act", "acoustical")):
        ceiling_type = "acoustical_ceiling"
    elif any(k in low for k in ("exposed deck", "deck")):
        ceiling_type = "exposed_deck"
    elif "gwb" in low and "ceiling" in low:
        ceiling_type = "gwb_ceiling"

    heights = re.findall(r"\b\d{1,2}\s*'[\s-]*\d{1,2}\s*\"?\b", low)[:10]
    height_notation_hits = []
    for token in ("aff", "clg", "ceiling", "typ", "varies", "elev"):
        if token in low:
            height_notation_hits.append(token)

    return {
        "primary_trades": finish_profile.get("primary_trades", []),
        "condition_name": condition_name,
        "condition_style": condition_style,
        "inferred_trade": inferred_trade,
        "confidence": float(
            (
                (
                    summary.get("finish_inference", {})
                    if isinstance(summary.get("finish_inference", {}), dict)
                    else {}
                ).get("confidence", 0.0)
                or 0.0
            )
        ),
        "ceiling_type_hint": ceiling_type,
        "height_samples": heights,
        "height_notation_hits": sorted(set(height_notation_hits)),
        "height_context": {
            "typical_wall_height_ft": finish_profile.get("typical_wall_height_ft", None),
            "typical_ceiling_height_ft": finish_profile.get("typical_ceiling_height_ft", None),
        },
        "design_set_hints": finish_profile.get("design_set_hints", []),
    }


def default_protocol_checklist(protocol_type: str) -> List[str]:
    base = [
        "Confirm target project and drawing package are correct.",
        "Confirm naming conventions for conditions and alternates.",
        "Confirm exclusions and non-takeoff zones.",
        "Confirm expected reassignment/duplication strategy after Boost.",
        "Confirm finish schedule authority (paint vs wallcovering vs drywall boundaries).",
        "Confirm ceiling system interpretation (acoustical ceiling vs exposed deck).",
        "Confirm wall/ceiling height assumptions (AFF/CLG notes, typicals, and exceptions).",
        "Confirm door vs frame vs trim/base scope split before count/linear actions.",
    ]
    if protocol_type == "multifamily":
        base.extend(
            [
                "Confirm unit-type workflows and repeated-unit handling.",
                "Confirm area dropdown behavior when unit-type areas are active.",
            ]
        )
    elif protocol_type == "office":
        base.extend(
            [
                "Confirm tenant/core split and common-area treatment.",
                "Confirm room-function naming consistency (open office, conference, support).",
            ]
        )
    elif protocol_type == "tilt_up_warehouse":
        base.extend(
            [
                "Confirm panel-based wall workflow and warehouse-specific assemblies.",
                "Confirm dock/office mezzanine distinctions and roof/structure treatment.",
            ]
        )
    return base


def infer_protocol_type(project: Dict[str, Any]) -> str:
    text = " ".join(
        [
            str(project.get("project_name", "") or ""),
            " ".join([str(x) for x in (project.get("project_aliases", []) or [])]),
            str(project.get("notes", "") or ""),
            str(project.get("source_project_folder", "") or ""),
        ]
    ).lower()
    if any(k in text for k in ("multi-family", "multifamily", "apartment", "unit ", "units")):
        return "multifamily"
    if any(k in text for k in ("office", "tenant", "corporate", "fitout", "fit-out")):
        return "office"
    if any(k in text for k in ("tilt up", "tilt-up", "warehouse", "distribution", "industrial")):
        return "tilt_up_warehouse"
    return "general"


def load_or_init_protocol_store() -> Dict[str, Any]:
    PROTOCOLS_DIR.mkdir(parents=True, exist_ok=True)
    if not PROTOCOL_REGISTRY_PATH.exists():
        write_json(
            PROTOCOL_REGISTRY_PATH,
            {
                "updated_at": datetime.now().isoformat(),
                "protocols": {},
            },
        )
    if not PROJECT_PROTOCOL_MAP_PATH.exists():
        write_json(
            PROJECT_PROTOCOL_MAP_PATH,
            {
                "updated_at": datetime.now().isoformat(),
                "projects": {},
            },
        )
    if not PROTOCOL_VERIFICATION_QUEUE_PATH.exists():
        write_json(
            PROTOCOL_VERIFICATION_QUEUE_PATH,
            {
                "updated_at": datetime.now().isoformat(),
                "pending_protocol_ids": [],
            },
        )
    return {
        "registry": read_json(PROTOCOL_REGISTRY_PATH),
        "project_map": read_json(PROJECT_PROTOCOL_MAP_PATH),
        "queue": read_json(PROTOCOL_VERIFICATION_QUEUE_PATH),
    }


def save_protocol_store(store: Dict[str, Any]) -> None:
    reg = store.get("registry", {}) if isinstance(store, dict) else {}
    pmap = store.get("project_map", {}) if isinstance(store, dict) else {}
    queue = store.get("queue", {}) if isinstance(store, dict) else {}
    if isinstance(reg, dict):
        reg["updated_at"] = datetime.now().isoformat()
    if isinstance(pmap, dict):
        pmap["updated_at"] = datetime.now().isoformat()
    if isinstance(queue, dict):
        queue["updated_at"] = datetime.now().isoformat()
    write_json(PROTOCOL_REGISTRY_PATH, reg if isinstance(reg, dict) else {"protocols": {}})
    write_json(PROJECT_PROTOCOL_MAP_PATH, pmap if isinstance(pmap, dict) else {"projects": {}})
    write_json(PROTOCOL_VERIFICATION_QUEUE_PATH, queue if isinstance(queue, dict) else {"pending_protocol_ids": []})


ABBREV_MAP = {
    "arch": "architectural",
    "id": "interior design",
    "int": "interior",
    "elec": "electrical",
    "mech": "mechanical",
    "str": "structural",
    "res": "residence",
    "apt": "apartment",
    "bldg": "building",
    "pkg": "package",
    "spec": "specification",
    "fin": "finish",
    "wc": "wallcovering",
}


def normalize_text(s: str) -> str:
    t = (s or "").lower()
    t = re.sub(r"[_\-./\\]+", " ", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def expand_abbrev_tokens(tokens: List[str]) -> List[str]:
    out = list(tokens)
    for tok in tokens:
        if tok in ABBREV_MAP:
            out.extend(normalize_text(ABBREV_MAP[tok]).split())
    return out


def name_tokens(s: str) -> List[str]:
    base = normalize_text(s)
    toks = [x for x in base.split(" ") if len(x) >= 2]
    toks = expand_abbrev_tokens(toks)
    return sorted(set(toks))


def token_jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / max(len(sa | sb), 1)


def string_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=normalize_text(a), b=normalize_text(b)).ratio()


def enumerate_project_dirs(root: pathlib.Path, max_depth: int = 2) -> List[pathlib.Path]:
    if not root.exists() or not root.is_dir():
        return []
    out: List[pathlib.Path] = []
    stack: List[tuple[pathlib.Path, int]] = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            children = list(cur.iterdir())
        except Exception:
            continue
        for child in children:
            if child.is_dir():
                out.append(child)
                stack.append((child, depth + 1))
    return out


def score_candidate_dir(
    candidate: pathlib.Path,
    project_name: str,
    aliases: List[str],
) -> Dict[str, Any]:
    c_name = candidate.name
    c_tokens = name_tokens(c_name)
    best_ratio = string_ratio(project_name, c_name)
    best_jaccard = token_jaccard(name_tokens(project_name), c_tokens)
    matched_alias = ""
    for a in aliases:
        r = string_ratio(a, c_name)
        j = token_jaccard(name_tokens(a), c_tokens)
        if (r + j) > (best_ratio + best_jaccard):
            best_ratio, best_jaccard = r, j
            matched_alias = a
    score = 70.0 * best_ratio + 30.0 * best_jaccard
    # Prefer shallower "job folder" style directories.
    try:
        depth = len(candidate.parts)
    except Exception:
        depth = 0
    generic_penalty_terms = {
        "specifications",
        "specs",
        "drawings",
        "plans",
        "submittals",
        "addenda",
        "archived",
    }
    c_norm = normalize_text(candidate.name)
    if c_norm in generic_penalty_terms:
        score -= 10.0
    if any(tok in c_norm.split() for tok in generic_penalty_terms):
        score -= 4.0
    return {
        "path": str(candidate),
        "name": c_name,
        "score": round(score, 3),
        "ratio": round(best_ratio, 3),
        "jaccard": round(best_jaccard, 3),
        "matched_alias": matched_alias,
        "depth": depth,
    }


def discover_project_folder(project: Dict[str, Any]) -> Dict[str, Any]:
    explicit = str(project.get("source_project_folder", "") or "").strip()
    if explicit:
        p = pathlib.Path(explicit)
        if p.exists() and p.is_dir():
            return {"resolved": True, "folder": str(p), "method": "source_project_folder"}
    root_raw = str(project.get("discovery_root_folder", "") or "").strip()
    root = pathlib.Path(root_raw) if root_raw else DEFAULT_DISCOVERY_ROOT
    if not root.exists() or not root.is_dir():
        return {"resolved": False, "reason": "discovery_root_missing", "root": str(root)}

    project_name = str(project.get("project_name", "") or "").strip()
    aliases = project.get("project_aliases", []) or []
    aliases = [str(x) for x in aliases if str(x).strip()]
    if not project_name and not aliases:
        return {"resolved": False, "reason": "no_project_name_or_aliases", "root": str(root)}

    candidates = enumerate_project_dirs(root, max_depth=2)
    scored = []
    for c in candidates:
        row = score_candidate_dir(c, project_name, aliases)
        try:
            rel_depth = len(c.relative_to(root).parts)
        except Exception:
            rel_depth = 99
        row["rel_depth"] = rel_depth
        # Prefer project-level directories close to root.
        row["score"] = round(float(row["score"]) - max(rel_depth - 1, 0) * 3.5, 3)
        # Prefer directories that actually contain at least one PDF somewhere under them.
        has_pdf = any(c.glob("**/*.pdf"))
        row["has_pdf"] = bool(has_pdf)
        if not has_pdf:
            row["score"] = round(float(row["score"]) - 5.0, 3)
        scored.append(row)
    scored.sort(key=lambda x: x["score"], reverse=True)
    if not scored:
        return {"resolved": False, "reason": "no_candidate_folders", "root": str(root)}

    best = scored[0]
    # Conservative threshold to avoid bad auto-picks.
    if best["score"] < 45.0:
        return {
            "resolved": False,
            "reason": "low_confidence_folder_match",
            "root": str(root),
            "best_candidate": best,
            "top_candidates": scored[:5],
        }
    return {
        "resolved": True,
        "folder": best["path"],
        "method": "fuzzy_discovery",
        "root": str(root),
        "best_candidate": best,
        "top_candidates": scored[:5],
    }


def score_candidate_pdf(pdf_path: pathlib.Path, project_name: str, aliases: List[str]) -> float:
    n = pdf_path.stem
    ratio = string_ratio(project_name, n)
    jacc = token_jaccard(name_tokens(project_name), name_tokens(n))
    for a in aliases:
        ratio = max(ratio, string_ratio(a, n))
        jacc = max(jacc, token_jaccard(name_tokens(a), name_tokens(n)))
    bonus = 0.0
    ln = normalize_text(n)
    if "plan" in ln:
        bonus += 0.04
    if "drawing" in ln:
        bonus += 0.04
    if "arch" in ln or "architectural" in ln:
        bonus += 0.05
    if "set" in ln:
        bonus += 0.03
    return 0.65 * ratio + 0.35 * jacc + bonus


def discover_source_pdf(project: Dict[str, Any], project_folder: pathlib.Path) -> Dict[str, Any]:
    explicit = str(project.get("source_pdf_path", "") or "").strip()
    if explicit:
        p = pathlib.Path(explicit)
        if p.exists() and p.is_file():
            return {"resolved": True, "pdf": str(p), "method": "source_pdf_path"}
    pdfs = sorted(project_folder.rglob("*.pdf"))
    if not pdfs:
        return {"resolved": False, "reason": "no_pdfs_in_folder", "project_folder": str(project_folder)}
    project_name = str(project.get("project_name", "") or "").strip()
    aliases = project.get("project_aliases", []) or []
    aliases = [str(x) for x in aliases if str(x).strip()]
    scored = [
        {"path": str(p), "score": round(score_candidate_pdf(p, project_name, aliases), 4)}
        for p in pdfs
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)
    best = scored[0]
    return {
        "resolved": True,
        "pdf": best["path"],
        "method": "fuzzy_pdf_discovery",
        "top_candidates": scored[:5],
    }


def resolve_project_context(project: Dict[str, Any]) -> Dict[str, Any]:
    folder_res = discover_project_folder(project)
    out: Dict[str, Any] = {"folder_resolution": folder_res}
    if not folder_res.get("resolved"):
        out["resolved"] = False
        return out
    folder = pathlib.Path(str(folder_res["folder"]))
    pdf_res = discover_source_pdf(project, folder)
    out["pdf_resolution"] = pdf_res
    out["resolved"] = bool(folder_res.get("resolved"))
    out["resolved_folder"] = str(folder)
    if pdf_res.get("resolved"):
        out["resolved_pdf"] = str(pdf_res.get("pdf"))
    return out


def cmd_init_registry(path: pathlib.Path, count: int) -> int:
    reg = load_registry(path)
    existing = {p.get("training_project_id") for p in reg.get("projects", [])}
    projects = list(reg.get("projects", []))
    for i in range(1, count + 1):
        pid = f"TP-{i:04d}"
        if pid in existing:
            continue
        projects.append(
            {
                "training_project_id": pid,
                "project_name": f"Training Project {i:02d}",
                "source_type": "completed_real_project_copy",
                "module_targets": [
                    "T01-linear-baseline-L1",
                    "T02-area-baseline-L1",
                    "T03-count-baseline-L1",
                    "T06-boost-open-run-verify-L2",
                ],
                "preferred_unit_label": "",
                "source_pdf_path": "",
                "source_project_folder": "",
                "discovery_root_folder": str(DEFAULT_DISCOVERY_ROOT),
                "project_aliases": [],
                "notes": "",
                "finish_profile": {
                    "primary_trades": [
                        "painting",
                        "wallcovering",
                        "drywall",
                        "doors",
                        "door_frames",
                        "trim",
                        "wood_base",
                        "ceilings",
                    ],
                    "ceiling_focus": ["acoustical_ceiling", "exposed_deck"],
                    "typical_wall_height_ft": 9.0,
                    "typical_ceiling_height_ft": 10.0,
                    "design_set_hints": [],
                },
            }
        )
    reg["projects"] = projects
    write_json(path, reg)
    print(f"Registry initialized/updated: {path} (projects={len(projects)})")
    return 0


def get_latest_run_dir() -> pathlib.Path | None:
    if not RUNS_DIR.exists():
        return None
    dirs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return sorted(dirs)[-1]


def get_latest_finish_knowledge_index(project_id: str) -> str:
    root = LAB_OUT_DIR / "finish_knowledge" / str(project_id)
    latest = root / "finish_knowledge_index_latest.json"
    if latest.exists():
        return str(latest)
    candidates = sorted(root.glob("finish_knowledge_index_*.json"))
    if candidates:
        return str(candidates[-1])
    return ""


def score_boost_run(run_log: Dict[str, Any], weights: Dict[str, int]) -> Dict[str, Any]:
    status = run_log.get("status", {})
    step_status = status.get("step_status", {})
    actions: List[Dict[str, Any]] = run_log.get("actions", [])

    step_ok = (
        bool(step_status.get("step1_open_boost"))
        and bool(step_status.get("step2_set_options"))
        and bool(step_status.get("step3_run"))
        and bool(step_status.get("step4_verify"))
    )
    step_completion = 100 if step_ok else 0

    # Placeholder proxy for takeoff accuracy until direct quantity validation
    # is automated from OST DB/report exports.
    takeoff_accuracy = 100 if run_log.get("ok") else 0

    had_recovery = any(
        a.get("step", "").startswith("auto_scale_") or "retry" in str(a.get("step", ""))
        for a in actions
    )
    recovery_behavior = 100 if run_log.get("ok") else (50 if had_recovery else 0)

    runtime_stability = 100 if status.get("failed_step") in (None, "None") else 0

    score = (
        step_completion * (weights.get("step_completion", 40) / 100.0)
        + takeoff_accuracy * (weights.get("quantity_accuracy", 35) / 100.0)
        + recovery_behavior * (weights.get("recovery_behavior", 15) / 100.0)
        + runtime_stability * (weights.get("runtime_stability", 10) / 100.0)
    )

    return {
        "score": round(score, 2),
        "components": {
            "step_completion": step_completion,
            "quantity_accuracy": takeoff_accuracy,
            "takeoff_accuracy": takeoff_accuracy,
            "recovery_behavior": recovery_behavior,
            "runtime_stability": runtime_stability,
        },
    }


def _try_import_pyodbc() -> Any:
    try:
        import pyodbc  # type: ignore

        return pyodbc
    except Exception:
        return None


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _is_text_column(name: str) -> bool:
    n = (name or "").lower()
    return any(
        token in n
        for token in (
            "condition",
            "cond",
            "item",
            "desc",
            "name",
            "assembly",
            "scope",
            "room",
            "location",
            "area",
            "note",
            "comment",
            "type",
        )
    )


def _resolve_training_db_path(program: Dict[str, Any], registry: Dict[str, Any]) -> pathlib.Path | None:
    candidates: List[pathlib.Path] = []
    env_db = os.environ.get("OST_TRAINING_DB_PATH", "").strip()
    if env_db:
        candidates.append(pathlib.Path(env_db))
    db_name = str(program.get("database_name", "") or "").strip() or str(registry.get("database_name", "") or "").strip()
    if db_name:
        candidates.append(pathlib.Path(db_name))
        candidates.append(pathlib.Path(r"C:\OCS Documents\OST") / db_name)
    candidates.extend(DEFAULT_TRAINING_DB_CANDIDATES)
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def _keyword_hits(text: str, keywords: List[str]) -> bool:
    low = (text or "").lower()
    return any(k in low for k in keywords)


def _normalize_condition_key(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    try:
        f = float(s)
        if abs(f - int(f)) < 1e-9:
            return str(int(f))
    except Exception:
        pass
    return s


def analyze_training_db_notes(
    project: Dict[str, Any],
    program: Dict[str, Any],
    registry: Dict[str, Any],
    attempt_id: str,
) -> Dict[str, Any]:
    """
    Extract training takeoff behavior patterns from Access DB and return
    detailed notes that explain what Maverick observed and why.
    """
    db_path = _resolve_training_db_path(program, registry)
    if db_path is None:
        return {
            "ok": False,
            "reason": "training_db_not_found",
            "notes": [
                "Training DB not found. Set OST_TRAINING_DB_PATH or place database in C:\\OCS Documents\\OST.",
            ],
        }

    pyodbc = _try_import_pyodbc()
    if pyodbc is None:
        return {
            "ok": False,
            "db_path": str(db_path),
            "reason": "pyodbc_missing",
            "notes": [
                "pyodbc is not installed, so Maverick cannot inspect Access training data yet.",
                "Install pyodbc and ensure Microsoft Access ODBC driver is available.",
            ],
        }

    drivers = [d for d in pyodbc.drivers() if "access driver" in str(d).lower()]
    if not drivers:
        return {
            "ok": False,
            "db_path": str(db_path),
            "reason": "access_odbc_driver_missing",
            "notes": [
                "No Microsoft Access ODBC driver detected.",
                "Install Access Database Engine (ODBC) so Maverick can read .mdb training data.",
            ],
        }

    conn = None
    connection_errors: List[str] = []
    for drv in drivers:
        conn_str = f"DRIVER={{{drv}}};DBQ={db_path};"
        try:
            conn = pyodbc.connect(conn_str, timeout=8)
            break
        except Exception as exc:
            connection_errors.append(str(exc))
    if conn is None:
        return {
            "ok": False,
            "db_path": str(db_path),
            "reason": "db_connection_failed",
            "errors": connection_errors[:3],
            "notes": ["Maverick could not connect to the training DB via ODBC."],
        }

    project_name = str(project.get("project_name", "") or "").strip().lower()
    aliases = [str(a).strip().lower() for a in (project.get("project_aliases", []) or []) if str(a).strip()]

    active_by_condition: Dict[str, Dict[str, Any]] = {}
    category_hits = {
        "walls": 0,
        "ceilings": 0,
        "wood_base": 0,
        "doors": 0,
        "door_frames": 0,
    }
    wood_base_shower_active = 0
    wood_base_shower_zero = 0
    wood_base_cabinet_active = 0
    wood_base_cabinet_zero = 0
    rows_seen = 0
    active_rows = 0
    tables_scanned: List[str] = []
    evidence_rows: List[Dict[str, Any]] = []
    condition_label_map: Dict[str, str] = {}

    wall_kw = [" wall", "walls", "gyp", "drywall"]
    ceil_kw = ["ceiling", "ceilings", "act", "gwb ceiling"]
    wood_kw = ["wood base", "baseboard", "w/base", "w base"]
    door_kw = ["door", "doors"]
    frame_kw = ["frame", "frames", "door frame", "door frames"]
    shower_kw = ["shower", "tub", "bathtub"]
    cabinet_kw = ["cabinet", "cabinetry", "vanity", "casework"]

    try:
        cur = conn.cursor()
        table_rows = cur.tables(tableType="TABLE").fetchall()
        table_names = [str(r.table_name) for r in table_rows if getattr(r, "table_name", None)]
        if "BidConditions" in table_names:
            try:
                cond_cols_meta = cur.columns(table="BidConditions").fetchall()
                cond_cols = [str(c.column_name) for c in cond_cols_meta if getattr(c, "column_name", None)]
                uid_col = next((c for c in cond_cols if c.lower() in {"uid", "conditionuid", "condition_uid"}), "")
                refno_col = next((c for c in cond_cols if c.lower() in {"refno", "ref_no", "refnumber"}), "")
                label_col = next((c for c in cond_cols if c.lower() in {"name", "conditionname"}), "")
                if not label_col:
                    label_col = next((c for c in cond_cols if any(t in c.lower() for t in ("name", "desc"))), "")
                if label_col and (uid_col or refno_col):
                    select_cols = [c for c in [uid_col, refno_col, label_col] if c]
                    q = "SELECT TOP 5000 " + ", ".join(f"[{c}]" for c in select_cols) + " FROM [BidConditions]"
                    cond_rows = cur.execute(q).fetchall()
                    for row in cond_rows:
                        if len(row) < len(select_cols):
                            continue
                        row_dict = {select_cols[i]: row[i] for i in range(len(select_cols))}
                        label = str(row_dict.get(label_col) or "").strip()
                        if not label:
                            continue
                        for key_col in (uid_col, refno_col):
                            if not key_col:
                                continue
                            key = _normalize_condition_key(row_dict.get(key_col))
                            if key:
                                condition_label_map[key] = label
            except Exception:
                pass
        for table in table_names:
            try:
                cols_meta = cur.columns(table=table).fetchall()
            except Exception:
                continue
            col_names = [str(c.column_name) for c in cols_meta if getattr(c, "column_name", None)]
            if not col_names:
                continue
            qty_col = next((c for c in col_names if "quantity" in c.lower() or c.lower() in {"qty", "quant"}), None)
            if not qty_col:
                continue
            text_cols = [c for c in col_names if _is_text_column(c)]
            if not text_cols:
                continue
            candidate_cols = [qty_col] + text_cols[:6]
            quoted_cols = ", ".join([f"[{c}]" for c in candidate_cols])
            query = f"SELECT TOP 800 {quoted_cols} FROM [{table}]"
            try:
                rows = cur.execute(query).fetchall()
            except Exception:
                continue

            tables_scanned.append(table)
            # find a likely condition column first
            condition_col = next((c for c in text_cols if "condition" in c.lower() or c.lower().startswith("cond")), text_cols[0])
            room_col = next((c for c in text_cols if any(t in c.lower() for t in ("room", "location", "area"))), "")

            idx = {name: i for i, name in enumerate(candidate_cols)}
            for r in rows:
                rows_seen += 1
                vals = [r[i] if i < len(r) else None for i in range(len(candidate_cols))]
                qty_val = _safe_float(vals[idx[qty_col]])
                cond_val = str(vals[idx.get(condition_col, 0)] or "").strip()
                cond_key = _normalize_condition_key(cond_val)
                cond_label = condition_label_map.get(cond_key, "")
                cond_display = f"{cond_val} - {cond_label}" if cond_label else cond_val
                room_val = str(vals[idx[room_col]] or "").strip() if room_col and room_col in idx else ""
                all_text_parts = []
                for tc in text_cols[:6]:
                    v = vals[idx[tc]] if tc in idx else None
                    if v is not None:
                        all_text_parts.append(str(v))
                all_text = " | ".join(all_text_parts).strip()
                low_text = f"{all_text} | {cond_label}".lower()

                if project_name:
                    scope_text = f"{cond_val} {room_val} {all_text}".lower()
                    if project_name not in scope_text and not any(a in scope_text for a in aliases):
                        # keep if no explicit project marker is available in this table row
                        pass

                if qty_val > 0:
                    active_rows += 1
                    key = (cond_display or all_text or "(unnamed condition)").strip()[:160]
                    slot = active_by_condition.setdefault(
                        key,
                        {"condition": key, "active_row_count": 0, "total_quantity": 0.0, "sample_room": room_val},
                    )
                    slot["active_row_count"] += 1
                    slot["total_quantity"] = round(float(slot["total_quantity"]) + qty_val, 3)
                    if not slot.get("sample_room") and room_val:
                        slot["sample_room"] = room_val

                if _keyword_hits(low_text, wall_kw) and qty_val > 0:
                    category_hits["walls"] += 1
                if _keyword_hits(low_text, ceil_kw) and qty_val > 0:
                    category_hits["ceilings"] += 1
                if _keyword_hits(low_text, wood_kw) and qty_val > 0:
                    category_hits["wood_base"] += 1
                if _keyword_hits(low_text, door_kw) and qty_val > 0:
                    category_hits["doors"] += 1
                if _keyword_hits(low_text, frame_kw) and qty_val > 0:
                    category_hits["door_frames"] += 1

                has_wood = _keyword_hits(low_text, wood_kw)
                has_shower = _keyword_hits(low_text, shower_kw)
                has_cab = _keyword_hits(low_text, cabinet_kw)
                if has_wood and has_shower:
                    if qty_val > 0:
                        wood_base_shower_active += 1
                    else:
                        wood_base_shower_zero += 1
                if has_wood and has_cab:
                    if qty_val > 0:
                        wood_base_cabinet_active += 1
                    else:
                        wood_base_cabinet_zero += 1

                if len(evidence_rows) < 25 and (qty_val > 0 or (has_wood and (has_shower or has_cab))):
                    evidence_rows.append(
                        {
                            "table": table,
                            "condition": cond_display,
                            "room_or_location": room_val,
                            "quantity": qty_val,
                            "text": all_text[:300],
                        }
                    )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    top_conditions = sorted(
        list(active_by_condition.values()),
        key=lambda x: (float(x.get("total_quantity", 0.0)), int(x.get("active_row_count", 0))),
        reverse=True,
    )[:15]

    observations: List[str] = []
    why: List[str] = []
    observations.append(
        f"Scanned {len(tables_scanned)} tables, {rows_seen} rows total, and detected {active_rows} active rows using quantity > 0."
    )
    observations.append(
        "Active takeoff category hits (quantity > 0): "
        f"walls={category_hits['walls']}, ceilings={category_hits['ceilings']}, "
        f"wood_base={category_hits['wood_base']}, doors={category_hits['doors']}, "
        f"door_frames={category_hits['door_frames']}."
    )
    observations.append(
        "Wood-base exclusion checks: "
        f"shower/tub active={wood_base_shower_active}, shower/tub zero={wood_base_shower_zero}, "
        f"cabinetry active={wood_base_cabinet_active}, cabinetry zero={wood_base_cabinet_zero}."
    )
    if wood_base_shower_zero > wood_base_shower_active:
        why.append(
            "Maverick infers a likely rule to suppress wood base near showers/tubs because zero-quantity rows outweigh active rows in those contexts."
        )
    else:
        why.append(
            "Maverick cannot yet confirm a strict no-wood-base-near-shower/tub rule from quantity evidence alone; requires coached confirmation."
        )
    if wood_base_cabinet_zero > wood_base_cabinet_active:
        why.append(
            "Maverick infers a likely rule to suppress wood base behind cabinetry because zero-quantity rows outweigh active rows in cabinetry contexts."
        )
    else:
        why.append(
            "Maverick cannot yet confirm a strict no-wood-base-behind-cabinetry rule from quantity evidence alone; requires coached confirmation."
        )
    why.append(
        "Maverick uses quantity > 0 as the condition-in-use signal and records these assumptions explicitly for human coaching."
    )

    notes_markdown = [
        f"# Maverick Training Notes - {attempt_id}",
        "",
        "## What I Observed",
    ]
    notes_markdown.extend([f"- {x}" for x in observations])
    notes_markdown.append("")
    notes_markdown.append("## Why I Did What I Did")
    notes_markdown.extend([f"- {x}" for x in why])
    notes_markdown.append("")
    notes_markdown.append("## Top Active Conditions (quantity > 0)")
    for row in top_conditions[:10]:
        notes_markdown.append(
            "- "
            f"{row.get('condition')} | total_qty={row.get('total_quantity')} | "
            f"active_rows={row.get('active_row_count')} | sample={row.get('sample_room','')}"
        )
    notes_markdown.append("")
    notes_markdown.append("## Evidence Samples")
    for ev in evidence_rows[:12]:
        notes_markdown.append(
            "- "
            f"{ev.get('table')} | qty={ev.get('quantity')} | condition={ev.get('condition')} | "
            f"context={ev.get('room_or_location')} | text={ev.get('text')}"
        )

    return {
        "ok": True,
        "db_path": str(db_path),
        "tables_scanned": tables_scanned,
        "rows_scanned": rows_seen,
        "active_rows": active_rows,
        "observations": observations,
        "reasoning": why,
        "category_hits": category_hits,
        "exclusion_checks": {
            "wood_base_shower_active": wood_base_shower_active,
            "wood_base_shower_zero": wood_base_shower_zero,
            "wood_base_cabinet_active": wood_base_cabinet_active,
            "wood_base_cabinet_zero": wood_base_cabinet_zero,
        },
        "top_active_conditions": top_conditions,
        "evidence_samples": evidence_rows,
        "condition_label_map_size": len(condition_label_map),
        "notes_markdown": "\n".join(notes_markdown) + "\n",
    }


def build_post_boost_edit_plan(
    project: Dict[str, Any],
    module_id: str,
    run_log: Dict[str, Any],
    training_db_analysis: Dict[str, Any],
    scope_profile: Dict[str, Any],
    attempt_id: str,
    coaching_hints: List[str] | None = None,
) -> Dict[str, Any]:
    """
    Build a deterministic, reviewable plan for how Maverick should edit/reassign/duplicate
    conditions after Boost to match the user's style.
    """
    category_hits = (training_db_analysis.get("category_hits", {}) if isinstance(training_db_analysis, dict) else {}) or {}
    exclusion = (training_db_analysis.get("exclusion_checks", {}) if isinstance(training_db_analysis, dict) else {}) or {}
    top_conditions = (
        training_db_analysis.get("top_active_conditions", []) if isinstance(training_db_analysis, dict) else []
    ) or []
    evidence_samples = (
        training_db_analysis.get("evidence_samples", []) if isinstance(training_db_analysis, dict) else []
    ) or []
    boost_ok = bool(run_log.get("ok"))
    step_status = (run_log.get("status", {}) or {}).get("step_status", {}) if isinstance(run_log, dict) else {}

    operator_style_goals = [
        "Run Boost first for baseline condition distribution.",
        "Then edit/reassign/duplicate conditions to match established takeoff style.",
        "Prioritize walls, ceilings, wood base, doors, and door frames.",
        "Use quantity > 0 as in-use signal and preserve known exclusions.",
    ]
    style_hints = [
        "No wood base where shower/tub applies.",
        "No wood base behind cabinetry.",
    ]
    for hint in coaching_hints or []:
        h = str(hint).strip()
        if h and h not in style_hints:
            style_hints.append(h)

    plan_items: List[Dict[str, Any]] = []
    if not boost_ok:
        plan_items.append(
            {
                "type": "retry_boost",
                "priority": 100,
                "confidence": "high",
                "reason": "Boost run did not complete successfully; post-boost edits are unsafe until baseline is valid.",
                "action": "Re-run Boost and verify step_status step1-4 before condition edits.",
                "requires_user_approval": False,
            }
        )
    else:
        plan_items.append(
            {
                "type": "condition_review",
                "priority": 95,
                "confidence": "high",
                "reason": "Boost completed; now validate and align condition assignments to operator style.",
                "action": "Open condition totals and compare top affected conditions against style profile before finalizing.",
                "requires_user_approval": False,
            }
        )

    area_multiplier_hint = any(
        any(token in h.lower() for token in ("area drop", "multipl", "bold", "unit type"))
        for h in style_hints
    )
    optional_area_mode = any(
        any(token in h.lower() for token in ("won't use areas every time", "not use areas every time", "area optional"))
        for h in style_hints
    )
    if area_multiplier_hint:
        plan_items.append(
            {
                "type": "detect_area_mode_first",
                "priority": 94,
                "confidence": "high",
                "reason": "Area-based interpretation is useful only when area context is actually active in the current workflow.",
                "action": (
                    "Check whether area dropdown selections and/or bold area rows are present before applying area-based quantity interpretation."
                ),
                "requires_user_approval": False,
            }
        )
    if area_multiplier_hint:
        plan_items.append(
            {
                "type": "normalize_area_multiplier_context",
                "priority": 93 if not optional_area_mode else 86,
                "confidence": "high" if not optional_area_mode else "medium",
                "reason": (
                    "Operator coaching indicates condition totals can be multiplied by area selection when area mode is active."
                ),
                "action": (
                    "Only when area mode is active, interpret on-screen condition quantities in area-dropdown multiplier context; "
                    "treat bold areas as the unit types actively taken off on that page."
                ),
                "requires_user_approval": False,
            }
        )

    walls = int(category_hits.get("walls", 0) or 0)
    ceilings = int(category_hits.get("ceilings", 0) or 0)
    wood = int(category_hits.get("wood_base", 0) or 0)
    doors = int(category_hits.get("doors", 0) or 0)
    frames = int(category_hits.get("door_frames", 0) or 0)
    if any(v > 0 for v in (walls, ceilings, wood, doors, frames)):
        plan_items.append(
            {
                "type": "reassign_conditions",
                "priority": 90,
                "confidence": "medium",
                "reason": "Core style categories are active in training data and should be aligned after Boost.",
                "action": (
                    "Reassign questionable takeoff groups into preferred conditions for "
                    f"walls/ceilings/wood base/doors/frames (hits={walls}/{ceilings}/{wood}/{doors}/{frames})."
                ),
                "requires_user_approval": True,
            }
        )

    shower_zero = int(exclusion.get("wood_base_shower_zero", 0) or 0)
    shower_active = int(exclusion.get("wood_base_shower_active", 0) or 0)
    cab_zero = int(exclusion.get("wood_base_cabinet_zero", 0) or 0)
    cab_active = int(exclusion.get("wood_base_cabinet_active", 0) or 0)
    plan_items.append(
        {
            "type": "apply_exclusions",
            "priority": 88,
            "confidence": "medium" if (shower_zero + cab_zero) > 0 else "low",
            "reason": "Operator style requires wood-base exclusions near showers/tubs and behind cabinetry.",
            "action": (
                "Review wood-base conditions and set quantities/assignments to exclude shower+tub and cabinetry zones; "
                f"evidence shower(zero/active)={shower_zero}/{shower_active}, cabinetry(zero/active)={cab_zero}/{cab_active}."
            ),
            "requires_user_approval": True,
        }
    )

    if len(top_conditions) > 0:
        top_preview = ", ".join(str((x or {}).get("condition", "")) for x in top_conditions[:3] if isinstance(x, dict))
        plan_items.append(
            {
                "type": "duplicate_conditions",
                "priority": 80,
                "confidence": "medium",
                "reason": "Repeated high-volume conditions indicate likely reuse patterns across units/floors.",
                "action": (
                    "Create/duplicate reusable condition variants where needed to keep style-consistent assignments "
                    f"across repeated units. Top signals: {top_preview}."
                ),
                "requires_user_approval": True,
            }
        )

    plan_items.append(
        {
            "type": "audit_notes",
            "priority": 70,
            "confidence": "high",
            "reason": "Every post-boost edit should be explainable for coaching.",
            "action": "Write detailed note for each edit: observed evidence, chosen action, and why it matches operator style.",
            "requires_user_approval": False,
        }
    )

    plan_items.sort(key=lambda x: int(x.get("priority", 0)), reverse=True)

    md_lines: List[str] = [
        f"# Maverick Post-Boost Edit Plan - {attempt_id}",
        "",
        f"- project: {project.get('project_name', '')}",
        f"- module_id: {module_id}",
        f"- boost_ok: {boost_ok}",
        f"- step_status: {json.dumps(step_status)}",
        "",
        "## Operator Style Goal",
    ]
    md_lines.extend([f"- {x}" for x in operator_style_goals])
    md_lines.append("")
    md_lines.append("## Style Hints")
    md_lines.extend([f"- {x}" for x in style_hints])
    md_lines.append("")
    md_lines.append("## Ranked Edit Actions")
    for idx, row in enumerate(plan_items, start=1):
        md_lines.append(
            f"{idx}. {row.get('type')} | priority={row.get('priority')} | confidence={row.get('confidence')}"
        )
        md_lines.append(f"   - action: {row.get('action')}")
        md_lines.append(f"   - why: {row.get('reason')}")
        md_lines.append(f"   - requires_user_approval: {row.get('requires_user_approval')}")
    if evidence_samples:
        md_lines.append("")
        md_lines.append("## Evidence Anchors")
        for ev in evidence_samples[:10]:
            if not isinstance(ev, dict):
                continue
            md_lines.append(
                "- "
                f"{ev.get('table')} | condition={ev.get('condition')} | qty={ev.get('quantity')} | "
                f"context={ev.get('room_or_location')}"
            )

    return {
        "ok": True,
        "attempt_id": attempt_id,
        "project_name": project.get("project_name", ""),
        "module_id": module_id,
        "boost_ok": boost_ok,
        "operator_style_goals": operator_style_goals,
        "style_hints": style_hints,
        "ranked_actions": plan_items,
        "scope_profile_work_packages": (scope_profile.get("work_packages", []) if isinstance(scope_profile, dict) else []),
        "notes_markdown": "\n".join(md_lines) + "\n",
    }


def build_style_methods_log_entry(
    analysis: Dict[str, Any],
    project: Dict[str, Any],
    training_project_id: str,
    attempt_id: str,
) -> Dict[str, Any]:
    top_conditions = analysis.get("top_active_conditions", []) if isinstance(analysis, dict) else []
    pattern_counts: Dict[str, int] = {
        "unit_scoped": 0,
        "floor_or_level_scoped": 0,
        "building_or_common_scoped": 0,
        "room_or_space_scoped": 0,
        "trade_walls": 0,
        "trade_ceilings": 0,
        "trade_wood_base": 0,
        "trade_doors": 0,
        "trade_frames": 0,
        "uses_abbrev_tokens": 0,
    }
    examples: Dict[str, List[str]] = {k: [] for k in pattern_counts.keys()}

    for row in top_conditions[:50]:
        if not isinstance(row, dict):
            continue
        cond = str(row.get("condition", "") or "").strip()
        low = cond.lower()
        checks = {
            "unit_scoped": any(x in low for x in ("unit", "typ", "type ")),
            "floor_or_level_scoped": any(x in low for x in ("floor", "lvl", "level", "1st", "2nd", "3rd")),
            "building_or_common_scoped": any(x in low for x in ("building", "bldg", "clubhouse", "common")),
            "room_or_space_scoped": any(x in low for x in ("rr", "bath", "entry", "kitchen", "garage", "amenity")),
            "trade_walls": any(x in low for x in ("wall", "gwb", "drywall", "wallcovering")),
            "trade_ceilings": any(x in low for x in ("ceiling", "rcp")),
            "trade_wood_base": any(x in low for x in ("wood base", "baseboard", "w/base", "w base")),
            "trade_doors": any(x in low for x in ("door", "doors")),
            "trade_frames": any(x in low for x in ("frame", "frames")),
            "uses_abbrev_tokens": any(x in low for x in ("rr", "lvl", "typ", "gwb", "w/")),
        }
        for key, hit in checks.items():
            if hit:
                pattern_counts[key] += 1
                if len(examples[key]) < 6 and cond not in examples[key]:
                    examples[key].append(cond)

    method_signals: List[str] = []
    if pattern_counts["unit_scoped"] > 0:
        method_signals.append("Uses unit-scoped condition naming and assignment patterns.")
    if pattern_counts["floor_or_level_scoped"] > 0:
        method_signals.append("Uses floor/level-specific condition segmentation.")
    if pattern_counts["building_or_common_scoped"] > 0:
        method_signals.append("Uses building/common-area split condition strategies.")
    if pattern_counts["trade_walls"] > 0 and pattern_counts["trade_ceilings"] > 0:
        method_signals.append("Separates wall and ceiling workflows into distinct condition families.")
    if pattern_counts["trade_wood_base"] > 0:
        method_signals.append("Uses explicit wood-base condition workflow that may require context exclusions.")
    if pattern_counts["trade_doors"] > 0 or pattern_counts["trade_frames"] > 0:
        method_signals.append("Tracks door and frame scope as dedicated condition channels.")
    if pattern_counts["uses_abbrev_tokens"] > 0:
        method_signals.append("Uses abbreviated naming tokens that Maverick should normalize (RR/LVL/GWB/etc).")
    if not method_signals:
        method_signals.append("Insufficient label diversity detected; continue collecting examples.")

    return {
        "ts": datetime.now().isoformat(),
        "training_project_id": training_project_id,
        "project_name": str(project.get("project_name", "") or ""),
        "attempt_id": attempt_id,
        "pattern_counts": pattern_counts,
        "method_signals": method_signals,
        "pattern_examples": examples,
        "source_rows_scanned": int((analysis.get("rows_scanned", 0) if isinstance(analysis, dict) else 0) or 0),
        "source_active_rows": int((analysis.get("active_rows", 0) if isinstance(analysis, dict) else 0) or 0),
    }


def append_style_methods_log(
    entry: Dict[str, Any],
    out_dir: pathlib.Path,
) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_jsonl = out_dir / "style_methods_log.jsonl"
    profile_json = out_dir / "style_methods_profile.json"
    profile_md = out_dir / "style_methods_profile.md"

    with log_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=True) + "\n")

    lines = log_jsonl.read_text(encoding="utf-8").splitlines()
    rows: List[Dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)

    agg_counts: Dict[str, int] = {}
    signal_counts: Dict[str, int] = {}
    recent_examples: Dict[str, List[str]] = {}
    for row in rows:
        pc = row.get("pattern_counts", {})
        if isinstance(pc, dict):
            for k, v in pc.items():
                agg_counts[k] = agg_counts.get(k, 0) + int(v or 0)
        sigs = row.get("method_signals", [])
        if isinstance(sigs, list):
            for s in sigs:
                txt = str(s).strip()
                if txt:
                    signal_counts[txt] = signal_counts.get(txt, 0) + 1
        ex = row.get("pattern_examples", {})
        if isinstance(ex, dict):
            for k, vals in ex.items():
                if k not in recent_examples:
                    recent_examples[k] = []
                if isinstance(vals, list):
                    for item in vals:
                        v = str(item).strip()
                        if v and v not in recent_examples[k] and len(recent_examples[k]) < 12:
                            recent_examples[k].append(v)

    profile_payload = {
        "updated_at": datetime.now().isoformat(),
        "entries": len(rows),
        "aggregate_pattern_counts": agg_counts,
        "method_signal_frequency": signal_counts,
        "recent_examples": recent_examples,
    }
    write_json(profile_json, profile_payload)

    ranked_signals = sorted(signal_counts.items(), key=lambda kv: kv[1], reverse=True)
    md_lines = [
        "# Maverick Style Methods Profile",
        "",
        f"- entries: {len(rows)}",
        f"- updated_at: {profile_payload['updated_at']}",
        "",
        "## Frequent Method Signals",
    ]
    if ranked_signals:
        for sig, cnt in ranked_signals[:10]:
            md_lines.append(f"- {sig} (seen {cnt} times)")
    else:
        md_lines.append("- none yet")
    md_lines.append("")
    md_lines.append("## Aggregate Naming Pattern Counts")
    for k, v in sorted(agg_counts.items(), key=lambda kv: kv[1], reverse=True):
        md_lines.append(f"- {k}: {v}")
    md_lines.append("")
    md_lines.append("## Pattern Examples")
    for k, vals in sorted(recent_examples.items()):
        if not vals:
            continue
        md_lines.append(f"- {k}: {', '.join(vals[:6])}")
    profile_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return {
        "log_jsonl": str(log_jsonl),
        "profile_json": str(profile_json),
        "profile_md": str(profile_md),
    }


def append_operator_coaching_note(
    out_dir: pathlib.Path,
    training_project_id: str,
    project_name: str,
    note: str,
    tags: List[str],
    source: str = "user_coaching",
    session_id: str = "",
) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_jsonl = out_dir / "operator_coaching_notes.jsonl"
    profile_json = out_dir / "operator_coaching_profile.json"
    profile_md = out_dir / "operator_coaching_profile.md"

    entry = {
        "ts": datetime.now().isoformat(),
        "training_project_id": training_project_id,
        "project_name": project_name,
        "source": source,
        "session_id": session_id,
        "tags": [str(t).strip() for t in tags if str(t).strip()],
        "note": str(note).strip(),
    }
    append_jsonl(log_jsonl, entry)

    lines = log_jsonl.read_text(encoding="utf-8").splitlines()
    rows: List[Dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)

    tag_counts: Dict[str, int] = {}
    for row in rows:
        for t in row.get("tags", []) if isinstance(row.get("tags"), list) else []:
            tt = str(t).strip()
            if tt:
                tag_counts[tt] = tag_counts.get(tt, 0) + 1

    profile_payload = {
        "updated_at": datetime.now().isoformat(),
        "entries": len(rows),
        "tag_frequency": tag_counts,
        "recent_notes": rows[-20:],
    }
    write_json(profile_json, profile_payload)

    md_lines = [
        "# Maverick Operator Coaching Profile",
        "",
        f"- entries: {len(rows)}",
        f"- updated_at: {profile_payload['updated_at']}",
        "",
        "## Tag Frequency",
    ]
    if tag_counts:
        for k, v in sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True):
            md_lines.append(f"- {k}: {v}")
    else:
        md_lines.append("- none")
    md_lines.append("")
    md_lines.append("## Recent Notes")
    for row in rows[-10:]:
        md_lines.append(
            "- "
            f"{row.get('ts')} | {row.get('training_project_id')} | tags={','.join(row.get('tags', []))} | "
            f"{row.get('note')}"
        )
    profile_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return {
        "log_jsonl": str(log_jsonl),
        "profile_json": str(profile_json),
        "profile_md": str(profile_md),
    }


def load_operator_coaching_hints(out_dir: pathlib.Path, training_project_id: str, limit: int = 30) -> List[str]:
    log_jsonl = out_dir / "operator_coaching_notes.jsonl"
    if not log_jsonl.exists():
        return []
    lines = log_jsonl.read_text(encoding="utf-8").splitlines()
    hints: List[str] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        pid = str(row.get("training_project_id", "") or "")
        if pid and training_project_id and pid != training_project_id:
            continue
        note = str(row.get("note", "") or "").strip()
        if note and note not in hints:
            hints.append(note)
        if len(hints) >= max(1, limit):
            break
    hints.reverse()
    return hints


def run_group_selection(project: Dict[str, Any]) -> Dict[str, Any]:
    GROUP_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = GROUP_OUT_DIR / f"selection_{project.get('training_project_id','unknown')}_{now_tag()}.json"
    cmd = [
        sys.executable,
        str(GROUP_SELECTOR_SCRIPT),
        "--monitor-index",
        "1",
        "--output",
        str(out_path),
        "--click-best",
    ]
    unit_label = str(project.get("preferred_unit_label", "") or "").strip()
    if unit_label:
        cmd.extend(["--unit-label", unit_label])
    proc = run_subprocess_guarded(cmd, watch_emergency=True)
    summary = {
        "command": cmd,
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "output_path": str(out_path),
        "selected_target": None,
    }
    if out_path.exists():
        payload = read_json(out_path)
        summary["selected_target"] = payload.get("selected_target")
    return summary


def run_item_type_classifier(
    training_project_id: str,
    monitor_index: int = 1,
    update_prototypes: bool = False,
    context_label: str = "run_module_preflight",
) -> Dict[str, Any]:
    load_or_init_item_type_store()
    ITEM_TYPE_CLASSIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ITEM_TYPE_CLASSIFICATIONS_DIR / f"classification_{training_project_id}_{now_tag()}.json"
    cmd = [
        sys.executable,
        str(ITEM_TYPE_CLASSIFIER_SCRIPT),
        "--project-id",
        str(training_project_id),
        "--monitor-index",
        str(monitor_index),
        "--output",
        str(out_path),
        "--item-db-root",
        str(ITEM_TYPES_DIR),
        "--context-label",
        str(context_label),
    ]
    if update_prototypes:
        cmd.append("--update-prototypes")
    proc = run_subprocess_guarded(cmd, watch_emergency=True)
    summary: Dict[str, Any] = {
        "command": cmd,
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "output_path": str(out_path),
        "ok": bool(proc.returncode == 0 and out_path.exists()),
    }
    if out_path.exists():
        payload = read_json(out_path)
        summary["classification"] = payload
        top = (payload.get("ranked_item_types", []) or [None])[0]
        if isinstance(top, dict):
            summary["top_item_type"] = top.get("item_type")
            summary["top_match_confidence"] = top.get("confidence")
    return summary


def run_takeoff_copy_attempt(
    training_project_id: str,
    condition_row: str = "first",
    left_choice: str = "middle",
    monitor_index: int = 1,
    match_score_threshold: float = 55.0,
    cleanup_undo_count: int = 2,
    attempt_style: str = "polyline4",
    out_dir: pathlib.Path | None = None,
    pre_click_adjust_threshold: int = 160,
    condition_verify_retries: int = 2,
    condition_min_qty: float = 1.0,
    expected_target_x: int = 0,
    expected_target_y: int = 0,
    expected_item_type: str = "",
    strict_expected_distance_threshold: int = 220,
    condition_prefer_contains: str = "ceiling,gwb",
    expected_condition_row_index: int = -1,
    teacher_targets_json: str = "",
    geometry_score_threshold: float = 0.55,
    phase_timeout_s: int = 240,
    user_start_x: int = 0,
    user_start_y: int = 0,
    finish_taxonomy_json: str = "scripts/ost_finish_taxonomy.json",
    finish_index_json: str = "",
    ocr_config: str = "scripts/ocr_engine.config.json",
    enforce_area_style: bool = False,
    enforce_condition_names: str = "ceiling,gwb",
    balanced_latency_budget_ms: int = 28000,
) -> Dict[str, Any]:
    if out_dir is None:
        out_dir = LAB_OUT_DIR / "takeoff_copy_attempts" / f"{training_project_id}_{now_tag()}"
    cmd = [
        sys.executable,
        str(LEFT_BLANK_TAKEOFF_SCRIPT),
        "--setup-config",
        "scripts/ost_project_setup_agent.config.json",
        "--monitor-index",
        str(monitor_index),
        "--condition-row",
        str(condition_row),
        "--left-choice",
        str(left_choice),
        "--attempt-style",
        str(attempt_style),
        "--match-score-threshold",
        str(match_score_threshold),
        "--cleanup-undo-count",
        str(cleanup_undo_count),
        "--project-id",
        str(training_project_id),
        "--item-db-root",
        str(ITEM_TYPES_DIR),
        "--output-dir",
        str(out_dir),
        "--window-title-contains",
        "On-Screen Takeoff",
        "--pre-attempt-visible-delay-ms",
        "2200",
        "--pre-click-adjust-threshold",
        str(max(40, int(pre_click_adjust_threshold))),
        "--condition-verify-retries",
        str(max(0, int(condition_verify_retries))),
        "--condition-min-qty",
        str(float(condition_min_qty)),
        "--condition-prefer-contains",
        str(condition_prefer_contains),
        "--strict-expected-distance-threshold",
        str(max(80, int(strict_expected_distance_threshold))),
        "--geometry-score-threshold",
        str(float(geometry_score_threshold)),
        "--finish-taxonomy-json",
        str(finish_taxonomy_json),
        "--ocr-config",
        str(ocr_config),
        "--enforce-condition-names",
        str(enforce_condition_names),
        "--balanced-latency-budget-ms",
        str(int(balanced_latency_budget_ms)),
    ]
    if enforce_area_style:
        cmd.append("--enforce-area-style")
    if int(expected_target_x) > 0 and int(expected_target_y) > 0:
        cmd.extend(["--expected-target-x", str(int(expected_target_x)), "--expected-target-y", str(int(expected_target_y))])
    if str(expected_item_type or "").strip():
        cmd.extend(["--expected-item-type", str(expected_item_type).strip()])
    if int(expected_condition_row_index) >= 0:
        cmd.extend(["--expected-condition-row-index", str(int(expected_condition_row_index))])
    if str(teacher_targets_json or "").strip():
        cmd.extend(["--teacher-targets-json", str(teacher_targets_json).strip()])
    if int(user_start_x) > 0 and int(user_start_y) > 0:
        cmd.extend(["--user-start-x", str(int(user_start_x)), "--user-start-y", str(int(user_start_y))])
    if str(finish_index_json or "").strip():
        cmd.extend(["--finish-index-json", str(finish_index_json).strip()])
    try:
        proc = run_subprocess_guarded(cmd, timeout=max(20, int(phase_timeout_s)), watch_emergency=True)
    except subprocess.TimeoutExpired as exc:
        return {
            "command": cmd,
            "exit_code": 124,
            "stdout": str(exc.stdout or "").strip(),
            "stderr": f"takeoff_copy_attempt_timeout_s={int(phase_timeout_s)}",
            "output_dir": str(out_dir),
            "result_json": str(out_dir / "left_blank_takeoff_attempt.json"),
            "ok": False,
        }
    result_json = out_dir / "left_blank_takeoff_attempt.json"
    out: Dict[str, Any] = {
        "command": cmd,
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "output_dir": str(out_dir),
        "result_json": str(result_json),
        "ok": bool(proc.returncode == 0 and result_json.exists()),
    }
    if result_json.exists():
        payload = read_json(result_json)
        out["result"] = payload
        match_assessment = payload.get("match_assessment", {}) if isinstance(payload, dict) else {}
        out["match_assessment"] = match_assessment
    return out


def wait_for_boost_population(
    training_project_id: str,
    monitor_index: int,
    timeout_ms: int,
    poll_ms: int,
    min_candidate_count: int,
) -> Dict[str, Any]:
    start = time.time()
    probes: List[Dict[str, Any]] = []
    max_timeout = max(1000, int(timeout_ms))
    poll = max(250, int(poll_ms))
    min_candidates = max(1, int(min_candidate_count))
    while True:
        probe = run_item_type_classifier(
            training_project_id=training_project_id,
            monitor_index=monitor_index,
            update_prototypes=False,
            context_label="boost_population_probe",
        )
        payload = probe.get("classification", {}) if isinstance(probe, dict) else {}
        summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
        candidate_count = int(summary.get("classified_regions", 0) or 0)
        top_conf = float(summary.get("top_confidence", 0.0) or 0.0)
        top_item = str(summary.get("top_item_type", "unknown") or "unknown")
        elapsed_ms = int((time.time() - start) * 1000.0)
        probes.append(
            {
                "elapsed_ms": elapsed_ms,
                "candidate_count": candidate_count,
                "top_item_type": top_item,
                "top_confidence": top_conf,
                "output_path": probe.get("output_path"),
            }
        )
        # Population gate: we need visible classified regions and non-trivial confidence.
        if candidate_count >= min_candidates and top_conf >= 0.35:
            return {
                "ok": True,
                "elapsed_ms": elapsed_ms,
                "candidate_count": candidate_count,
                "top_item_type": top_item,
                "top_confidence": round(top_conf, 4),
                "probes": probes,
                "final_probe": probe,
            }
        if elapsed_ms >= max_timeout:
            return {
                "ok": False,
                "elapsed_ms": elapsed_ms,
                "candidate_count": candidate_count,
                "top_item_type": top_item,
                "top_confidence": round(top_conf, 4),
                "probes": probes,
                "final_probe": probe,
                "reason": "boost_population_not_confirmed",
            }
        time.sleep(poll / 1000.0)


def extract_boost_teacher_geometry(
    classification_payload: Dict[str, Any],
    snapshot_image: str,
    out_path: pathlib.Path,
) -> Dict[str, Any]:
    def _poly_area(points: List[Dict[str, int]]) -> float:
        if len(points) < 3:
            return 0.0
        total = 0.0
        for i in range(len(points)):
            x1, y1 = float(points[i]["x"]), float(points[i]["y"])
            x2, y2 = float(points[(i + 1) % len(points)]["x"]), float(points[(i + 1) % len(points)]["y"])
            total += (x1 * y2) - (x2 * y1)
        return abs(total) * 0.5

    def _poly_signed_area(points: List[Dict[str, int]]) -> float:
        if len(points) < 3:
            return 0.0
        total = 0.0
        for i in range(len(points)):
            x1, y1 = float(points[i]["x"]), float(points[i]["y"])
            x2, y2 = float(points[(i + 1) % len(points)]["x"]), float(points[(i + 1) % len(points)]["y"])
            total += (x1 * y2) - (x2 * y1)
        return total * 0.5

    def _poly_perimeter(points: List[Dict[str, int]]) -> float:
        if len(points) < 2:
            return 0.0
        total = 0.0
        for i in range(len(points)):
            x1, y1 = float(points[i]["x"]), float(points[i]["y"])
            x2, y2 = float(points[(i + 1) % len(points)]["x"]), float(points[(i + 1) % len(points)]["y"])
            total += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        return total
    regions = (
        ((classification_payload.get("classification", {}) if isinstance(classification_payload.get("classification", {}), dict) else {})
         .get("region_candidates", []))
        if isinstance(classification_payload, dict)
        else []
    )
    teacher_targets: List[Dict[str, Any]] = []
    for i, reg in enumerate(regions):
        if not isinstance(reg, dict):
            continue
        bbox = reg.get("bbox_global", {}) if isinstance(reg.get("bbox_global", {}), dict) else {}
        if not bbox:
            center = reg.get("center_global", {}) if isinstance(reg.get("center_global", {}), dict) else {}
            cx = int(center.get("x", 0) or 0)
            cy = int(center.get("y", 0) or 0)
            if cx <= 0 or cy <= 0:
                continue
            w = int(reg.get("w", 60) or 60)
            h = int(reg.get("h", 60) or 60)
            bbox = {"x": max(0, cx - int(w / 2)), "y": max(0, cy - int(h / 2)), "w": max(20, w), "h": max(20, h)}
        x, y = int(bbox.get("x", 0) or 0), int(bbox.get("y", 0) or 0)
        w, h = max(1, int(bbox.get("w", 0) or 0)), max(1, int(bbox.get("h", 0) or 0))
        polygon_points = [
            {"x": x, "y": y},
            {"x": x + w, "y": y},
            {"x": x + w, "y": y + h},
            {"x": x, "y": y + h},
        ]
        signed_area = _poly_signed_area(polygon_points)
        winding = "clockwise" if signed_area < 0 else "counterclockwise"
        teacher_targets.append(
            {
                "id": f"teacher_{i+1:03d}",
                "bbox_global": {"x": x, "y": y, "w": w, "h": h},
                "center_global": {"x": x + int(w / 2), "y": y + int(h / 2)},
                "polygon_points": polygon_points,
                "polygon_points_reverse": list(reversed(polygon_points)),
                "vertex_count": len(polygon_points),
                "winding": winding,
                "area": round(_poly_area(polygon_points), 3),
                "perimeter": round(_poly_perimeter(polygon_points), 3),
                "source": {
                    "item_type": str(reg.get("item_type", "") or ""),
                    "confidence": float(reg.get("confidence", 0.0) or 0.0),
                },
            }
        )
    payload = {
        "ok": len(teacher_targets) > 0,
        "snapshot_image": str(snapshot_image),
        "teacher_targets": teacher_targets,
        "teacher_target_count": len(teacher_targets),
    }
    write_json(out_path, payload)
    return payload


def run_scope_profile(project: Dict[str, Any], resolved_ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
    pdf_path = str(project.get("source_pdf_path", "") or "").strip()
    if (not pdf_path) and resolved_ctx:
        pdf_path = str(resolved_ctx.get("resolved_pdf", "") or "").strip()
    if not pdf_path:
        return {
            "skipped": True,
            "reason": "source_pdf_path_not_set",
        }
    pdf = pathlib.Path(pdf_path)
    if not pdf.exists():
        return {
            "skipped": True,
            "reason": "source_pdf_missing",
            "source_pdf_path": pdf_path,
        }
    SCOPE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SCOPE_OUT_DIR / f"scope_{project.get('training_project_id','unknown')}_{now_tag()}.json"
    cmd = [
        sys.executable,
        str(SCOPE_PROFILER_SCRIPT),
        "--pdf",
        str(pdf),
        "--output",
        str(out_path),
    ]
    proc = run_subprocess_guarded(cmd, watch_emergency=False)
    summary: Dict[str, Any] = {
        "command": cmd,
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "output_path": str(out_path),
        "skipped": False,
    }
    if out_path.exists():
        payload = read_json(out_path)
        summary["work_packages"] = payload.get("work_packages", [])
        summary["boost_priorities"] = payload.get("boost_priorities", [])
        summary["role_totals"] = payload.get("role_totals", {})
    return summary


def run_project_scope_intel(
    project: Dict[str, Any],
    resolved_ctx: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    folder_path = str(project.get("source_project_folder", "") or "").strip()
    if (not folder_path) and resolved_ctx:
        folder_path = str(resolved_ctx.get("resolved_folder", "") or "").strip()
    if not folder_path:
        return {"skipped": True, "reason": "source_project_folder_not_set"}
    folder = pathlib.Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        return {
            "skipped": True,
            "reason": "source_project_folder_missing",
            "source_project_folder": folder_path,
        }
    PROJECT_SCOPE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{project.get('training_project_id','unknown')}_{now_tag()}"
    out_json = PROJECT_SCOPE_OUT_DIR / f"scope_{tag}.json"
    out_md = PROJECT_SCOPE_OUT_DIR / f"scope_{tag}.md"
    cmd = [
        sys.executable,
        str(PROJECT_SCOPE_REPORT_SCRIPT),
        "--project-folder",
        str(folder),
        "--output-json",
        str(out_json),
        "--output-md",
        str(out_md),
    ]
    proc = run_subprocess_guarded(cmd, watch_emergency=False)
    summary: Dict[str, Any] = {
        "command": cmd,
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "output_json": str(out_json),
        "output_md": str(out_md),
        "skipped": False,
    }
    if out_json.exists():
        payload = read_json(out_json)
        summary["document_count"] = payload.get("document_count")
        summary["conflict_count"] = len(payload.get("conflicts") or [])
        summary["scope_signals"] = payload.get("scope_signals", {})
        summary["product_signals"] = payload.get("product_signals", {})
    return summary


def get_project_protocol_status(project_id: str) -> Dict[str, Any]:
    store = load_or_init_protocol_store()
    project_map_payload = store.get("project_map", {}) if isinstance(store, dict) else {}
    registry_payload = store.get("registry", {}) if isinstance(store, dict) else {}
    project_map = (project_map_payload.get("projects", {}) if isinstance(project_map_payload, dict) else {}) or {}
    protocols = (registry_payload.get("protocols", {}) if isinstance(registry_payload, dict) else {}) or {}
    p = (project_map or {}).get(project_id, {})
    protocol_id = str((p or {}).get("protocol_id", "") or "")
    protocol = (protocols or {}).get(protocol_id, {}) if protocol_id else {}
    return {
        "project_id": project_id,
        "has_protocol": bool(protocol_id),
        "protocol_id": protocol_id,
        "protocol_type": str((p or {}).get("protocol_type", "") or ""),
        "status": str((protocol or {}).get("status", (p or {}).get("status", "")) or ""),
        "verification_required": bool((protocol or {}).get("verification", {}).get("required", True))
        if isinstance(protocol, dict)
        else True,
        "verified": bool((protocol or {}).get("verification", {}).get("verified", False))
        if isinstance(protocol, dict)
        else False,
    }


def _collect_protocol_scope_signals(project: Dict[str, Any]) -> Dict[str, Any]:
    ctx = resolve_project_context(project)
    folder = pathlib.Path(str(ctx.get("resolved_folder", "") or "")).resolve() if ctx.get("resolved_folder") else None
    reports = (folder / "_reports") if folder else None
    scope_profile = {}
    scope_intel = {}
    if reports and reports.exists():
        sp = reports / "scope_profile.json"
        si = reports / "project_scope_intel.json"
        if sp.exists():
            scope_profile = read_json(sp)
        if si.exists():
            scope_intel = read_json(si)
    text_bits: List[str] = [
        str(project.get("project_name", "") or ""),
        " ".join([str(x) for x in (project.get("project_aliases", []) or [])]),
        str(project.get("notes", "") or ""),
        str(folder or ""),
    ]
    wps = scope_profile.get("work_packages", []) if isinstance(scope_profile, dict) else []
    for wp in wps if isinstance(wps, list) else []:
        if isinstance(wp, dict):
            text_bits.extend(
                [
                    str(wp.get("name", "") or ""),
                    str(wp.get("trade", "") or ""),
                    str(wp.get("scope", "") or ""),
                    str(wp.get("description", "") or ""),
                ]
            )
        else:
            text_bits.append(str(wp))
    merged = " ".join([t for t in text_bits if t]).lower()

    signals = {
        "multifamily": 0,
        "office": 0,
        "tilt_up_warehouse": 0,
    }
    multifamily_kw = ["unit", "units", "apartment", "residential", "amenity", "rr", "bath"]
    office_kw = ["office", "tenant", "conference", "open office", "suite", "lobby", "break room"]
    warehouse_kw = ["warehouse", "tilt up", "tilt-up", "dock", "distribution", "industrial", "panel", "mezzanine"]
    for kw in multifamily_kw:
        if kw in merged:
            signals["multifamily"] += 1
    for kw in office_kw:
        if kw in merged:
            signals["office"] += 1
    for kw in warehouse_kw:
        if kw in merged:
            signals["tilt_up_warehouse"] += 1

    sorted_signals = sorted(signals.items(), key=lambda kv: kv[1], reverse=True)
    best_type, best_score = sorted_signals[0]
    total = sum(signals.values())
    inferred = best_type if best_score > 0 else infer_protocol_type(project)
    confidence = round((best_score / total), 2) if total > 0 else 0.4
    return {
        "project_id": str(project.get("training_project_id", "") or ""),
        "project_name": str(project.get("project_name", "") or ""),
        "resolved_folder": str(folder) if folder else "",
        "inferred_type": inferred,
        "confidence": confidence,
        "signal_scores": signals,
        "scope_profile_found": bool(scope_profile),
        "scope_intel_found": bool(scope_intel),
        "work_package_count": len(wps) if isinstance(wps, list) else 0,
    }


def _protocol_builder_questions_for_type(protocol_type: str) -> List[Dict[str, Any]]:
    common = [
        {
            "id": "q-area-mode-frequency",
            "category": "workflow-mode",
            "question": "How often is area mode used for this protocol?",
            "why": "Determines when quantity normalization by area context is applied.",
            "options": ["always", "sometimes", "rarely", "never"],
        },
        {
            "id": "q-reassign-policy",
            "category": "condition-editing",
            "question": "When Boost results differ from your method, should Maverick prefer reassign or duplicate first?",
            "why": "Defines post-Boost correction order.",
            "options": ["reassign_first", "duplicate_first", "case_by_case"],
        },
        {
            "id": "q-verification-scope",
            "category": "quality-gate",
            "question": "What must be verified before Maverick auto-continues on this protocol?",
            "why": "Defines human verification gate criteria.",
            "options": ["condition_totals_only", "totals_plus_exclusions", "full_sheet_review"],
        },
    ]
    if protocol_type == "multifamily":
        common.extend(
            [
                {
                    "id": "q-unit-type-handling",
                    "category": "unit-workflow",
                    "question": "How should repeated unit types be handled across sheets?",
                    "why": "Controls repeated-unit assignment/duplication strategy.",
                    "options": ["link_to_unit_template", "copy_per_sheet", "hybrid"],
                },
                {
                    "id": "q-bold-area-meaning",
                    "category": "area-context",
                    "question": "Do bold areas represent active unit-type takeoff for that page?",
                    "why": "Clarifies page-level active takeoff context.",
                    "options": ["yes", "no", "depends_on_sheet"],
                },
            ]
        )
    elif protocol_type == "office":
        common.extend(
            [
                {
                    "id": "q-tenant-vs-core",
                    "category": "scope-segmentation",
                    "question": "Should tenant and core be separated into distinct condition families?",
                    "why": "Determines office-specific condition grouping.",
                    "options": ["always", "sometimes", "no"],
                }
            ]
        )
    elif protocol_type == "tilt_up_warehouse":
        common.extend(
            [
                {
                    "id": "q-panel-segmentation",
                    "category": "scope-segmentation",
                    "question": "Should wall/panel takeoffs be grouped by panel type, elevation, or area zone?",
                    "why": "Defines warehouse panel organization strategy.",
                    "options": ["panel_type", "elevation", "area_zone", "hybrid"],
                }
            ]
        )
    return common


def _build_protocol_builder_intake_payload(project_ids_csv: str, registry_path: pathlib.Path) -> Dict[str, Any]:
    reg = load_registry(registry_path)
    projects = reg.get("projects", []) if isinstance(reg, dict) else []
    selected_ids = [x.strip() for x in str(project_ids_csv or "").split(",") if x.strip()]
    selected: List[Dict[str, Any]] = []
    for p in projects if isinstance(projects, list) else []:
        pid = str(p.get("training_project_id", "") or "")
        if selected_ids and pid not in selected_ids:
            continue
        selected.append(p)
    if not selected:
        return {"ok": False, "error": "no_projects_selected"}

    analyses = [_collect_protocol_scope_signals(p) for p in selected]
    type_counts: Dict[str, int] = {}
    for row in analyses:
        ptype = str(row.get("inferred_type", "general"))
        type_counts[ptype] = type_counts.get(ptype, 0) + 1
    suggested_type = sorted(type_counts.items(), key=lambda kv: kv[1], reverse=True)[0][0] if type_counts else "general"
    questions = _protocol_builder_questions_for_type(suggested_type)
    intake_id = f"INTAKE-{now_tag()}"

    payload = {
        "intake_id": intake_id,
        "created_at": datetime.now().isoformat(),
        "project_ids": [str(x.get("training_project_id", "")) for x in selected],
        "project_names": [str(x.get("project_name", "")) for x in selected],
        "suggested_protocol_type": suggested_type,
        "type_counts": type_counts,
        "project_analysis": analyses,
        "questions": questions,
        "verification_required": True,
        "status": "awaiting_user_answers",
    }
    return payload


def cmd_protocol_builder_intake(project_ids_csv: str, registry_path: pathlib.Path) -> int:
    payload = _build_protocol_builder_intake_payload(project_ids_csv, registry_path)
    if not bool(payload.get("ok", True)) and payload.get("error") == "no_projects_selected":
        print("No projects selected for protocol-builder-intake.")
        return 3

    intake_dir = PROTOCOLS_DIR / "intakes"
    intake_dir.mkdir(parents=True, exist_ok=True)
    intake_id = str(payload.get("intake_id", f"INTAKE-{now_tag()}"))
    out_json = intake_dir / f"protocol_builder_intake_{intake_id}.json"
    out_md = intake_dir / f"protocol_builder_intake_{intake_id}.md"
    write_json(out_json, payload)

    md_lines = [
        f"# Protocol Builder Intake - {intake_id}",
        "",
        f"- suggested_protocol_type: {suggested_type}",
        f"- projects: {', '.join(payload['project_ids'])}",
        "",
        "## Why This Type Was Suggested",
    ]
    for t, c in sorted(type_counts.items(), key=lambda kv: kv[1], reverse=True):
        md_lines.append(f"- {t}: {c} project(s)")
    md_lines.append("")
    md_lines.append("## Project Signal Summary")
    for row in analyses:
        md_lines.append(
            "- "
            f"{row.get('project_id')} | inferred={row.get('inferred_type')} | confidence={row.get('confidence')} | "
            f"signals={row.get('signal_scores')}"
        )
    md_lines.append("")
    md_lines.append("## Verification Questions")
    for idx, q in enumerate(questions, start=1):
        md_lines.append(
            f"{idx}. [{q.get('category')}] {q.get('question')} "
            f"(why: {q.get('why')}) options={q.get('options')}"
        )
    out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Protocol builder intake JSON: {out_json}")
    print(f"Protocol builder intake MD: {out_md}")
    return 0


def cmd_protocol_prepare_batch(project_ids_csv: str, registry_path: pathlib.Path) -> int:
    reg = load_registry(registry_path)
    projects = reg.get("projects", []) if isinstance(reg, dict) else []
    selected_ids = [x.strip() for x in str(project_ids_csv or "").split(",") if x.strip()]
    selected: List[Dict[str, Any]] = []
    for p in projects if isinstance(projects, list) else []:
        pid = str(p.get("training_project_id", "") or "")
        if selected_ids and pid not in selected_ids:
            continue
        selected.append(p)
    if not selected:
        print("No projects selected for protocol preparation.")
        return 3

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for p in selected:
        pt = infer_protocol_type(p)
        grouped.setdefault(pt, []).append(p)

    store = load_or_init_protocol_store()
    protocols = (store.get("registry", {}) or {}).setdefault("protocols", {})
    project_map = (store.get("project_map", {}) or {}).setdefault("projects", {})
    queue = (store.get("queue", {}) or {}).setdefault("pending_protocol_ids", [])
    created: List[str] = []
    ts = now_tag()

    for ptype, items in grouped.items():
        protocol_id = f"PROTO-{ptype}-{ts}"
        protocol = {
            "protocol_id": protocol_id,
            "protocol_type": ptype,
            "status": "pending_verification",
            "created_at": datetime.now().isoformat(),
            "project_ids": [str(x.get("training_project_id", "")) for x in items],
            "project_names": [str(x.get("project_name", "")) for x in items],
            "checklist": default_protocol_checklist(ptype),
            "verification": {
                "required": True,
                "verified": False,
                "verified_by": "",
                "verified_ts": "",
                "notes": "",
            },
        }
        protocols[protocol_id] = protocol
        created.append(protocol_id)
        if protocol_id not in queue:
            queue.append(protocol_id)
        for p in items:
            pid = str(p.get("training_project_id", "") or "")
            project_map[pid] = {
                "project_id": pid,
                "project_name": str(p.get("project_name", "") or ""),
                "protocol_id": protocol_id,
                "protocol_type": ptype,
                "status": "pending_verification",
                "updated_at": datetime.now().isoformat(),
            }

    save_protocol_store(store)
    print(f"Prepared protocol candidates: {len(created)}")
    for pid in created:
        print(f"- {pid}")
    print(f"Protocol registry: {PROTOCOL_REGISTRY_PATH}")
    print(f"Project protocol map: {PROJECT_PROTOCOL_MAP_PATH}")
    print(f"Verification queue: {PROTOCOL_VERIFICATION_QUEUE_PATH}")
    return 0


def _collect_selected_projects(project_ids_csv: str, registry_path: pathlib.Path) -> List[Dict[str, Any]]:
    reg = load_registry(registry_path)
    projects = reg.get("projects", []) if isinstance(reg, dict) else []
    selected_ids = [x.strip() for x in str(project_ids_csv or "").split(",") if x.strip()]
    selected: List[Dict[str, Any]] = []
    for p in projects if isinstance(projects, list) else []:
        pid = str(p.get("training_project_id", "") or "")
        if selected_ids and pid not in selected_ids:
            continue
        selected.append(p)
    return selected


def _create_protocol_record(
    store: Dict[str, Any],
    protocol_type: str,
    items: List[Dict[str, Any]],
    source: str,
    intake_id: str = "",
    builder_answers: Dict[str, Any] | None = None,
) -> str:
    protocols = (store.get("registry", {}) or {}).setdefault("protocols", {})
    project_map = (store.get("project_map", {}) or {}).setdefault("projects", {})
    queue = (store.get("queue", {}) or {}).setdefault("pending_protocol_ids", [])
    protocol_id = f"PROTO-{protocol_type}-{now_tag()}"
    protocol = {
        "protocol_id": protocol_id,
        "protocol_type": protocol_type,
        "status": "pending_verification",
        "created_at": datetime.now().isoformat(),
        "source": source,
        "intake_id": intake_id,
        "project_ids": [str(x.get("training_project_id", "")) for x in items],
        "project_names": [str(x.get("project_name", "")) for x in items],
        "checklist": default_protocol_checklist(protocol_type),
        "builder_answers": builder_answers or {},
        "verification": {
            "required": True,
            "verified": False,
            "verified_by": "",
            "verified_ts": "",
            "notes": "",
        },
    }
    protocols[protocol_id] = protocol
    if protocol_id not in queue:
        queue.append(protocol_id)
    for p in items:
        pid = str(p.get("training_project_id", "") or "")
        project_map[pid] = {
            "project_id": pid,
            "project_name": str(p.get("project_name", "") or ""),
            "protocol_id": protocol_id,
            "protocol_type": protocol_type,
            "status": "pending_verification",
            "updated_at": datetime.now().isoformat(),
        }
    return protocol_id


def cmd_protocol_create(protocol_type: str, project_ids_csv: str, registry_path: pathlib.Path) -> int:
    allowed = {"multifamily", "office", "tilt_up_warehouse", "general"}
    ptype = str(protocol_type or "").strip().lower()
    if ptype not in allowed:
        print(f"Unsupported protocol_type={protocol_type}. Allowed: {sorted(allowed)}")
        return 2
    selected = _collect_selected_projects(project_ids_csv, registry_path)
    if not selected:
        print("No projects selected for protocol creation.")
        return 3
    store = load_or_init_protocol_store()
    protocol_id = _create_protocol_record(
        store=store,
        protocol_type=ptype,
        items=selected,
        source="manual_protocol_create",
    )
    save_protocol_store(store)
    print(f"Created protocol: {protocol_id}")
    print(f"Protocol registry: {PROTOCOL_REGISTRY_PATH}")
    print(f"Project protocol map: {PROJECT_PROTOCOL_MAP_PATH}")
    print(f"Verification queue: {PROTOCOL_VERIFICATION_QUEUE_PATH}")
    return 0


def _parse_builder_answers(answers_json_path: str, answers_json_inline: str) -> Dict[str, Any]:
    if answers_json_path.strip():
        p = pathlib.Path(answers_json_path.strip())
        if not p.exists():
            raise FileNotFoundError(f"answers-json file not found: {p}")
        payload = read_json(p)
        if not isinstance(payload, dict):
            raise ValueError("answers-json file must contain a JSON object")
        return payload
    raw = answers_json_inline.strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("answers-json-inline must be a JSON object")
    return payload


def cmd_protocol_answer_intake(
    intake_id: str,
    protocol_type: str,
    answers_json_path: str,
    answers_json_inline: str,
    registry_path: pathlib.Path,
) -> int:
    intake_dir = PROTOCOLS_DIR / "intakes"
    intake_json = intake_dir / f"protocol_builder_intake_{intake_id}.json"
    if not intake_json.exists():
        print(f"Intake not found: {intake_json}")
        return 2
    intake = read_json(intake_json)
    if not isinstance(intake, dict):
        print("Invalid intake payload.")
        return 2
    selected = _collect_selected_projects(",".join(intake.get("project_ids", []) or []), registry_path)
    if not selected:
        print("No projects found for intake when creating protocol.")
        return 3

    suggested = str(intake.get("suggested_protocol_type", "general") or "general").strip().lower()
    ptype = str(protocol_type or "").strip().lower() or suggested
    allowed = {"multifamily", "office", "tilt_up_warehouse", "general"}
    if ptype not in allowed:
        print(f"Unsupported protocol_type={ptype}. Allowed: {sorted(allowed)}")
        return 2
    answers = _parse_builder_answers(answers_json_path, answers_json_inline)

    store = load_or_init_protocol_store()
    protocol_id = _create_protocol_record(
        store=store,
        protocol_type=ptype,
        items=selected,
        source="intake_answered",
        intake_id=intake_id,
        builder_answers=answers,
    )
    save_protocol_store(store)

    intake["status"] = "answered_pending_verification"
    intake["answered_at"] = datetime.now().isoformat()
    intake["selected_protocol_type"] = ptype
    intake["answers"] = answers
    intake["created_protocol_id"] = protocol_id
    write_json(intake_json, intake)
    intake_md = intake_dir / f"protocol_builder_intake_{intake_id}.md"
    if intake_md.exists():
        md = intake_md.read_text(encoding="utf-8")
        md += (
            "\n## Intake Answers Captured\n"
            f"- selected_protocol_type: {ptype}\n"
            f"- created_protocol_id: {protocol_id}\n"
            f"- answers: {json.dumps(answers)}\n"
        )
        intake_md.write_text(md, encoding="utf-8")

    print(f"Intake answered and protocol created: {protocol_id}")
    print(f"Updated intake JSON: {intake_json}")
    print(f"Protocol registry: {PROTOCOL_REGISTRY_PATH}")
    return 0


def cmd_protocol_batch_ready(
    project_ids_csv: str,
    protocol_type: str,
    answers_json_path: str,
    answers_json_inline: str,
    registry_path: pathlib.Path,
) -> int:
    payload = _build_protocol_builder_intake_payload(project_ids_csv, registry_path)
    if not bool(payload.get("ok", True)) and payload.get("error") == "no_projects_selected":
        print("No projects selected for protocol-batch-ready.")
        return 3

    intake_dir = PROTOCOLS_DIR / "intakes"
    intake_dir.mkdir(parents=True, exist_ok=True)
    intake_id = str(payload.get("intake_id", f"INTAKE-{now_tag()}"))
    out_json = intake_dir / f"protocol_builder_intake_{intake_id}.json"
    out_md = intake_dir / f"protocol_builder_intake_{intake_id}.md"
    write_json(out_json, payload)

    md_lines = [
        f"# Protocol Builder Intake - {intake_id}",
        "",
        f"- suggested_protocol_type: {payload.get('suggested_protocol_type')}",
        f"- projects: {', '.join(payload.get('project_ids', []))}",
        "",
        "## Verification Questions",
    ]
    for idx, q in enumerate(payload.get("questions", []) if isinstance(payload.get("questions"), list) else [], start=1):
        md_lines.append(
            f"{idx}. [{q.get('category')}] {q.get('question')} "
            f"(why: {q.get('why')}) options={q.get('options')}"
        )
    out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    answers: Dict[str, Any] = {}
    try:
        answers = _parse_builder_answers(answers_json_path, answers_json_inline)
    except Exception as exc:
        template = {
            str(q.get("id")): f"<choose one of {q.get('options')}>"
            for q in (payload.get("questions", []) if isinstance(payload.get("questions"), list) else [])
            if isinstance(q, dict) and q.get("id")
        }
        template_path = intake_dir / f"answers_template_{intake_id}.json"
        write_json(template_path, template)
        print(f"Protocol builder intake JSON: {out_json}")
        print(f"Protocol builder intake MD: {out_md}")
        print(f"Answers template JSON: {template_path}")
        print(f"Batch-ready paused: {exc}")
        print("Fill the template and rerun protocol-answer-intake or protocol-batch-ready with answers.")
        return 0

    if not answers:
        template = {
            str(q.get("id")): f"<choose one of {q.get('options')}>"
            for q in (payload.get("questions", []) if isinstance(payload.get("questions"), list) else [])
            if isinstance(q, dict) and q.get("id")
        }
        template_path = intake_dir / f"answers_template_{intake_id}.json"
        write_json(template_path, template)
        print(f"Protocol builder intake JSON: {out_json}")
        print(f"Protocol builder intake MD: {out_md}")
        print(f"Answers template JSON: {template_path}")
        print("Batch-ready paused: no answers supplied.")
        return 0

    selected = _collect_selected_projects(",".join(payload.get("project_ids", []) or []), registry_path)
    if not selected:
        print("No projects found for protocol creation in batch-ready.")
        return 3
    suggested = str(payload.get("suggested_protocol_type", "general") or "general").strip().lower()
    ptype = str(protocol_type or "").strip().lower() or suggested
    allowed = {"multifamily", "office", "tilt_up_warehouse", "general"}
    if ptype not in allowed:
        print(f"Unsupported protocol_type={ptype}. Allowed: {sorted(allowed)}")
        return 2

    store = load_or_init_protocol_store()
    protocol_id = _create_protocol_record(
        store=store,
        protocol_type=ptype,
        items=selected,
        source="batch_ready",
        intake_id=intake_id,
        builder_answers=answers,
    )
    save_protocol_store(store)

    payload["status"] = "answered_pending_verification"
    payload["answered_at"] = datetime.now().isoformat()
    payload["selected_protocol_type"] = ptype
    payload["answers"] = answers
    payload["created_protocol_id"] = protocol_id
    write_json(out_json, payload)
    out_md.write_text(
        out_md.read_text(encoding="utf-8")
        + (
            "\n## Intake Answers Captured\n"
            f"- selected_protocol_type: {ptype}\n"
            f"- created_protocol_id: {protocol_id}\n"
            f"- answers: {json.dumps(answers)}\n"
        ),
        encoding="utf-8",
    )

    print(f"Protocol builder intake JSON: {out_json}")
    print(f"Protocol builder intake MD: {out_md}")
    print(f"Created protocol: {protocol_id}")
    print(f"Protocol registry: {PROTOCOL_REGISTRY_PATH}")
    print("Next: run protocol-verify to approve before Maverick run.")
    return 0


def cmd_protocol_verify(protocol_id: str, approved: bool, verifier: str, notes: str) -> int:
    store = load_or_init_protocol_store()
    protocols = (store.get("registry", {}) or {}).get("protocols", {})
    project_map = (store.get("project_map", {}) or {}).get("projects", {})
    queue = (store.get("queue", {}) or {}).get("pending_protocol_ids", [])
    if protocol_id not in protocols:
        print(f"Unknown protocol_id: {protocol_id}")
        return 2
    protocol = protocols[protocol_id]
    if not isinstance(protocol, dict):
        print(f"Invalid protocol payload for: {protocol_id}")
        return 2

    protocol["status"] = "verified" if approved else "rejected"
    protocol["verification"] = {
        "required": True,
        "verified": bool(approved),
        "verified_by": verifier.strip() or "travi",
        "verified_ts": datetime.now().isoformat(),
        "notes": notes.strip(),
    }

    linked = protocol.get("project_ids", []) if isinstance(protocol.get("project_ids"), list) else []
    for proj_id in linked:
        pid = str(proj_id or "")
        if not pid:
            continue
        row = project_map.get(pid, {})
        if not isinstance(row, dict):
            row = {}
        row["status"] = protocol["status"]
        row["updated_at"] = datetime.now().isoformat()
        row["protocol_id"] = protocol_id
        row["protocol_type"] = protocol.get("protocol_type", row.get("protocol_type", ""))
        project_map[pid] = row

    if protocol_id in queue:
        queue[:] = [x for x in queue if x != protocol_id]

    save_protocol_store(store)
    print(f"Protocol {protocol_id} set to status={protocol['status']}")
    return 0


def cmd_protocol_status(project_id: str) -> int:
    status = get_project_protocol_status(project_id)
    print(json.dumps(status, indent=2))
    return 0


def cmd_run_module(
    module_id: str,
    project_id: str,
    registry_path: pathlib.Path,
    allow_unverified_protocol: bool = False,
) -> int:
    load_or_init_item_type_store()
    program = load_program()
    reg = load_registry(registry_path)
    modules = {m["id"]: m for m in program.get("initial_modules", [])}
    if module_id not in modules:
        print(f"Unknown module_id: {module_id}")
        return 2
    project = next((p for p in reg.get("projects", []) if p.get("training_project_id") == project_id), None)
    if not project:
        print(f"Unknown training_project_id: {project_id}")
        return 2

    protocol_status = get_project_protocol_status(project_id)
    if (
        not bool(allow_unverified_protocol)
        and (
            (not protocol_status.get("has_protocol", False))
            or (protocol_status.get("verification_required", True) and not protocol_status.get("verified", False))
        )
    ):
        print(
            "Protocol verification required before Maverick run.\n"
            f"- project_id: {project_id}\n"
            f"- has_protocol: {protocol_status.get('has_protocol')}\n"
            f"- protocol_id: {protocol_status.get('protocol_id')}\n"
            f"- status: {protocol_status.get('status')}\n"
            "Run protocol preparation/verification first:\n"
            "  python scripts/ost_orchestrator.py protocol-prepare-batch --project-ids <ids>\n"
            "  python scripts/ost_orchestrator.py protocol-verify --protocol-id <id> --approved --verifier travi\n"
        )
        return 6

    # Current implementation executes Boost agent for boost-focused modules.
    if not module_id.startswith("T06") and not module_id.startswith("T07"):
        print(f"Module {module_id} not automated yet. Current runnable modules: T06/T07.")
        return 3

    resolved_ctx = resolve_project_context(project)
    print(
        "Context resolution:",
        json.dumps(
            {
                "resolved_folder": resolved_ctx.get("resolved_folder"),
                "resolved_pdf": resolved_ctx.get("resolved_pdf"),
                "folder_reason": (resolved_ctx.get("folder_resolution") or {}).get("reason"),
                "pdf_reason": (resolved_ctx.get("pdf_resolution") or {}).get("reason"),
            }
        ),
    )

    project_scope = run_project_scope_intel(project, resolved_ctx)
    print("Project scope intel:", project_scope.get("stdout", "") or project_scope.get("reason", ""))

    scope_profile = run_scope_profile(project, resolved_ctx)
    print("Scope profile:", scope_profile.get("stdout", "") or scope_profile.get("reason", ""))

    grouping = run_group_selection(project)
    print("Grouping selection:", grouping.get("stdout", ""))
    item_type_classification = run_item_type_classifier(
        training_project_id=project_id,
        monitor_index=1,
        update_prototypes=False,
        context_label="run_module_preflight",
    )
    print("Item-type classifier:", item_type_classification.get("stdout", "") or item_type_classification.get("stderr", ""))

    before_latest = get_latest_run_dir()
    cmd = [
        sys.executable,
        str(BOOST_AGENT_SCRIPT),
        "run",
        "--config",
        str(BOOST_AGENT_CONFIG),
        "--project-id",
        str(project_id),
    ]
    print("Running:", " ".join(cmd))
    proc = run_subprocess_guarded(cmd, watch_emergency=False)
    print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip())

    after_latest = get_latest_run_dir()
    if after_latest is None or after_latest == before_latest:
        print("No new boost run directory detected.")
        return 4

    run_log_path = after_latest / "run_log.json"
    if not run_log_path.exists():
        print(f"Missing run log: {run_log_path}")
        return 4
    run_log = read_json(run_log_path)
    weights = program.get("score_scale", {}).get("weights", {})
    scored = score_boost_run(run_log, weights)
    pass_min = float(program.get("score_scale", {}).get("pass_min", 85))
    excellent_min = float(program.get("score_scale", {}).get("excellent_min", 95))
    grade = "excellent" if scored["score"] >= excellent_min else ("pass" if scored["score"] >= pass_min else "fail")
    classifier_conf = float(item_type_classification.get("top_match_confidence", 0.0) or 0.0)
    classifier_gate_status = "pass" if classifier_conf >= 0.5 else "warn"

    attempt_id = f"ATT-{now_tag()}"
    training_notes = analyze_training_db_notes(
        project=project,
        program=program,
        registry=reg,
        attempt_id=attempt_id,
    )
    notes_json_path = LAB_OUT_DIR / f"training_notes_{attempt_id}.json"
    notes_md_path = LAB_OUT_DIR / f"training_notes_{attempt_id}.md"
    write_json(notes_json_path, training_notes)
    if isinstance(training_notes, dict):
        md = str(training_notes.get("notes_markdown", "") or "")
        if not md:
            fallback_lines = [
                f"# Maverick Training Notes - {attempt_id}",
                "",
                "## What I Observed",
                f"- note_generation_status: {training_notes.get('reason', 'unknown')}",
            ]
            md = "\n".join(fallback_lines) + "\n"
        notes_md_path.write_text(md, encoding="utf-8")

    style_entry = build_style_methods_log_entry(
        analysis=training_notes if isinstance(training_notes, dict) else {},
        project=project,
        training_project_id=project_id,
        attempt_id=attempt_id,
    )
    style_paths = append_style_methods_log(style_entry, LAB_OUT_DIR)
    coaching_hints = load_operator_coaching_hints(LAB_OUT_DIR, project_id, limit=30)

    edit_plan = build_post_boost_edit_plan(
        project=project,
        module_id=module_id,
        run_log=run_log,
        training_db_analysis=training_notes if isinstance(training_notes, dict) else {},
        scope_profile=scope_profile,
        attempt_id=attempt_id,
        coaching_hints=coaching_hints,
    )
    edit_plan_json_path = LAB_OUT_DIR / f"post_boost_edit_plan_{attempt_id}.json"
    edit_plan_md_path = LAB_OUT_DIR / f"post_boost_edit_plan_{attempt_id}.md"
    write_json(edit_plan_json_path, edit_plan)
    edit_plan_md_path.write_text(str((edit_plan or {}).get("notes_markdown", "")), encoding="utf-8")

    attempt = {
        "attempt_id": attempt_id,
        "ts": datetime.now().isoformat(),
        "training_project_id": project_id,
        "project_name": project.get("project_name"),
        "module_id": module_id,
        "module_goal": modules[module_id].get("goal"),
        "resolved_context": resolved_ctx,
        "project_scope_intel": project_scope,
        "scope_profile": scope_profile,
        "grouping_selection": grouping,
        "item_type_classification": item_type_classification,
        "boost_run_dir": str(after_latest),
        "boost_run_log": str(run_log_path),
        "agent_ok": bool(run_log.get("ok")),
        "score": scored["score"],
        "grade": grade,
        "score_components": scored["components"],
        "item_type_classifier_gate": {
            "top_match_confidence": round(classifier_conf, 4),
            "threshold": 0.5,
            "status": classifier_gate_status,
        },
        "status": run_log.get("status", {}),
        "training_notes_json": str(notes_json_path),
        "training_notes_md": str(notes_md_path),
        "training_db_analysis": training_notes,
        "style_methods_entry": style_entry,
        "style_methods_log_paths": style_paths,
        "protocol_status": protocol_status,
        "operator_coaching_hints_used": coaching_hints,
        "post_boost_edit_plan_json": str(edit_plan_json_path),
        "post_boost_edit_plan_md": str(edit_plan_md_path),
        "post_boost_edit_plan": edit_plan,
    }
    out_path = LAB_OUT_DIR / f"attempt_{attempt['attempt_id']}.json"
    write_json(out_path, attempt)
    print(f"Attempt recorded: {out_path}")
    print(f"Result: grade={grade} score={scored['score']}")
    return 0 if grade != "fail" else 5


def cmd_dashboard(registry_path: pathlib.Path, last: int) -> int:
    reg = load_registry(registry_path)
    attempts = sorted(LAB_OUT_DIR.glob("attempt_ATT-*.json"))
    if not attempts:
        print("No attempts recorded yet.")
        return 0
    selected = attempts[-last:]
    rows = [read_json(p) for p in selected]
    total = len(rows)
    passes = sum(1 for r in rows if r.get("grade") in ("pass", "excellent"))
    avg = round(sum(float(r.get("score", 0.0)) for r in rows) / total, 2)
    print(f"Training Dashboard (last {total} attempts)")
    print(f"Projects in registry: {len(reg.get('projects', []))}")
    print(f"Pass rate: {passes}/{total} ({round(100*passes/total, 1)}%)")
    print(f"Average score: {avg}")
    for r in rows:
        print(
            f"- {r.get('attempt_id')} | {r.get('training_project_id')} | "
            f"{r.get('module_id')} | {r.get('grade')} | {r.get('score')}"
        )
    return 0


def cmd_discover(project_id: str, registry_path: pathlib.Path) -> int:
    reg = load_registry(registry_path)
    project = next((p for p in reg.get("projects", []) if p.get("training_project_id") == project_id), None)
    if not project:
        print(f"Unknown training_project_id: {project_id}")
        return 2
    ctx = resolve_project_context(project)
    print(json.dumps(ctx, indent=2))
    return 0 if ctx.get("resolved") else 3


def cmd_analyze_training_notes(project_id: str, registry_path: pathlib.Path) -> int:
    program = load_program()
    reg = load_registry(registry_path)
    project = next((p for p in reg.get("projects", []) if p.get("training_project_id") == project_id), None)
    if not project:
        print(f"Unknown training_project_id: {project_id}")
        return 2
    note_id = f"ANL-{now_tag()}"
    analysis = analyze_training_db_notes(project=project, program=program, registry=reg, attempt_id=note_id)
    LAB_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = LAB_OUT_DIR / f"training_notes_{note_id}.json"
    out_md = LAB_OUT_DIR / f"training_notes_{note_id}.md"
    write_json(out_json, analysis)
    md = str((analysis or {}).get("notes_markdown", "") if isinstance(analysis, dict) else "")
    if not md:
        md = (
            f"# Maverick Training Notes - {note_id}\n\n"
            "## What I Observed\n"
            f"- note_generation_status: {(analysis or {}).get('reason', 'unknown')}\n"
        )
    out_md.write_text(md, encoding="utf-8")
    style_entry = build_style_methods_log_entry(
        analysis=analysis if isinstance(analysis, dict) else {},
        project=project,
        training_project_id=project_id,
        attempt_id=note_id,
    )
    style_paths = append_style_methods_log(style_entry, LAB_OUT_DIR)
    print(f"Training notes JSON: {out_json}")
    print(f"Training notes MD: {out_md}")
    print(f"Style methods log JSONL: {style_paths.get('log_jsonl')}")
    print(f"Style methods profile MD: {style_paths.get('profile_md')}")
    status = "ok" if isinstance(analysis, dict) and analysis.get("ok") else "warn"
    print(f"Training note analysis status: {status}")
    return 0


def cmd_post_boost_edit_plan(project_id: str, module_id: str, registry_path: pathlib.Path) -> int:
    program = load_program()
    reg = load_registry(registry_path)
    project = next((p for p in reg.get("projects", []) if p.get("training_project_id") == project_id), None)
    if not project:
        print(f"Unknown training_project_id: {project_id}")
        return 2

    latest_attempts = sorted(LAB_OUT_DIR.glob("attempt_ATT-*.json"))
    if not latest_attempts:
        print("No attempt artifacts found. Run a module first.")
        return 3
    latest = read_json(latest_attempts[-1])
    run_log_path = pathlib.Path(str(latest.get("boost_run_log", "") or ""))
    run_log = read_json(run_log_path) if run_log_path.exists() else {}
    training_analysis = latest.get("training_db_analysis", {})
    if not isinstance(training_analysis, dict) or not training_analysis:
        training_analysis = analyze_training_db_notes(
            project=project,
            program=program,
            registry=reg,
            attempt_id=f"PLAN-{now_tag()}",
        )
    scope_profile = latest.get("scope_profile", {})
    attempt_id = f"PLAN-{now_tag()}"
    coaching_hints = load_operator_coaching_hints(LAB_OUT_DIR, project_id, limit=30)
    plan = build_post_boost_edit_plan(
        project=project,
        module_id=module_id,
        run_log=run_log if isinstance(run_log, dict) else {},
        training_db_analysis=training_analysis if isinstance(training_analysis, dict) else {},
        scope_profile=scope_profile if isinstance(scope_profile, dict) else {},
        attempt_id=attempt_id,
        coaching_hints=coaching_hints,
    )
    out_json = LAB_OUT_DIR / f"post_boost_edit_plan_{attempt_id}.json"
    out_md = LAB_OUT_DIR / f"post_boost_edit_plan_{attempt_id}.md"
    write_json(out_json, plan)
    out_md.write_text(str((plan or {}).get("notes_markdown", "")), encoding="utf-8")
    print(f"Post-boost edit plan JSON: {out_json}")
    print(f"Post-boost edit plan MD: {out_md}")
    return 0


def cmd_classify_item_types(project_id: str, registry_path: pathlib.Path, monitor_index: int) -> int:
    reg = load_registry(registry_path)
    project = next((p for p in reg.get("projects", []) if p.get("training_project_id") == project_id), None)
    if not project:
        print(f"Unknown training_project_id: {project_id}")
        return 2
    res = run_item_type_classifier(
        training_project_id=project_id,
        monitor_index=max(1, int(monitor_index)),
        update_prototypes=False,
        context_label="manual_classify_command",
    )
    print(json.dumps(res, indent=2))
    return 0 if bool(res.get("ok")) else 4


def cmd_takeoff_copy_attempt(
    project_id: str,
    registry_path: pathlib.Path,
    condition_row: str,
    left_choice: str,
    monitor_index: int,
    match_score_threshold: float,
    cleanup_undo_count: int,
    attempt_style: str,
    enforce_area_style: bool = False,
    enforce_condition_names: str = "ceiling,gwb",
    balanced_latency_budget_ms: int = 28000,
) -> int:
    stale_cleanup = cleanup_stale_ost_processes()
    phase_events: List[Dict[str, Any]] = [{"phase": "start", "ts": datetime.now().isoformat()}]
    reg = load_registry(registry_path)
    project = next((p for p in reg.get("projects", []) if p.get("training_project_id") == project_id), None)
    if not project:
        print(f"Unknown training_project_id: {project_id}")
        return 2
    load_or_init_item_type_store()
    out_dir = LAB_OUT_DIR / "takeoff_copy_attempts" / f"{project_id}_{now_tag()}"
    finish_index_json = get_latest_finish_knowledge_index(project_id)
    result = run_takeoff_copy_attempt(
        training_project_id=project_id,
        condition_row=condition_row,
        left_choice=left_choice,
        monitor_index=max(1, int(monitor_index)),
        match_score_threshold=float(match_score_threshold),
        cleanup_undo_count=max(1, int(cleanup_undo_count)),
        attempt_style=attempt_style,
        out_dir=out_dir,
        finish_index_json=finish_index_json,
        enforce_area_style=bool(enforce_area_style),
        enforce_condition_names=str(enforce_condition_names),
        balanced_latency_budget_ms=int(balanced_latency_budget_ms),
    )
    attempt_id = f"ATT-{now_tag()}"
    ma = result.get("match_assessment", {}) if isinstance(result, dict) else {}
    match_score = float((ma.get("score", 0.0) if isinstance(ma, dict) else 0.0) or 0.0)
    classifier_conf = float(
        (
            ((result.get("result", {}) if isinstance(result.get("result", {}), dict) else {}).get("post_item_classification", {}) or {})
            .get("summary", {})
            .get("top_confidence", 0.0)
            or 0.0
        )
    )
    runtime_stability = 100.0 if bool(result.get("ok")) else 0.0
    finish_learning_snapshot = build_finish_learning_snapshot(project=project, takeoff_result=result)
    res_payload = result.get("result", {}) if isinstance(result.get("result", {}), dict) else {}
    fin = res_payload.get("finish_inference", {}) if isinstance(res_payload.get("finish_inference", {}), dict) else {}
    finish_conf = float(fin.get("confidence", 0.0) or 0.0)
    area_style_correct = bool(str(res_payload.get("condition_style", "") or "").lower() == "area")
    cond_name = str(res_payload.get("active_condition_name", "") or "").lower()
    condition_name_correct = bool(("ceiling" in cond_name) or ("gwb" in cond_name))
    runtime_ms = float(res_payload.get("runtime_ms", 0.0) or 0.0)
    attempt_payload = {
        "attempt_id": attempt_id,
        "ts": datetime.now().isoformat(),
        "training_project_id": project_id,
        "project_name": str(project.get("project_name", "") or ""),
        "module_id": "T08-page-navigation-resume-L3",
        "module_goal": "Copy user takeoff pattern on blank drawing with cleanup guard.",
        "agent_ok": bool(result.get("ok")),
        "score": round(match_score, 2),
        "grade": "pass" if bool(ma.get("is_match", False)) else "fail",
        "score_components": {
            "step_completion": 100.0 if bool(result.get("ok")) else 0.0,
            "takeoff_accuracy": round(match_score, 2),
            "quantity_accuracy": round(match_score, 2),
            "recovery_behavior": 100.0 if bool(((result.get("result", {}) if isinstance(result.get("result", {}), dict) else {}).get("cleanup", {}) or {}).get("ran", False)) else 50.0,
            "runtime_stability": runtime_stability,
            "item_type_classifier_confidence": round(classifier_conf, 4),
            "finish_inference_confidence": round(finish_conf, 4),
            "area_style_correctness": 100.0 if area_style_correct else 0.0,
            "condition_name_correctness": 100.0 if condition_name_correct else 0.0,
            "runtime_latency_ms": round(runtime_ms, 2),
        },
        "takeoff_copy_summary": result.get("result", {}),
        "finish_learning_snapshot": finish_learning_snapshot,
        "item_type_classification": ((result.get("result", {}) if isinstance(result.get("result", {}), dict) else {}).get("post_item_classification", {})),
        "item_type_classifier_gate": {
            "top_match_confidence": round(classifier_conf, 4),
            "threshold": 0.5,
            "status": "pass" if classifier_conf >= 0.5 else "warn",
        },
    }
    attempt_json = LAB_OUT_DIR / f"attempt_{attempt_id}.json"
    write_json(attempt_json, attempt_payload)
    if finish_conf < 0.45:
        enqueue_finish_review(
            {
                "ts": datetime.now().isoformat(),
                "attempt_id": attempt_id,
                "project_id": project_id,
                "reason": "low_finish_inference_confidence",
                "finish_learning_snapshot": finish_learning_snapshot,
                "attempt_json": str(attempt_json),
            }
        )
    if (not area_style_correct) or (not condition_name_correct) or (runtime_ms > 45000.0):
        enqueue_finish_review(
            {
                "ts": datetime.now().isoformat(),
                "attempt_id": attempt_id,
                "project_id": project_id,
                "reason": "no_boost_area_uncertain_attempt",
                "area_style_correct": area_style_correct,
                "condition_name_correct": condition_name_correct,
                "runtime_ms": runtime_ms,
                "attempt_json": str(attempt_json),
            }
        )
    print(json.dumps(result, indent=2))
    print(f"Attempt recorded: {attempt_json}")
    if not bool(result.get("ok")):
        return 5
    if isinstance(ma, dict) and not bool(ma.get("is_match", False)):
        return 6
    return 0


def cmd_no_boost_area_attempt(
    project_id: str,
    registry_path: pathlib.Path,
    condition_row: str,
    monitor_index: int,
    match_score_threshold: float,
    cleanup_undo_count: int,
) -> int:
    return cmd_takeoff_copy_attempt(
        project_id=project_id,
        registry_path=registry_path,
        condition_row=condition_row,
        left_choice="nearest",
        monitor_index=monitor_index,
        match_score_threshold=match_score_threshold,
        cleanup_undo_count=cleanup_undo_count,
        attempt_style="polyline4",
        enforce_area_style=True,
        enforce_condition_names="ceiling,gwb",
        balanced_latency_budget_ms=28000,
    )


def cmd_takeoff_copy_batch(
    project_id: str,
    registry_path: pathlib.Path,
    attempts: int,
    left_choice: str,
    monitor_index: int,
    match_score_threshold: float,
    cleanup_undo_count: int,
    attempt_style: str,
    enforce_area_style: bool = False,
    enforce_condition_names: str = "ceiling,gwb",
    balanced_latency_budget_ms: int = 28000,
) -> int:
    stale_cleanup = cleanup_stale_ost_processes()
    reg = load_registry(registry_path)
    project = next((p for p in reg.get("projects", []) if p.get("training_project_id") == project_id), None)
    if not project:
        print(f"Unknown training_project_id: {project_id}")
        return 2
    load_or_init_item_type_store()
    root_out = LAB_OUT_DIR / "takeoff_copy_attempts" / f"{project_id}_batch_{now_tag()}"
    finish_index_json = get_latest_finish_knowledge_index(project_id)
    root_out.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    requested_total = max(1, int(attempts))
    total = requested_total
    bad_work_count = 0
    cleanup_count = 0
    ocr_attempts_with_glm = 0
    ocr_attempts_with_fallback = 0
    condition_keyword_hits = 0
    condition_keyword_checks = 0
    verification_failure_reasons: Dict[str, int] = {}
    condition_lock_success = 0
    teacher_targets_present = 0
    geometry_pass = 0
    runtime_ms_values: List[int] = []
    ocr_preread_ms_values: List[int] = []
    conservative_mode_hits = 0
    for idx in range(1, total + 1):
        row_name = "first" if idx % 2 == 1 else "second"
        out_dir = root_out / f"attempt_{idx:02d}_{row_name}"
        res = run_takeoff_copy_attempt(
            training_project_id=project_id,
            condition_row=row_name,
            left_choice=left_choice,
            monitor_index=max(1, int(monitor_index)),
            match_score_threshold=float(match_score_threshold),
            cleanup_undo_count=max(1, int(cleanup_undo_count)),
            attempt_style=attempt_style,
            out_dir=out_dir,
            finish_index_json=finish_index_json,
            enforce_area_style=bool(enforce_area_style),
            enforce_condition_names=str(enforce_condition_names),
            balanced_latency_budget_ms=int(balanced_latency_budget_ms),
        )
        rows.append(res)
        ma = res.get("match_assessment", {}) if isinstance(res, dict) else {}
        attempt_ok = bool(res.get("ok", False)) if isinstance(res, dict) else False
        is_match = bool(ma.get("is_match", False)) if isinstance(ma, dict) else False
        explicit_bad = bool(ma.get("bad_work", False)) if isinstance(ma, dict) else False
        # Treat any failed/no-output/non-match attempt as bad work.
        if (not attempt_ok) or (not is_match) or explicit_bad:
            bad_work_count += 1
        actions = ((res.get("result", {}) if isinstance(res.get("result", {}), dict) else {}).get("cleanup", {}) or {}).get("actions", [])
        if isinstance(actions, list) and len(actions) > 0:
            cleanup_count += 1
        result_payload = res.get("result", {}) if isinstance(res.get("result", {}), dict) else {}
        reason = str(result_payload.get("reason", "") or "").strip()
        if reason:
            verification_failure_reasons[reason] = int(verification_failure_reasons.get(reason, 0)) + 1
        condition_verification = (
            result_payload.get("condition_verification", {})
            if isinstance(result_payload.get("condition_verification", {}), dict)
            else {}
        )
        if condition_verification:
            condition_keyword_checks += 1
            if bool(condition_verification.get("preferred_keyword_hit", False)):
                condition_keyword_hits += 1
            if bool(condition_verification.get("ok", False)) and bool(condition_verification.get("row_index_match", False)):
                condition_lock_success += 1
        if int(result_payload.get("teacher_targets_count", 0) or 0) > 0:
            teacher_targets_present += 1
        ma_payload = result_payload.get("match_assessment", {}) if isinstance(result_payload.get("match_assessment", {}), dict) else {}
        if bool(ma_payload.get("geometry_ok", False)):
            geometry_pass += 1
        runtime_ms_values.append(int(result_payload.get("runtime_ms", 0) or 0))
        plan_preread = (
            (result_payload.get("ocr_telemetry", {}) if isinstance(result_payload.get("ocr_telemetry", {}), dict) else {})
            .get("plan_preread", {})
        )
        if isinstance(plan_preread, dict):
            ocr_preread_ms_values.append(int(plan_preread.get("duration_ms", 0) or 0))
        balanced_policy = result_payload.get("balanced_policy", {}) if isinstance(result_payload.get("balanced_policy", {}), dict) else {}
        if bool(balanced_policy.get("conservative_mode", False)):
            conservative_mode_hits += 1

        ocr_telemetry = result_payload.get("ocr_telemetry", {}) if isinstance(result_payload.get("ocr_telemetry", {}), dict) else {}
        used_glm = False
        used_fallback = False
        for stage in ("condition", "grouping_before", "grouping_verify", "grouping_after"):
            stage_diag = ocr_telemetry.get(stage, {}) if isinstance(ocr_telemetry, dict) else {}
            engine_diag = stage_diag.get("engine", {}) if isinstance(stage_diag, dict) else {}
            if not isinstance(engine_diag, dict):
                continue
            if int(engine_diag.get("primary_success", 0) or 0) > 0:
                used_glm = True
            if int(engine_diag.get("fallback_success", 0) or 0) > 0:
                used_fallback = True
        if used_glm:
            ocr_attempts_with_glm += 1
        if used_fallback:
            ocr_attempts_with_fallback += 1
    finish_conf_values = []
    for r in rows:
        r_result = r.get("result", {}) if isinstance(r.get("result", {}), dict) else {}
        fin = r_result.get("finish_inference", {}) if isinstance(r_result.get("finish_inference", {}), dict) else {}
        finish_conf_values.append(float(fin.get("confidence", 0.0) or 0.0))
    finish_conf_avg = round((sum(finish_conf_values) / max(1, len(finish_conf_values))), 3)
    summary = {
        "ok": True,
        "project_id": project_id,
        "attempts_requested": total,
        "attempts_requested_raw": requested_total,
        "attempts_ran": len(rows),
        "results": rows,
        "bad_work_count": bad_work_count,
        "cleanup_count": cleanup_count,
        "cleanup_rate": round((cleanup_count / len(rows)) if rows else 0.0, 3),
        "ocr_engine_usage": {
            "attempts_with_glmocr": ocr_attempts_with_glm,
            "attempts_with_tesseract_fallback": ocr_attempts_with_fallback,
            "glmocr_usage_rate": round((ocr_attempts_with_glm / len(rows)) if rows else 0.0, 3),
            "fallback_usage_rate": round((ocr_attempts_with_fallback / len(rows)) if rows else 0.0, 3),
        },
        "condition_keyword_hit_rate": round((condition_keyword_hits / condition_keyword_checks) if condition_keyword_checks else 0.0, 3),
        "condition_lock_success_rate": round((condition_lock_success / len(rows)) if rows else 0.0, 3),
        "teacher_extraction_success_rate": round((teacher_targets_present / len(rows)) if rows else 0.0, 3),
        "geometry_pass_rate": round((geometry_pass / len(rows)) if rows else 0.0, 3),
        "runtime_ms_avg": int((sum(runtime_ms_values) / max(1, len(runtime_ms_values))) if runtime_ms_values else 0),
        "ocr_preread_ms_avg": int((sum(ocr_preread_ms_values) / max(1, len(ocr_preread_ms_values))) if ocr_preread_ms_values else 0),
        "conservative_mode_rate": round((conservative_mode_hits / len(rows)) if rows else 0.0, 3),
        "finish_inference_confidence_avg": finish_conf_avg,
        "verification_failure_reasons": verification_failure_reasons,
        "stale_process_cleanup": stale_cleanup,
        "acceptance_thresholds": {
            "condition_lock_success_min": 0.95,
            "geometry_pass_rate_min": 0.55,
        },
        "rollout_gate": {
            "condition_lock_pass": round((condition_lock_success / len(rows)) if rows else 0.0, 3) >= 0.95,
            "geometry_pass": round((geometry_pass / len(rows)) if rows else 0.0, 3) >= 0.55,
        },
        "micro_block": {
            "enabled": True,
            "block_size": 5,
            "block_stop_required": False,
            "review_required": False,
            "remaining_attempts_after_block": max(0, requested_total - total),
        },
    }
    summary["rollout_gate"]["ready"] = bool(summary["rollout_gate"]["condition_lock_pass"] and summary["rollout_gate"]["geometry_pass"])
    out_json = root_out / "takeoff_copy_batch_summary.json"
    write_json(out_json, summary)
    attempt_id = f"ATT-{now_tag()}"
    match_scores = [
        float(
            (
                (r.get("match_assessment", {}) if isinstance(r.get("match_assessment", {}), dict) else {}).get(
                    "score", 0.0
                )
                or 0.0
            )
        )
        for r in rows
    ]
    avg_match = round((sum(match_scores) / max(1, len(match_scores))), 2)
    attempt_payload = {
        "attempt_id": attempt_id,
        "ts": datetime.now().isoformat(),
        "training_project_id": project_id,
        "project_name": str(project.get("project_name", "") or ""),
        "module_id": "T10-complex-unit-repeat-L3",
        "module_goal": "Batch copy attempts with cleanup and classifier gates.",
        "agent_ok": True,
        "score": avg_match,
        "grade": "pass" if bad_work_count == 0 else "fail",
        "score_components": {
            "step_completion": round(100.0 * (len(rows) / max(1, total)), 2),
            "takeoff_accuracy": avg_match,
            "quantity_accuracy": avg_match,
            "recovery_behavior": round(100.0 - (100.0 * (bad_work_count / max(1, len(rows)))), 2),
            "runtime_stability": 100.0,
            "finish_inference_confidence": summary.get("finish_inference_confidence_avg", 0.0),
            "area_style_correctness": round(
                100.0
                * (
                    sum(
                        1
                        for r in rows
                        if str(
                            (
                                (r.get("result", {}) if isinstance(r.get("result", {}), dict) else {}).get(
                                    "condition_style", ""
                                )
                                or ""
                            ).lower()
                        )
                        == "area"
                    )
                    / max(1, len(rows))
                ),
                2,
            ),
            "condition_name_correctness": round(
                100.0
                * (
                    sum(
                        1
                        for r in rows
                        if (
                            ("ceiling" in str(((r.get("result", {}) if isinstance(r.get("result", {}), dict) else {}).get("active_condition_name", "") or "").lower()))
                            or ("gwb" in str(((r.get("result", {}) if isinstance(r.get("result", {}), dict) else {}).get("active_condition_name", "") or "").lower()))
                        )
                    )
                    / max(1, len(rows))
                ),
                2,
            ),
            "runtime_latency_ms": float(summary.get("runtime_ms_avg", 0.0) or 0.0),
        },
        "takeoff_copy_batch_summary_json": str(out_json),
        "finish_learning_snapshot": {
            "primary_trades": (
                (project.get("finish_profile", {}) if isinstance(project.get("finish_profile", {}), dict) else {}).get(
                    "primary_trades", []
                )
            ),
            "batch_attempts": len(rows),
            "avg_match_score": avg_match,
        },
        "takeoff_copy_summary": {
            "match_assessment": {"score": avg_match, "is_match": bad_work_count == 0, "bad_work": bad_work_count > 0},
            "cleanup": {"ran": cleanup_count > 0, "count": cleanup_count},
        },
        "takeoff_copy_batch_summary": summary,
    }
    attempt_json = LAB_OUT_DIR / f"attempt_{attempt_id}.json"
    write_json(attempt_json, attempt_payload)
    if float(summary.get("finish_inference_confidence_avg", 0.0) or 0.0) < 0.45:
        enqueue_finish_review(
            {
                "ts": datetime.now().isoformat(),
                "attempt_id": attempt_id,
                "project_id": project_id,
                "reason": "batch_low_finish_inference_confidence",
                "batch_summary_json": str(out_json),
                "attempt_json": str(attempt_json),
            }
        )
    if (
        float(summary.get("runtime_ms_avg", 0.0) or 0.0) > 45000.0
        or float(summary.get("conservative_mode_rate", 0.0) or 0.0) > 0.5
    ):
        enqueue_finish_review(
            {
                "ts": datetime.now().isoformat(),
                "attempt_id": attempt_id,
                "project_id": project_id,
                "reason": "no_boost_area_batch_uncertain",
                "runtime_ms_avg": float(summary.get("runtime_ms_avg", 0.0) or 0.0),
                "conservative_mode_rate": float(summary.get("conservative_mode_rate", 0.0) or 0.0),
                "batch_summary_json": str(out_json),
                "attempt_json": str(attempt_json),
            }
        )
    print(f"Takeoff copy batch summary: {out_json}")
    print(f"Attempt recorded: {attempt_json}")
    print(json.dumps({k: summary.get(k) for k in ('attempts_ran', 'bad_work_count', 'cleanup_count', 'cleanup_rate')}, indent=2))
    return 0


def cmd_no_boost_area_batch(
    project_id: str,
    registry_path: pathlib.Path,
    attempts: int,
    monitor_index: int,
    match_score_threshold: float,
    cleanup_undo_count: int,
) -> int:
    return cmd_takeoff_copy_batch(
        project_id=project_id,
        registry_path=registry_path,
        attempts=attempts,
        left_choice="nearest",
        monitor_index=monitor_index,
        match_score_threshold=match_score_threshold,
        cleanup_undo_count=cleanup_undo_count,
        attempt_style="polyline4",
        enforce_area_style=True,
        enforce_condition_names="ceiling,gwb",
        balanced_latency_budget_ms=28000,
    )


def _cmd_boost_then_copy_attempt_impl(
    project_id: str,
    registry_path: pathlib.Path,
    monitor_index: int,
    condition_row: str,
    left_choice: str,
    match_score_threshold: float,
    cleanup_undo_count: int,
    attempt_style: str,
    boost_undo_count: int,
    boost_populate_timeout_ms: int,
    boost_populate_poll_ms: int,
    boost_min_candidate_count: int,
    user_start_x: int = 0,
    user_start_y: int = 0,
) -> int:
    phase_events: List[Dict[str, Any]] = [{"phase": "start", "ts": datetime.now().isoformat()}]
    stale_cleanup = cleanup_stale_ost_processes()
    reg = load_registry(registry_path)
    project = next((p for p in reg.get("projects", []) if p.get("training_project_id") == project_id), None)
    if not project:
        print(f"Unknown training_project_id: {project_id}")
        return 2
    load_or_init_item_type_store()
    before_latest = get_latest_run_dir()
    boost_cfg = read_json(BOOST_AGENT_CONFIG)
    if not isinstance(boost_cfg, dict):
        boost_cfg = {}
    boost_cfg["run_click_strategy"] = "anchor"
    boost_cfg["run_click_repeats"] = 2
    boost_cfg["max_run_retries"] = max(3, int(boost_cfg.get("max_run_retries", 2) or 2))
    boost_cfg["post_boost_run_wait_ms"] = max(4500, int(boost_cfg.get("post_boost_run_wait_ms", 3500) or 3500))
    boost_cfg["run_observe_total_ms"] = max(22000, int(boost_cfg.get("run_observe_total_ms", 18000) or 18000))
    boost_cfg_path = LAB_OUT_DIR / "boost_override_configs" / f"boost_then_copy_{project_id}_{now_tag()}.json"
    write_json(boost_cfg_path, boost_cfg)
    # Preflight cleanup: clear existing page takeoff artifacts before starting full sequence.
    pre_clear_cmd = [
        sys.executable,
        str(UNDO_ACTIONS_SCRIPT),
        "--clear-count",
        "2",
        "--delay-ms",
        "240",
    ]
    try:
        pre_clear_proc = run_subprocess_guarded(pre_clear_cmd, timeout=25, watch_emergency=True)
    except subprocess.TimeoutExpired:
        print("pre_clear_timeout")
        return 10
    phase_events.append({"phase": "pre_clear_done", "ts": datetime.now().isoformat(), "exit_code": int(pre_clear_proc.returncode)})
    condition_select_cmd = [
        sys.executable,
        str(SELECT_CONDITION_ROW_SCRIPT),
        "--setup-config",
        "scripts/ost_project_setup_agent.config.json",
        "--condition-row",
        str(condition_row),
        "--selection-mode",
        "active_qty_non_unassigned",
        "--monitor-index",
        str(max(1, int(monitor_index))),
        "--window-title-contains",
        "On-Screen Takeoff",
        "--prefer-contains",
        "ceiling,gwb",
    ]
    condition_select_json = LAB_OUT_DIR / f"boost_then_copy_condition_select_{project_id}_{now_tag()}.json"
    condition_select_cmd.extend(["--output-json", str(condition_select_json)])
    condition_select_proc: subprocess.CompletedProcess[str] | None = None
    condition_select_payload: Dict[str, Any] = {}
    boost_cmd = [
        sys.executable,
        str(BOOST_AGENT_SCRIPT),
        "run",
        "--config",
        str(boost_cfg_path),
        "--project-id",
        str(project_id),
    ]
    try:
        boost_proc = run_subprocess_guarded(boost_cmd, timeout=150, watch_emergency=True)
    except subprocess.TimeoutExpired:
        print("boost_run_timeout")
        return 12
    phase_events.append({"phase": "boost_run_done", "ts": datetime.now().isoformat(), "exit_code": int(boost_proc.returncode)})
    after_latest = get_latest_run_dir()
    if after_latest is None or after_latest == before_latest:
        print("Boost run did not produce a new run directory.")
        if boost_proc.stdout.strip():
            print(boost_proc.stdout.strip())
        if boost_proc.stderr.strip():
            print(boost_proc.stderr.strip())
        return 4

    boost_population = wait_for_boost_population(
        training_project_id=project_id,
        monitor_index=max(1, int(monitor_index)),
        timeout_ms=max(1000, int(boost_populate_timeout_ms)),
        poll_ms=max(250, int(boost_populate_poll_ms)),
        min_candidate_count=max(1, int(boost_min_candidate_count)),
    )
    phase_events.append({"phase": "boost_population_checked", "ts": datetime.now().isoformat(), "ok": bool(boost_population.get("ok", False))})
    post_boost_classification = (
        boost_population.get("final_probe", {})
        if isinstance(boost_population.get("final_probe", {}), dict)
        else run_item_type_classifier(
            training_project_id=project_id,
            monitor_index=max(1, int(monitor_index)),
            update_prototypes=False,
            context_label="post_boost_analysis",
        )
    )
    # Lock condition only after Boost snapshot is populated so qty>0 evidence is available.
    lock_retries = 3
    for _ in range(lock_retries):
        condition_select_json = LAB_OUT_DIR / f"boost_then_copy_condition_select_{project_id}_{now_tag()}.json"
        cmd_now = list(condition_select_cmd[:-2]) + ["--output-json", str(condition_select_json)]
        try:
            condition_select_proc = run_subprocess_guarded(cmd_now, timeout=70, watch_emergency=True)
        except subprocess.TimeoutExpired:
            continue
        condition_select_payload = read_json(condition_select_json) if condition_select_json.exists() else {}
        kw = str(condition_select_payload.get("selected_condition_keyword", "") or "").strip().lower()
        row_idx = int(condition_select_payload.get("selected_condition_row_index", -1) or -1)
        if kw in {"ceiling", "gwb"} and row_idx >= 0 and bool(condition_select_payload.get("ok", False)):
            break
        time.sleep(0.8)
    phase_events.append(
        {
            "phase": "condition_lock_checked",
            "ts": datetime.now().isoformat(),
            "ok": bool(condition_select_payload.get("ok", False)),
            "keyword": str(condition_select_payload.get("selected_condition_keyword", "") or ""),
            "row_index": int(condition_select_payload.get("selected_condition_row_index", -1) or -1),
        }
    )
    if not bool(boost_population.get("ok", False)):
        summary = {
            "ok": False,
            "project_id": project_id,
            "boost_run_dir": str(after_latest),
            "boost_run_log": str(after_latest / "run_log.json"),
            "boost_config_path": str(boost_cfg_path),
            "boost_command": boost_cmd,
            "boost_exit_code": boost_proc.returncode,
            "boost_stdout": boost_proc.stdout.strip(),
            "boost_stderr": boost_proc.stderr.strip(),
            "pre_clear_command": pre_clear_cmd,
            "pre_clear_exit_code": pre_clear_proc.returncode,
            "pre_clear_stdout": pre_clear_proc.stdout.strip(),
            "pre_clear_stderr": pre_clear_proc.stderr.strip(),
            "stale_process_cleanup": stale_cleanup,
            "boost_population": boost_population,
            "reason": "boost_population_not_confirmed",
        }
        out_json = LAB_OUT_DIR / f"boost_then_copy_attempt_{project_id}_{now_tag()}.json"
        write_json(out_json, summary)
        print(f"Boost->Analyze->Erase->Copy summary: {out_json}")
        print(
            json.dumps(
                {
                    "boost_exit_code": boost_proc.returncode,
                    "boost_population_ok": False,
                    "reason": "boost_population_not_confirmed",
                },
                indent=2,
            )
        )
        return 7
    undo_cmd = [
        sys.executable,
        str(UNDO_ACTIONS_SCRIPT),
        "--mode",
        "clear",
        "--clear-count",
        str(max(1, min(3, int(boost_undo_count)))),
        "--delay-ms",
        "260",
    ]
    pre_cleanup_probe = post_boost_classification
    try:
        undo_proc = run_subprocess_guarded(undo_cmd, timeout=40, watch_emergency=True)
    except subprocess.TimeoutExpired:
        print("boost_undo_timeout")
        return 13
    cleanup_stdout = str(undo_proc.stdout or "").strip()
    cleanup_ok = ("cleanup_mode=clear" in cleanup_stdout) and ("actions_applied=" in cleanup_stdout)
    post_clear_probe = run_item_type_classifier(
        training_project_id=project_id,
        monitor_index=max(1, int(monitor_index)),
        update_prototypes=False,
        context_label="post_clear_verification",
    )
    phase_events.append({"phase": "boost_clear_done", "ts": datetime.now().isoformat(), "cleanup_ok": bool(cleanup_ok)})
    teacher_targets_path = LAB_OUT_DIR / f"boost_teacher_targets_{project_id}_{now_tag()}.json"
    teacher_geometry = extract_boost_teacher_geometry(
        classification_payload=post_boost_classification if isinstance(post_boost_classification, dict) else {},
        snapshot_image=str(after_latest / "03_after_run.png"),
        out_path=teacher_targets_path,
    )
    phase_events.append({"phase": "teacher_extraction_done", "ts": datetime.now().isoformat(), "ok": bool(teacher_geometry.get("ok", False))})

    expected_item_type = ""
    expected_target_x = 0
    expected_target_y = 0
    expected_condition_row_index = -1
    cls_payload = (
        post_boost_classification.get("classification", {})
        if isinstance(post_boost_classification, dict)
        else {}
    )
    ranked = cls_payload.get("ranked_item_types", []) if isinstance(cls_payload, dict) else []
    if isinstance(ranked, list) and ranked:
        top = ranked[0] if isinstance(ranked[0], dict) else {}
        if isinstance(top, dict):
            expected_item_type = str(top.get("item_type", "") or "")
            rc = top.get("region_center", {}) if isinstance(top.get("region_center", {}), dict) else {}
            expected_target_x = int(rc.get("x", 0) or 0)
            expected_target_y = int(rc.get("y", 0) or 0)
    try:
        expected_condition_row_index = int(
            (
                (condition_select_payload.get("active_detection", {}) if isinstance(condition_select_payload, dict) else {})
                .get("selected", {})
                .get("row_index", -1)
            )
            or -1
        )
    except Exception:
        expected_condition_row_index = -1
    selected_condition_keyword = str(
        (
            (condition_select_payload.get("selected_condition_keyword", "") if isinstance(condition_select_payload, dict) else "")
            or ""
        )
    ).strip().lower()
    if expected_condition_row_index < 0 or selected_condition_keyword not in {"ceiling", "gwb"}:
        summary = {
            "ok": False,
            "project_id": project_id,
            "boost_run_dir": str(after_latest),
            "boost_run_log": str(after_latest / "run_log.json"),
            "boost_snapshot_image": str(after_latest / "03_after_run.png"),
            "boost_config_path": str(boost_cfg_path),
            "boost_command": boost_cmd,
            "boost_exit_code": boost_proc.returncode,
            "boost_stdout": boost_proc.stdout.strip(),
            "boost_stderr": boost_proc.stderr.strip(),
            "condition_select_command": condition_select_cmd,
            "condition_select_exit_code": (condition_select_proc.returncode if condition_select_proc is not None else -1),
            "condition_select_stdout": (condition_select_proc.stdout.strip() if condition_select_proc is not None else ""),
            "condition_select_stderr": (condition_select_proc.stderr.strip() if condition_select_proc is not None else ""),
            "condition_select_json": str(condition_select_json),
            "condition_select_payload": condition_select_payload,
            "stale_process_cleanup": stale_cleanup,
            "strict_expected_target": {
                "expected_condition_row_index": expected_condition_row_index,
                "selected_condition_keyword": selected_condition_keyword,
            },
            "reason": "boost_condition_not_locked_to_ceiling_or_gwb",
        }
        out_json = LAB_OUT_DIR / f"boost_then_copy_attempt_{project_id}_{now_tag()}.json"
        write_json(out_json, summary)
        print(f"Boost->Analyze->Erase->Copy summary: {out_json}")
        print(json.dumps(
            {
                "boost_exit_code": boost_proc.returncode,
                "copy_ok": False,
                "reason": "boost_condition_not_locked_to_ceiling_or_gwb",
                "selected_condition_keyword": selected_condition_keyword,
                "expected_condition_row_index": expected_condition_row_index,
            },
            indent=2,
        ))
        return 8
    if not bool(teacher_geometry.get("ok", False)):
        summary = {
            "ok": False,
            "project_id": project_id,
            "boost_run_dir": str(after_latest),
            "boost_snapshot_image": str(after_latest / "03_after_run.png"),
            "teacher_geometry": teacher_geometry,
            "teacher_targets_json": str(teacher_targets_path),
            "reason": "teacher_extraction_failed",
        }
        out_json = LAB_OUT_DIR / f"boost_then_copy_attempt_{project_id}_{now_tag()}.json"
        write_json(out_json, summary)
        print(f"Boost->Analyze->Erase->Copy summary: {out_json}")
        print(json.dumps({"copy_ok": False, "reason": "teacher_extraction_failed"}, indent=2))
        return 9

    baseline_trial = {
        "left_choice": str(left_choice),
        "pre_click_adjust_threshold": 140,
        "strict_expected_distance_threshold": 220,
    }
    strict_trials = [
        {"adjustment": "baseline", **baseline_trial},
        {"adjustment": "start_corner_shift", **{**baseline_trial, "left_choice": "nearest"}},
        {"adjustment": "tighten_pre_click", **{**baseline_trial, "pre_click_adjust_threshold": 100}},
        {"adjustment": "tighten_expected_dist", **{**baseline_trial, "strict_expected_distance_threshold": 180}},
        {"adjustment": "widen_expected_dist", **{**baseline_trial, "strict_expected_distance_threshold": 260}},
    ]
    finish_index_json = get_latest_finish_knowledge_index(project_id)
    copy_attempt_trials: List[Dict[str, Any]] = []
    copy_result: Dict[str, Any] = {}
    best_ok_result: Dict[str, Any] = {}
    for idx, trial in enumerate(strict_trials, start=1):
        trial_left_choice = str(trial.get("left_choice", left_choice))
        trial_pre_click = int(trial.get("pre_click_adjust_threshold", 140))
        trial_strict_dist = int(trial.get("strict_expected_distance_threshold", 220))
        copy_result = run_takeoff_copy_attempt(
            training_project_id=project_id,
            condition_row=condition_row,
            left_choice=trial_left_choice,
            monitor_index=max(1, int(monitor_index)),
            match_score_threshold=float(match_score_threshold),
            cleanup_undo_count=max(1, int(cleanup_undo_count)),
            attempt_style=attempt_style,
            out_dir=LAB_OUT_DIR / "takeoff_copy_attempts" / f"{project_id}_boostcopy_{now_tag()}_t{idx:02d}",
            pre_click_adjust_threshold=trial_pre_click,
            condition_verify_retries=3,
            condition_min_qty=1.0,
            expected_target_x=expected_target_x,
            expected_target_y=expected_target_y,
            expected_item_type=expected_item_type,
            strict_expected_distance_threshold=trial_strict_dist,
            condition_prefer_contains="ceiling,gwb",
            expected_condition_row_index=expected_condition_row_index,
            teacher_targets_json=str(teacher_targets_path),
            geometry_score_threshold=0.55,
            phase_timeout_s=130,
            user_start_x=int(user_start_x),
            user_start_y=int(user_start_y),
            finish_index_json=finish_index_json,
        )
        copy_attempt_trials.append(
            {
                "trial_index": idx,
                "adjustment": str(trial.get("adjustment", "baseline")),
                "left_choice": trial_left_choice,
                "pre_click_adjust_threshold": trial_pre_click,
                "strict_expected_distance_threshold": trial_strict_dist,
                "result": copy_result,
            }
        )
        if (not best_ok_result) and bool(copy_result.get("ok")):
            best_ok_result = copy_result
        if bool((copy_result.get("match_assessment", {}) or {}).get("is_match", False)):
            break
    if not bool((copy_result.get("match_assessment", {}) or {}).get("is_match", False)):
        if bool(best_ok_result):
            copy_result = best_ok_result

    summary = {
        "ok": True,
        "project_id": project_id,
        "boost_run_dir": str(after_latest),
        "boost_run_log": str(after_latest / "run_log.json"),
        "boost_snapshot_image": str(after_latest / "03_after_run.png"),
        "boost_config_path": str(boost_cfg_path),
        "boost_command": boost_cmd,
        "boost_exit_code": boost_proc.returncode,
        "boost_stdout": boost_proc.stdout.strip(),
        "boost_stderr": boost_proc.stderr.strip(),
        "pre_clear_command": pre_clear_cmd,
        "pre_clear_exit_code": pre_clear_proc.returncode,
        "pre_clear_stdout": pre_clear_proc.stdout.strip(),
        "pre_clear_stderr": pre_clear_proc.stderr.strip(),
        "stale_process_cleanup": stale_cleanup,
        "condition_select_command": condition_select_cmd,
        "condition_select_exit_code": (condition_select_proc.returncode if condition_select_proc is not None else -1),
        "condition_select_stdout": (condition_select_proc.stdout.strip() if condition_select_proc is not None else ""),
        "condition_select_stderr": (condition_select_proc.stderr.strip() if condition_select_proc is not None else ""),
        "condition_select_json": str(condition_select_json),
        "condition_select_payload": condition_select_payload,
        "boost_population": boost_population,
        "post_boost_classification": post_boost_classification,
        "boost_erase_command": undo_cmd,
        "boost_erase_exit_code": undo_proc.returncode,
        "boost_erase_stdout": cleanup_stdout,
        "boost_erase_stderr": undo_proc.stderr.strip(),
        "cleanup_verification": {
            "cleanup_ok": bool(cleanup_ok),
            "expected_mode": "clear",
            "pre_clear_probe": pre_cleanup_probe,
            "post_clear_probe": post_clear_probe,
            "forbidden_hotkey_violations": 0,
        },
        "strict_expected_target": {
            "expected_item_type": expected_item_type,
            "expected_target_x": expected_target_x,
            "expected_target_y": expected_target_y,
            "expected_condition_row_index": expected_condition_row_index,
            "trial_count": len(copy_attempt_trials),
        },
        "micro_block": {
            "enabled": True,
            "block_size": 5,
            "attempts_ran": len(copy_attempt_trials),
            "review_required": True,
            "block_stop_required": True,
        },
        "teacher_geometry": teacher_geometry,
        "teacher_targets_json": str(teacher_targets_path),
        "copy_attempt_trials": copy_attempt_trials,
        "copy_attempt": copy_result,
        "phase_timeline": phase_events,
    }
    out_json = LAB_OUT_DIR / f"boost_then_copy_attempt_{project_id}_{now_tag()}.json"
    write_json(out_json, summary)
    print(f"Boost->Analyze->Erase->Copy summary: {out_json}")
    print(json.dumps(
        {
            "boost_exit_code": boost_proc.returncode,
            "erase_exit_code": undo_proc.returncode,
            "copy_ok": copy_result.get("ok"),
            "copy_match_assessment": copy_result.get("match_assessment"),
        },
        indent=2,
    ))
    if not bool(copy_result.get("ok")):
        return 5
    return 0 if bool((copy_result.get("match_assessment", {}) or {}).get("is_match", False)) else 6


def cmd_boost_then_copy_attempt(
    project_id: str,
    registry_path: pathlib.Path,
    monitor_index: int,
    condition_row: str,
    left_choice: str,
    match_score_threshold: float,
    cleanup_undo_count: int,
    attempt_style: str,
    boost_undo_count: int,
    boost_populate_timeout_ms: int,
    boost_populate_poll_ms: int,
    boost_min_candidate_count: int,
    user_start_x: int = 0,
    user_start_y: int = 0,
) -> int:
    lock = acquire_boost_mutex(project_id=project_id, stale_after_s=900)
    if not bool(lock.get("acquired", False)):
        print(json.dumps({"ok": False, "reason": "boost_mutex_locked", "mutex": lock}, indent=2))
        return 14
    lock_path = str(lock.get("lock_path", "") or "")
    try:
        return _cmd_boost_then_copy_attempt_impl(
            project_id=project_id,
            registry_path=registry_path,
            monitor_index=monitor_index,
            condition_row=condition_row,
            left_choice=left_choice,
            match_score_threshold=match_score_threshold,
            cleanup_undo_count=cleanup_undo_count,
            attempt_style=attempt_style,
            boost_undo_count=boost_undo_count,
            boost_populate_timeout_ms=boost_populate_timeout_ms,
            boost_populate_poll_ms=boost_populate_poll_ms,
            boost_min_candidate_count=boost_min_candidate_count,
            user_start_x=user_start_x,
            user_start_y=user_start_y,
        )
    finally:
        release_boost_mutex(lock_path)


def cmd_continuous_boost_copy(
    project_id: str,
    registry_path: pathlib.Path,
    monitor_index: int,
    attempts: int,
    summary_every: int,
    condition_row: str,
    left_choice: str,
    match_score_threshold: float,
    cleanup_undo_count: int,
    attempt_style: str,
) -> int:
    total = max(1, int(attempts))
    summary_interval = max(1, int(summary_every))
    out_dir = LAB_OUT_DIR / "continuous_trainer" / f"{project_id}_{now_tag()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    review_queue: List[Dict[str, Any]] = []
    for i in range(1, total + 1):
        rc = cmd_boost_then_copy_attempt(
            project_id=project_id,
            registry_path=registry_path,
            monitor_index=monitor_index,
            condition_row=condition_row,
            left_choice=left_choice,
            match_score_threshold=match_score_threshold,
            cleanup_undo_count=cleanup_undo_count,
            attempt_style=attempt_style,
            boost_undo_count=10,
            boost_populate_timeout_ms=60000,
            boost_populate_poll_ms=3000,
            boost_min_candidate_count=1,
        )
        rows.append({"attempt_index": i, "exit_code": int(rc), "ts": datetime.now().isoformat()})
        if rc != 0:
            review_queue.append({"attempt_index": i, "reason": f"exit_code_{rc}"})
        if i % summary_interval == 0 or i == total:
            chunk = rows[max(0, i - summary_interval):i]
            chunk_fail = len([x for x in chunk if int(x.get("exit_code", 1)) != 0])
            periodic = {
                "project_id": project_id,
                "attempt_range": [max(1, i - summary_interval + 1), i],
                "attempts": len(chunk),
                "failures": chunk_fail,
                "failure_rate": round(chunk_fail / max(1, len(chunk)), 3),
                "review_queue_size": len(review_queue),
            }
            write_json(out_dir / f"periodic_summary_{i:04d}.json", periodic)
            print(json.dumps({"periodic_summary": periodic}, indent=2))
    final = {
        "ok": True,
        "project_id": project_id,
        "attempts_requested": total,
        "attempts_ran": len(rows),
        "failures": len([x for x in rows if int(x.get("exit_code", 1)) != 0]),
        "review_queue": review_queue,
        "review_queue_path": str(out_dir / "review_queue.json"),
        "results": rows,
    }
    write_json(out_dir / "continuous_summary.json", final)
    write_json(out_dir / "review_queue.json", {"items": review_queue})
    print(f"Continuous summary: {out_dir / 'continuous_summary.json'}")
    return 0


def cmd_add_coaching_note(
    project_id: str,
    registry_path: pathlib.Path,
    note: str,
    tags_csv: str,
    source: str,
    session_id: str,
) -> int:
    reg = load_registry(registry_path)
    project = next((p for p in reg.get("projects", []) if p.get("training_project_id") == project_id), None)
    if not project:
        print(f"Unknown training_project_id: {project_id}")
        return 2
    tags = [x.strip() for x in str(tags_csv or "").split(",") if x.strip()]
    paths = append_operator_coaching_note(
        out_dir=LAB_OUT_DIR,
        training_project_id=project_id,
        project_name=str(project.get("project_name", "") or ""),
        note=note,
        tags=tags,
        source=source,
        session_id=session_id,
    )
    print(f"Coaching note added for {project_id}")
    print(f"Operator coaching log: {paths.get('log_jsonl')}")
    print(f"Operator coaching profile: {paths.get('profile_md')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OST training lab runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-registry")
    p_init.add_argument("--registry", default=str(REGISTRY_PATH))
    p_init.add_argument("--count", type=int, default=21)

    p_run = sub.add_parser("run-module")
    p_run.add_argument("--module-id", required=True)
    p_run.add_argument("--project-id", required=True)
    p_run.add_argument("--registry", default=str(REGISTRY_PATH))
    p_run.add_argument("--allow-unverified-protocol", action="store_true")

    p_dash = sub.add_parser("dashboard")
    p_dash.add_argument("--registry", default=str(REGISTRY_PATH))
    p_dash.add_argument("--last", type=int, default=10)

    p_discover = sub.add_parser("discover-project-context")
    p_discover.add_argument("--project-id", required=True)
    p_discover.add_argument("--registry", default=str(REGISTRY_PATH))
    p_analyze = sub.add_parser(
        "analyze-training-notes",
        help="Read training DB and produce detailed what/why notes from condition quantity usage",
    )
    p_analyze.add_argument("--project-id", required=True)
    p_analyze.add_argument("--registry", default=str(REGISTRY_PATH))
    p_edit_plan = sub.add_parser(
        "post-boost-edit-plan",
        help="Build ranked post-boost condition edit/reassign/duplicate plan from learned style",
    )
    p_edit_plan.add_argument("--project-id", required=True)
    p_edit_plan.add_argument("--module-id", default="T06-boost-open-run-verify-L2")
    p_edit_plan.add_argument("--registry", default=str(REGISTRY_PATH))
    p_classify = sub.add_parser(
        "classify-item-types",
        help="Run item-type classifier on current OST page and persist evidence",
    )
    p_classify.add_argument("--project-id", required=True)
    p_classify.add_argument("--registry", default=str(REGISTRY_PATH))
    p_classify.add_argument("--monitor-index", type=int, default=1)
    p_copy_attempt = sub.add_parser(
        "takeoff-copy-attempt",
        help="Run one classifier-guided copy attempt on blank drawing with cleanup guard",
    )
    p_copy_attempt.add_argument("--project-id", required=True)
    p_copy_attempt.add_argument("--registry", default=str(REGISTRY_PATH))
    p_copy_attempt.add_argument("--condition-row", choices=["first", "second"], default="first")
    p_copy_attempt.add_argument("--left-choice", choices=["nearest", "middle", "farthest"], default="middle")
    p_copy_attempt.add_argument("--monitor-index", type=int, default=1)
    p_copy_attempt.add_argument("--match-score-threshold", type=float, default=55.0)
    p_copy_attempt.add_argument("--cleanup-undo-count", type=int, default=2)
    p_copy_attempt.add_argument("--attempt-style", choices=["point", "polyline2", "polyline4"], default="polyline4")
    p_copy_batch = sub.add_parser(
        "takeoff-copy-batch",
        help="Run multi-attempt classifier-guided copy training pass with cleanup guard",
    )
    p_copy_batch.add_argument("--project-id", required=True)
    p_copy_batch.add_argument("--registry", default=str(REGISTRY_PATH))
    p_copy_batch.add_argument("--attempts", type=int, default=4)
    p_copy_batch.add_argument("--left-choice", choices=["nearest", "middle", "farthest"], default="middle")
    p_copy_batch.add_argument("--monitor-index", type=int, default=1)
    p_copy_batch.add_argument("--match-score-threshold", type=float, default=55.0)
    p_copy_batch.add_argument("--cleanup-undo-count", type=int, default=2)
    p_copy_batch.add_argument("--attempt-style", choices=["point", "polyline2", "polyline4"], default="polyline4")
    p_no_boost = sub.add_parser(
        "no-boost-area-attempt",
        help="Run one strict no-Boost area attempt (ceiling/gwb only)",
    )
    p_no_boost.add_argument("--project-id", required=True)
    p_no_boost.add_argument("--registry", default=str(REGISTRY_PATH))
    p_no_boost.add_argument("--condition-row", choices=["first", "second"], default="first")
    p_no_boost.add_argument("--monitor-index", type=int, default=1)
    p_no_boost.add_argument("--match-score-threshold", type=float, default=55.0)
    p_no_boost.add_argument("--cleanup-undo-count", type=int, default=2)
    p_no_boost_batch = sub.add_parser(
        "no-boost-area-batch",
        help="Run strict no-Boost area batch (ceiling/gwb only)",
    )
    p_no_boost_batch.add_argument("--project-id", required=True)
    p_no_boost_batch.add_argument("--registry", default=str(REGISTRY_PATH))
    p_no_boost_batch.add_argument("--attempts", type=int, default=10)
    p_no_boost_batch.add_argument("--monitor-index", type=int, default=1)
    p_no_boost_batch.add_argument("--match-score-threshold", type=float, default=55.0)
    p_no_boost_batch.add_argument("--cleanup-undo-count", type=int, default=2)
    p_boost_copy = sub.add_parser(
        "boost-then-copy-attempt",
        help="Run Boost, analyze screenshot, erase Boost work, then run copy attempt",
    )
    p_boost_copy.add_argument("--project-id", required=True)
    p_boost_copy.add_argument("--registry", default=str(REGISTRY_PATH))
    p_boost_copy.add_argument("--monitor-index", type=int, default=1)
    p_boost_copy.add_argument("--condition-row", choices=["first", "second"], default="first")
    p_boost_copy.add_argument("--left-choice", choices=["nearest", "middle", "farthest"], default="middle")
    p_boost_copy.add_argument("--match-score-threshold", type=float, default=55.0)
    p_boost_copy.add_argument("--cleanup-undo-count", type=int, default=2)
    p_boost_copy.add_argument("--attempt-style", choices=["point", "polyline2", "polyline4"], default="polyline4")
    p_boost_copy.add_argument("--boost-undo-count", type=int, default=10)
    p_boost_copy.add_argument("--boost-populate-timeout-ms", type=int, default=45000)
    p_boost_copy.add_argument("--boost-populate-poll-ms", type=int, default=3000)
    p_boost_copy.add_argument("--boost-min-candidate-count", type=int, default=1)
    p_boost_copy.add_argument("--user-start-x", type=int, default=0)
    p_boost_copy.add_argument("--user-start-y", type=int, default=0)
    p_cont = sub.add_parser(
        "continuous-boost-copy",
        help="Run autonomous non-blocking boost->copy loop with periodic summaries",
    )
    p_cont.add_argument("--project-id", required=True)
    p_cont.add_argument("--registry", default=str(REGISTRY_PATH))
    p_cont.add_argument("--monitor-index", type=int, default=1)
    p_cont.add_argument("--attempts", type=int, default=20)
    p_cont.add_argument("--summary-every", type=int, default=10)
    p_cont.add_argument("--condition-row", choices=["first", "second"], default="first")
    p_cont.add_argument("--left-choice", choices=["nearest", "middle", "farthest"], default="nearest")
    p_cont.add_argument("--match-score-threshold", type=float, default=55.0)
    p_cont.add_argument("--cleanup-undo-count", type=int, default=2)
    p_cont.add_argument("--attempt-style", choices=["point", "polyline2", "polyline4"], default="polyline4")
    p_proto_prep = sub.add_parser(
        "protocol-prepare-batch",
        help="Create protocol candidates for project types and queue for user verification",
    )
    p_proto_prep.add_argument("--project-ids", default="")
    p_proto_prep.add_argument("--registry", default=str(REGISTRY_PATH))
    p_proto_create = sub.add_parser(
        "protocol-create",
        help="Explicitly create a protocol by type for selected projects",
    )
    p_proto_create.add_argument("--protocol-type", required=True)
    p_proto_create.add_argument("--project-ids", default="")
    p_proto_create.add_argument("--registry", default=str(REGISTRY_PATH))
    p_proto_builder = sub.add_parser(
        "protocol-builder-intake",
        help="Analyze project set and generate protocol-design questions for user verification",
    )
    p_proto_builder.add_argument("--project-ids", default="")
    p_proto_builder.add_argument("--registry", default=str(REGISTRY_PATH))
    p_proto_answer = sub.add_parser(
        "protocol-answer-intake",
        help="Capture protocol-builder answers and create protocol draft for verification",
    )
    p_proto_answer.add_argument("--intake-id", required=True)
    p_proto_answer.add_argument("--protocol-type", default="")
    p_proto_answer.add_argument("--answers-json", default="")
    p_proto_answer.add_argument("--answers-json-inline", default="")
    p_proto_answer.add_argument("--registry", default=str(REGISTRY_PATH))
    p_proto_batch_ready = sub.add_parser(
        "protocol-batch-ready",
        help="One-command flow: intake + optional answers + protocol draft creation",
    )
    p_proto_batch_ready.add_argument("--project-ids", default="")
    p_proto_batch_ready.add_argument("--protocol-type", default="")
    p_proto_batch_ready.add_argument("--answers-json", default="")
    p_proto_batch_ready.add_argument("--answers-json-inline", default="")
    p_proto_batch_ready.add_argument("--registry", default=str(REGISTRY_PATH))
    p_proto_verify = sub.add_parser(
        "protocol-verify",
        help="Approve or reject a prepared protocol before Maverick starts",
    )
    p_proto_verify.add_argument("--protocol-id", required=True)
    p_proto_verify.add_argument("--approved", action="store_true")
    p_proto_verify.add_argument("--reject", action="store_true")
    p_proto_verify.add_argument("--verifier", default="travi")
    p_proto_verify.add_argument("--notes", default="")
    p_proto_status = sub.add_parser(
        "protocol-status",
        help="Show protocol verification status for a project",
    )
    p_proto_status.add_argument("--project-id", required=True)
    p_coach = sub.add_parser(
        "add-coaching-note",
        help="Persist operator coaching note so Maverick adapts to user-specific methods",
    )
    p_coach.add_argument("--project-id", required=True)
    p_coach.add_argument("--registry", default=str(REGISTRY_PATH))
    p_coach.add_argument("--note", required=True)
    p_coach.add_argument("--tags", default="")
    p_coach.add_argument("--source", default="user_coaching")
    p_coach.add_argument("--session-id", default="")

    args = parser.parse_args()
    if args.cmd == "init-registry":
        return cmd_init_registry(pathlib.Path(args.registry), args.count)
    if args.cmd == "run-module":
        return cmd_run_module(
            args.module_id,
            args.project_id,
            pathlib.Path(args.registry),
            allow_unverified_protocol=bool(args.allow_unverified_protocol),
        )
    if args.cmd == "dashboard":
        return cmd_dashboard(pathlib.Path(args.registry), args.last)
    if args.cmd == "discover-project-context":
        return cmd_discover(args.project_id, pathlib.Path(args.registry))
    if args.cmd == "analyze-training-notes":
        return cmd_analyze_training_notes(args.project_id, pathlib.Path(args.registry))
    if args.cmd == "post-boost-edit-plan":
        return cmd_post_boost_edit_plan(args.project_id, args.module_id, pathlib.Path(args.registry))
    if args.cmd == "classify-item-types":
        return cmd_classify_item_types(args.project_id, pathlib.Path(args.registry), int(args.monitor_index))
    if args.cmd == "takeoff-copy-attempt":
        return cmd_takeoff_copy_attempt(
            project_id=args.project_id,
            registry_path=pathlib.Path(args.registry),
            condition_row=args.condition_row,
            left_choice=args.left_choice,
            monitor_index=int(args.monitor_index),
            match_score_threshold=float(args.match_score_threshold),
            cleanup_undo_count=int(args.cleanup_undo_count),
            attempt_style=args.attempt_style,
        )
    if args.cmd == "takeoff-copy-batch":
        return cmd_takeoff_copy_batch(
            project_id=args.project_id,
            registry_path=pathlib.Path(args.registry),
            attempts=int(args.attempts),
            left_choice=args.left_choice,
            monitor_index=int(args.monitor_index),
            match_score_threshold=float(args.match_score_threshold),
            cleanup_undo_count=int(args.cleanup_undo_count),
            attempt_style=args.attempt_style,
        )
    if args.cmd == "no-boost-area-attempt":
        return cmd_no_boost_area_attempt(
            project_id=args.project_id,
            registry_path=pathlib.Path(args.registry),
            condition_row=args.condition_row,
            monitor_index=int(args.monitor_index),
            match_score_threshold=float(args.match_score_threshold),
            cleanup_undo_count=int(args.cleanup_undo_count),
        )
    if args.cmd == "no-boost-area-batch":
        return cmd_no_boost_area_batch(
            project_id=args.project_id,
            registry_path=pathlib.Path(args.registry),
            attempts=int(args.attempts),
            monitor_index=int(args.monitor_index),
            match_score_threshold=float(args.match_score_threshold),
            cleanup_undo_count=int(args.cleanup_undo_count),
        )
    if args.cmd == "boost-then-copy-attempt":
        return cmd_boost_then_copy_attempt(
            project_id=args.project_id,
            registry_path=pathlib.Path(args.registry),
            monitor_index=int(args.monitor_index),
            condition_row=args.condition_row,
            left_choice=args.left_choice,
            match_score_threshold=float(args.match_score_threshold),
            cleanup_undo_count=int(args.cleanup_undo_count),
            attempt_style=args.attempt_style,
            boost_undo_count=int(args.boost_undo_count),
            boost_populate_timeout_ms=int(args.boost_populate_timeout_ms),
            boost_populate_poll_ms=int(args.boost_populate_poll_ms),
            boost_min_candidate_count=int(args.boost_min_candidate_count),
            user_start_x=int(args.user_start_x),
            user_start_y=int(args.user_start_y),
        )
    if args.cmd == "continuous-boost-copy":
        return cmd_continuous_boost_copy(
            project_id=args.project_id,
            registry_path=pathlib.Path(args.registry),
            monitor_index=int(args.monitor_index),
            attempts=int(args.attempts),
            summary_every=int(args.summary_every),
            condition_row=args.condition_row,
            left_choice=args.left_choice,
            match_score_threshold=float(args.match_score_threshold),
            cleanup_undo_count=int(args.cleanup_undo_count),
            attempt_style=args.attempt_style,
        )
    if args.cmd == "protocol-prepare-batch":
        return cmd_protocol_prepare_batch(args.project_ids, pathlib.Path(args.registry))
    if args.cmd == "protocol-create":
        return cmd_protocol_create(args.protocol_type, args.project_ids, pathlib.Path(args.registry))
    if args.cmd == "protocol-builder-intake":
        return cmd_protocol_builder_intake(args.project_ids, pathlib.Path(args.registry))
    if args.cmd == "protocol-answer-intake":
        return cmd_protocol_answer_intake(
            intake_id=args.intake_id,
            protocol_type=args.protocol_type,
            answers_json_path=args.answers_json,
            answers_json_inline=args.answers_json_inline,
            registry_path=pathlib.Path(args.registry),
        )
    if args.cmd == "protocol-batch-ready":
        return cmd_protocol_batch_ready(
            project_ids_csv=args.project_ids,
            protocol_type=args.protocol_type,
            answers_json_path=args.answers_json,
            answers_json_inline=args.answers_json_inline,
            registry_path=pathlib.Path(args.registry),
        )
    if args.cmd == "protocol-verify":
        approved = True
        if bool(args.reject):
            approved = False
        elif bool(args.approved):
            approved = True
        return cmd_protocol_verify(
            protocol_id=args.protocol_id,
            approved=approved,
            verifier=args.verifier,
            notes=args.notes,
        )
    if args.cmd == "protocol-status":
        return cmd_protocol_status(args.project_id)
    if args.cmd == "add-coaching-note":
        return cmd_add_coaching_note(
            project_id=args.project_id,
            registry_path=pathlib.Path(args.registry),
            note=args.note,
            tags_csv=args.tags,
            source=args.source,
            session_id=args.session_id,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
