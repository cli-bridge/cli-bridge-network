"""Controlled Adapter Agent tool-use actions for first-run setup."""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cbn_adapter_agent.workflow_init import build_workflow_initialization_plan

if TYPE_CHECKING:
    from cbn_audit.log import AuditLog
    from cbn_events.bus import EventBus


ALLOWED_SECRET_NAMES = {"OBSIDIAN_API_KEY"}
START_COMMAND_IDS = {"login", "login-headless"}


@dataclass(frozen=True)
class SetupCommandExecution:
    call_id: str
    setup_id: str
    command_id: str
    argv: tuple[str, ...]
    env_store: dict[str, str]
    timeout_seconds: int
    audit_log: AuditLog | None
    event_bus: EventBus | None


def store_session_secret(
    env_store: dict[str, str],
    *,
    name: str,
    value: str,
    audit_log: "AuditLog | None" = None,
    event_bus: "EventBus | None" = None,
) -> dict[str, Any]:
    call_id = str(uuid.uuid4())
    if name not in ALLOWED_SECRET_NAMES:
        result = _store_secret_error(call_id, f"secret name is not allowed: {name}")
        _record_lifecycle(audit_log, event_bus, "blocked", result, subject=name)
        return result
    if not value:
        result = _store_secret_error(call_id, "secret value is empty")
        _record_lifecycle(audit_log, event_bus, "blocked", result, subject=name)
        return result
    _record_lifecycle(audit_log, event_bus, "started", _store_secret_started(call_id, name), subject=name)
    env_store[name] = value
    result = _store_secret_success(call_id, name)
    _record_lifecycle(audit_log, event_bus, "completed", result, subject=name)
    return result


def _store_secret_error(call_id: str, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "AdapterAgentToolUseResult",
        "call_id": call_id,
        "action": "store-secret",
        "error": error,
    }


def _store_secret_started(call_id: str, name: str) -> dict[str, Any]:
    return {"call_id": call_id, "action": "store-secret", "stored": name}


def _store_secret_success(call_id: str, name: str) -> dict[str, Any]:
    return {
        "ok": True,
        "kind": "AdapterAgentToolUseResult",
        "call_id": call_id,
        "action": "store-secret",
        "stored": name,
        "persisted": False,
        "note": "Secret is stored only in the current daemon process environment overlay.",
    }


def run_setup_tool(
    *,
    workflow_path: str | Path,
    setup_id: str,
    command_id: str,
    env_store: dict[str, str] | None = None,
    timeout_seconds: int = 30,
    audit_log: "AuditLog | None" = None,
    event_bus: "EventBus | None" = None,
) -> dict[str, Any]:
    call_id = str(uuid.uuid4())
    plan = build_workflow_initialization_plan(Path(workflow_path))
    resolved = _resolve_setup_command(plan, setup_id, command_id, call_id)
    if not resolved["ok"]:
        return _blocked_setup_error(
            audit_log,
            event_bus,
            setup_id,
            resolved["result"],
        )
    execution = SetupCommandExecution(
        call_id=call_id,
        setup_id=setup_id,
        command_id=command_id,
        argv=resolved["argv"],
        env_store=env_store or {},
        timeout_seconds=timeout_seconds,
        audit_log=audit_log,
        event_bus=event_bus,
    )
    return _dispatch_setup_command(execution)


def _resolve_setup_command(
    plan: dict[str, Any],
    setup_id: str,
    command_id: str,
    call_id: str,
) -> dict[str, Any]:
    guide = _setup_guide(plan, setup_id)
    if guide is None:
        return {"ok": False, "result": _error("run-setup-tool", f"unknown setup_id: {setup_id}", call_id=call_id)}
    command = _setup_command(guide, command_id)
    if command is None:
        return {
            "ok": False,
            "result": _error(
                "run-setup-tool",
                f"unknown command_id for {setup_id}: {command_id}",
                call_id=call_id,
                setup_id=setup_id,
                command_id=command_id,
            ),
        }
    argv = _setup_command_argv(command)
    if not argv:
        return {
            "ok": False,
            "result": _error(
                "run-setup-tool",
                "setup command has no argv",
                call_id=call_id,
                setup_id=setup_id,
                command_id=command_id,
            ),
        }
    return {"ok": True, "argv": argv}


def _setup_guide(plan: dict[str, Any], setup_id: str) -> dict[str, Any] | None:
    return next((item for item in plan.get("setup_guides", []) if item.get("setup_id") == setup_id), None)


def _setup_command(guide: dict[str, Any], command_id: str) -> dict[str, Any] | None:
    return next(
        (item for item in guide.get("verification_commands", []) if item.get("id") == command_id),
        None,
    )


def _setup_command_argv(command: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(part) for part in command.get("argv", []))


