#!/usr/bin/env python3
"""
OST Orchestrator

Single entrypoint for intake, analysis, setup, and training automation.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import shlex
import json
from datetime import datetime
from typing import List

WORKSPACE_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _pause_flag_path() -> pathlib.Path:
    raw = str(os.environ.get("MAVERICK_EMERGENCY_PAUSE_FLAG", "") or "").strip()
    if raw:
        p = pathlib.Path(raw)
        return p if p.is_absolute() else (WORKSPACE_ROOT / p)
    return WORKSPACE_ROOT / "output" / "maverick" / "emergency_pause.flag"


def _runner_mode() -> str:
    mode = str(os.environ.get("MAVERICK_RUNNER_MODE", "local") or "local").strip().lower()
    return mode if mode in {"local", "isolated"} else "local"


def _start_emergency_pause_watch() -> subprocess.Popen[str] | None:
    enabled_raw = str(os.environ.get("MAVERICK_AUTO_EMERGENCY_WATCH", "1")).strip().lower()
    enabled = enabled_raw not in {"0", "false", "no", "off"}
    if not enabled:
        return None
    script_path = WORKSPACE_ROOT / "scripts" / "ost_emergency_pause_hotkey.py"
    if not script_path.exists():
        return None
    try:
        return subprocess.Popen(
            [sys.executable, str(script_path), "watch"],
            cwd=str(WORKSPACE_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            env={
                **os.environ,
                "MAVERICK_EMERGENCY_PAUSE_FLAG": str(_pause_flag_path()),
            },
        )
    except Exception:
        return None


def _run_local_cmd(cmd: List[str], timeout_s: int | None = None) -> int:
    watcher: subprocess.Popen[str] | None = _start_emergency_pause_watch()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            timeout=timeout_s,
            env={**os.environ, "MAVERICK_EMERGENCY_PAUSE_FLAG": str(_pause_flag_path())},
        )
        return int(proc.returncode)
    except subprocess.TimeoutExpired:
        print(f"ERROR: command_timeout_s={int(timeout_s or 0)}")
        return 124
    finally:
        if watcher is not None and watcher.poll() is None:
            try:
                watcher.terminate()
            except Exception:
                pass


def _run_isolated_cmd(cmd: List[str], timeout_s: int | None = None) -> int:
    host = str(os.environ.get("MAVERICK_ISOLATED_SSH_HOST", "") or "").strip()
    if not host:
        print("ERROR: isolated_runner_missing_host (set MAVERICK_ISOLATED_SSH_HOST)")
        return 98
    remote_workdir = str(os.environ.get("MAVERICK_ISOLATED_WORKDIR", str(WORKSPACE_ROOT)) or str(WORKSPACE_ROOT))
    remote_python = str(os.environ.get("MAVERICK_ISOLATED_PYTHON", "python") or "python")
    args = [shlex.quote(str(x)) for x in cmd[1:]]
    remote_parts = [
        f"cd /d {shlex.quote(remote_workdir)}",
        f"set MAVERICK_EMERGENCY_PAUSE_FLAG={shlex.quote(str(_pause_flag_path()))}",
        f"{shlex.quote(remote_python)} {shlex.quote(str(cmd[0]))}",
    ]
    if args:
        remote_parts[-1] = remote_parts[-1] + " " + " ".join(args)
    remote_cmd = " && ".join(remote_parts)
    try:
        proc = subprocess.run(["ssh", host, remote_cmd], cwd=str(WORKSPACE_ROOT), timeout=timeout_s)
        return int(proc.returncode)
    except subprocess.TimeoutExpired:
        print(f"ERROR: isolated_command_timeout_s={int(timeout_s or 0)}")
        return 124


def run_cmd(cmd: List[str], timeout_s: int | None = None) -> int:
    print("RUN>", " ".join(cmd))
    mode = _runner_mode()
    if mode == "isolated":
        return _run_isolated_cmd(cmd, timeout_s=timeout_s)
    return _run_local_cmd(cmd, timeout_s=timeout_s)


def _parse_iso8601(raw: str) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _validate_plan_pages_scan(scan_json: str, max_age_minutes: int) -> tuple[bool, str]:
    p = pathlib.Path(scan_json)
    if not p.is_absolute():
        p = WORKSPACE_ROOT / p
    if not p.exists():
        return False, f"missing_plan_pages_scan_json path={p}"
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"invalid_plan_pages_scan_json path={p} err={exc}"
    if not isinstance(payload, dict):
        return False, f"invalid_plan_pages_scan_payload path={p}"
    if not bool(payload.get("ok", False)):
        reason = str(payload.get("reason", "scan_not_ok"))
        return False, f"plan_pages_scan_not_ok path={p} reason={reason}"
    counts = payload.get("counts", {}) if isinstance(payload.get("counts", {}), dict) else {}
    unique_rows = int(counts.get("unique_rows_seen", 0) or 0)
    if unique_rows <= 0:
        return False, f"plan_pages_scan_empty path={p}"
    if int(max_age_minutes) > 0:
        ts = _parse_iso8601(str(payload.get("created_at", "") or ""))
        if ts is None:
            return False, f"plan_pages_scan_missing_timestamp path={p}"
        now = datetime.now(tz=ts.tzinfo) if ts.tzinfo is not None else datetime.now()
        age_min = (now - ts).total_seconds() / 60.0
        if age_min > float(max_age_minutes):
            return False, (
                f"plan_pages_scan_stale path={p} age_min={age_min:.1f} "
                f"max_age_min={int(max_age_minutes)}"
            )
    return True, f"plan_pages_scan_ok path={p}"


def cmd_intake_once(project_filter: str, dry_run: bool, config: str) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_project_intake.py",
        "--config",
        config,
        "--once",
    ]
    if project_filter.strip():
        cmd.extend(["--project-filter", project_filter.strip()])
    if dry_run:
        cmd.append("--dry-run")
    return run_cmd(cmd)


def cmd_intake_watch(project_filter: str, config: str) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_project_intake.py",
        "--config",
        config,
        "--watch",
    ]
    if project_filter.strip():
        cmd.extend(["--project-filter", project_filter.strip()])
    return run_cmd(cmd)


def cmd_discover(project_id: str, registry: str) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "discover-project-context",
            "--project-id",
            project_id,
            "--registry",
            registry,
        ]
    )


def cmd_analyze_training_notes(project_id: str, registry: str) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "analyze-training-notes",
            "--project-id",
            project_id,
            "--registry",
            registry,
        ]
    )


def cmd_post_boost_edit_plan(project_id: str, module_id: str, registry: str) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "post-boost-edit-plan",
            "--project-id",
            project_id,
            "--module-id",
            module_id,
            "--registry",
            registry,
        ]
    )


def cmd_classify_item_types(project_id: str, registry: str, monitor_index: int) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "classify-item-types",
            "--project-id",
            project_id,
            "--registry",
            registry,
            "--monitor-index",
            str(monitor_index),
        ]
    )


def cmd_symbol_knowledge_ingest(
    project_id: str,
    dataset_root: str,
    dataset_name: str,
    output_root: str,
    limit: int,
    min_per_class: int,
    max_file_size_mb: int,
    scan_max_files: int,
    allow_warnings: bool,
    skip_safety_scan: bool,
    quarantine_dir: str,
) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_symbol_knowledge_ingest.py",
        "--project-id",
        project_id,
        "--dataset-root",
        dataset_root,
        "--dataset-name",
        dataset_name,
        "--limit",
        str(int(limit)),
        "--min-per-class",
        str(int(min_per_class)),
        "--max-file-size-mb",
        str(int(max_file_size_mb)),
        "--scan-max-files",
        str(int(scan_max_files)),
    ]
    if output_root.strip():
        cmd.extend(["--output-root", output_root.strip()])
    if allow_warnings:
        cmd.append("--allow-warnings")
    if skip_safety_scan:
        cmd.append("--skip-safety-scan")
    if quarantine_dir.strip():
        cmd.extend(["--quarantine-dir", quarantine_dir.strip()])
    return run_cmd(cmd)


def cmd_symbol_knowledge_query(image: str, index_json: str, top_k: int) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_symbol_knowledge_query.py",
            "--image",
            image,
            "--index-json",
            index_json,
            "--top-k",
            str(int(top_k)),
        ]
    )


def cmd_dataset_safety_scan(
    dataset_root: str,
    report_json: str,
    max_file_size_mb: int,
    max_files: int,
) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_dataset_safety_scan.py",
            "--dataset-root",
            dataset_root,
            "--report-json",
            report_json,
            "--max-file-size-mb",
            str(int(max_file_size_mb)),
            "--max-files",
            str(int(max_files)),
        ]
    )


def cmd_finish_knowledge_index_build(
    project_id: str,
    symbol_index_glob: str,
    attempt_glob: str,
    output_root: str,
    min_class_support: int,
    max_example_paths: int,
) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_finish_knowledge_index.py",
            "--project-id",
            project_id,
            "--symbol-index-glob",
            symbol_index_glob,
            "--attempt-glob",
            attempt_glob,
            "--output-root",
            output_root,
            "--min-class-support",
            str(int(min_class_support)),
            "--max-example-paths",
            str(int(max_example_paths)),
        ]
    )


def cmd_accuracy_ingestion(
    project_id: str,
    registry: str,
    output_root: str,
    finish_taxonomy_json: str,
    attempt_glob: str,
    training_notes_glob: str,
    symbol_dataset_root: str,
    symbol_dataset_name: str,
    require_plan_pages_scan: bool,
    plan_pages_scan_json: str,
    plan_pages_scan_max_age_minutes: int,
) -> int:
    if bool(require_plan_pages_scan):
        ok, msg = _validate_plan_pages_scan(
            scan_json=str(plan_pages_scan_json),
            max_age_minutes=int(plan_pages_scan_max_age_minutes),
        )
        if not ok:
            print(f"ERROR: {msg}")
            print(
                "HINT: run `python scripts/ost_orchestrator.py plan-pages-highlight-scan` "
                "before `accuracy-ingestion`, or pass --allow-missing-plan-pages-scan to bypass."
            )
            return 97
        print(f"PRECHECK: {msg}")
    cmd = [
        sys.executable,
        "scripts/ost_accuracy_ingestion.py",
        "--project-id",
        project_id,
        "--registry",
        registry,
        "--output-root",
        output_root,
        "--finish-taxonomy-json",
        finish_taxonomy_json,
        "--attempt-glob",
        attempt_glob,
        "--training-notes-glob",
        training_notes_glob,
    ]
    if str(symbol_dataset_root or "").strip():
        cmd.extend(["--symbol-dataset-root", str(symbol_dataset_root).strip()])
        cmd.extend(["--symbol-dataset-name", str(symbol_dataset_name).strip() or "accuracy_ingest"])
    return run_cmd(cmd)


def cmd_plan_pages_highlight_scan(
    monitor_index: int,
    window_title_contains: str,
    setup_config: str,
    scroll_steps: int,
    scroll_amount: int,
    list_width_px: int,
    list_height_px: int,
    row_height_px: int,
    min_highlight_score: float,
    ui_delay_ms: int,
    capture_highlighted: bool,
    page_render_wait_ms: int,
    capture_dir: str,
    output_json: str,
) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_plan_pages_highlight_scan.py",
        "--monitor-index",
        str(int(monitor_index)),
        "--window-title-contains",
        str(window_title_contains),
        "--setup-config",
        str(setup_config),
        "--scroll-steps",
        str(int(scroll_steps)),
        "--scroll-amount",
        str(int(scroll_amount)),
        "--list-width-px",
        str(int(list_width_px)),
        "--list-height-px",
        str(int(list_height_px)),
        "--row-height-px",
        str(int(row_height_px)),
        "--min-highlight-score",
        str(float(min_highlight_score)),
        "--ui-delay-ms",
        str(int(ui_delay_ms)),
        "--page-render-wait-ms",
        str(int(page_render_wait_ms)),
        "--capture-dir",
        str(capture_dir),
        "--output-json",
        str(output_json),
    ]
    if bool(capture_highlighted):
        cmd.append("--capture-highlighted")
    return run_cmd(cmd, timeout_s=max(180, 20 * max(1, int(scroll_steps))))


def cmd_takeoff_copy_attempt(
    project_id: str,
    registry: str,
    condition_row: str,
    left_choice: str,
    monitor_index: int,
    match_score_threshold: float,
    cleanup_undo_count: int,
    attempt_style: str,
) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "takeoff-copy-attempt",
            "--project-id",
            project_id,
            "--registry",
            registry,
            "--condition-row",
            condition_row,
            "--left-choice",
            left_choice,
            "--monitor-index",
            str(monitor_index),
            "--match-score-threshold",
            str(match_score_threshold),
            "--cleanup-undo-count",
            str(cleanup_undo_count),
            "--attempt-style",
            attempt_style,
        ]
    )


def cmd_takeoff_copy_batch(
    project_id: str,
    registry: str,
    attempts: int,
    left_choice: str,
    monitor_index: int,
    match_score_threshold: float,
    cleanup_undo_count: int,
    attempt_style: str,
) -> int:
    bounded_attempts = max(1, int(attempts))
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "takeoff-copy-batch",
            "--project-id",
            project_id,
            "--registry",
            registry,
            "--attempts",
            str(bounded_attempts),
            "--left-choice",
            left_choice,
            "--monitor-index",
            str(monitor_index),
            "--match-score-threshold",
            str(match_score_threshold),
            "--cleanup-undo-count",
            str(cleanup_undo_count),
            "--attempt-style",
            attempt_style,
        ],
        timeout_s=max(180, 80 * bounded_attempts),
    )


def cmd_no_boost_area_attempt(
    project_id: str,
    registry: str,
    condition_row: str,
    monitor_index: int,
    match_score_threshold: float,
    cleanup_undo_count: int,
) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "no-boost-area-attempt",
            "--project-id",
            project_id,
            "--registry",
            registry,
            "--condition-row",
            condition_row,
            "--monitor-index",
            str(monitor_index),
            "--match-score-threshold",
            str(match_score_threshold),
            "--cleanup-undo-count",
            str(cleanup_undo_count),
        ]
    )


def cmd_no_boost_area_batch(
    project_id: str,
    registry: str,
    attempts: int,
    monitor_index: int,
    match_score_threshold: float,
    cleanup_undo_count: int,
) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "no-boost-area-batch",
            "--project-id",
            project_id,
            "--registry",
            registry,
            "--attempts",
            str(int(attempts)),
            "--monitor-index",
            str(monitor_index),
            "--match-score-threshold",
            str(match_score_threshold),
            "--cleanup-undo-count",
            str(cleanup_undo_count),
        ],
        timeout_s=max(180, int(attempts) * 90),
    )


def cmd_boost_then_copy_attempt(
    project_id: str,
    registry: str,
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
    user_start_x: int,
    user_start_y: int,
) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "boost-then-copy-attempt",
            "--project-id",
            project_id,
            "--registry",
            registry,
            "--monitor-index",
            str(monitor_index),
            "--condition-row",
            condition_row,
            "--left-choice",
            left_choice,
            "--match-score-threshold",
            str(match_score_threshold),
            "--cleanup-undo-count",
            str(cleanup_undo_count),
            "--attempt-style",
            attempt_style,
            "--boost-undo-count",
            str(boost_undo_count),
            "--boost-populate-timeout-ms",
            str(boost_populate_timeout_ms),
            "--boost-populate-poll-ms",
            str(boost_populate_poll_ms),
            "--boost-min-candidate-count",
            str(boost_min_candidate_count),
            "--user-start-x",
            str(int(user_start_x)),
            "--user-start-y",
            str(int(user_start_y)),
        ],
        timeout_s=420,
    )


def cmd_continuous_boost_copy(
    project_id: str,
    registry: str,
    monitor_index: int,
    attempts: int,
    summary_every: int,
    condition_row: str,
    left_choice: str,
    match_score_threshold: float,
    cleanup_undo_count: int,
    attempt_style: str,
) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "continuous-boost-copy",
            "--project-id",
            project_id,
            "--registry",
            registry,
            "--monitor-index",
            str(monitor_index),
            "--attempts",
            str(attempts),
            "--summary-every",
            str(summary_every),
            "--condition-row",
            condition_row,
            "--left-choice",
            left_choice,
            "--match-score-threshold",
            str(match_score_threshold),
            "--cleanup-undo-count",
            str(cleanup_undo_count),
            "--attempt-style",
            attempt_style,
        ],
        timeout_s=max(600, int(attempts) * 120),
    )


def cmd_maverick_style_walk(
    project_id: str,
    monitor_index: int,
    duration_seconds: int,
    interval_seconds: float,
    window_title_contains: str,
    emit_video: bool,
    video_fps: float,
    analyze_every_n: int,
    setup_config: str,
) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_style_walk.py",
        "--project-id",
        project_id,
        "--monitor-index",
        str(monitor_index),
        "--duration-seconds",
        str(duration_seconds),
        "--interval-seconds",
        str(interval_seconds),
        "--window-title-contains",
        window_title_contains,
        "--video-fps",
        str(video_fps),
        "--analyze-every-n",
        str(max(1, int(analyze_every_n))),
        "--setup-config",
        str(setup_config),
    ]
    if emit_video:
        cmd.append("--emit-video")
    return run_cmd(cmd)


def cmd_add_coaching_note(
    project_id: str,
    note: str,
    tags: str,
    registry: str,
    source: str,
    session_id: str,
) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "add-coaching-note",
            "--project-id",
            project_id,
            "--registry",
            registry,
            "--note",
            note,
            "--tags",
            tags,
            "--source",
            source,
            "--session-id",
            session_id,
        ]
    )


def cmd_protocol_prepare_batch(project_ids: str, registry: str) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_training_lab.py",
        "protocol-prepare-batch",
        "--project-ids",
        project_ids,
        "--registry",
        registry,
    ]
    return run_cmd(cmd)


def cmd_protocol_builder_intake(project_ids: str, registry: str) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_training_lab.py",
        "protocol-builder-intake",
        "--project-ids",
        project_ids,
        "--registry",
        registry,
    ]
    return run_cmd(cmd)


def cmd_protocol_create(protocol_type: str, project_ids: str, registry: str) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_training_lab.py",
        "protocol-create",
        "--protocol-type",
        protocol_type,
        "--project-ids",
        project_ids,
        "--registry",
        registry,
    ]
    return run_cmd(cmd)


def cmd_protocol_answer_intake(
    intake_id: str,
    protocol_type: str,
    answers_json: str,
    answers_json_inline: str,
    registry: str,
) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_training_lab.py",
        "protocol-answer-intake",
        "--intake-id",
        intake_id,
        "--protocol-type",
        protocol_type,
        "--answers-json",
        answers_json,
        "--answers-json-inline",
        answers_json_inline,
        "--registry",
        registry,
    ]
    return run_cmd(cmd)


def cmd_protocol_batch_ready(
    project_ids: str,
    protocol_type: str,
    answers_json: str,
    answers_json_inline: str,
    registry: str,
) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_training_lab.py",
        "protocol-batch-ready",
        "--project-ids",
        project_ids,
        "--protocol-type",
        protocol_type,
        "--answers-json",
        answers_json,
        "--answers-json-inline",
        answers_json_inline,
        "--registry",
        registry,
    ]
    return run_cmd(cmd)


def cmd_protocol_verify(
    protocol_id: str,
    approved: bool,
    verifier: str,
    notes: str,
) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_training_lab.py",
        "protocol-verify",
        "--protocol-id",
        protocol_id,
        "--verifier",
        verifier,
        "--notes",
        notes,
    ]
    if approved:
        cmd.append("--approved")
    else:
        cmd.append("--reject")
    return run_cmd(cmd)


def cmd_protocol_status(project_id: str) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "protocol-status",
            "--project-id",
            project_id,
        ]
    )


def cmd_run_module(module_id: str, project_id: str, registry: str, allow_unverified_protocol: bool = False) -> int:
    cmd = [
        sys.executable,
        "scripts/ost_training_lab.py",
        "run-module",
        "--module-id",
        module_id,
        "--project-id",
        project_id,
        "--registry",
        registry,
    ]
    if allow_unverified_protocol:
        cmd.append("--allow-unverified-protocol")
    return run_cmd(cmd)


def cmd_dashboard(last: int, registry: str) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/ost_training_lab.py",
            "dashboard",
            "--last",
            str(last),
            "--registry",
            registry,
        ]
    )


def cmd_maverick_always_on(config: str) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/maverick_runtime.py",
            "--config",
            config,
            "always-on",
        ]
    )


def cmd_maverick_chat(config: str, user: str, project: str, message: str) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/maverick_runtime.py",
            "--config",
            config,
            "chat",
            "--user",
            user,
            "--project",
            project,
            "--message",
            message,
        ]
    )


def cmd_maverick_summary(config: str, project: str, advance_cursor: bool) -> int:
    cmd = [
        sys.executable,
        "scripts/maverick_runtime.py",
        "--config",
        config,
        "summary",
        "--project",
        project,
    ]
    if advance_cursor:
        cmd.append("--advance-cursor")
    return run_cmd(cmd)


def cmd_maverick_blockers(config: str, project: str) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/maverick_runtime.py",
            "--config",
            config,
            "blockers",
            "--project",
            project,
        ]
    )


def cmd_maverick_failure_trends(config: str, project: str, top: int) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/maverick_runtime.py",
            "--config",
            config,
            "failure-trends",
            "--project",
            project,
            "--top",
            str(top),
        ]
    )


def cmd_maverick_quality_gates(config: str, project: str) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/maverick_runtime.py",
            "--config",
            config,
            "quality-gates",
            "--project",
            project,
        ]
    )


def cmd_maverick_startup_self_check(config: str) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/maverick_runtime.py",
            "--config",
            config,
            "startup-self-check",
        ]
    )


def cmd_maverick_daily_report(config: str, project: str, top: int) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/maverick_runtime.py",
            "--config",
            config,
            "daily-report",
            "--project",
            project,
            "--top",
            str(top),
        ]
    )


def cmd_maverick_daily_report_all(config: str, top: int) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/maverick_runtime.py",
            "--config",
            config,
            "daily-report-all",
            "--top",
            str(top),
        ]
    )


def cmd_maverick_log_step(
    config: str,
    project: str,
    action: str,
    outcome: str,
    archetype: str,
    expected: str,
    observed: str,
    error: str,
    resolution: str,
) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/maverick_runtime.py",
            "--config",
            config,
            "log-step",
            "--project",
            project,
            "--action",
            action,
            "--outcome",
            outcome,
            "--archetype",
            archetype,
            "--expected",
            expected,
            "--observed",
            observed,
            "--error",
            error,
            "--resolution",
            resolution,
        ]
    )


def cmd_maverick_record_click(
    config: str, project: str, archetype: str, x: int, y: int, context: str
) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/maverick_runtime.py",
            "--config",
            config,
            "record-click",
            "--project",
            project,
            "--archetype",
            archetype,
            "--x",
            str(x),
            "--y",
            str(y),
            "--context",
            context,
        ]
    )


def cmd_full_cycle(
    project_filter: str,
    dry_run: bool,
    intake_config: str,
    run_boost_module: bool,
    module_id: str,
    project_id: str,
    registry: str,
    allow_unverified_protocol: bool,
) -> int:
    rc = cmd_intake_once(project_filter=project_filter, dry_run=dry_run, config=intake_config)
    if rc != 0:
        return rc
    if run_boost_module:
        return cmd_run_module(
            module_id=module_id,
            project_id=project_id,
            registry=registry,
            allow_unverified_protocol=allow_unverified_protocol,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OST automation orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_intake_once = sub.add_parser("intake-once", help="Run one intake pass")
    p_intake_once.add_argument("--project-filter", default="")
    p_intake_once.add_argument("--dry-run", action="store_true")
    p_intake_once.add_argument("--intake-config", default="scripts/ost_project_intake.config.json")

    p_intake_watch = sub.add_parser("intake-watch", help="Run continuous intake watch")
    p_intake_watch.add_argument("--project-filter", default="")
    p_intake_watch.add_argument("--intake-config", default="scripts/ost_project_intake.config.json")

    p_discover = sub.add_parser("discover", help="Resolve project folder/pdf context")
    p_discover.add_argument("--project-id", required=True)
    p_discover.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_analyze = sub.add_parser(
        "training-notes",
        help="Analyze training DB and write detailed Maverick what/why notes",
    )
    p_analyze.add_argument("--project-id", required=True)
    p_analyze.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_post = sub.add_parser(
        "post-boost-edit-plan",
        help="Build ranked post-boost condition edit plan from learned operator style",
    )
    p_post.add_argument("--project-id", required=True)
    p_post.add_argument("--module-id", default="T06-boost-open-run-verify-L2")
    p_post.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_classify = sub.add_parser(
        "classify-item-types",
        help="Classify page item types from visual patterns",
    )
    p_classify.add_argument("--project-id", required=True)
    p_classify.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_classify.add_argument("--monitor-index", type=int, default=1)
    p_sym_ing = sub.add_parser(
        "symbol-knowledge-ingest",
        help="Ingest symbol dataset into local symbol knowledge index",
    )
    p_sym_ing.add_argument("--project-id", default="TP-0001")
    p_sym_ing.add_argument("--dataset-root", required=True)
    p_sym_ing.add_argument("--dataset-name", default="custom")
    p_sym_ing.add_argument("--output-root", default="")
    p_sym_ing.add_argument("--limit", type=int, default=0)
    p_sym_ing.add_argument("--min-per-class", type=int, default=3)
    p_sym_ing.add_argument("--max-file-size-mb", type=int, default=50)
    p_sym_ing.add_argument("--scan-max-files", type=int, default=0)
    p_sym_ing.add_argument("--allow-warnings", action="store_true")
    p_sym_ing.add_argument("--skip-safety-scan", action="store_true")
    p_sym_ing.add_argument("--quarantine-dir", default="")
    p_sym_q = sub.add_parser(
        "symbol-knowledge-query",
        help="Query local symbol knowledge index with one image",
    )
    p_sym_q.add_argument("--image", required=True)
    p_sym_q.add_argument("--index-json", required=True)
    p_sym_q.add_argument("--top-k", type=int, default=5)
    p_scan = sub.add_parser(
        "dataset-safety-scan",
        help="Scan a dataset root for unsafe file types before ingestion",
    )
    p_scan.add_argument("--dataset-root", required=True)
    p_scan.add_argument("--report-json", required=True)
    p_scan.add_argument("--max-file-size-mb", type=int, default=50)
    p_scan.add_argument("--max-files", type=int, default=0)
    p_finish_idx = sub.add_parser(
        "finish-knowledge-index-build",
        help="Build merged finish knowledge index from symbol and attempt artifacts",
    )
    p_finish_idx.add_argument("--project-id", default="TP-0001")
    p_finish_idx.add_argument("--symbol-index-glob", default="output/ost-training-lab/symbol_knowledge/*/symbol_index_*.json")
    p_finish_idx.add_argument("--attempt-glob", default="output/ost-training-lab/attempt_ATT-*.json")
    p_finish_idx.add_argument("--output-root", default="output/ost-training-lab/finish_knowledge")
    p_finish_idx.add_argument("--min-class-support", type=int, default=5)
    p_finish_idx.add_argument("--max-example-paths", type=int, default=20)
    p_accuracy_ingest = sub.add_parser(
        "accuracy-ingestion",
        help="Run accuracy-only ingestion across all knowledge domains",
    )
    p_accuracy_ingest.add_argument("--project-id", default="TP-0001")
    p_accuracy_ingest.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_accuracy_ingest.add_argument("--output-root", default="output/ost-training-lab/accuracy_knowledge")
    p_accuracy_ingest.add_argument("--finish-taxonomy-json", default="scripts/ost_finish_taxonomy.json")
    p_accuracy_ingest.add_argument("--attempt-glob", default="output/ost-training-lab/attempt_ATT-*.json")
    p_accuracy_ingest.add_argument("--training-notes-glob", default="output/ost-training-lab/training_notes_ANL-*.json")
    p_accuracy_ingest.add_argument("--symbol-dataset-root", default="")
    p_accuracy_ingest.add_argument("--symbol-dataset-name", default="accuracy_ingest")
    p_accuracy_ingest.add_argument(
        "--plan-pages-scan-json",
        default="output/ost-training-lab/plan_pages_highlight_scan_latest.json",
    )
    p_accuracy_ingest.add_argument("--plan-pages-scan-max-age-minutes", type=int, default=240)
    p_accuracy_ingest.add_argument(
        "--allow-missing-plan-pages-scan",
        action="store_true",
        help="Bypass enforced precheck for recent successful plan-pages-highlight-scan",
    )
    p_plan_pages = sub.add_parser(
        "plan-pages-highlight-scan",
        help="Scan Plan Pages dropdown and prioritize highlighted pages for ingestion",
    )
    p_plan_pages.add_argument("--monitor-index", type=int, default=1)
    p_plan_pages.add_argument("--window-title-contains", default="On-Screen Takeoff")
    p_plan_pages.add_argument("--setup-config", default="scripts/ost_project_setup_agent.config.json")
    p_plan_pages.add_argument("--scroll-steps", type=int, default=12)
    p_plan_pages.add_argument("--scroll-amount", type=int, default=400)
    p_plan_pages.add_argument("--list-width-px", type=int, default=760)
    p_plan_pages.add_argument("--list-height-px", type=int, default=620)
    p_plan_pages.add_argument("--row-height-px", type=int, default=24)
    p_plan_pages.add_argument("--min-highlight-score", type=float, default=0.07)
    p_plan_pages.add_argument("--ui-delay-ms", type=int, default=260)
    p_plan_pages.add_argument("--capture-highlighted", action="store_true")
    p_plan_pages.add_argument("--page-render-wait-ms", type=int, default=800)
    p_plan_pages.add_argument("--capture-dir", default="output/ost-training-lab/plan_page_captures")
    p_plan_pages.add_argument(
        "--output-json",
        default="output/ost-training-lab/plan_pages_highlight_scan_latest.json",
    )
    p_copy_attempt = sub.add_parser(
        "takeoff-copy-attempt",
        help="Run one classifier-guided copy attempt on a blank drawing",
    )
    p_copy_attempt.add_argument("--project-id", required=True)
    p_copy_attempt.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_copy_attempt.add_argument("--condition-row", choices=["first", "second"], default="first")
    p_copy_attempt.add_argument("--left-choice", choices=["nearest", "middle", "farthest"], default="middle")
    p_copy_attempt.add_argument("--monitor-index", type=int, default=1)
    p_copy_attempt.add_argument("--match-score-threshold", type=float, default=55.0)
    p_copy_attempt.add_argument("--cleanup-undo-count", type=int, default=2)
    p_copy_attempt.add_argument("--attempt-style", choices=["point", "polyline2", "polyline4"], default="polyline4")
    p_copy_batch = sub.add_parser(
        "takeoff-copy-batch",
        help="Run a batch of classifier-guided copy attempts",
    )
    p_copy_batch.add_argument("--project-id", required=True)
    p_copy_batch.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_copy_batch.add_argument("--attempts", type=int, default=5, help="Requested number of attempts.")
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
    p_no_boost.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_no_boost.add_argument("--condition-row", choices=["first", "second"], default="first")
    p_no_boost.add_argument("--monitor-index", type=int, default=1)
    p_no_boost.add_argument("--match-score-threshold", type=float, default=55.0)
    p_no_boost.add_argument("--cleanup-undo-count", type=int, default=2)
    p_no_boost_batch = sub.add_parser(
        "no-boost-area-batch",
        help="Run strict no-Boost area batch (ceiling/gwb only)",
    )
    p_no_boost_batch.add_argument("--project-id", required=True)
    p_no_boost_batch.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_no_boost_batch.add_argument("--attempts", type=int, default=10)
    p_no_boost_batch.add_argument("--monitor-index", type=int, default=1)
    p_no_boost_batch.add_argument("--match-score-threshold", type=float, default=55.0)
    p_no_boost_batch.add_argument("--cleanup-undo-count", type=int, default=2)
    p_boost_copy = sub.add_parser(
        "boost-then-copy-attempt",
        help="Run Boost, analyze, erase Boost result, then attempt copy on blank drawing",
    )
    p_boost_copy.add_argument("--project-id", required=True)
    p_boost_copy.add_argument("--registry", default="scripts/ost_training_registry.json")
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
        help="Run continuous autonomous boost->copy loop with periodic summaries",
    )
    p_cont.add_argument("--project-id", required=True)
    p_cont.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_cont.add_argument("--monitor-index", type=int, default=1)
    p_cont.add_argument("--attempts", type=int, default=20)
    p_cont.add_argument("--summary-every", type=int, default=10)
    p_cont.add_argument("--condition-row", choices=["first", "second"], default="first")
    p_cont.add_argument("--left-choice", choices=["nearest", "middle", "farthest"], default="nearest")
    p_cont.add_argument("--match-score-threshold", type=float, default=55.0)
    p_cont.add_argument("--cleanup-undo-count", type=int, default=2)
    p_cont.add_argument("--attempt-style", choices=["point", "polyline2", "polyline4"], default="polyline4")
    p_walk = sub.add_parser(
        "maverick-style-walk",
        help="Capture live OST page-scroll walkthrough for style learning",
    )
    p_walk.add_argument("--project-id", default="TP-0001")
    p_walk.add_argument("--monitor-index", type=int, default=1)
    p_walk.add_argument("--duration-seconds", type=int, default=90)
    p_walk.add_argument("--interval-seconds", type=float, default=1.8)
    p_walk.add_argument("--window-title-contains", default="On-Screen Takeoff")
    p_walk.add_argument("--emit-video", action="store_true")
    p_walk.add_argument("--video-fps", type=float, default=4.0)
    p_walk.add_argument("--analyze-every-n", type=int, default=1)
    p_walk.add_argument("--setup-config", default="scripts/ost_project_setup_agent.config.json")
    p_coach = sub.add_parser(
        "coach-note",
        help="Persist a user coaching note so Maverick learns operator-specific methods",
    )
    p_coach.add_argument("--project-id", required=True)
    p_coach.add_argument("--note", required=True)
    p_coach.add_argument("--tags", default="")
    p_coach.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_coach.add_argument("--source", default="user_coaching")
    p_coach.add_argument("--session-id", default="")
    p_proto_prep = sub.add_parser(
        "protocol-prepare-batch",
        help="Prepare protocol candidates by project type for user verification",
    )
    p_proto_prep.add_argument("--project-ids", default="")
    p_proto_prep.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_proto_builder = sub.add_parser(
        "protocol-builder-intake",
        help="Analyze selected projects and generate protocol-builder questions for user verification",
    )
    p_proto_builder.add_argument("--project-ids", default="")
    p_proto_builder.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_proto_create = sub.add_parser(
        "protocol-create",
        help="Explicitly create a typed protocol for selected projects",
    )
    p_proto_create.add_argument("--protocol-type", required=True)
    p_proto_create.add_argument("--project-ids", default="")
    p_proto_create.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_proto_answer = sub.add_parser(
        "protocol-answer-intake",
        help="Capture answers for a protocol intake and create draft protocol",
    )
    p_proto_answer.add_argument("--intake-id", required=True)
    p_proto_answer.add_argument("--protocol-type", default="")
    p_proto_answer.add_argument("--answers-json", default="")
    p_proto_answer.add_argument("--answers-json-inline", default="")
    p_proto_answer.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_proto_batch_ready = sub.add_parser(
        "protocol-batch-ready",
        help="One-command protocol intake + answer capture + draft creation",
    )
    p_proto_batch_ready.add_argument("--project-ids", default="")
    p_proto_batch_ready.add_argument("--protocol-type", default="")
    p_proto_batch_ready.add_argument("--answers-json", default="")
    p_proto_batch_ready.add_argument("--answers-json-inline", default="")
    p_proto_batch_ready.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_proto_verify = sub.add_parser(
        "protocol-verify",
        help="Approve or reject a protocol before Maverick starts",
    )
    p_proto_verify.add_argument("--protocol-id", required=True)
    p_proto_verify.add_argument("--approved", action="store_true")
    p_proto_verify.add_argument("--reject", action="store_true")
    p_proto_verify.add_argument("--verifier", default="travi")
    p_proto_verify.add_argument("--notes", default="")
    p_proto_status = sub.add_parser(
        "protocol-status",
        help="Show current protocol assignment/verification status for a project",
    )
    p_proto_status.add_argument("--project-id", required=True)

    p_run = sub.add_parser("run-module", help="Run one training module")
    p_run.add_argument("--module-id", default="T06-boost-open-run-verify-L2")
    p_run.add_argument("--project-id", required=True)
    p_run.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_run.add_argument("--allow-unverified-protocol", action="store_true")

    p_dash = sub.add_parser("dashboard", help="Show training dashboard")
    p_dash.add_argument("--last", type=int, default=10)
    p_dash.add_argument("--registry", default="scripts/ost_training_registry.json")

    p_cycle = sub.add_parser("full-cycle", help="Run intake then optional module")
    p_cycle.add_argument("--project-filter", default="")
    p_cycle.add_argument("--dry-run", action="store_true")
    p_cycle.add_argument("--intake-config", default="scripts/ost_project_intake.config.json")
    p_cycle.add_argument("--run-boost-module", action="store_true")
    p_cycle.add_argument("--module-id", default="T06-boost-open-run-verify-L2")
    p_cycle.add_argument("--project-id", default="TP-0001")
    p_cycle.add_argument("--registry", default="scripts/ost_training_registry.json")
    p_cycle.add_argument("--allow-unverified-protocol", action="store_true")

    p_mav_on = sub.add_parser(
        "maverick-always-on", help="Run Maverick with ordered startup and watchdog"
    )
    p_mav_on.add_argument("--config", default="scripts/maverick_runtime.config.json")

    p_mav_chat = sub.add_parser("maverick-chat", help="Send a message to Maverick")
    p_mav_chat.add_argument("--config", default="scripts/maverick_runtime.config.json")
    p_mav_chat.add_argument("--user", default="travi")
    p_mav_chat.add_argument("--project", default="")
    p_mav_chat.add_argument("--message", required=True)

    p_mav_sum = sub.add_parser(
        "maverick-summary", help="Summarize what Maverick has done since last time"
    )
    p_mav_sum.add_argument("--config", default="scripts/maverick_runtime.config.json")
    p_mav_sum.add_argument("--project", default="")
    p_mav_sum.add_argument("--advance-cursor", action="store_true")

    p_mav_blockers = sub.add_parser("maverick-blockers", help="Show unresolved Maverick blockers")
    p_mav_blockers.add_argument("--config", default="scripts/maverick_runtime.config.json")
    p_mav_blockers.add_argument("--project", default="")

    p_mav_trends = sub.add_parser("maverick-failure-trends", help="Show top failure archetypes")
    p_mav_trends.add_argument("--config", default="scripts/maverick_runtime.config.json")
    p_mav_trends.add_argument("--project", default="")
    p_mav_trends.add_argument("--top", type=int, default=10)

    p_mav_quality = sub.add_parser("maverick-quality-gates", help="Show scope and QA gate status")
    p_mav_quality.add_argument("--config", default="scripts/maverick_runtime.config.json")
    p_mav_quality.add_argument("--project", default="")

    p_mav_startup = sub.add_parser(
        "maverick-startup-self-check", help="Verify Maverick startup/dependency health"
    )
    p_mav_startup.add_argument("--config", default="scripts/maverick_runtime.config.json")

    p_mav_daily = sub.add_parser("maverick-daily-report", help="Generate consolidated Maverick daily report")
    p_mav_daily.add_argument("--config", default="scripts/maverick_runtime.config.json")
    p_mav_daily.add_argument("--project", default="")
    p_mav_daily.add_argument("--top", type=int, default=5)
    p_mav_daily_all = sub.add_parser(
        "maverick-daily-report-all", help="Generate daily reports for all tracked projects"
    )
    p_mav_daily_all.add_argument("--config", default="scripts/maverick_runtime.config.json")
    p_mav_daily_all.add_argument("--top", type=int, default=5)

    p_mav_step = sub.add_parser("maverick-log-step", help="Log step/failure/resolution")
    p_mav_step.add_argument("--config", default="scripts/maverick_runtime.config.json")
    p_mav_step.add_argument("--project", default="")
    p_mav_step.add_argument("--action", required=True)
    p_mav_step.add_argument("--outcome", required=True, choices=["success", "failure"])
    p_mav_step.add_argument("--archetype", required=True)
    p_mav_step.add_argument("--expected", default="")
    p_mav_step.add_argument("--observed", default="")
    p_mav_step.add_argument("--error", default="")
    p_mav_step.add_argument("--resolution", default="")

    p_mav_click = sub.add_parser(
        "maverick-record-click", help="Record guided clicks for post-failure coaching"
    )
    p_mav_click.add_argument("--config", default="scripts/maverick_runtime.config.json")
    p_mav_click.add_argument("--project", default="")
    p_mav_click.add_argument("--archetype", required=True)
    p_mav_click.add_argument("--x", type=int, required=True)
    p_mav_click.add_argument("--y", type=int, required=True)
    p_mav_click.add_argument("--context", default="")

    args = parser.parse_args()
    if args.cmd == "intake-once":
        return cmd_intake_once(args.project_filter, bool(args.dry_run), args.intake_config)
    if args.cmd == "intake-watch":
        return cmd_intake_watch(args.project_filter, args.intake_config)
    if args.cmd == "discover":
        return cmd_discover(args.project_id, args.registry)
    if args.cmd == "training-notes":
        return cmd_analyze_training_notes(args.project_id, args.registry)
    if args.cmd == "post-boost-edit-plan":
        return cmd_post_boost_edit_plan(args.project_id, args.module_id, args.registry)
    if args.cmd == "classify-item-types":
        return cmd_classify_item_types(args.project_id, args.registry, int(args.monitor_index))
    if args.cmd == "symbol-knowledge-ingest":
        return cmd_symbol_knowledge_ingest(
            project_id=args.project_id,
            dataset_root=args.dataset_root,
            dataset_name=args.dataset_name,
            output_root=args.output_root,
            limit=int(args.limit),
            min_per_class=int(args.min_per_class),
            max_file_size_mb=int(args.max_file_size_mb),
            scan_max_files=int(args.scan_max_files),
            allow_warnings=bool(args.allow_warnings),
            skip_safety_scan=bool(args.skip_safety_scan),
            quarantine_dir=str(args.quarantine_dir),
        )
    if args.cmd == "symbol-knowledge-query":
        return cmd_symbol_knowledge_query(
            image=args.image,
            index_json=args.index_json,
            top_k=int(args.top_k),
        )
    if args.cmd == "dataset-safety-scan":
        return cmd_dataset_safety_scan(
            dataset_root=args.dataset_root,
            report_json=args.report_json,
            max_file_size_mb=int(args.max_file_size_mb),
            max_files=int(args.max_files),
        )
    if args.cmd == "finish-knowledge-index-build":
        return cmd_finish_knowledge_index_build(
            project_id=args.project_id,
            symbol_index_glob=args.symbol_index_glob,
            attempt_glob=args.attempt_glob,
            output_root=args.output_root,
            min_class_support=int(args.min_class_support),
            max_example_paths=int(args.max_example_paths),
        )
    if args.cmd == "accuracy-ingestion":
        return cmd_accuracy_ingestion(
            project_id=args.project_id,
            registry=args.registry,
            output_root=args.output_root,
            finish_taxonomy_json=args.finish_taxonomy_json,
            attempt_glob=args.attempt_glob,
            training_notes_glob=args.training_notes_glob,
            symbol_dataset_root=args.symbol_dataset_root,
            symbol_dataset_name=args.symbol_dataset_name,
            require_plan_pages_scan=not bool(args.allow_missing_plan_pages_scan),
            plan_pages_scan_json=args.plan_pages_scan_json,
            plan_pages_scan_max_age_minutes=int(args.plan_pages_scan_max_age_minutes),
        )
    if args.cmd == "plan-pages-highlight-scan":
        return cmd_plan_pages_highlight_scan(
            monitor_index=int(args.monitor_index),
            window_title_contains=str(args.window_title_contains),
            setup_config=str(args.setup_config),
            scroll_steps=int(args.scroll_steps),
            scroll_amount=int(args.scroll_amount),
            list_width_px=int(args.list_width_px),
            list_height_px=int(args.list_height_px),
            row_height_px=int(args.row_height_px),
            min_highlight_score=float(args.min_highlight_score),
            ui_delay_ms=int(args.ui_delay_ms),
            capture_highlighted=bool(args.capture_highlighted),
            page_render_wait_ms=int(args.page_render_wait_ms),
            capture_dir=str(args.capture_dir),
            output_json=str(args.output_json),
        )
    if args.cmd == "takeoff-copy-attempt":
        return cmd_takeoff_copy_attempt(
            project_id=args.project_id,
            registry=args.registry,
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
            registry=args.registry,
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
            registry=args.registry,
            condition_row=args.condition_row,
            monitor_index=int(args.monitor_index),
            match_score_threshold=float(args.match_score_threshold),
            cleanup_undo_count=int(args.cleanup_undo_count),
        )
    if args.cmd == "no-boost-area-batch":
        return cmd_no_boost_area_batch(
            project_id=args.project_id,
            registry=args.registry,
            attempts=int(args.attempts),
            monitor_index=int(args.monitor_index),
            match_score_threshold=float(args.match_score_threshold),
            cleanup_undo_count=int(args.cleanup_undo_count),
        )
    if args.cmd == "boost-then-copy-attempt":
        return cmd_boost_then_copy_attempt(
            project_id=args.project_id,
            registry=args.registry,
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
            registry=args.registry,
            monitor_index=int(args.monitor_index),
            attempts=int(args.attempts),
            summary_every=int(args.summary_every),
            condition_row=args.condition_row,
            left_choice=args.left_choice,
            match_score_threshold=float(args.match_score_threshold),
            cleanup_undo_count=int(args.cleanup_undo_count),
            attempt_style=args.attempt_style,
        )
    if args.cmd == "maverick-style-walk":
        return cmd_maverick_style_walk(
            project_id=args.project_id,
            monitor_index=int(args.monitor_index),
            duration_seconds=int(args.duration_seconds),
            interval_seconds=float(args.interval_seconds),
            window_title_contains=str(args.window_title_contains),
            emit_video=bool(args.emit_video),
            video_fps=float(args.video_fps),
            analyze_every_n=int(args.analyze_every_n),
            setup_config=str(args.setup_config),
        )
    if args.cmd == "coach-note":
        return cmd_add_coaching_note(
            project_id=args.project_id,
            note=args.note,
            tags=args.tags,
            registry=args.registry,
            source=args.source,
            session_id=args.session_id,
        )
    if args.cmd == "protocol-prepare-batch":
        return cmd_protocol_prepare_batch(args.project_ids, args.registry)
    if args.cmd == "protocol-builder-intake":
        return cmd_protocol_builder_intake(args.project_ids, args.registry)
    if args.cmd == "protocol-create":
        return cmd_protocol_create(args.protocol_type, args.project_ids, args.registry)
    if args.cmd == "protocol-answer-intake":
        return cmd_protocol_answer_intake(
            intake_id=args.intake_id,
            protocol_type=args.protocol_type,
            answers_json=args.answers_json,
            answers_json_inline=args.answers_json_inline,
            registry=args.registry,
        )
    if args.cmd == "protocol-batch-ready":
        return cmd_protocol_batch_ready(
            project_ids=args.project_ids,
            protocol_type=args.protocol_type,
            answers_json=args.answers_json,
            answers_json_inline=args.answers_json_inline,
            registry=args.registry,
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
    if args.cmd == "run-module":
        return cmd_run_module(
            args.module_id,
            args.project_id,
            args.registry,
            allow_unverified_protocol=bool(args.allow_unverified_protocol),
        )
    if args.cmd == "dashboard":
        return cmd_dashboard(args.last, args.registry)
    if args.cmd == "full-cycle":
        return cmd_full_cycle(
            project_filter=args.project_filter,
            dry_run=bool(args.dry_run),
            intake_config=args.intake_config,
            run_boost_module=bool(args.run_boost_module),
            module_id=args.module_id,
            project_id=args.project_id,
            registry=args.registry,
            allow_unverified_protocol=bool(args.allow_unverified_protocol),
        )
    if args.cmd == "maverick-always-on":
        return cmd_maverick_always_on(args.config)
    if args.cmd == "maverick-chat":
        return cmd_maverick_chat(args.config, args.user, args.project, args.message)
    if args.cmd == "maverick-summary":
        return cmd_maverick_summary(args.config, args.project, bool(args.advance_cursor))
    if args.cmd == "maverick-blockers":
        return cmd_maverick_blockers(args.config, args.project)
    if args.cmd == "maverick-failure-trends":
        return cmd_maverick_failure_trends(args.config, args.project, int(args.top))
    if args.cmd == "maverick-quality-gates":
        return cmd_maverick_quality_gates(args.config, args.project)
    if args.cmd == "maverick-startup-self-check":
        return cmd_maverick_startup_self_check(args.config)
    if args.cmd == "maverick-daily-report":
        return cmd_maverick_daily_report(args.config, args.project, int(args.top))
    if args.cmd == "maverick-daily-report-all":
        return cmd_maverick_daily_report_all(args.config, int(args.top))
    if args.cmd == "maverick-log-step":
        return cmd_maverick_log_step(
            config=args.config,
            project=args.project,
            action=args.action,
            outcome=args.outcome,
            archetype=args.archetype,
            expected=args.expected,
            observed=args.observed,
            error=args.error,
            resolution=args.resolution,
        )
    if args.cmd == "maverick-record-click":
        return cmd_maverick_record_click(
            config=args.config,
            project=args.project,
            archetype=args.archetype,
            x=args.x,
            y=args.y,
            context=args.context,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
