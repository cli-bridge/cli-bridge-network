"""Controlled Adapter Agent tool-use actions for first-run setup."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from cbn_adapter_agent.workflow_init import build_workflow_initialization_plan


ALLOWED_SECRET_NAMES = {"OBSIDIAN_API_KEY"}
START_COMMAND_IDS = {"login", "login-headless"}


def store_session_secret(
    env_store: dict[str, str],
    *,
    name: str,
    value: str,
) -> dict[str, Any]:
    if name not in ALLOWED_SECRET_NAMES:
        return {
            "ok": False,
            "kind": "AdapterAgentToolUseResult",
            "action": "store-secret",
            "error": f"secret name is not allowed: {name}",
        }
    if not value:
        return {
            "ok": False,
            "kind": "AdapterAgentToolUseResult",
            "action": "store-secret",
            "error": "secret value is empty",
        }
    env_store[name] = value
    return {
        "ok": True,
        "kind": "AdapterAgentToolUseResult",
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
) -> dict[str, Any]:
    plan = build_workflow_initialization_plan(Path(workflow_path))
    guide = next((item for item in plan.get("setup_guides", []) if item.get("setup_id") == setup_id), None)
    if guide is None:
        return _error("run-setup-tool", f"unknown setup_id: {setup_id}")
    command = next(
        (item for item in guide.get("verification_commands", []) if item.get("id") == command_id),
        None,
    )
    if command is None:
        return _error("run-setup-tool", f"unknown command_id for {setup_id}: {command_id}")
    argv = tuple(str(part) for part in command.get("argv", []))
    if not argv:
        return _error("run-setup-tool", "setup command has no argv")

    if command_id in START_COMMAND_IDS:
        return _start_command(setup_id=setup_id, command_id=command_id, argv=argv)
    return _run_command(
        setup_id=setup_id,
        command_id=command_id,
        argv=argv,
        env_store=env_store or {},
        timeout_seconds=timeout_seconds,
    )


def _start_command(*, setup_id: str, command_id: str, argv: tuple[str, ...]) -> dict[str, Any]:
    try:
        if os.name == "nt":
            proc = subprocess.Popen(
                list(argv),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        else:
            proc = subprocess.Popen(list(argv))
    except OSError as exc:
        return _error("start-setup-command", str(exc), setup_id=setup_id, command_id=command_id, argv=argv)
    return {
        "ok": True,
        "kind": "AdapterAgentToolUseResult",
        "action": "start-setup-command",
        "setup_id": setup_id,
        "command_id": command_id,
        "argv": list(argv),
        "pid": proc.pid,
        "status": "started",
        "note": "Complete the login flow in the opened CLI/browser, then run verification.",
    }


def _run_command(
    *,
    setup_id: str,
    command_id: str,
    argv: tuple[str, ...],
    env_store: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(env_store)
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
        return {
            "ok": False,
            "kind": "AdapterAgentToolUseResult",
            "action": "run-setup-command",
            "setup_id": setup_id,
            "command_id": command_id,
            "argv": list(argv),
            "status": "timeout",
            "stdout": _timeout_text(exc.stdout),
            "stderr": _timeout_text(exc.stderr),
        }
    except OSError as exc:
        return _error("run-setup-command", str(exc), setup_id=setup_id, command_id=command_id, argv=argv)
    return {
        "ok": proc.returncode == 0,
        "kind": "AdapterAgentToolUseResult",
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
    setup_id: str | None = None,
    command_id: str | None = None,
    argv: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "AdapterAgentToolUseResult",
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
