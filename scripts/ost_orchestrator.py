#!/usr/bin/env python3
"""
OST Orchestrator

Single entrypoint for intake, analysis, setup, and training automation.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
from typing import List

WORKSPACE_ROOT = pathlib.Path(__file__).resolve().parent.parent


def run_cmd(cmd: List[str]) -> int:
    print("RUN>", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT))
    return proc.returncode


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
            str(attempts),
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
        ]
    )


def cmd_maverick_style_walk(
    project_id: str,
    monitor_index: int,
    duration_seconds: int,
    interval_seconds: float,
    window_title_contains: str,
) -> int:
    return run_cmd(
        [
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
        ]
    )


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
    p_copy_batch.add_argument("--attempts", type=int, default=4)
    p_copy_batch.add_argument("--left-choice", choices=["nearest", "middle", "farthest"], default="middle")
    p_copy_batch.add_argument("--monitor-index", type=int, default=1)
    p_copy_batch.add_argument("--match-score-threshold", type=float, default=55.0)
    p_copy_batch.add_argument("--cleanup-undo-count", type=int, default=2)
    p_copy_batch.add_argument("--attempt-style", choices=["point", "polyline2", "polyline4"], default="polyline4")
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
    p_walk = sub.add_parser(
        "maverick-style-walk",
        help="Capture live OST page-scroll walkthrough for style learning",
    )
    p_walk.add_argument("--project-id", default="TP-0001")
    p_walk.add_argument("--monitor-index", type=int, default=1)
    p_walk.add_argument("--duration-seconds", type=int, default=90)
    p_walk.add_argument("--interval-seconds", type=float, default=1.8)
    p_walk.add_argument("--window-title-contains", default="On-Screen Takeoff")
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
        )
    if args.cmd == "maverick-style-walk":
        return cmd_maverick_style_walk(
            project_id=args.project_id,
            monitor_index=int(args.monitor_index),
            duration_seconds=int(args.duration_seconds),
            interval_seconds=float(args.interval_seconds),
            window_title_contains=str(args.window_title_contains),
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
