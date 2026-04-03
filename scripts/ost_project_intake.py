#!/usr/bin/env python3
"""
OST Project Intake

Watches an allowed root for project folders, then:
1) organizes files into predictable buckets
2) renames files to consistent names
3) runs scope intelligence reports
4) runs scope profiler on best plan PDF
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple


DEFAULT_CONFIG = {
    "allowed_roots": [r"G:\Shared drives\SKYLINE 2026\AI Bids"],
    "watch_root": r"G:\Shared drives\SKYLINE 2026\AI Bids",
    "poll_seconds": 15,
    "auto_apply": True,
    "max_project_depth": 2,
    "min_idle_seconds_before_process": 20,
    "organization_folder": "_organized",
    "reports_folder": "_reports",
    "processed_state_path": "output/ost-project-intake/state.json",
    "processed_log_path": "output/ost-project-intake/processed_projects.jsonl",
    "retry_queue_path": "output/ost-project-intake/retry_queue.json",
    "retry_min_interval_seconds": 300,
    "retry_backoff_seconds": 300,
    "retry_max_interval_seconds": 3600,
    "scope_intel_max_files": 160,
    "scope_intel_max_pdf_pages": 80,
    "scope_profile_max_pages": 120,
    "scope_intel_timeout_seconds": 90,
    "scope_profile_timeout_seconds": 90,
    "ost_setup_timeout_seconds": 90,
    "max_moves_per_run": 120,
    "ost_setup": {
        "enabled": True,
        "config_path": "scripts/ost_project_setup_agent.config.json",
        "script_path": "scripts/ost_project_setup_agent.py",
    },
}


BUCKET_RULES: List[Tuple[str, List[str]]] = [
    ("plans", ["plan", "drawing", "sheet", "arch", "architectural", "rcp", "elevation"]),
    ("specifications", ["spec", "specification", "division", "section"]),
    ("schedules", ["schedule", "finish", "door", "window", "room finish"]),
    ("addenda", ["addendum", "addenda", "bulletin", "asi", "rfi"]),
    ("submittals", ["submittal", "product data", "shop drawing"]),
]


def now_iso() -> str:
    return datetime.now().isoformat()


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_jsonl(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")


def load_config(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        write_json(path, DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    raw = read_json(path)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(raw)
    return cfg


def load_retry_queue(path: pathlib.Path) -> Dict[str, Any]:
    data = read_json(path) if path.exists() else {}
    if not isinstance(data, dict):
        data = {}
    items = data.get("items", [])
    if not isinstance(items, list):
        items = []
    return {"items": items}


def save_retry_queue(path: pathlib.Path, queue: Dict[str, Any]) -> None:
    write_json(path, queue if isinstance(queue, dict) else {"items": []})


def queue_get_item(queue: Dict[str, Any], project_key: str) -> Dict[str, Any] | None:
    items = queue.get("items", []) if isinstance(queue, dict) else []
    for item in items:
        if isinstance(item, dict) and str(item.get("project_key", "")) == project_key:
            return item
    return None


def queue_set_item(queue: Dict[str, Any], item: Dict[str, Any]) -> None:
    items = queue.setdefault("items", [])
    for i, cur in enumerate(items):
        if isinstance(cur, dict) and str(cur.get("project_key", "")) == str(item.get("project_key", "")):
            items[i] = item
            return
    items.append(item)


def queue_remove_item(queue: Dict[str, Any], project_key: str) -> None:
    items = queue.get("items", []) if isinstance(queue, dict) else []
    queue["items"] = [
        x for x in items if not (isinstance(x, dict) and str(x.get("project_key", "")) == project_key)
    ]


def normalize_text(s: str) -> str:
    x = (s or "").lower()
    x = re.sub(r"[_\-.]+", " ", x)
    x = re.sub(r"[^a-z0-9\s]", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x


def slugify(s: str) -> str:
    x = normalize_text(s).replace(" ", "_")
    x = re.sub(r"_+", "_", x).strip("_")
    return x[:120] or "file"


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_takeoff_plans_dir(project_dir: pathlib.Path) -> pathlib.Path | None:
    candidates: List[pathlib.Path] = []
    for p in project_dir.iterdir():
        if not p.is_dir():
            continue
        n = norm_name(p.name)
        if "takeoff" in n and "plan" in n:
            candidates.append(p)
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x.name.lower())[0]


def first_upload_file(folder: pathlib.Path) -> pathlib.Path | None:
    if not folder or not folder.exists() or not folder.is_dir():
        return None
    files = [p for p in folder.iterdir() if p.is_file()]
    if not files:
        return None
    pdfs = sorted([p for p in files if p.suffix.lower() == ".pdf"], key=lambda x: x.name.lower())
    if pdfs:
        return pdfs[0]
    return sorted(files, key=lambda x: x.name.lower())[0]


def is_takeoff_plans_path(path: pathlib.Path) -> bool:
    for part in path.parts:
        n = norm_name(part)
        if "takeoff" in n and "plan" in n:
            return True
    return False


def iter_source_files(project_dir: pathlib.Path) -> List[pathlib.Path]:
    out: List[pathlib.Path] = []
    skip_dirs = {"_organized", "_reports", "output"}
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        r = pathlib.Path(root)
        for f in files:
            out.append(r / f)
    return sorted(out)


def is_allowed(path: pathlib.Path, allowed_roots: List[str]) -> bool:
    rp = path.resolve()
    for root in allowed_roots:
        rr = pathlib.Path(root).resolve()
        try:
            rp.relative_to(rr)
            return True
        except Exception:
            continue
    return False


def classify_bucket(path: pathlib.Path) -> str:
    n = normalize_text(path.name)
    full = normalize_text(str(path))
    # Strong path context first.
    if "specification" in full or "\\specifications\\" in str(path).lower() or "/specifications/" in str(path).lower():
        return "specifications"
    if "addendum" in full or "addenda" in full:
        return "addenda"
    if "schedule" in full or "finish schedule" in full:
        return "schedules"
    if "submittal" in full:
        return "submittals"
    for bucket, keywords in BUCKET_RULES:
        if any(k in n for k in keywords):
            return bucket
    if path.suffix.lower() in {".pdf", ".dwg", ".dxf"}:
        return "plans"
    return "other"


def best_plan_pdf(project_dir: pathlib.Path) -> pathlib.Path | None:
    # Rule 1: if TAKE-OFF PLANS folder exists, use first file from that folder.
    takeoff_dir = find_takeoff_plans_dir(project_dir)
    first_takeoff = first_upload_file(takeoff_dir) if takeoff_dir else None
    if first_takeoff:
        return first_takeoff

    # Rule 2: fallback to best-scored PDF in whole project.
    pdfs = list(project_dir.rglob("*.pdf"))
    if not pdfs:
        return None
    scored: List[Tuple[float, pathlib.Path]] = []
    for p in pdfs:
        n = normalize_text(p.stem)
        score = 0.0
        if "plan" in n:
            score += 2.0
        if "drawing" in n:
            score += 1.6
        if "arch" in n or "architectural" in n:
            score += 1.4
        if "set" in n:
            score += 0.8
        if "spec" in n:
            score -= 1.0
        if "addendum" in n:
            score -= 0.7
        score += min(len(n) / 120.0, 0.5)
        scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def enumerate_project_dirs(root: pathlib.Path, max_depth: int) -> List[pathlib.Path]:
    # Treat first-level directories under watch_root as project folders.
    # This avoids processing nested folders (e.g., Specifications) as separate projects.
    out: List[pathlib.Path] = []
    try:
        children = list(root.iterdir())
    except Exception:
        return out
    for c in children:
        if not c.is_dir():
            continue
        if c.name in {"_organized", "_reports", "output"}:
            continue
        out.append(c)
    return out


def latest_mtime(project_dir: pathlib.Path) -> float:
    # Only consider source files. Ignore generated outputs so we do not
    # retrigger processing from our own writes.
    skip_dirs = {"_organized", "_reports", "output"}
    latest = 0.0
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        r = pathlib.Path(root)
        for name in files:
            p = r / name
            if not p.exists():
                continue
            latest = max(latest, p.stat().st_mtime)
    return latest


def organize_project(project_dir: pathlib.Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    org_dir = project_dir / str(cfg.get("organization_folder", "_organized"))
    reports_dir = project_dir / str(cfg.get("reports_folder", "_reports"))
    org_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    apply_changes = bool(cfg.get("auto_apply", True))
    max_moves_per_run = int(cfg.get("max_moves_per_run", 120))

    actions: List[Dict[str, Any]] = []
    move_errors: List[Dict[str, Any]] = []
    skipped_locked_files = 0
    preserved_takeoff_files = 0
    bucket_counts: Dict[str, int] = {}
    seq_by_bucket: Dict[str, int] = {}
    applied_moves = 0
    move_limit_reached = False

    for p in iter_source_files(project_dir):
        if apply_changes and applied_moves >= max(1, max_moves_per_run):
            move_limit_reached = True
            break
        if is_takeoff_plans_path(p):
            # Preserve TAKE-OFF PLANS source files for OST upload workflow.
            preserved_takeoff_files += 1
            actions.append(
                {
                    "action": "preserve_takeoff_file",
                    "from": str(p),
                    "applied": False,
                    "reason": "preserve_takeoff_plans_source",
                }
            )
            continue
        bucket = classify_bucket(p)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        seq_by_bucket[bucket] = seq_by_bucket.get(bucket, 0) + 1
        seq = seq_by_bucket[bucket]
        target_dir = org_dir / bucket
        target_dir.mkdir(parents=True, exist_ok=True)
        new_name = f"{bucket}_{seq:04d}_{slugify(p.stem)}{p.suffix.lower()}"
        target_path = target_dir / new_name
        i = 1
        while target_path.exists():
            target_path = target_dir / f"{bucket}_{seq:04d}_{slugify(p.stem)}_{i}{p.suffix.lower()}"
            i += 1
        act = {
            "action": "move_rename",
            "from": str(p),
            "to": str(target_path),
            "bucket": bucket,
            "applied": apply_changes,
        }
        if apply_changes:
            try:
                shutil.move(str(p), str(target_path))
                applied_moves += 1
            except PermissionError as exc:
                # Often means file is in use by OST/Explorer/sync. Skip and continue.
                skipped_locked_files += 1
                act["applied"] = False
                act["skipped"] = True
                act["skip_reason"] = "file_locked"
                move_errors.append(
                    {
                        "from": str(p),
                        "to": str(target_path),
                        "error": str(exc),
                        "kind": "PermissionError",
                    }
                )
            except Exception as exc:
                # Record unexpected move error and continue processing remaining files.
                act["applied"] = False
                act["skipped"] = True
                act["skip_reason"] = "move_error"
                move_errors.append(
                    {
                        "from": str(p),
                        "to": str(target_path),
                        "error": str(exc),
                        "kind": type(exc).__name__,
                    }
                )
        actions.append(act)

    scope_json = reports_dir / "project_scope_intel.json"
    scope_md = reports_dir / "project_scope_intel.md"
    scope_cmd = [
        sys.executable,
        "scripts/ost_project_scope_report.py",
        "--project-folder",
        str(project_dir),
        "--output-json",
        str(scope_json),
        "--output-md",
        str(scope_md),
        "--max-files",
        str(int(cfg.get("scope_intel_max_files", 160))),
        "--max-pdf-pages",
        str(int(cfg.get("scope_intel_max_pdf_pages", 80))),
    ]
    scope_timeout = int(cfg.get("scope_intel_timeout_seconds", 90))
    scope_timed_out = False
    try:
        scope_proc = subprocess.run(
            scope_cmd,
            capture_output=True,
            text=True,
            timeout=max(10, scope_timeout),
        )
        scope_exit_code = int(scope_proc.returncode)
        scope_stdout = scope_proc.stdout.strip()
        scope_stderr = scope_proc.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        scope_timed_out = True
        scope_exit_code = -1
        scope_stdout = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
        scope_stderr = f"timeout after {scope_timeout}s"

    plan_pdf = best_plan_pdf(project_dir)
    profile_out = reports_dir / "scope_profile.json"
    profile_result: Dict[str, Any] = {"skipped": True, "reason": "no_plan_pdf_found"}
    if plan_pdf:
        profile_cmd = [
            sys.executable,
            "scripts/ost_scope_profiler.py",
            "--pdf",
            str(plan_pdf),
            "--output",
            str(profile_out),
            "--max-pages",
            str(int(cfg.get("scope_profile_max_pages", 120))),
        ]
        profile_timeout = int(cfg.get("scope_profile_timeout_seconds", 90))
        profile_timed_out = False
        try:
            prof_proc = subprocess.run(
                profile_cmd,
                capture_output=True,
                text=True,
                timeout=max(10, profile_timeout),
            )
            profile_exit_code = int(prof_proc.returncode)
            profile_stdout = prof_proc.stdout.strip()
            profile_stderr = prof_proc.stderr.strip()
        except subprocess.TimeoutExpired as exc:
            profile_timed_out = True
            profile_exit_code = -1
            profile_stdout = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
            profile_stderr = f"timeout after {profile_timeout}s"
        profile_result = {
            "skipped": False,
            "plan_pdf": str(plan_pdf),
            "exit_code": profile_exit_code,
            "stdout": profile_stdout,
            "stderr": profile_stderr,
            "timed_out": profile_timed_out,
            "output": str(profile_out),
        }

    setup_cfg = cfg.get("ost_setup", {}) or {}
    setup_enabled = bool(setup_cfg.get("enabled", False))
    setup_result: Dict[str, Any] = {"skipped": True, "reason": "setup_disabled"}
    if setup_enabled:
        setup_script = pathlib.Path(str(setup_cfg.get("script_path", "scripts/ost_project_setup_agent.py")))
        setup_config = pathlib.Path(
            str(setup_cfg.get("config_path", "scripts/ost_project_setup_agent.config.json"))
        )
        setup_out = reports_dir / "ost_setup"
        setup_out.mkdir(parents=True, exist_ok=True)
        setup_cmd = [
            sys.executable,
            str(setup_script),
            "--config",
            str(setup_config),
            "--project-name",
            project_dir.name,
            "--project-id",
            project_dir.name,
            "--project-dir",
            str(project_dir),
            "--plan-pdf",
            str(plan_pdf or ""),
            "--out-dir",
            str(setup_out),
        ]
        if not apply_changes:
            setup_cmd.append("--dry-run")
        setup_timeout = int(cfg.get("ost_setup_timeout_seconds", 90))
        setup_timed_out = False
        try:
            proc = subprocess.run(
                setup_cmd,
                capture_output=True,
                text=True,
                timeout=max(10, setup_timeout),
            )
            setup_exit_code = int(proc.returncode)
            setup_stdout = proc.stdout.strip()
            setup_stderr = proc.stderr.strip()
        except subprocess.TimeoutExpired as exc:
            setup_timed_out = True
            setup_exit_code = -1
            setup_stdout = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
            setup_stderr = f"timeout after {setup_timeout}s"
        setup_result = {
            "skipped": False,
            "command": setup_cmd,
            "exit_code": setup_exit_code,
            "stdout": setup_stdout,
            "stderr": setup_stderr,
            "timed_out": setup_timed_out,
            "output_dir": str(setup_out),
            "result_json": str(setup_out / "setup_result.json"),
        }

    manifest = {
        "ts": now_iso(),
        "project_dir": str(project_dir),
        "auto_apply": apply_changes,
        "bucket_counts": bucket_counts,
        "moved_files": len(actions),
        "applied_moves": applied_moves,
        "max_moves_per_run": max_moves_per_run,
        "move_limit_reached": move_limit_reached,
        "skipped_locked_files": skipped_locked_files,
        "preserved_takeoff_files": preserved_takeoff_files,
        "move_errors": move_errors,
        "actions": actions,
        "scope_intel": {
            "cmd": scope_cmd,
            "exit_code": scope_exit_code,
            "stdout": scope_stdout,
            "stderr": scope_stderr,
            "timed_out": scope_timed_out,
            "incomplete": scope_timed_out or scope_exit_code != 0,
            "json": str(scope_json),
            "md": str(scope_md),
        },
        "scope_profile": profile_result,
        "ost_project_setup": setup_result,
    }
    write_json(reports_dir / "intake_manifest.json", manifest)
    return manifest


def run_once(cfg: Dict[str, Any], state_path: pathlib.Path, project_filter: str = "") -> int:
    watch_root = pathlib.Path(str(cfg.get("watch_root", DEFAULT_CONFIG["watch_root"])))
    allowed_roots = [str(x) for x in (cfg.get("allowed_roots", []) or [])]
    if not is_allowed(watch_root, allowed_roots):
        print(f"watch_root not in allowed_roots: {watch_root}")
        return 2
    state = read_json(state_path) if state_path.exists() else {"projects": {}}
    retry_queue_path = pathlib.Path(str(cfg.get("retry_queue_path", DEFAULT_CONFIG["retry_queue_path"])))
    retry_queue = load_retry_queue(retry_queue_path)
    processed_log_path = pathlib.Path(
        str(cfg.get("processed_log_path", DEFAULT_CONFIG["processed_log_path"]))
    )
    state.setdefault("projects", {})
    changed = 0
    idle_needed = int(cfg.get("min_idle_seconds_before_process", 20))
    max_depth = int(cfg.get("max_project_depth", 2))

    projects = enumerate_project_dirs(watch_root, max_depth=max_depth)
    print(f"watch_root={watch_root}")
    print(f"project_scan_count={len(projects)}")
    valid_project_keys = {str(p.resolve()) for p in projects}
    existing_keys = list((state.get("projects", {}) or {}).keys())
    pruned = 0
    for key in existing_keys:
        if key not in valid_project_keys:
            state["projects"].pop(key, None)
            queue_remove_item(retry_queue, key)
            pruned += 1
    if pruned:
        print(f"pruned_legacy_state_entries={pruned}")
    if project_filter.strip():
        needle = normalize_text(project_filter)
        projects = [p for p in projects if needle in normalize_text(str(p))]

    for prj in projects:
        if not is_allowed(prj, allowed_roots):
            continue
        key = str(prj.resolve())
        mtime = latest_mtime(prj)
        if mtime <= 0:
            continue
        now = time.time()
        retry_item = queue_get_item(retry_queue, key)
        retry_due = False
        retry_attempt = 0
        if isinstance(retry_item, dict):
            retry_attempt = int(retry_item.get("attempt", 0) or 0)
            retry_due = now >= float(retry_item.get("next_retry_ts", 0.0) or 0.0)
        if now - mtime < idle_needed:
            if not retry_due:
                continue
        prev = float(state["projects"].get(key, {}).get("last_processed_mtime", 0.0))
        has_source_change = mtime > prev
        if not has_source_change and not retry_due:
            continue
        reason = "source_change" if has_source_change else "retry_queue"
        print(f"Processing project under watch_root: {prj} reason={reason}")

        effective_cfg = dict(cfg)
        if retry_due:
            # Adaptive retry limits for timed-out analysis runs.
            scale = max(1, retry_attempt + 1)
            effective_cfg["scope_intel_max_files"] = min(
                320, int(cfg.get("scope_intel_max_files", 160)) + (20 * scale)
            )
            effective_cfg["scope_intel_max_pdf_pages"] = min(
                160, int(cfg.get("scope_intel_max_pdf_pages", 80)) + (10 * scale)
            )
            effective_cfg["scope_profile_max_pages"] = min(
                220, int(cfg.get("scope_profile_max_pages", 120)) + (20 * scale)
            )
            effective_cfg["scope_intel_timeout_seconds"] = min(
                240, int(cfg.get("scope_intel_timeout_seconds", 90)) + (15 * scale)
            )
            effective_cfg["scope_profile_timeout_seconds"] = min(
                240, int(cfg.get("scope_profile_timeout_seconds", 90)) + (15 * scale)
            )

        manifest = organize_project(prj, effective_cfg)
        append_jsonl(
            processed_log_path,
            {
                "ts": now_iso(),
                "project_dir": str(prj),
                "source_latest_mtime": mtime,
                "reason": reason,
                "retry_attempt": retry_attempt,
                "manifest_path": str(
                    prj / str(cfg.get("reports_folder", "_reports")) / "intake_manifest.json"
                ),
                "moved_files": int(manifest.get("moved_files", 0)),
                "applied_moves": int(manifest.get("applied_moves", 0)),
            },
        )
        state["projects"][key] = {
            "last_processed_mtime": mtime,
            "last_processed_at": now_iso(),
            "last_manifest": str(prj / str(cfg.get("reports_folder", "_reports")) / "intake_manifest.json"),
            "moved_files": manifest.get("moved_files", 0),
            "last_scope_intel_timed_out": bool(
                ((manifest.get("scope_intel") or {}).get("timed_out", False))
            ),
            "last_scope_profile_timed_out": bool(
                ((manifest.get("scope_profile") or {}).get("timed_out", False))
            ),
        }
        scope_timed_out = bool(((manifest.get("scope_intel") or {}).get("timed_out", False))
                               or ((manifest.get("scope_profile") or {}).get("timed_out", False)))
        if scope_timed_out:
            min_interval = int(cfg.get("retry_min_interval_seconds", 300))
            backoff = int(cfg.get("retry_backoff_seconds", 300))
            max_interval = int(cfg.get("retry_max_interval_seconds", 3600))
            next_attempt = retry_attempt + 1
            next_in = min(max_interval, max(min_interval, backoff * max(1, next_attempt)))
            queue_set_item(
                retry_queue,
                {
                    "project_key": key,
                    "project_dir": str(prj),
                    "attempt": next_attempt,
                    "next_retry_ts": now + next_in,
                    "next_retry_iso": datetime.fromtimestamp(now + next_in).isoformat(),
                    "last_reason": "scope_timeout",
                },
            )
        else:
            queue_remove_item(retry_queue, key)
        changed += 1

    write_json(state_path, state)
    save_retry_queue(retry_queue_path, retry_queue)
    print(f"processed_projects={changed}")
    return 0


def watch_loop(cfg: Dict[str, Any], state_path: pathlib.Path, project_filter: str = "") -> int:
    poll = int(cfg.get("poll_seconds", 15))
    print(f"Watching with poll_seconds={poll}")
    while True:
        rc = run_once(cfg, state_path, project_filter=project_filter)
        if rc not in (0,):
            return rc
        time.sleep(max(3, poll))


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-intake project folders and build scope reports")
    parser.add_argument("--config", default="scripts/ost_project_intake.config.json")
    parser.add_argument("--once", action="store_true", help="Process one pass and exit")
    parser.add_argument("--watch", action="store_true", help="Run continuously")
    parser.add_argument("--project-filter", default="", help="Only process matching project path text")
    parser.add_argument("--dry-run", action="store_true", help="Compute actions but do not move/rename files")
    args = parser.parse_args()

    cfg = load_config(pathlib.Path(args.config))
    if args.dry_run:
        cfg["auto_apply"] = False
    state_path = pathlib.Path(str(cfg.get("processed_state_path", DEFAULT_CONFIG["processed_state_path"])))

    if args.watch:
        return watch_loop(cfg, state_path, project_filter=args.project_filter)
    return run_once(cfg, state_path, project_filter=args.project_filter)


if __name__ == "__main__":
    raise SystemExit(main())
