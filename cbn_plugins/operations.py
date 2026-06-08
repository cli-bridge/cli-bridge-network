"""Observed plugin operation runner."""

from __future__ import annotations

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
        self._audit(
            "plugin.operation.started",
            operation_id,
            plan,
            {"command_count": len(plan.commands)},
        )
        self._publish(
            EventType.PLUGIN_OPERATION_STARTED,
            plan.plugin_id,
            {"operation_id": operation_id, "action": plan.action},
            operation_id,
        )
        Path(plan.plugin_dir).mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        status = "completed"

        for index, command in enumerate(plan.commands):
            result = self._execute_command(operation_id, plan, index, command)
            results.append(result)
            if result.get("exit_code") not in (0, None) and not command.optional:
                status = "failed"
                break

        payload = {
            "operation_id": operation_id,
            "plugin_id": plan.plugin_id,
            "action": plan.action,
            "status": status,
            "started_at": started_at,
            "completed_at": now_iso(),
            "results": results,
        }
        self._audit("plugin.operation.completed", operation_id, plan, payload)
        self._publish(EventType.PLUGIN_OPERATION_COMPLETED, plan.plugin_id, payload, operation_id)
        return payload

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
