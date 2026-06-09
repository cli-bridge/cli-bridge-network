"""Observed plugin operation runner."""

from __future__ import annotations

import os
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from cbn_audit.log import AuditLog
from cbn_artifacts.store import ArtifactStore
from cbn_events.bus import EventBus
from cbn_plugins.manager import PluginCommand, PluginPlan
from protocol import EventType


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class PluginOperationRunner:
    def __init__(
        self,
        audit_log: AuditLog | None = None,
        event_bus: EventBus | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.audit_log = audit_log
        self.event_bus = event_bus
        self.artifact_store = artifact_store

    def execute(self, plan: PluginPlan) -> dict[str, Any]:
        operation_id = str(uuid.uuid4())
        started_at = now_iso()
        plugin_dir = Path(plan.plugin_dir)
        plugin_dir.mkdir(parents=True, exist_ok=True)
        lock = self._acquire_lock(plan, operation_id, started_at)
        if not lock["acquired"]:
            payload = {
                "operation_id": operation_id,
                "plugin_id": plan.plugin_id,
                "action": plan.action,
                "status": "blocked",
                "started_at": started_at,
                "completed_at": now_iso(),
                "blockers": ["plugin operation already running"],
                "lock": lock,
                "results": [],
            }
            self._audit("plugin.operation.blocked", operation_id, plan, payload)
            self._publish(EventType.PLUGIN_OPERATION_COMPLETED, plan.plugin_id, payload, operation_id)
            return payload

        self._audit(
            "plugin.operation.started",
            operation_id,
            plan,
            {"command_count": len(plan.commands), "lock": lock},
        )
        self._publish(
            EventType.PLUGIN_OPERATION_STARTED,
            plan.plugin_id,
            {"operation_id": operation_id, "action": plan.action},
            operation_id,
        )
        results: list[dict[str, Any]] = []
        status = "completed"

        try:
            for index, command in enumerate(plan.commands):
                result = self._execute_command(operation_id, plan, index, command)
                results.append(result)
                if result.get("exit_code") not in (0, None) and not command.optional:
                    status = "failed"
                    break
        finally:
            self._release_lock(lock)

        payload = {
            "operation_id": operation_id,
            "plugin_id": plan.plugin_id,
            "action": plan.action,
            "status": status,
            "started_at": started_at,
            "completed_at": now_iso(),
            "lock": lock,
            "results": results,
        }
        self._audit("plugin.operation.completed", operation_id, plan, payload)
        self._publish(EventType.PLUGIN_OPERATION_COMPLETED, plan.plugin_id, payload, operation_id)
        return payload

    def _acquire_lock(self, plan: PluginPlan, operation_id: str, started_at: str) -> dict[str, Any]:
        lock_path = Path(plan.plugin_dir) / ".operation.lock"
        holder_path = lock_path / "holder.json"
        try:
            lock_path.mkdir()
        except FileExistsError:
            return {
                "acquired": False,
                "path": str(lock_path),
                "holder": _read_lock_holder(holder_path),
            }
        holder = {
            "operation_id": operation_id,
            "plugin_id": plan.plugin_id,
            "action": plan.action,
            "started_at": started_at,
        }
        holder_path.write_text(json.dumps(holder, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "acquired": True,
            "path": str(lock_path),
            "holder": holder,
        }

    def _release_lock(self, lock: dict[str, Any]) -> None:
        if not lock.get("acquired"):
            return
        lock_path = Path(str(lock["path"]))
        holder_path = lock_path / "holder.json"
        try:
            if holder_path.exists():
                holder_path.unlink()
            lock_path.rmdir()
        except OSError:
            pass

    def _execute_command(
        self,
        operation_id: str,
        plan: PluginPlan,
        index: int,
        command: PluginCommand,
    ) -> dict[str, Any]:
        command_id = f"{operation_id}:{index}"
        plugin_dir = Path(plan.plugin_dir)
        if command.label.startswith("Clone") and (plugin_dir / "repo").exists():
            result = {
                "command_id": command_id,
                "label": command.label,
                "argv": list(command.argv),
                "skipped": True,
                "reason": "repository already exists",
                "artifact_ids": [],
            }
            self._audit("plugin.command.skipped", operation_id, plan, result)
            self._publish(EventType.PLUGIN_COMMAND_COMPLETED, plan.plugin_id, result, operation_id)
            return result

        self._audit(
            "plugin.command.started",
            operation_id,
            plan,
            {
                "command_id": command_id,
                "label": command.label,
                "argv": list(command.argv),
                "cwd": command.cwd,
                "optional": command.optional,
                "timeout_seconds": command.timeout_seconds,
                "env_overrides": sorted((command.env or {}).keys()),
            },
        )
        self._publish(
            EventType.PLUGIN_COMMAND_STARTED,
            plan.plugin_id,
            {
                "command_id": command_id,
                "label": command.label,
                "argv": list(command.argv),
                "timeout_seconds": command.timeout_seconds,
            },
            operation_id,
        )
        try:
            proc = subprocess.run(
                list(command.argv),
                cwd=command.cwd,
                env=_operation_env(command.env),
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=command.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _timeout_text(exc.stdout)
            stderr = _timeout_text(exc.stderr)
            if stderr:
                stderr = f"{stderr}\n"
            stderr = f"{stderr}command timed out after {command.timeout_seconds} seconds"
            result = {
                "command_id": command_id,
                "label": command.label,
                "argv": list(command.argv),
                "cwd": command.cwd,
                "optional": command.optional,
                "timeout_seconds": command.timeout_seconds,
                "timed_out": True,
                "exit_code": 124,
                "stdout": stdout[-4000:],
                "stderr": stderr[-4000:],
                "artifact_ids": self._record_artifact_texts(
                    plan.plugin_id,
                    operation_id,
                    command_id,
                    stdout,
                    stderr,
                ),
            }
            self._audit("plugin.command.completed", operation_id, plan, result)
            self._publish(EventType.PLUGIN_COMMAND_COMPLETED, plan.plugin_id, result, operation_id)
            return result
        except OSError as exc:
            result = {
                "command_id": command_id,
                "label": command.label,
                "argv": list(command.argv),
                "cwd": command.cwd,
                "optional": command.optional,
                "timeout_seconds": command.timeout_seconds,
                "timed_out": False,
                "exit_code": 127,
                "stdout": "",
                "stderr": f"{command.argv[0]} failed to start: {exc}",
                "artifact_ids": [],
            }
            self._audit("plugin.command.completed", operation_id, plan, result)
            self._publish(EventType.PLUGIN_COMMAND_COMPLETED, plan.plugin_id, result, operation_id)
            return result
        artifact_ids = self._record_artifacts(plan.plugin_id, operation_id, command_id, proc)
        result = {
            "command_id": command_id,
            "label": command.label,
            "argv": list(command.argv),
            "cwd": command.cwd,
            "optional": command.optional,
            "timeout_seconds": command.timeout_seconds,
            "timed_out": False,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "artifact_ids": artifact_ids,
        }
        self._audit("plugin.command.completed", operation_id, plan, result)
        self._publish(EventType.PLUGIN_COMMAND_COMPLETED, plan.plugin_id, result, operation_id)
        return result

    def _record_artifacts(
        self,
        plugin_id: str,
        operation_id: str,
        command_id: str,
        proc: subprocess.CompletedProcess[str],
    ) -> list[str]:
        if self.artifact_store is None:
            return []
        return self._record_artifact_texts(
            plugin_id,
            operation_id,
            command_id,
            proc.stdout,
            proc.stderr,
        )

    def _record_artifact_texts(
        self,
        plugin_id: str,
        operation_id: str,
        command_id: str,
        stdout: str,
        stderr: str,
    ) -> list[str]:
        if self.artifact_store is None:
            return []
        records = []
        for kind, text in (("stdout", stdout), ("stderr", stderr)):
            record = self.artifact_store.create_text(
                capability_id=f"plugin.{plugin_id}",
                call_id=operation_id,
                kind=f"{command_id}.{kind}",
                text=text,
            )
            if record is not None:
                records.append(record.artifact_id)
        return records

    def _audit(
        self,
        event_type: str,
        operation_id: str,
        plan: PluginPlan,
        payload: dict[str, Any],
    ) -> None:
        if self.audit_log is None:
            return
        self.audit_log.append(
            {
                "type": event_type,
                "operation_id": operation_id,
                "plugin_id": plan.plugin_id,
                "action": plan.action,
                "payload": payload,
            }
        )

    def _publish(
        self,
        event_type: EventType,
        subject: str,
        payload: dict[str, Any],
        operation_id: str,
    ) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(str(event_type), subject, payload, correlation_id=operation_id)


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _operation_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if overrides:
        env.update({str(key): str(value) for key, value in overrides.items()})
    return env


def _read_lock_holder(holder_path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(holder_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
