"""Observed plugin operation runner."""

from __future__ import annotations

import os
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from cbn_audit.log import AuditLog
from cbn_artifacts.store import ArtifactStore
from cbn_events.bus import EventBus
from cbn_plugins.manager import PluginCommand, PluginPlan
from protocol import EventType


PLUGIN_COMMAND_OUTPUT_LIMIT_BYTES = 1024 * 1024
PLUGIN_COMMAND_RESULT_TAIL_CHARS = 4000

_ENV_ALLOWLIST = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
)
_SECRET_ENV_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH", "COOKIE")


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
        operation_id, started_at, lock = self._prepare_operation(plan)
        if not lock["acquired"]:
            return self._blocked_operation(operation_id, started_at, plan, lock, {"results": []})
        self._start_operation(operation_id, plan, lock, {"command_count": len(plan.commands)})
        try:
            results, status = self._run_commands(operation_id, plan)
        finally:
            self._release_lock(lock)
        return self._complete_operation(
            operation_id,
            started_at,
            plan,
            lock,
            status,
            {"results": results},
        )

    def execute_write(
        self,
        plan: PluginPlan,
        writer: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        operation_id, started_at, lock = self._prepare_operation(plan)
        if not lock["acquired"]:
            return self._blocked_operation(
                operation_id,
                started_at,
                plan,
                lock,
                {"write_result": None, "artifact_ids": []},
            )
        self._start_operation(operation_id, plan, lock, {"write": True})
        try:
            write_result, status = self._run_writer(operation_id, writer)
        finally:
            self._release_lock(lock)
        artifact_ids = self._record_write_artifact(plan.plugin_id, operation_id, write_result)
        return self._complete_operation(
            operation_id,
            started_at,
            plan,
            lock,
            status,
            {"write_result": write_result, "artifact_ids": artifact_ids},
        )

    def _prepare_operation(self, plan: PluginPlan) -> tuple[str, str, dict[str, Any]]:
        operation_id = str(uuid.uuid4())
        started_at = now_iso()
        Path(plan.plugin_dir).mkdir(parents=True, exist_ok=True)
        lock = self._acquire_lock(plan, operation_id, started_at)
        return operation_id, started_at, lock

    def _blocked_operation(
        self,
        operation_id: str,
        started_at: str,
        plan: PluginPlan,
        lock: dict[str, Any],
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._operation_payload(operation_id, started_at, plan, lock, "blocked", fields)
        payload["blockers"] = ["plugin operation already running"]
        self._audit("plugin.operation.blocked", operation_id, plan, payload)
        self._publish(EventType.PLUGIN_OPERATION_COMPLETED, plan.plugin_id, payload, operation_id)
        return payload

    def _start_operation(
        self,
        operation_id: str,
        plan: PluginPlan,
        lock: dict[str, Any],
        fields: dict[str, Any],
    ) -> None:
        payload = dict(fields)
        payload["lock"] = lock
        self._audit("plugin.operation.started", operation_id, plan, payload)
        started_event = {"operation_id": operation_id, "action": plan.action}
        if fields.get("write") is True:
            started_event["write"] = True
        self._publish(EventType.PLUGIN_OPERATION_STARTED, plan.plugin_id, started_event, operation_id)

    def _run_commands(
        self,
        operation_id: str,
        plan: PluginPlan,
    ) -> tuple[list[dict[str, Any]], str]:
        results: list[dict[str, Any]] = []
        status = "completed"
        for index, command in enumerate(plan.commands):
            result = self._execute_command(operation_id, plan, index, command)
            results.append(result)
            if result.get("exit_code") not in (0, None) and not command.optional:
                status = "failed"
                break
        return results, status

    def _run_writer(
        self,
        operation_id: str,
        writer: Callable[[str], dict[str, Any]],
    ) -> tuple[dict[str, Any], str]:
        try:
            write_result = writer(operation_id)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return {"status": "failed", "error": str(exc), "written": [], "backups": []}, "failed"
        if write_result.get("status") in (None, "completed"):
            return write_result, "completed"
        return write_result, str(write_result.get("status"))

    def _complete_operation(
        self,
        operation_id: str,
        started_at: str,
        plan: PluginPlan,
        lock: dict[str, Any],
        status: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._operation_payload(operation_id, started_at, plan, lock, status, fields)
        self._audit("plugin.operation.completed", operation_id, plan, payload)
        self._publish(EventType.PLUGIN_OPERATION_COMPLETED, plan.plugin_id, payload, operation_id)
        return payload

    def _operation_payload(
        self,
        operation_id: str,
        started_at: str,
        plan: PluginPlan,
        lock: dict[str, Any],
        status: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "operation_id": operation_id,
            "plugin_id": plan.plugin_id,
            "action": plan.action,
            "status": status,
            "started_at": started_at,
            "completed_at": now_iso(),
            "lock": lock,
        }
        payload.update(fields)
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
        skipped = self._skip_existing_clone(operation_id, plan, command_id, command)
        if skipped is not None:
            return skipped
        env, env_policy = _operation_env(command.env)
        self._start_command(operation_id, plan, command_id, command, env_policy)
        captured = _run_command_with_bounded_output(
            argv=command.argv,
            cwd=command.cwd,
            env=env,
            timeout_seconds=command.timeout_seconds,
            output_limit_bytes=PLUGIN_COMMAND_OUTPUT_LIMIT_BYTES,
        )
        result = self._command_result(operation_id, plan, command_id, command, captured, env_policy)
        self._complete_command(operation_id, plan, result)
        return result

    def _skip_existing_clone(
        self,
        operation_id: str,
        plan: PluginPlan,
        command_id: str,
        command: PluginCommand,
    ) -> dict[str, Any] | None:
        if not command.label.startswith("Clone"):
            return None
        if not (Path(plan.plugin_dir) / "repo").exists():
            return None
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

    def _start_command(
        self,
        operation_id: str,
        plan: PluginPlan,
        command_id: str,
        command: PluginCommand,
        env_policy: dict[str, Any],
    ) -> None:
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
                "env_policy": env_policy,
                "output_limit_bytes": PLUGIN_COMMAND_OUTPUT_LIMIT_BYTES,
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

    def _command_result(
        self,
        operation_id: str,
        plan: PluginPlan,
        command_id: str,
        command: PluginCommand,
        captured: dict[str, Any],
        env_policy: dict[str, Any],
    ) -> dict[str, Any]:
        if captured.get("timed_out"):
            return self._timeout_result(operation_id, plan, command_id, command, captured, env_policy)
        if captured.get("spawn_error"):
            return self._spawn_error_result(command_id, command, captured, env_policy)
        return self._success_result(operation_id, plan, command_id, command, captured, env_policy)

    def _timeout_result(
        self,
        operation_id: str,
        plan: PluginPlan,
        command_id: str,
        command: PluginCommand,
        captured: dict[str, Any],
        env_policy: dict[str, Any],
    ) -> dict[str, Any]:
        stdout = str(captured.get("stdout") or "")
        stderr = str(captured.get("stderr") or "")
        if stderr:
            stderr = f"{stderr}\n"
        stderr = f"{stderr}command timed out after {command.timeout_seconds} seconds"
        result = self._base_command_result(command_id, command, captured, env_policy)
        result.update(
            {
                "timed_out": True,
                "exit_code": 124,
                "stdout": stdout[-PLUGIN_COMMAND_RESULT_TAIL_CHARS:],
                "stderr": stderr[-PLUGIN_COMMAND_RESULT_TAIL_CHARS:],
                "artifact_ids": self._record_artifact_texts(
                    plan.plugin_id,
                    operation_id,
                    command_id,
                    stdout,
                    stderr,
                ),
            }
        )
        return result

    def _spawn_error_result(
        self,
        command_id: str,
        command: PluginCommand,
        captured: dict[str, Any],
        env_policy: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._base_command_result(command_id, command, {}, env_policy)
        result.update(
            {
                "timed_out": False,
                "exit_code": 127,
                "stdout": "",
                "stderr": f"{command.argv[0]} failed to start: {captured['spawn_error']}",
                "artifact_ids": [],
            }
        )
        return result

    def _success_result(
        self,
        operation_id: str,
        plan: PluginPlan,
        command_id: str,
        command: PluginCommand,
        captured: dict[str, Any],
        env_policy: dict[str, Any],
    ) -> dict[str, Any]:
        stdout = str(captured.get("stdout") or "")
        stderr = str(captured.get("stderr") or "")
        result = self._base_command_result(command_id, command, captured, env_policy)
        result.update(
            {
                "timed_out": False,
                "exit_code": captured.get("exit_code"),
                "stdout": stdout[-PLUGIN_COMMAND_RESULT_TAIL_CHARS:],
                "stderr": stderr[-PLUGIN_COMMAND_RESULT_TAIL_CHARS:],
                "artifact_ids": self._record_artifact_texts(
                    plan.plugin_id,
                    operation_id,
                    command_id,
                    stdout,
                    stderr,
                ),
            }
        )
        return result

    def _base_command_result(
        self,
        command_id: str,
        command: PluginCommand,
        captured: dict[str, Any],
        env_policy: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "command_id": command_id,
            "label": command.label,
            "argv": list(command.argv),
            "cwd": command.cwd,
            "optional": command.optional,
            "timeout_seconds": command.timeout_seconds,
            "stdout_bytes": captured.get("stdout_bytes", 0),
            "stderr_bytes": captured.get("stderr_bytes", 0),
            "stdout_truncated": captured.get("stdout_truncated", False),
            "stderr_truncated": captured.get("stderr_truncated", False),
            "output_limit_bytes": PLUGIN_COMMAND_OUTPUT_LIMIT_BYTES,
            "env_policy": env_policy,
        }

    def _complete_command(
        self,
        operation_id: str,
        plan: PluginPlan,
        result: dict[str, Any],
    ) -> None:
        self._audit("plugin.command.completed", operation_id, plan, result)
        self._publish(EventType.PLUGIN_COMMAND_COMPLETED, plan.plugin_id, result, operation_id)

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

    def _record_write_artifact(
        self,
        plugin_id: str,
        operation_id: str,
        write_result: dict[str, Any],
    ) -> list[str]:
        if self.artifact_store is None:
            return []
        record = self.artifact_store.create_json(
            capability_id=f"plugin.{plugin_id}",
            call_id=operation_id,
            kind="write-summary",
            payload=write_result,
        )
        return [record.artifact_id]

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


def _run_command_with_bounded_output(
    argv: tuple[str, ...],
    cwd: str | None,
    env: dict[str, str],
    timeout_seconds: int,
    output_limit_bytes: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="cbn-plugin-output-") as tmp:
        stdout_path = Path(tmp) / "stdout.bin"
        stderr_path = Path(tmp) / "stderr.bin"
        process = _run_command_to_files(argv, cwd, env, timeout_seconds, stdout_path, stderr_path)
        if process.get("spawn_error"):
            return process
        return _bounded_command_result(process, stdout_path, stderr_path, output_limit_bytes)


def _run_command_to_files(
    argv: tuple[str, ...],
    cwd: str | None,
    env: dict[str, str],
    timeout_seconds: int,
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, Any]:
    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        try:
            proc = subprocess.Popen(list(argv), cwd=cwd, env=env, stdout=stdout_file, stderr=stderr_file)
        except OSError as exc:
            return {"spawn_error": str(exc)}
        return _wait_for_process(proc, timeout_seconds)


def _wait_for_process(proc: subprocess.Popen[Any], timeout_seconds: int) -> dict[str, Any]:
    try:
        return {"exit_code": proc.wait(timeout=timeout_seconds), "timed_out": False}
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return {"exit_code": 124, "timed_out": True}


def _bounded_command_result(
    process: dict[str, Any],
    stdout_path: Path,
    stderr_path: Path,
    output_limit_bytes: int,
) -> dict[str, Any]:
    stdout = _read_output_tail(stdout_path, output_limit_bytes)
    stderr = _read_output_tail(stderr_path, output_limit_bytes)
    return {
        "exit_code": process["exit_code"],
        "timed_out": process["timed_out"],
        "stdout": stdout["text"],
        "stderr": stderr["text"],
        "stdout_bytes": stdout["total_bytes"],
        "stderr_bytes": stderr["total_bytes"],
        "stdout_truncated": stdout["truncated"],
        "stderr_truncated": stderr["truncated"],
    }


def _read_output_tail(path: Path, limit_bytes: int) -> dict[str, Any]:
    total_bytes = path.stat().st_size if path.exists() else 0
    truncated = total_bytes > limit_bytes
    with path.open("rb") as handle:
        if truncated:
            handle.seek(max(0, total_bytes - limit_bytes))
        data = handle.read(limit_bytes + 1)
    if len(data) > limit_bytes:
        data = data[-limit_bytes:]
        truncated = True
    text = data.decode("utf-8", errors="replace")
    if truncated:
        text = f"[output truncated to last {limit_bytes} of {total_bytes} bytes]\n{text}"
    return {"text": text, "total_bytes": total_bytes, "truncated": truncated}


def _operation_env(overrides: dict[str, str] | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    source_by_upper = {name.upper(): (name, value) for name, value in os.environ.items()}
    env: dict[str, str] = {}
    inherited: list[str] = []
    denied: list[str] = []
    for allow_name in _ENV_ALLOWLIST:
        source = source_by_upper.get(allow_name)
        if source is None:
            continue
        name, value = source
        if _is_secret_env_name(name):
            denied.append(name)
            continue
        env[name] = value
        inherited.append(name)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    inherited.extend(["PYTHONIOENCODING", "PYTHONUTF8"])
    override_keys: list[str] = []
    if overrides:
        for key, value in overrides.items():
            env_name = str(key)
            if _is_secret_env_name(env_name):
                denied.append(env_name)
                continue
            env[env_name] = str(value)
            override_keys.append(env_name)
    return env, {
        "mode": "allowlist",
        "inherited": sorted(set(inherited)),
        "overrides": sorted(set(override_keys)),
        "denied": sorted(set(denied)),
    }


def _is_secret_env_name(name: str) -> bool:
    upper = name.upper()
    if upper in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC"}:
        return False
    return any(marker in upper for marker in _SECRET_ENV_MARKERS)


def _read_lock_holder(holder_path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(holder_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
