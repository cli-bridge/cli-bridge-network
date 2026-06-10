"""Controlled Adapter Agent tool-use actions for first-run setup."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cbn_adapter_agent.workflow_init import build_workflow_initialization_plan

if TYPE_CHECKING:
    from cbn_audit.log import AuditLog
    from cbn_events.bus import EventBus


ALLOWED_SECRET_NAMES = {"OBSIDIAN_API_KEY"}
START_COMMAND_IDS = {"login", "login-headless"}


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
        result = {
            "ok": False,
            "kind": "AdapterAgentToolUseResult",
            "call_id": call_id,
            "action": "store-secret",
            "error": f"secret name is not allowed: {name}",
        }
        _record_lifecycle(audit_log, event_bus, "blocked", result, subject=name)
        return result
    if not value:
        result = {
            "ok": False,
            "kind": "AdapterAgentToolUseResult",
            "call_id": call_id,
            "action": "store-secret",
            "error": "secret value is empty",
        }
        _record_lifecycle(audit_log, event_bus, "blocked", result, subject=name)
        return result
    _record_lifecycle(
        audit_log,
        event_bus,
        "started",
        {"call_id": call_id, "action": "store-secret", "stored": name},
        subject=name,
    )
    env_store[name] = value
    result = {
        "ok": True,
        "kind": "AdapterAgentToolUseResult",
        "call_id": call_id,
        "action": "store-secret",
        "stored": name,
        "persisted": False,
        "note": "Secret is stored only in the current daemon process environment overlay.",
    }
    _record_lifecycle(audit_log, event_bus, "completed", result, subject=name)
    return result


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
    guide = next((item for item in plan.get("setup_guides", []) if item.get("setup_id") == setup_id), None)
    if guide is None:
        result = _error("run-setup-tool", f"unknown setup_id: {setup_id}", call_id=call_id)
        _record_lifecycle(audit_log, event_bus, "blocked", result, subject=setup_id)
        return result
    command = next(
        (item for item in guide.get("verification_commands", []) if item.get("id") == command_id),
        None,
    )
    if command is None:
        result = _error(
            "run-setup-tool",
            f"unknown command_id for {setup_id}: {command_id}",
            call_id=call_id,
            setup_id=setup_id,
            command_id=command_id,
        )
        _record_lifecycle(audit_log, event_bus, "blocked", result, subject=setup_id)
        return result
    argv = tuple(str(part) for part in command.get("argv", []))
    if not argv:
        result = _error(
            "run-setup-tool",
            "setup command has no argv",
            call_id=call_id,
            setup_id=setup_id,
            command_id=command_id,
        )
        _record_lifecycle(audit_log, event_bus, "blocked", result, subject=setup_id)
        return result

    if command_id in START_COMMAND_IDS:
        return _start_command(
            call_id=call_id,
            setup_id=setup_id,
            command_id=command_id,
            argv=argv,
            audit_log=audit_log,
            event_bus=event_bus,
        )
    return _run_command(
        call_id=call_id,
        setup_id=setup_id,
        command_id=command_id,
        argv=argv,
        env_store=env_store or {},
        timeout_seconds=timeout_seconds,
        audit_log=audit_log,
        event_bus=event_bus,
    )


def _start_command(
    *,
    call_id: str,
    setup_id: str,
    command_id: str,
    argv: tuple[str, ...],
    audit_log: "AuditLog | None",
    event_bus: "EventBus | None",
) -> dict[str, Any]:
    _record_lifecycle(
        audit_log,
        event_bus,
        "started",
        {"call_id": call_id, "action": "start-setup-command", "setup_id": setup_id, "command_id": command_id, "argv": list(argv)},
        subject=setup_id,
    )
    try:
        if os.name == "nt":
            proc = subprocess.Popen(
                list(argv),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        else:
            proc = subprocess.Popen(list(argv))
    except OSError as exc:
        result = _error(
            "start-setup-command",
            str(exc),
            call_id=call_id,
            setup_id=setup_id,
            command_id=command_id,
            argv=argv,
        )
        _record_lifecycle(audit_log, event_bus, "failed", result, subject=setup_id)
        return result
    result = {
        "ok": True,
        "kind": "AdapterAgentToolUseResult",
        "call_id": call_id,
        "action": "start-setup-command",
        "setup_id": setup_id,
        "command_id": command_id,
        "argv": list(argv),
        "pid": proc.pid,
        "status": "started",
        "note": "Complete the login flow in the opened CLI/browser, then run verification.",
    }
    _record_lifecycle(audit_log, event_bus, "completed", result, subject=setup_id)
    return result


def _run_command(
    *,
    call_id: str,
    setup_id: str,
    command_id: str,
    argv: tuple[str, ...],
    env_store: dict[str, str],
    timeout_seconds: int,
    audit_log: "AuditLog | None",
    event_bus: "EventBus | None",
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(env_store)
    _record_lifecycle(
        audit_log,
        event_bus,
        "started",
        {"call_id": call_id, "action": "run-setup-command", "setup_id": setup_id, "command_id": command_id, "argv": list(argv)},
        subject=setup_id,
    )
    try:
        proc = subprocess.run(
            list(argv),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        result = {
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
        _record_lifecycle(audit_log, event_bus, "failed", result, subject=setup_id)
        return result
    except OSError as exc:
        result = _error(
            "run-setup-command",
            str(exc),
            call_id=call_id,
            setup_id=setup_id,
            command_id=command_id,
            argv=argv,
        )
        _record_lifecycle(audit_log, event_bus, "failed", result, subject=setup_id)
        return result
    result = {
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
    _record_lifecycle(
        audit_log,
        event_bus,
        "completed" if result["ok"] else "failed",
        result,
        subject=setup_id,
    )
    return result


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