def _blocked_setup_error(
    audit_log: "AuditLog | None",
    event_bus: "EventBus | None",
    setup_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    _record_lifecycle(audit_log, event_bus, "blocked", result, subject=setup_id)
    return result


def _dispatch_setup_command(request: SetupCommandExecution) -> dict[str, Any]:
    if request.command_id in START_COMMAND_IDS:
        return _start_command(request)
    return _run_command(request)


def _start_command(request: SetupCommandExecution) -> dict[str, Any]:
    _record_lifecycle(
        request.audit_log,
        request.event_bus,
        "started",
        _setup_command_event_payload(request, "start-setup-command"),
        subject=request.setup_id,
    )
    try:
        proc = _launch_setup_command(request.argv)
    except OSError as exc:
        result = _error(
            "start-setup-command",
            str(exc),
            call_id=request.call_id,
            setup_id=request.setup_id,
            command_id=request.command_id,
            argv=request.argv,
        )
        _record_lifecycle(request.audit_log, request.event_bus, "failed", result, subject=request.setup_id)
        return result
    result = {
        "ok": True,
        "kind": "AdapterAgentToolUseResult",
        "call_id": request.call_id,
        "action": "start-setup-command",
        "setup_id": request.setup_id,
        "command_id": request.command_id,
        "argv": list(request.argv),
        "pid": proc.pid,
        "status": "started",
        "note": "Complete the login flow in the opened CLI/browser, then run verification.",
    }
    _record_lifecycle(request.audit_log, request.event_bus, "completed", result, subject=request.setup_id)
    return result


def _launch_setup_command(argv: tuple[str, ...]) -> subprocess.Popen[Any]:
    if os.name == "nt":
        return subprocess.Popen(
            list(argv),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    return subprocess.Popen(list(argv))


def _run_command(request: SetupCommandExecution) -> dict[str, Any]:
    _record_lifecycle(
        request.audit_log,
        request.event_bus,
        "started",
        _setup_command_event_payload(request, "run-setup-command"),
        subject=request.setup_id,
    )
    try:
        proc = _run_setup_subprocess(request.argv, request.env_store, request.timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        result = _timeout_result(request.call_id, request.setup_id, request.command_id, request.argv, exc)
        _record_lifecycle(request.audit_log, request.event_bus, "failed", result, subject=request.setup_id)
        return result
    except OSError as exc:
        result = _error(
            "run-setup-command",
            str(exc),
            call_id=request.call_id,
            setup_id=request.setup_id,
            command_id=request.command_id,
            argv=request.argv,
        )
        _record_lifecycle(request.audit_log, request.event_bus, "failed", result, subject=request.setup_id)
        return result
    result = _completed_run_result(request.call_id, request.setup_id, request.command_id, request.argv, proc)
    _record_lifecycle(
        request.audit_log,
        request.event_bus,
        "completed" if result["ok"] else "failed",
        result,
        subject=request.setup_id,
    )
    return result


def _setup_command_event_payload(request: SetupCommandExecution, action: str) -> dict[str, Any]:
    return {
        "call_id": request.call_id,
        "action": action,
        "setup_id": request.setup_id,
        "command_id": request.command_id,
        "argv": list(request.argv),
    }


def _run_setup_subprocess(
    argv: tuple[str, ...],
    env_store: dict[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_store)
    return subprocess.run(
        list(argv),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        env=env,
    )


def _timeout_result(
    call_id: str,
    setup_id: str,
    command_id: str,
    argv: tuple[str, ...],
    exc: subprocess.TimeoutExpired,
) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "AdapterAgentToolUseResult",
        "call_id": call_id,
        "action": "run-setup-command",
        "setup_id": setup_id,
        "command_id": command_id,
        "argv": list(argv),
        "status": "timeout",
        "stdout": _timeout_text(exc.stdout),
        "stderr": _timeout_text(exc.stderr),
    }


def _completed_run_result(
    call_id: str,
    setup_id: str,
    command_id: str,
    argv: tuple[str, ...],
    proc: subprocess.CompletedProcess[str],
) -> dict[str, Any]:
    return {
        "ok": proc.returncode == 0,
        "kind": "AdapterAgentToolUseResult",
        "call_id": call_id,
        "action": "run-setup-command",
        "setup_id": setup_id,
        "command_id": command_id,
        "argv": list(argv),
        "status": "completed" if proc.returncode == 0 else "failed",
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _error(
    action: str,
    error: str,
    *,
    call_id: str | None = None,
    setup_id: str | None = None,
    command_id: str | None = None,
    argv: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "AdapterAgentToolUseResult",
        "call_id": call_id or str(uuid.uuid4()),
        "action": action,
        "setup_id": setup_id,
        "command_id": command_id,
        "argv": list(argv),
        "error": error,
    }


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _record_lifecycle(
    audit_log: "AuditLog | None",
    event_bus: "EventBus | None",
    phase: str,
    payload: dict[str, Any],
    *,
    subject: str,
) -> None:
    call_id = str(payload.get("call_id") or "")
    safe_payload = _redact_result(payload)
    if audit_log is not None:
        audit_log.append(
            {
                "type": f"adapter_agent.tool_call.{phase}",
                "call_id": call_id,
                "subject": subject,
                "payload": safe_payload,
            }
        )
    if event_bus is not None:
        event_bus.publish(
            f"adapter_agent.tool_call.{phase}",
            subject=subject,
            payload=safe_payload,
            correlation_id=call_id or None,
        )


def _redact_result(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    for key in ("stdout", "stderr"):
        value = redacted.get(key)
        if isinstance(value, str) and len(value) > 500:
            redacted[key] = value[:500]
            redacted[f"{key}_truncated"] = True
    return redacted
