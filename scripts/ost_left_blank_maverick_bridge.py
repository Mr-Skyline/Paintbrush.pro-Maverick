#!/usr/bin/env python3
"""
Bridge left-blank takeoff attempt artifacts into Maverick step logging.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List


MANAGED_ARCHETYPES = [
    "left-blank-condition-verify",
    "left-blank-expected-target-gate",
    "left-blank-quality-gate",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def workspace_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def read_json(path: pathlib.Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_runtime_config(config_path: pathlib.Path) -> Dict[str, Any]:
    cfg = read_json(config_path, {})
    return cfg if isinstance(cfg, dict) else {}


def output_root_from_config(config_path: pathlib.Path) -> pathlib.Path:
    cfg = load_runtime_config(config_path)
    out = pathlib.Path(str(cfg.get("output_root", "output/maverick")))
    if not out.is_absolute():
        out = workspace_root() / out
    return out


def resolve_attempt_json(attempt_json: str, attempt_root: str) -> pathlib.Path:
    root = workspace_root()
    if attempt_json.strip():
        p = pathlib.Path(attempt_json)
        if not p.is_absolute():
            p = root / p
        return p
    scan_root = pathlib.Path(attempt_root)
    if not scan_root.is_absolute():
        scan_root = root / scan_root
    candidates = sorted(
        scan_root.rglob("left_blank_takeoff_attempt.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No left_blank_takeoff_attempt.json under {scan_root}")
    return candidates[0]


def _short_text(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _metric_summary(match: Dict[str, Any]) -> str:
    score = float(match.get("score", 0.0) or 0.0)
    threshold = float(match.get("threshold", 0.0) or 0.0)
    conf = float(match.get("classifier_top_confidence", 0.0) or 0.0)
    conf_threshold = float(match.get("classifier_threshold", 0.0) or 0.0)
    item_match = bool(match.get("expected_item_type_match", True))
    return (
        f"score={score:.2f}/{threshold:.2f}, "
        f"classifier={conf:.3f}/{conf_threshold:.3f}, "
        f"expected_item_type_match={item_match}"
    )


def derive_project(payload: Dict[str, Any], explicit_project: str) -> str:
    if explicit_project.strip():
        return explicit_project.strip()
    for key in ("project_id", "project", "training_project_id"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            return value
    return ""


def derive_failure_event(payload: Dict[str, Any]) -> Dict[str, str]:
    reason = str(payload.get("reason", "") or "").strip()
    cond = payload.get("condition_verification", {})
    cond = cond if isinstance(cond, dict) else {}
    match = payload.get("match_assessment", {})
    match = match if isinstance(match, dict) else {}
    selected_text = _short_text(cond.get("text", ""))

    if reason == "condition_verification_failed":
        observed = (
            "Condition verification failed: "
            f"selected_by={cond.get('selected_by', '')}, "
            f"keyword_hit={cond.get('preferred_keyword_hit', False)}, "
            f"y_aligned={cond.get('y_aligned', False)}, "
            f"qty={cond.get('qty', 0.0)}, text={selected_text}"
        )
        return {
            "action": "left_blank_attempt_bridge",
            "outcome": "failure",
            "archetype": "left-blank-condition-verify",
            "expected": "Select a valid active non-unassigned condition row before drawing.",
            "observed": observed,
            "error": reason,
            "resolution": "",
        }

    if reason == "expected_target_gate_failed":
        target = payload.get("expected_target", {})
        target = target if isinstance(target, dict) else {}
        observed = (
            "Expected target gate failed: "
            f"distance_px={target.get('distance_px', -1)}, "
            f"threshold_px={target.get('threshold_px', -1)}, "
            f"item_type={target.get('item_type', '')}"
        )
        return {
            "action": "left_blank_attempt_bridge",
            "outcome": "failure",
            "archetype": "left-blank-expected-target-gate",
            "expected": "Chosen target stays near the expected Boost-derived region.",
            "observed": observed,
            "error": reason,
            "resolution": "",
        }

    observed = f"Quality gate failed: {_metric_summary(match)}"
    return {
        "action": "left_blank_attempt_bridge",
        "outcome": "failure",
        "archetype": "left-blank-quality-gate",
        "expected": "Left-blank attempt passes match and classifier quality gates.",
        "observed": observed,
        "error": reason or "quality_gate_failed",
        "resolution": "",
    }


def derive_success_events(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    match = payload.get("match_assessment", {})
    match = match if isinstance(match, dict) else {}
    summary = _metric_summary(match)
    return [
        {
            "action": "left_blank_attempt_bridge",
            "outcome": "success",
            "archetype": archetype,
            "expected": "Left-blank attempt completes all gates cleanly.",
            "observed": f"Attempt passed gates: {summary}",
            "error": "",
            "resolution": "attempt passed gates",
        }
        for archetype in MANAGED_ARCHETYPES
    ]


def derive_events(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    match = payload.get("match_assessment", {})
    match = match if isinstance(match, dict) else {}
    reason = str(payload.get("reason", "") or "").strip()
    is_match = bool(match.get("is_match", False))
    bad_work = bool(match.get("bad_work", False))
    if reason or bad_work or (payload.get("ok") is True and not is_match):
        return [derive_failure_event(payload)]
    if bool(payload.get("ok", False)):
        return derive_success_events(payload)
    return [derive_failure_event(payload)]


def processed_state_path(output_root: pathlib.Path) -> pathlib.Path:
    return output_root / "left_blank_bridge_state.json"


def build_fingerprint(path: pathlib.Path) -> str:
    stat = path.stat()
    return f"{path.resolve()}::{stat.st_mtime_ns}::{stat.st_size}"


def is_processed(state_path: pathlib.Path, fingerprint: str) -> bool:
    state = read_json(state_path, {"processed": {}})
    processed = state.get("processed", {}) if isinstance(state, dict) else {}
    return fingerprint in processed if isinstance(processed, dict) else False


def mark_processed(
    state_path: pathlib.Path,
    fingerprint: str,
    attempt_json: pathlib.Path,
    project: str,
    event_count: int,
) -> None:
    state = read_json(state_path, {"processed": {}})
    if not isinstance(state, dict):
        state = {"processed": {}}
    processed = state.setdefault("processed", {})
    if not isinstance(processed, dict):
        processed = {}
        state["processed"] = processed
    processed[fingerprint] = {
        "attempt_json": str(attempt_json),
        "project": project,
        "event_count": event_count,
        "logged_at": utc_now_iso(),
    }
    write_json(state_path, state)


def log_event(config_path: pathlib.Path, project: str, event: Dict[str, str]) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/maverick_runtime.py",
        "--config",
        str(config_path),
        "log-step",
        "--project",
        project,
        "--action",
        event["action"],
        "--outcome",
        event["outcome"],
        "--archetype",
        event["archetype"],
        "--expected",
        event["expected"],
        "--observed",
        event["observed"],
        "--error",
        event["error"],
        "--resolution",
        event["resolution"],
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(workspace_root()),
        capture_output=True,
        text=True,
        timeout=25,
    )
    return {
        "cmd": cmd,
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Log latest left-blank takeoff attempt results into Maverick."
    )
    parser.add_argument("--config", default="scripts/maverick_runtime.config.json")
    parser.add_argument("--attempt-json", default="")
    parser.add_argument("--attempt-root", default="output/ost-condition-takeoff")
    parser.add_argument("--project", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = workspace_root()
    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    attempt_json = resolve_attempt_json(args.attempt_json, args.attempt_root)
    payload = read_json(attempt_json, {})
    if not isinstance(payload, dict) or not payload:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "invalid_attempt_payload",
                    "attempt_json": str(attempt_json),
                },
                indent=2,
            )
        )
        return 2

    output_root = output_root_from_config(config_path)
    state_path = processed_state_path(output_root)
    fingerprint = build_fingerprint(attempt_json)
    project = derive_project(payload, str(args.project))
    events = derive_events(payload)

    if not args.force and is_processed(state_path, fingerprint):
        print(
            json.dumps(
                {
                    "ok": True,
                    "skipped": True,
                    "reason": "already_processed",
                    "attempt_json": str(attempt_json),
                    "project": project,
                    "events": events,
                },
                indent=2,
            )
        )
        return 0

    results: List[Dict[str, Any]] = []
    if not args.dry_run:
        for event in events:
            results.append(log_event(config_path=config_path, project=project, event=event))
        mark_processed(
            state_path=state_path,
            fingerprint=fingerprint,
            attempt_json=attempt_json,
            project=project,
            event_count=len(events),
        )

    print(
        json.dumps(
            {
                "ok": True,
                "attempt_json": str(attempt_json),
                "project": project,
                "dry_run": bool(args.dry_run),
                "events": events,
                "results": results,
                "state_path": str(state_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
