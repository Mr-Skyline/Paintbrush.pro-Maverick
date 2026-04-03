#!/usr/bin/env python3
"""
Maverick runtime controller.

Provides:
- always-on dependency startup in strict sequence
- dependency health watchdog and dependency-first recovery
- step/failure/resolution audit logging
- conversation memory and delta summaries
- 10-failure coaching trigger + click learning logs
- suggest-only update proposal queue
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG: Dict[str, Any] = {
    "agent_name": "Maverick",
    "output_root": "output/maverick",
    "lock_file": "output/maverick/runtime.lock",
    "runtime": {
        "heartbeat_seconds": 4,
        "stability_window_seconds": 8,
        "boot_retry_limit": 3,
        "restart_backoff_seconds": 3,
        "coach_failure_threshold": 10,
    },
    "update_policy": "suggest-only",
    "quality": {
        "exclude_project_name_patterns": ["backup", "archive"],
    },
    "dependencies": [
        {
            "id": "training_db_monitor",
            "enabled": True,
            "startup_delay_seconds": 1,
            "ready_timeout_seconds": 10,
            "command": [
                "{python}",
                "scripts/monitor_ost_training_db.py",
                "--file",
                r"C:\OCS Documents\OST\Training Playground.mdb",
                "--log",
                "output/maverick/training_db_monitor.jsonl",
            ],
        },
        {
            "id": "intake_watch",
            "enabled": True,
            "startup_delay_seconds": 2,
            "ready_timeout_seconds": 12,
            "command": [
                "{python}",
                "scripts/ost_project_intake.py",
                "--config",
                "scripts/ost_project_intake.config.json",
                "--watch",
            ],
        },
    ],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: pathlib.Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, payload: Any) -> None:
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
    cfg = dict(DEFAULT_CONFIG)
    raw = read_json(path, {})
    cfg.update(raw if isinstance(raw, dict) else {})
    runtime = dict(DEFAULT_CONFIG["runtime"])
    runtime.update(cfg.get("runtime", {}) or {})
    cfg["runtime"] = runtime
    return cfg


def workspace_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def render_tokens(value: str, root: pathlib.Path) -> str:
    return (
        str(value)
        .replace("{python}", sys.executable)
        .replace("{workspace}", str(root))
        .replace("{agent}", "Maverick")
    )


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        # Windows can raise access errors for existing processes; fall back to tasklist.
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            text = (proc.stdout or "") + "\n" + (proc.stderr or "")
            return str(pid) in text
        except Exception:
            return False
    except Exception:
        return False
    return True


@dataclass
class DependencyHandle:
    dep_id: str
    command: List[str]
    startup_delay_seconds: int
    ready_timeout_seconds: int
    process: Optional[subprocess.Popen[str]] = None
    start_ts: float = 0.0

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def pid(self) -> Optional[int]:
        return None if self.process is None else self.process.pid


class MaverickRuntime:
    def __init__(self, config_path: pathlib.Path):
        self.root = workspace_root()
        self.config_path = config_path
        self.config = load_config(config_path)
        self.agent_name = str(self.config.get("agent_name", "Maverick"))
        self.output_root = self.root / str(self.config.get("output_root", "output/maverick"))
        self.lock_file = self.root / str(self.config.get("lock_file", "output/maverick/runtime.lock"))
        self.runtime_cfg = self.config.get("runtime", {}) or {}
        self.heartbeat_seconds = max(1, int(self.runtime_cfg.get("heartbeat_seconds", 4)))
        self.stability_window_seconds = max(3, int(self.runtime_cfg.get("stability_window_seconds", 8)))
        self.boot_retry_limit = max(1, int(self.runtime_cfg.get("boot_retry_limit", 3)))
        self.restart_backoff_seconds = max(1, int(self.runtime_cfg.get("restart_backoff_seconds", 3)))
        self.coach_failure_threshold = max(1, int(self.runtime_cfg.get("coach_failure_threshold", 10)))
        self.update_policy = str(self.config.get("update_policy", "suggest-only"))
        self.quality_cfg = self.config.get("quality", {}) or {}
        self.session_id = f"session-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:6]}"

        self.state_file = self.output_root / "runtime_state.json"
        self.event_log = self.output_root / "runtime_events.jsonl"
        self.step_log = self.output_root / "step_log.jsonl"
        self.failures_file = self.output_root / "failures.json"
        self.coach_file = self.output_root / "coach_requests.jsonl"
        self.click_log = self.output_root / "click_learning.jsonl"
        self.conversation_file = self.output_root / "conversations.jsonl"
        self.summary_cursor_file = self.output_root / "summary_cursor.json"
        self.proposals_file = self.output_root / "proposed_updates.md"
        self.learned_rules_file = self.output_root / "learned_rules.json"

        self.dependencies: List[DependencyHandle] = []
        self.state: str = "booting"
        self.maverick_online = False
        self._last_green_at = 0.0
        self._last_state_emit: Dict[str, Any] = {"state": "", "note": "", "maverick_online": None}

    def _log_runtime_event(self, event: str, **kwargs: Any) -> None:
        payload = {
            "ts": utc_now_iso(),
            "session_id": self.session_id,
            "event": event,
            "state": self.state,
            "maverick_online": self.maverick_online,
        }
        payload.update(kwargs)
        append_jsonl(self.event_log, payload)

    def _write_state(self, note: str = "") -> None:
        payload = {
            "ts": utc_now_iso(),
            "session_id": self.session_id,
            "state": self.state,
            "maverick_online": self.maverick_online,
            "note": note,
            "dependencies": [
                {
                    "id": d.dep_id,
                    "pid": d.pid(),
                    "running": d.is_running(),
                    "start_ts": d.start_ts,
                }
                for d in self.dependencies
            ],
        }
        write_json(self.state_file, payload)

    def _set_state(self, state: str, note: str = "") -> None:
        self.state = state
        self._write_state(note=note)
        if (
            self._last_state_emit.get("state") == self.state
            and self._last_state_emit.get("note") == note
            and self._last_state_emit.get("maverick_online") == self.maverick_online
        ):
            return
        self._last_state_emit = {
            "state": self.state,
            "note": note,
            "maverick_online": self.maverick_online,
        }
        self._log_runtime_event("state_changed", note=note)

    def _acquire_lock(self) -> None:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_file.exists():
            try:
                data = read_json(self.lock_file, {})
                pid = int((data or {}).get("pid", 0))
                if pid > 0 and not pid_alive(pid):
                    # stale lock from crashed/terminated runtime; safe to clear.
                    self.lock_file.unlink(missing_ok=True)
                    self._log_runtime_event("stale_lock_cleared", stale_pid=pid)
                    return self._acquire_lock()
                if pid > 0:
                    self._log_runtime_event("lock_exists", existing_pid=pid)
                    raise RuntimeError(
                        f"runtime lock exists ({self.lock_file}); another Maverick runtime may already be active"
                    )
            except Exception as exc:
                raise RuntimeError(f"runtime lock exists ({self.lock_file})") from exc
        write_json(
            self.lock_file,
            {"pid": os.getpid(), "ts": utc_now_iso(), "session_id": self.session_id},
        )

    def _release_lock(self) -> None:
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
        except Exception:
            pass

    def _load_dependencies(self) -> None:
        deps = self.config.get("dependencies", []) or []
        out: List[DependencyHandle] = []
        for raw in deps:
            if not isinstance(raw, dict):
                continue
            if not bool(raw.get("enabled", True)):
                continue
            dep_id = str(raw.get("id", "")).strip()
            if not dep_id:
                continue
            cmd_raw = raw.get("command", []) or []
            cmd = [render_tokens(str(x), self.root) for x in cmd_raw]
            if not cmd:
                continue
            out.append(
                DependencyHandle(
                    dep_id=dep_id,
                    command=cmd,
                    startup_delay_seconds=max(0, int(raw.get("startup_delay_seconds", 1))),
                    ready_timeout_seconds=max(2, int(raw.get("ready_timeout_seconds", 10))),
                )
            )
        self.dependencies = out

    def _start_dependency(self, dep: DependencyHandle) -> bool:
        self._log_runtime_event("dependency_starting", dep_id=dep.dep_id, command=dep.command)
        try:
            dep.process = subprocess.Popen(
                dep.command,
                cwd=str(self.root),
                text=True,
            )
            dep.start_ts = time.time()
        except Exception as exc:
            self._log_step(
                action="dependency_start",
                outcome="failure",
                archetype=f"startup:{dep.dep_id}",
                expected="process starts",
                observed="start exception",
                error=str(exc),
            )
            return False

        ready_deadline = time.time() + dep.ready_timeout_seconds
        while time.time() < ready_deadline:
            if dep.process is None:
                break
            if dep.process.poll() is not None:
                self._log_step(
                    action="dependency_start",
                    outcome="failure",
                    archetype=f"startup:{dep.dep_id}",
                    expected="long-running process alive",
                    observed=f"process exited rc={dep.process.returncode}",
                    error=f"dependency exited early: {dep.dep_id}",
                )
                return False
            if time.time() - dep.start_ts >= dep.startup_delay_seconds:
                self._log_step(
                    action="dependency_start",
                    outcome="success",
                    archetype=f"startup:{dep.dep_id}",
                    expected="process alive after startup delay",
                    observed="process alive",
                )
                self._log_runtime_event("dependency_ready", dep_id=dep.dep_id, pid=dep.pid())
                return True
            time.sleep(0.25)

        self._log_step(
            action="dependency_start",
            outcome="failure",
            archetype=f"startup:{dep.dep_id}",
            expected="ready before timeout",
            observed="startup timeout",
            error=f"dependency did not become ready in {dep.ready_timeout_seconds}s",
        )
        return False

    def _stop_dependency(self, dep: DependencyHandle) -> None:
        p = dep.process
        if p is None:
            return
        if p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=6)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        dep.process = None

    def _all_dependencies_running(self) -> bool:
        return all(d.is_running() for d in self.dependencies)

    def _boot_dependencies(self) -> bool:
        for dep in self.dependencies:
            ok = False
            for _ in range(self.boot_retry_limit):
                if self._start_dependency(dep):
                    ok = True
                    break
                time.sleep(self.restart_backoff_seconds)
            if not ok:
                self._log_runtime_event("dependency_boot_failed", dep_id=dep.dep_id)
                return False
        return True

    def _degraded_recover(self) -> None:
        self.maverick_online = False
        self._set_state("degraded", note="dependency failure detected; entering recovery")
        for dep in self.dependencies:
            if dep.is_running():
                continue
            self._log_runtime_event("dependency_recovery_start", dep_id=dep.dep_id)
            self._stop_dependency(dep)
            ok = False
            for _ in range(self.boot_retry_limit):
                if self._start_dependency(dep):
                    ok = True
                    break
                time.sleep(self.restart_backoff_seconds)
            if not ok:
                self._log_runtime_event("dependency_recovery_failed", dep_id=dep.dep_id)
                return
        self._last_green_at = time.time()
        self._set_state("deps_ready", note="dependencies recovered")

    def _log_step(
        self,
        action: str,
        outcome: str,
        archetype: str,
        expected: str,
        observed: str,
        project: str = "",
        error: str = "",
        resolution: str = "",
    ) -> None:
        row = {
            "ts": utc_now_iso(),
            "session_id": self.session_id,
            "project": project,
            "action": action,
            "archetype": archetype,
            "expected": expected,
            "observed": observed,
            "outcome": outcome,
            "error": error,
            "resolution": resolution,
        }
        append_jsonl(self.step_log, row)
        if outcome.lower() == "failure":
            self._register_failure(archetype=archetype, project=project, reason=error or observed)
        if outcome.lower() == "success" and archetype:
            self._resolve_failure(archetype=archetype, project=project, resolution=resolution or "success")

    def _register_failure(self, archetype: str, project: str, reason: str) -> None:
        payload = read_json(self.failures_file, {"counts": {}, "history": []})
        counts = payload.setdefault("counts", {})
        key = f"{project or '_global'}::{archetype}"
        entry = counts.get(key, {"count": 0, "last_reason": "", "last_ts": ""})
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_reason"] = reason
        entry["last_ts"] = utc_now_iso()
        counts[key] = entry
        payload.setdefault("history", []).append(
            {
                "ts": utc_now_iso(),
                "project": project,
                "archetype": archetype,
                "reason": reason,
                "event": "failure",
            }
        )
        write_json(self.failures_file, payload)
        if int(entry["count"]) >= self.coach_failure_threshold:
            self._create_coach_request(project=project, archetype=archetype, count=int(entry["count"]), reason=reason)

    def _resolve_failure(self, archetype: str, project: str, resolution: str) -> None:
        payload = read_json(self.failures_file, {"counts": {}, "history": []})
        key = f"{project or '_global'}::{archetype}"
        counts = payload.setdefault("counts", {})
        if key in counts:
            counts[key]["count"] = 0
            counts[key]["last_resolution"] = resolution
            counts[key]["resolved_ts"] = utc_now_iso()
        payload.setdefault("history", []).append(
            {
                "ts": utc_now_iso(),
                "project": project,
                "archetype": archetype,
                "resolution": resolution,
                "event": "resolved",
            }
        )
        write_json(self.failures_file, payload)
        self._resolve_pending_coach_requests(archetype=archetype, project=project, resolution=resolution)

    def _resolve_pending_coach_requests(self, archetype: str, project: str, resolution: str) -> None:
        if not self.coach_file.exists():
            return
        lines = self.coach_file.read_text(encoding="utf-8").splitlines()
        updated: List[Dict[str, Any]] = []
        changed = False
        now = utc_now_iso()
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if (
                isinstance(row, dict)
                and row.get("status") == "pending"
                and str(row.get("archetype", "")) == archetype
                and (not project or str(row.get("project", "")) in {project, ""})
            ):
                row["status"] = "resolved"
                row["resolved_ts"] = now
                row["resolution"] = resolution
                changed = True
            updated.append(row)
        if not changed:
            return
        self.coach_file.parent.mkdir(parents=True, exist_ok=True)
        with self.coach_file.open("w", encoding="utf-8") as f:
            for row in updated:
                f.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _create_coach_request(self, project: str, archetype: str, count: int, reason: str) -> None:
        req = {
            "ts": utc_now_iso(),
            "project": project,
            "archetype": archetype,
            "count": count,
            "reason": reason,
            "status": "pending",
            "questions": [
                f"Please show Maverick the expected workflow for '{archetype}'.",
                "After you demonstrate it, run click capture so Maverick can learn your exact interaction.",
            ],
        }
        append_jsonl(self.coach_file, req)
        self._propose_update(
            title=f"Coach workflow capture for {archetype}",
            reason=f"{count} consecutive failures reached threshold",
            impact="Improve interaction reliability on this workflow",
            risk="low",
            rollback="Discard captured click playbook entry if incorrect",
        )

    def _propose_update(self, title: str, reason: str, impact: str, risk: str, rollback: str) -> None:
        if self.update_policy != "suggest-only":
            # Guardrail currently selected by user: suggest-only.
            return
        self.proposals_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.proposals_file.exists():
            self.proposals_file.write_text("# Proposed Updates (Manual Approval Required)\n\n", encoding="utf-8")
        with self.proposals_file.open("a", encoding="utf-8") as f:
            f.write(
                f"## {utc_now_iso()} - {title}\n"
                f"- reason: {reason}\n"
                f"- expected_impact: {impact}\n"
                f"- risk_level: {risk}\n"
                f"- rollback: {rollback}\n\n"
            )

    def _extract_learning(self, message: str) -> List[str]:
        learned: List[str] = []
        lower = (message or "").lower()
        triggers = ["must", "should", "need", "always", "prefer", "important"]
        if any(t in lower for t in triggers):
            learned.append(message.strip())
        return learned

    def _save_learnings(self, learnings: List[str]) -> None:
        if not learnings:
            return
        data = read_json(self.learned_rules_file, {"rules": []})
        rules = data.setdefault("rules", [])
        for item in learnings:
            if item and item not in rules:
                rules.append(item)
        write_json(self.learned_rules_file, data)

    def chat(self, user: str, project: str, message: str) -> Dict[str, Any]:
        user = user.strip() or "travi"
        project = project.strip()
        msg = message.strip()
        if not msg:
            return {"ok": False, "error": "empty_message"}

        conversation_id = f"conv-{uuid.uuid4().hex[:10]}"
        append_jsonl(
            self.conversation_file,
            {
                "ts": utc_now_iso(),
                "conversation_id": conversation_id,
                "role": "user",
                "user": user,
                "project": project,
                "message": msg,
            },
        )

        learnings = self._extract_learning(msg)
        self._save_learnings(learnings)
        for item in learnings:
            self._propose_update(
                title="Captured user operating preference",
                reason=item[:180],
                impact="Improve Maverick behavior consistency",
                risk="low",
                rollback="Remove this preference from learned_rules.json",
            )

        response = self._build_chat_response(project=project, message=msg)
        append_jsonl(
            self.conversation_file,
            {
                "ts": utc_now_iso(),
                "conversation_id": conversation_id,
                "role": "assistant",
                "agent": self.agent_name,
                "project": project,
                "message": response,
            },
        )
        return {"ok": True, "agent": self.agent_name, "response": response}

    def _build_chat_response(self, project: str, message: str) -> str:
        lower = message.lower()
        if "blocker" in lower or "blocked" in lower:
            blockers = self.blockers(project=project)
            return blockers.get("summary", "No unresolved blockers found.")
        if "failed most" in lower or "failure trend" in lower or "most failures" in lower:
            trends = self.failure_trends(project=project, top=5)
            return trends.get("summary", "No failure trend data found.")
        if "quality" in lower or "scope status" in lower or "qa" in lower:
            gates = self.quality_gates(project=project)
            return gates.get("summary", "No quality gate data found.")
        if "since last" in lower or "summary" in lower or "what changed" in lower:
            summary = self.summary(project=project, advance_cursor=True)
            return summary.get("summary", "No changes found since last summary.")

        pending = self._pending_coach_for_project(project)
        if pending:
            return (
                f"{self.agent_name}: I have a pending coaching request for '{pending.get('archetype', 'workflow')}' "
                "after repeated failures. Please demonstrate the flow, then record guidance clicks."
            )

        return (
            f"{self.agent_name}: Logged. I will apply this guidance to project operations and keep a step-by-step "
            "audit trail including failures and resolutions."
        )

    def _pending_coach_for_project(self, project: str) -> Optional[Dict[str, Any]]:
        if not self.coach_file.exists():
            return None
        lines = self.coach_file.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("status") != "pending":
                continue
            if project and row.get("project") and row.get("project") != project:
                continue
            return row
        return None

    def _project_filter_match(self, project_filter: str, project_path: str) -> bool:
        if not project_filter:
            return True
        return project_filter.lower() in (project_path or "").lower()

    def _project_excluded(self, project_path: str) -> bool:
        patterns = self.quality_cfg.get("exclude_project_name_patterns", []) if isinstance(self.quality_cfg, dict) else []
        low = (project_path or "").lower()
        for pat in patterns or []:
            if str(pat).strip().lower() and str(pat).strip().lower() in low:
                return True
        return False

    def _collect_scope_quality(self, project_filter: str) -> Dict[str, Any]:
        state_path = self.root / "output/ost-project-intake/state.json"
        state = read_json(state_path, {"projects": {}})
        projects = state.get("projects", {}) if isinstance(state, dict) else {}
        considered = 0
        with_scope_profile = 0
        with_scope_intel = 0
        total_conflicts = 0
        critical_conflicts = 0
        warn_conflicts = 0
        high_confidence_conflicts = 0
        medium_confidence_conflicts = 0
        low_confidence_conflicts = 0
        actionable_conflicts = 0
        informational_conflicts = 0
        total_docs = 0
        total_work_packages = 0
        warnings: List[str] = []
        excluded_projects = 0
        incomplete_projects: List[str] = []

        for project_path in projects.keys():
            if not self._project_filter_match(project_filter, str(project_path)):
                continue
            if self._project_excluded(str(project_path)):
                excluded_projects += 1
                continue
            considered += 1
            p = pathlib.Path(str(project_path))
            reports = p / "_reports"
            scope_profile = reports / "scope_profile.json"
            scope_intel = reports / "project_scope_intel.json"
            intake_manifest = reports / "intake_manifest.json"
            if intake_manifest.exists():
                im = read_json(intake_manifest, {})
                scope_meta = (im.get("scope_intel") or {}) if isinstance(im, dict) else {}
                profile_meta = (im.get("scope_profile") or {}) if isinstance(im, dict) else {}
                if bool(scope_meta.get("incomplete", False)) or bool(scope_meta.get("timed_out", False)):
                    incomplete_projects.append(f"{p.name}:scope_intel")
                if bool(profile_meta.get("timed_out", False)):
                    incomplete_projects.append(f"{p.name}:scope_profile")

            if scope_profile.exists():
                with_scope_profile += 1
                data = read_json(scope_profile, {})
                wps = data.get("work_packages", []) if isinstance(data, dict) else []
                total_work_packages += len(wps) if isinstance(wps, list) else 0
            else:
                warnings.append(f"missing scope_profile: {p.name}")

            if scope_intel.exists():
                with_scope_intel += 1
                data = read_json(scope_intel, {})
                conflicts = data.get("conflicts", []) if isinstance(data, dict) else []
                total_conflicts += len(conflicts) if isinstance(conflicts, list) else 0
                summary = data.get("conflict_summary", {}) if isinstance(data, dict) else {}
                if isinstance(summary, dict):
                    critical_conflicts += int(summary.get("critical", 0) or 0)
                    warn_conflicts += int(summary.get("warn", 0) or 0)
                    high_confidence_conflicts += int(summary.get("high_confidence", 0) or 0)
                    medium_confidence_conflicts += int(summary.get("medium_confidence", 0) or 0)
                    low_confidence_conflicts += int(summary.get("low_confidence", 0) or 0)
                    actionable_conflicts += int(summary.get("actionable", 0) or 0)
                    informational_conflicts += int(summary.get("informational", 0) or 0)
                    if (
                        isinstance(conflicts, list)
                        and len(conflicts) > 0
                        and int(summary.get("critical", 0) or 0) == 0
                        and int(summary.get("warn", 0) or 0) == 0
                    ):
                        # Legacy reports may omit conflict-summary buckets.
                        # Fall back to conservative assumptions so confidence metrics are non-empty.
                        warn_conflicts += len(conflicts)
                        low_confidence_conflicts += len(conflicts)
                        informational_conflicts += len(conflicts)
                elif isinstance(conflicts, list):
                    # Backward-compatible fallback for older reports.
                    critical_conflicts += sum(
                        1 for c in conflicts if isinstance(c, dict) and c.get("severity") == "critical"
                    )
                    warn_conflicts += sum(
                        1 for c in conflicts if isinstance(c, dict) and c.get("severity") == "warn"
                    )
                    high_confidence_conflicts += sum(
                        1 for c in conflicts if isinstance(c, dict) and c.get("confidence") == "high"
                    )
                    medium_confidence_conflicts += sum(
                        1 for c in conflicts if isinstance(c, dict) and c.get("confidence") == "medium"
                    )
                    low_confidence_conflicts += sum(
                        1 for c in conflicts if isinstance(c, dict) and c.get("confidence") == "low"
                    )
                    actionable_conflicts += sum(
                        1
                        for c in conflicts
                        if isinstance(c, dict)
                        and (c.get("severity") == "critical" or c.get("confidence") in {"high", "medium"})
                    )
                    informational_conflicts += sum(
                        1
                        for c in conflicts
                        if isinstance(c, dict)
                        and c.get("severity") != "critical"
                        and c.get("confidence") == "low"
                    )
                total_docs += int((data.get("document_count", 0) if isinstance(data, dict) else 0) or 0)
            else:
                warnings.append(f"missing project_scope_intel: {p.name}")

        if considered == 0:
            coverage_status = "warn"
        elif with_scope_profile == considered and with_scope_intel == considered:
            coverage_status = "pass"
        else:
            coverage_status = "warn"
        if incomplete_projects:
            coverage_status = "warn"

        # Consistency gates use critical conflicts as primary signal, but very high warning
        # volume still indicates noisy/inconsistent source inputs that need review.
        if critical_conflicts == 0:
            consistency_status = "pass" if warn_conflicts <= 20 else "warn"
        else:
            consistency_status = "warn" if critical_conflicts <= 3 else "fail"
        work_pkg_status = "pass" if total_work_packages > 0 else "warn"

        return {
            "considered_projects": considered,
            "excluded_projects": excluded_projects,
            "with_scope_profile": with_scope_profile,
            "with_scope_intel": with_scope_intel,
            "total_conflicts": total_conflicts,
            "critical_conflicts": critical_conflicts,
            "warn_conflicts": warn_conflicts,
            "high_confidence_conflicts": high_confidence_conflicts,
            "medium_confidence_conflicts": medium_confidence_conflicts,
            "low_confidence_conflicts": low_confidence_conflicts,
            "actionable_conflicts": actionable_conflicts,
            "informational_conflicts": informational_conflicts,
            "total_documents": total_docs,
            "total_work_packages": total_work_packages,
            "coverage_status": coverage_status,
            "consistency_status": consistency_status,
            "work_package_status": work_pkg_status,
            "warnings": warnings[:20],
            "incomplete_projects": incomplete_projects[:20],
        }

    def _collect_estimator_qa(self, project_filter: str) -> Dict[str, Any]:
        attempts_dir = self.root / "output/ost-training-lab"
        attempt_files = (
            sorted(attempts_dir.glob("attempt_ATT-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if attempts_dir.exists()
            else []
        )
        selected_rows: List[Dict[str, Any]] = []
        for p in attempt_files:
            row = read_json(p, {})
            if not isinstance(row, dict):
                continue
            if project_filter:
                project_name = str(row.get("project_name", "")).lower()
                project_id = str(row.get("training_project_id", "")).lower()
                needle = project_filter.lower()
                if needle not in project_name and needle not in project_id:
                    continue
            selected_rows.append(row)

        takeoff_values: List[float] = []
        stability_values: List[float] = []
        classifier_confidence_values: List[float] = []
        copy_match_values: List[float] = []
        cleanup_event_count = 0
        copy_attempt_count = 0
        for row in selected_rows:
            comps = row.get("score_components", {}) if isinstance(row, dict) else {}
            try:
                takeoff_values.append(
                    float((comps or {}).get("takeoff_accuracy", (comps or {}).get("quantity_accuracy", 0.0)))
                )
            except Exception:
                pass
            try:
                stability_values.append(float((comps or {}).get("runtime_stability", 0.0)))
            except Exception:
                pass
            classification = row.get("item_type_classification", {}) if isinstance(row, dict) else {}
            top_conf = (classification.get("top_match_confidence", None) if isinstance(classification, dict) else None)
            if top_conf is None and isinstance(classification, dict):
                c_payload = classification.get("classification", {})
                if isinstance(c_payload, dict):
                    top_conf = ((c_payload.get("summary", {}) if isinstance(c_payload.get("summary", {}), dict) else {}).get("top_confidence", None))
            try:
                if top_conf is not None:
                    classifier_confidence_values.append(float(top_conf))
            except Exception:
                pass
            copy_summary = row.get("takeoff_copy_summary", {}) if isinstance(row, dict) else {}
            if isinstance(copy_summary, dict):
                ma = copy_summary.get("match_assessment", {})
                if isinstance(ma, dict):
                    try:
                        copy_match_values.append(float(ma.get("score", 0.0) or 0.0))
                    except Exception:
                        pass
                    copy_attempt_count += 1
                cleanup = copy_summary.get("cleanup", {})
                if isinstance(cleanup, dict) and bool(cleanup.get("ran", False)):
                    cleanup_event_count += 1

        def stats(vals: List[float]) -> Dict[str, float]:
            if not vals:
                return {"count": 0.0, "avg": 0.0, "min": 0.0, "max": 0.0, "stdev": 0.0}
            n = len(vals)
            avg = sum(vals) / n
            var = sum((v - avg) ** 2 for v in vals) / n
            return {
                "count": float(n),
                "avg": round(avg, 2),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "stdev": round(math.sqrt(var), 2),
            }

        q_stats = stats(takeoff_values)
        s_stats = stats(stability_values)
        classifier_stats = stats(classifier_confidence_values)
        copy_match_stats = stats(copy_match_values)
        takeoff_accuracy_variance_status = "pass"
        if q_stats["count"] >= 2:
            if q_stats["stdev"] > 20 or (q_stats["max"] - q_stats["min"]) > 30:
                takeoff_accuracy_variance_status = "warn"
        runtime_stability_status = "pass"
        if s_stats["count"] >= 2 and s_stats["stdev"] > 15:
            runtime_stability_status = "warn"
        classifier_confidence_status = "pass"
        if classifier_stats["count"] >= 1 and classifier_stats["avg"] < 0.5:
            classifier_confidence_status = "warn"
        copy_match_status = "pass"
        if copy_match_stats["count"] >= 1 and copy_match_stats["avg"] < 55.0:
            copy_match_status = "warn"

        # Missing work-package coverage heuristic:
        # If scope profiles indicate work packages but no training attempts exist, flag as warn.
        state_path = self.root / "output/ost-project-intake/state.json"
        state = read_json(state_path, {"projects": {}})
        projects = state.get("projects", {}) if isinstance(state, dict) else {}
        scope_projects = 0
        projects_with_work_packages = 0
        for project_path in projects.keys():
            if project_filter and project_filter.lower() not in str(project_path).lower():
                continue
            if self._project_excluded(str(project_path)):
                continue
            scope_projects += 1
            prof = pathlib.Path(str(project_path)) / "_reports" / "scope_profile.json"
            if prof.exists():
                data = read_json(prof, {})
                wps = data.get("work_packages", []) if isinstance(data, dict) else []
                if isinstance(wps, list) and len(wps) > 0:
                    projects_with_work_packages += 1

        work_package_coverage_status = "pass"
        if projects_with_work_packages > 0 and len(selected_rows) == 0:
            work_package_coverage_status = "warn"

        return {
            "attempt_count": len(selected_rows),
            "takeoff_accuracy": q_stats,
            "quantity_accuracy": q_stats,
            "runtime_stability": s_stats,
            "takeoff_accuracy_variance_status": takeoff_accuracy_variance_status,
            "quantity_variance_status": takeoff_accuracy_variance_status,
            "runtime_stability_status": runtime_stability_status,
            "item_type_classifier_confidence": classifier_stats,
            "item_type_classifier_confidence_status": classifier_confidence_status,
            "takeoff_copy_match_score": copy_match_stats,
            "takeoff_copy_match_status": copy_match_status,
            "takeoff_copy_attempt_count": copy_attempt_count,
            "takeoff_copy_cleanup_events": cleanup_event_count,
            "scope_projects": scope_projects,
            "projects_with_work_packages": projects_with_work_packages,
            "work_package_coverage_status": work_package_coverage_status,
        }

    def quality_gates(self, project: str) -> Dict[str, Any]:
        q = self._collect_scope_quality(project_filter=project)
        eqa = self._collect_estimator_qa(project_filter=project)
        summary = (
            f"{self.agent_name} quality gates:\n"
            f"- projects_considered: {q['considered_projects']}\n"
            f"- projects_excluded: {q['excluded_projects']}\n"
            f"- coverage_status: {q['coverage_status']} "
            f"({q['with_scope_profile']}/{q['considered_projects']} scope_profiles, "
            f"{q['with_scope_intel']}/{q['considered_projects']} scope_intel)\n"
            f"- consistency_status: {q['consistency_status']} "
            f"(critical={q['critical_conflicts']} warn={q['warn_conflicts']} total={q['total_conflicts']})\n"
            f"- conflict_confidence: high={q['high_confidence_conflicts']} "
            f"medium={q['medium_confidence_conflicts']} low={q['low_confidence_conflicts']}\n"
            f"- conflict_buckets: actionable={q['actionable_conflicts']} "
            f"informational={q['informational_conflicts']}\n"
            f"- work_package_status: {q['work_package_status']} (work_packages={q['total_work_packages']})\n"
            f"- estimator_qa: takeoff_accuracy_variance={eqa.get('takeoff_accuracy_variance_status', eqa.get('quantity_variance_status', 'pass'))} "
            f"runtime_stability={eqa['runtime_stability_status']} "
            f"work_package_coverage={eqa['work_package_coverage_status']} "
            f"classifier_confidence={eqa.get('item_type_classifier_confidence_status', 'pass')} "
            f"takeoff_copy_match={eqa.get('takeoff_copy_match_status', 'pass')}\n"
        )
        if q["warnings"]:
            summary += "- warnings:\n"
            for w in q["warnings"][:5]:
                summary += f"  - {w}\n"
        if q.get("incomplete_projects"):
            summary += "- incomplete_analysis:\n"
            for row in (q.get("incomplete_projects") or [])[:5]:
                summary += f"  - {row}\n"
        return {"ok": True, "project": project, "quality": q, "estimator_qa": eqa, "summary": summary.strip()}

    def blockers(self, project: str) -> Dict[str, Any]:
        failures = read_json(self.failures_file, {"counts": {}})
        counts = failures.get("counts", {}) if isinstance(failures, dict) else {}
        rows: List[Dict[str, Any]] = []
        for key, val in counts.items():
            try:
                prj, arch = key.split("::", 1)
            except ValueError:
                prj, arch = "_global", key
            if project and prj not in ("_global", project):
                continue
            count = int((val or {}).get("count", 0))
            if count <= 0:
                continue
            rows.append(
                {
                    "project": prj,
                    "archetype": arch,
                    "count": count,
                    "last_reason": (val or {}).get("last_reason", ""),
                    "last_ts": (val or {}).get("last_ts", ""),
                }
            )
        rows.sort(key=lambda x: x["count"], reverse=True)
        summary = (
            f"{self.agent_name} unresolved blockers:\n"
            f"- total_active_blockers: {len(rows)}\n"
        )
        if rows:
            for r in rows[:8]:
                summary += (
                    f"- {r['project']} | {r['archetype']} | count={r['count']} | "
                    f"reason={r['last_reason']}\n"
                )
        else:
            summary += "- none\n"
        return {"ok": True, "project": project, "blockers": rows, "summary": summary.strip()}

    def _retry_hint_for_archetype(self, archetype: str) -> str:
        a = (archetype or "").lower()
        if "boost-run-click" in a:
            return "Re-map run button anchor, verify dialog is fully rendered, then retry with auto-detect enabled."
        if "boost-open-dialog" in a:
            return "Verify Boost button anchor and add post-open wait before run-step."
        if "boost-scale-warning" in a:
            return "Run scale correction flow and reopen Boost before attempting run."
        if "setup-missing-anchor" in a:
            return "Capture missing setup anchor in UI mapper and validate click target on monitor 1."
        if "setup-focus-window" in a or "boost-focus-window" in a:
            return "Bring OST window to foreground and verify window title match in config."
        if a.startswith("startup:"):
            return "Check dependency script path/config and retry boot sequence."
        return "Re-run with fresh screenshots and inspect latest evidence artifacts."

    def _latest_evidence_for_archetype(self, archetype: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        a = (archetype or "").lower()
        if "boost" in a:
            boost_root = self.root / "output/ost-boost-agent"
            if boost_root.exists():
                latest = sorted(
                    [p for p in boost_root.iterdir() if p.is_dir()],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if latest:
                    d = latest[0]
                    run_log = d / "run_log.json"
                    out["evidence_dir"] = str(d)
                    if run_log.exists():
                        out["run_log"] = str(run_log)
                    for img in ("01_before.png", "02_after_open.png", "03_after_run.png"):
                        p = d / img
                        if p.exists():
                            out.setdefault("screenshots", []).append(str(p))
        elif "setup" in a:
            setup_root = self.root / "output/ost-project-setup"
            if setup_root.exists():
                latest = sorted(
                    [p for p in setup_root.rglob("setup_result.json") if p.is_file()],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if latest:
                    out["setup_result"] = str(latest[0])
                    out["evidence_dir"] = str(latest[0].parent)
        return out

    def failure_trends(self, project: str, top: int = 10) -> Dict[str, Any]:
        failures = read_json(self.failures_file, {"history": []})
        counts_payload = failures.get("counts", {}) if isinstance(failures, dict) else {}
        history = failures.get("history", []) if isinstance(failures, dict) else []
        aggregate: Dict[str, int] = {}
        for row in history:
            if not isinstance(row, dict):
                continue
            if str(row.get("event", "")) != "failure":
                continue
            prj = str(row.get("project", ""))
            if project and prj not in ("", project):
                continue
            arch = str(row.get("archetype", "unknown"))
            key = f"{prj or '_global'}::{arch}"
            aggregate[key] = aggregate.get(key, 0) + 1
        ranked = sorted(aggregate.items(), key=lambda kv: kv[1], reverse=True)
        items = []
        for k, c in ranked[: max(1, top)]:
            prj, arch = (k.split("::", 1) + ["unknown"])[:2]
            detail = counts_payload.get(k, {}) if isinstance(counts_payload, dict) else {}
            items.append(
                {
                    "key": k,
                    "count": c,
                    "last_reason": (detail or {}).get("last_reason", ""),
                    "last_ts": (detail or {}).get("last_ts", ""),
                    "retry_hint": self._retry_hint_for_archetype(arch),
                    "evidence": self._latest_evidence_for_archetype(arch),
                }
            )
        summary = (
            f"{self.agent_name} failure trends:\n"
            f"- tracked_archetypes: {len(aggregate)}\n"
        )
        if items:
            for row in items:
                summary += (
                    f"- {row['key']} | failures={row['count']} | "
                    f"reason={row.get('last_reason', '')}\n"
                    f"  hint: {row.get('retry_hint', '')}\n"
                )
        else:
            summary += "- none\n"
        return {"ok": True, "project": project, "trends": items, "summary": summary.strip()}

    def startup_self_check(self) -> Dict[str, Any]:
        lock = read_json(self.lock_file, {})
        lock_pid = int((lock or {}).get("pid", 0)) if isinstance(lock, dict) else 0
        lock_alive = pid_alive(lock_pid) if lock_pid > 0 else False
        state = read_json(self.state_file, {})
        deps = state.get("dependencies", []) if isinstance(state, dict) else []
        dep_checks = []
        all_deps_running = True
        for dep in deps if isinstance(deps, list) else []:
            running = bool((dep or {}).get("running", False))
            dep_checks.append(
                {"id": (dep or {}).get("id", "unknown"), "running": running, "pid": (dep or {}).get("pid")}
            )
            if not running:
                all_deps_running = False
        state_name = str((state or {}).get("state", "unknown"))
        m_online = bool((state or {}).get("maverick_online", False))
        # Lock health is useful signal, but runtime can still be healthy if a stale lock remains.
        ok = all_deps_running and m_online and state_name in {"maverick_ready", "running"}
        lock_status = "pass" if lock_alive else "warn"
        summary = (
            f"{self.agent_name} startup self-check:\n"
            f"- lock_status: {lock_status} (alive={lock_alive})\n"
            f"- state: {state_name}\n"
            f"- maverick_online: {m_online}\n"
            f"- dependencies_running: {all_deps_running} ({len(dep_checks)} deps)\n"
            f"- overall: {'pass' if ok else 'warn'}"
        )
        return {
            "ok": True,
            "check_passed": ok,
            "lock_pid": lock_pid,
            "lock_alive": lock_alive,
            "lock_status": lock_status,
            "state": state_name,
            "maverick_online": m_online,
            "dependencies": dep_checks,
            "summary": summary,
        }

    def daily_report(self, project: str, top: int = 5) -> Dict[str, Any]:
        summary = self.summary(project=project, advance_cursor=False)
        blockers = self.blockers(project=project)
        trends = self.failure_trends(project=project, top=top)
        quality = self.quality_gates(project=project)
        action_candidates: List[Dict[str, Any]] = []
        q = quality.get("quality", {}) if isinstance(quality, dict) else {}
        eqa = quality.get("estimator_qa", {}) if isinstance(quality, dict) else {}
        if q.get("coverage_status") == "warn":
            action_candidates.append(
                {
                    "action": "Regenerate missing scope profile/intel artifacts for uncovered projects.",
                    "priority": 95,
                    "reason": "coverage_status_warn",
                }
            )
        if q.get("consistency_status") in {"warn", "fail"}:
            high = int(q.get("high_confidence_conflicts", 0) or 0)
            med = int(q.get("medium_confidence_conflicts", 0) or 0)
            if high + med > 0:
                action_candidates.append(
                    {
                        "action": "Review high/medium-confidence conflicts and confirm product-family intent.",
                        "priority": 90 + min(9, high + med),
                        "reason": "high_medium_conflict_presence",
                    }
                )
            else:
                action_candidates.append(
                    {
                        "action": "Re-run scope intel on timed-out projects to enrich conflict confidence signals.",
                        "priority": 80,
                        "reason": "low_confidence_conflict_only",
                    }
                )
        takeoff_variance_status = str(
            eqa.get("takeoff_accuracy_variance_status", eqa.get("quantity_variance_status", "pass"))
        )
        if takeoff_variance_status == "warn":
            quantity_stdev = float(
                (
                    (eqa.get("takeoff_accuracy") or eqa.get("quantity_accuracy") or {}).get("stdev", 0.0) or 0.0
                )
            )
            action_candidates.append(
                {
                    "action": "Review recent takeoff-accuracy variance across attempts and calibrate workflow.",
                    "priority": 85 + min(10, int(quantity_stdev // 5)),
                    "reason": "takeoff_accuracy_variance_warn",
                }
            )
        if eqa.get("runtime_stability_status") == "warn":
            runtime_stdev = float(((eqa.get("runtime_stability") or {}).get("stdev", 0.0) or 0.0))
            action_candidates.append(
                {
                    "action": "Stabilize runtime flow by tuning retries/waits for top unstable archetypes.",
                    "priority": 75 + min(10, int(runtime_stdev // 5)),
                    "reason": "runtime_stability_warn",
                }
            )
        if eqa.get("item_type_classifier_confidence_status") == "warn":
            top_conf = float(((eqa.get("item_type_classifier_confidence") or {}).get("avg", 0.0) or 0.0))
            action_candidates.append(
                {
                    "action": "Capture clearer pre-attempt screenshots and tune item-type prototypes for low-confidence classifications.",
                    "priority": 80 + min(10, int((1.0 - max(0.0, top_conf)) * 10)),
                    "reason": "item_type_classifier_confidence_warn",
                }
            )
        if eqa.get("takeoff_copy_match_status") == "warn":
            copy_avg = float(((eqa.get("takeoff_copy_match_score") or {}).get("avg", 0.0) or 0.0))
            action_candidates.append(
                {
                    "action": "Review takeoff copy mismatch attempts and refine blank-drawing target selection before reruns.",
                    "priority": 84 + min(10, int(max(0.0, (55.0 - copy_avg)) // 5)),
                    "reason": "takeoff_copy_match_warn",
                }
            )
        if eqa.get("work_package_coverage_status") == "warn":
            action_candidates.append(
                {
                    "action": "Run training/boost modules for projects with detected scope work packages.",
                    "priority": 82,
                    "reason": "work_package_coverage_warn",
                }
            )
        b = blockers.get("blockers", []) if isinstance(blockers, dict) else []
        if b:
            top_blocker_count = int((b[0] or {}).get("count", 1)) if isinstance(b[0], dict) else 1
            action_candidates.append(
                {
                    "action": "Resolve top blocker archetypes and record guided clicks when repeated.",
                    "priority": 88 + min(10, top_blocker_count),
                    "reason": "active_blockers_present",
                }
            )
        t = trends.get("trends", []) if isinstance(trends, dict) else []
        if t:
            top_trend_count = int((t[0] or {}).get("count", 1)) if isinstance(t[0], dict) else 1
            action_candidates.append(
                {
                    "action": "Address top failure trend with one targeted workflow fix.",
                    "priority": 78 + min(10, top_trend_count),
                    "reason": "failure_trend_present",
                }
            )
        if not action_candidates:
            action_candidates.append(
                {
                    "action": "Continue intake watch and monitor for new project changes.",
                    "priority": 20,
                    "reason": "steady_state",
                }
            )

        action_candidates.sort(key=lambda x: int(x.get("priority", 0)), reverse=True)
        ranked_actions: List[Dict[str, Any]] = []
        seen_actions = set()
        for row in action_candidates:
            action_text = str(row.get("action", "")).strip()
            if not action_text or action_text in seen_actions:
                continue
            seen_actions.add(action_text)
            ranked_actions.append(row)

        report_text = (
            f"{self.agent_name} daily report\n\n"
            f"## Since Last Check\n{summary.get('summary', '')}\n\n"
            f"## Blockers\n{blockers.get('summary', '')}\n\n"
            f"## Failure Trends\n{trends.get('summary', '')}\n\n"
            f"## Quality Gates\n{quality.get('summary', '')}\n\n"
            f"## Top Next Actions\n"
        )
        for idx, row in enumerate(ranked_actions[:3], start=1):
            report_text += (
                f"{idx}. {row.get('action')}\n"
                f"   - priority: {row.get('priority')}\n"
                f"   - reason: {row.get('reason')}\n"
            )

        # Persist project-scoped report artifacts with delta snapshot.
        project_key = (project or "_global").strip().replace(" ", "_").replace("/", "_").replace("\\", "_")
        report_dir = self.output_root / "project_reports" / project_key
        report_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = report_dir / "last_snapshot.json"
        prev = read_json(
            snapshot_path,
            {
                "steps_succeeded": 0,
                "steps_failed": 0,
                "unresolved_blockers": 0,
                "considered_projects": 0,
                "critical_conflicts": 0,
                "warn_conflicts": 0,
            },
        )
        cur = {
            "ts": utc_now_iso(),
            "steps_succeeded": int((summary.get("counts") or {}).get("steps_succeeded", 0)),
            "steps_failed": int((summary.get("counts") or {}).get("steps_failed", 0)),
            "unresolved_blockers": int((summary.get("counts") or {}).get("unresolved_blockers", 0)),
            "considered_projects": int((q.get("considered_projects", 0) if isinstance(q, dict) else 0) or 0),
            "critical_conflicts": int((q.get("critical_conflicts", 0) if isinstance(q, dict) else 0) or 0),
            "warn_conflicts": int((q.get("warn_conflicts", 0) if isinstance(q, dict) else 0) or 0),
        }
        delta = {
            "steps_succeeded_delta": cur["steps_succeeded"] - int(prev.get("steps_succeeded", 0)),
            "steps_failed_delta": cur["steps_failed"] - int(prev.get("steps_failed", 0)),
            "unresolved_blockers_delta": cur["unresolved_blockers"] - int(prev.get("unresolved_blockers", 0)),
            "critical_conflicts_delta": cur["critical_conflicts"] - int(prev.get("critical_conflicts", 0)),
            "warn_conflicts_delta": cur["warn_conflicts"] - int(prev.get("warn_conflicts", 0)),
        }
        write_json(snapshot_path, cur)

        report_text += (
            "\n## New Since Last Report\n"
            f"- steps_succeeded_delta: {delta['steps_succeeded_delta']}\n"
            f"- steps_failed_delta: {delta['steps_failed_delta']}\n"
            f"- unresolved_blockers_delta: {delta['unresolved_blockers_delta']}\n"
            f"- critical_conflicts_delta: {delta['critical_conflicts_delta']}\n"
            f"- warn_conflicts_delta: {delta['warn_conflicts_delta']}\n"
        )

        report_md_path = report_dir / "daily_report.md"
        report_json_path = report_dir / "daily_report.json"
        report_md_path.write_text(report_text.strip() + "\n", encoding="utf-8")

        payload = {
            "ok": True,
            "project": project,
            "summary": summary,
            "blockers": blockers,
            "trends": trends,
            "quality": quality,
            "next_actions": [str(r.get("action", "")) for r in ranked_actions[:3]],
            "ranked_next_actions": ranked_actions[:5],
            "report": report_text.strip(),
            "delta": delta,
            "report_md_path": str(report_md_path),
            "report_json_path": str(report_json_path),
        }
        write_json(report_json_path, payload)
        return payload

    def daily_report_all_projects(self, top: int = 5) -> Dict[str, Any]:
        state_path = self.root / "output/ost-project-intake/state.json"
        state = read_json(state_path, {"projects": {}})
        projects = state.get("projects", {}) if isinstance(state, dict) else {}
        out: List[Dict[str, Any]] = []
        for project_path in sorted(projects.keys()):
            p = pathlib.Path(str(project_path))
            project_name = p.name
            if self._project_excluded(str(project_path)):
                continue
            out.append(self.daily_report(project=project_name, top=top))
        global_report = self.daily_report(project="", top=top)
        return {
            "ok": True,
            "project_count": len(out),
            "projects": out,
            "global": global_report,
        }

    def summary(self, project: str, advance_cursor: bool) -> Dict[str, Any]:
        cursor = read_json(self.summary_cursor_file, {"last_ts": ""})
        last_ts = str(cursor.get("last_ts", ""))
        conv_lines = self.conversation_file.read_text(encoding="utf-8").splitlines() if self.conversation_file.exists() else []
        step_lines = self.step_log.read_text(encoding="utf-8").splitlines() if self.step_log.exists() else []

        conv_new: List[Dict[str, Any]] = []
        for line in conv_lines:
            try:
                row = json.loads(line)
            except Exception:
                continue
            ts = str(row.get("ts", ""))
            if last_ts and ts <= last_ts:
                continue
            if project and row.get("project") not in ("", project):
                continue
            conv_new.append(row)

        steps_new: List[Dict[str, Any]] = []
        for line in step_lines:
            try:
                row = json.loads(line)
            except Exception:
                continue
            ts = str(row.get("ts", ""))
            if last_ts and ts <= last_ts:
                continue
            if project and row.get("project") not in ("", project):
                continue
            steps_new.append(row)

        success = sum(1 for s in steps_new if str(s.get("outcome", "")).lower() == "success")
        failure = sum(1 for s in steps_new if str(s.get("outcome", "")).lower() == "failure")
        unresolved = [s for s in steps_new if str(s.get("outcome", "")).lower() == "failure"][-5:]
        latest_ts = utc_now_iso()
        if conv_new or steps_new:
            latest_ts = max([str(x.get("ts", "")) for x in conv_new + steps_new if x.get("ts")], default=latest_ts)

        summary_text = (
            f"{self.agent_name} summary since last check:\n"
            f"- conversation_events: {len(conv_new)}\n"
            f"- steps_succeeded: {success}\n"
            f"- steps_failed: {failure}\n"
            f"- unresolved_blockers: {len(unresolved)}\n"
        )
        if unresolved:
            summary_text += "- recent_failures:\n"
            for item in unresolved:
                summary_text += (
                    f"  - {item.get('archetype', 'unknown')} | "
                    f"{item.get('error') or item.get('observed')}\n"
                )

        gates = self._collect_scope_quality(project_filter=project)
        summary_text += (
            "- quality_gates:\n"
            f"  - coverage: {gates['coverage_status']}\n"
            f"  - consistency: {gates['consistency_status']} "
            f"(critical={gates['critical_conflicts']} warn={gates['warn_conflicts']})\n"
            f"  - conflict_confidence: high={gates['high_confidence_conflicts']} "
            f"medium={gates['medium_confidence_conflicts']} low={gates['low_confidence_conflicts']}\n"
            f"  - work_packages: {gates['work_package_status']} (count={gates['total_work_packages']})\n"
        )

        if advance_cursor:
            write_json(self.summary_cursor_file, {"last_ts": latest_ts, "ts": utc_now_iso()})

        return {
            "ok": True,
            "project": project,
            "summary": summary_text.strip(),
            "counts": {
                "conversation_events": len(conv_new),
                "steps_succeeded": success,
                "steps_failed": failure,
                "unresolved_blockers": len(unresolved),
            },
            "quality_gates": gates,
        }

    def log_step(
        self,
        project: str,
        action: str,
        outcome: str,
        archetype: str,
        expected: str,
        observed: str,
        error: str,
        resolution: str,
    ) -> Dict[str, Any]:
        self._log_step(
            action=action,
            outcome=outcome,
            archetype=archetype,
            expected=expected,
            observed=observed,
            project=project,
            error=error,
            resolution=resolution,
        )
        return {"ok": True}

    def record_click(self, project: str, archetype: str, x: int, y: int, context: str) -> Dict[str, Any]:
        row = {
            "ts": utc_now_iso(),
            "project": project,
            "archetype": archetype,
            "x": x,
            "y": y,
            "context": context,
        }
        append_jsonl(self.click_log, row)
        self._resolve_failure(archetype=archetype, project=project, resolution="guided click recorded")
        return {"ok": True, "recorded": row}

    def always_on(self) -> int:
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        self._load_dependencies()
        if not self.dependencies:
            self._set_state("failed", note="no dependencies configured")
            self._release_lock()
            return 2

        try:
            self._set_state("booting", note="starting dependencies in sequence")
            if not self._boot_dependencies():
                self._set_state("failed", note="boot sequence failed")
                return 3

            self._set_state("deps_ready", note="all dependencies started")
            self._last_green_at = time.time()
            while True:
                all_green = self._all_dependencies_running()
                if not all_green:
                    self._degraded_recover()
                    time.sleep(self.heartbeat_seconds)
                    continue

                if not self.maverick_online:
                    if time.time() - self._last_green_at >= self.stability_window_seconds:
                        self.maverick_online = True
                        self._set_state("maverick_ready", note="stability window passed")
                else:
                    self._set_state("running", note="healthy")

                time.sleep(self.heartbeat_seconds)
        except KeyboardInterrupt:
            self._set_state("stopped", note="keyboard interrupt")
            return 0
        finally:
            for dep in self.dependencies:
                self._stop_dependency(dep)
            self._release_lock()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Maverick runtime controller")
    p.add_argument("--config", default="scripts/maverick_runtime.config.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("always-on", help="Run always-on startup sequence and watchdog")

    p_chat = sub.add_parser("chat", help="Send a message to Maverick")
    p_chat.add_argument("--user", default="travi")
    p_chat.add_argument("--project", default="")
    p_chat.add_argument("--message", required=True)

    p_summary = sub.add_parser("summary", help="Get summary since last conversation")
    p_summary.add_argument("--project", default="")
    p_summary.add_argument("--advance-cursor", action="store_true")
    p_summary.add_argument("--include-quality-gates", action="store_true")

    p_blockers = sub.add_parser("blockers", help="Show unresolved blockers")
    p_blockers.add_argument("--project", default="")

    p_trends = sub.add_parser("failure-trends", help="Show failure trend ranking")
    p_trends.add_argument("--project", default="")
    p_trends.add_argument("--top", type=int, default=10)

    p_quality = sub.add_parser("quality-gates", help="Show scope and QA gate status")
    p_quality.add_argument("--project", default="")

    sub.add_parser("startup-self-check", help="Verify startup health and dependency readiness")

    p_daily = sub.add_parser("daily-report", help="Produce combined daily status report")
    p_daily.add_argument("--project", default="")
    p_daily.add_argument("--top", type=int, default=5)
    p_daily_all = sub.add_parser("daily-report-all", help="Produce daily reports for all tracked projects")
    p_daily_all.add_argument("--top", type=int, default=5)

    p_step = sub.add_parser("log-step", help="Log one step with outcome")
    p_step.add_argument("--project", default="")
    p_step.add_argument("--action", required=True)
    p_step.add_argument("--outcome", required=True, choices=["success", "failure"])
    p_step.add_argument("--archetype", required=True)
    p_step.add_argument("--expected", default="")
    p_step.add_argument("--observed", default="")
    p_step.add_argument("--error", default="")
    p_step.add_argument("--resolution", default="")

    p_click = sub.add_parser("record-click", help="Record a guided click for coach mode")
    p_click.add_argument("--project", default="")
    p_click.add_argument("--archetype", required=True)
    p_click.add_argument("--x", type=int, required=True)
    p_click.add_argument("--y", type=int, required=True)
    p_click.add_argument("--context", default="")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    rt = MaverickRuntime(config_path=pathlib.Path(args.config))

    if args.cmd == "always-on":
        return rt.always_on()
    if args.cmd == "chat":
        result = rt.chat(user=args.user, project=args.project, message=args.message)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "summary":
        result = rt.summary(project=args.project, advance_cursor=bool(args.advance_cursor))
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "blockers":
        result = rt.blockers(project=args.project)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "failure-trends":
        result = rt.failure_trends(project=args.project, top=int(args.top))
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "quality-gates":
        result = rt.quality_gates(project=args.project)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "startup-self-check":
        result = rt.startup_self_check()
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "daily-report":
        result = rt.daily_report(project=args.project, top=int(args.top))
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "daily-report-all":
        result = rt.daily_report_all_projects(top=int(args.top))
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "log-step":
        result = rt.log_step(
            project=args.project,
            action=args.action,
            outcome=args.outcome,
            archetype=args.archetype,
            expected=args.expected,
            observed=args.observed,
            error=args.error,
            resolution=args.resolution,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "record-click":
        result = rt.record_click(
            project=args.project,
            archetype=args.archetype,
            x=int(args.x),
            y=int(args.y),
            context=args.context,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
