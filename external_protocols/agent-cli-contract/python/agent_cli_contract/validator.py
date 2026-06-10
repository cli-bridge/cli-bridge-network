"""Small stdlib validator for AgentCliCard and RunReceipt fixtures."""

from __future__ import annotations

from typing import Any


API_VERSION = "agent-cli.dev/v1alpha1"
CARD_KIND = "AgentCliCard"
RECEIPT_KIND = "RunReceipt"
RISKS = {"read", "write-workspace", "privileged", "external-network"}
RUNTIME_KINDS = {"stdio", "pty", "http", "mcp", "agent"}
RECEIPT_STATUSES = {"completed", "failed", "blocked", "running", "canceled"}


def validate_agent_cli_card(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    _require_const(errors, payload, "apiVersion", API_VERSION)
    _require_const(errors, payload, "kind", CARD_KIND)
    metadata = _object(errors, payload, "metadata")
    for key in ("id", "name", "version"):
        _required_string(errors, metadata, f"metadata.{key}", key)
    spec = _object(errors, payload, "spec")
    commands = spec.get("commands")
    if not isinstance(commands, list) or not commands:
        errors.append("spec.commands must be a non-empty array")
        commands = []
    runtime = spec.get("runtime")
    if isinstance(runtime, dict) and runtime.get("kind") not in (None, *RUNTIME_KINDS):
        errors.append(f"spec.runtime.kind is unsupported: {runtime.get('kind')}")
    command_ids: set[str] = set()
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            errors.append(f"spec.commands[{index}] must be an object")
            continue
        _required_string(errors, command, f"spec.commands[{index}].id", "id")
        _required_string(errors, command, f"spec.commands[{index}].title", "title")
        command_id = command.get("id")
        if isinstance(command_id, str):
            if command_id in command_ids:
                errors.append(f"duplicate command id: {command_id}")
            command_ids.add(command_id)
        argv = command.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            errors.append(f"spec.commands[{index}].argv must be a non-empty string array")
        policy = command.get("policy")
        if isinstance(policy, dict) and policy.get("risk") not in (None, *RISKS):
            errors.append(f"spec.commands[{index}].policy.risk is unsupported: {policy.get('risk')}")
    return {
        "ok": not errors,
        "kind": CARD_KIND,
        "errors": errors,
        "command_count": len(commands),
        "command_ids": sorted(command_ids),
    }


def validate_run_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    _require_const(errors, payload, "apiVersion", API_VERSION)
    _require_const(errors, payload, "kind", RECEIPT_KIND)
    for key in ("runId", "cardId", "commandId"):
        _required_string(errors, payload, key, key)
    status = payload.get("status")
    if status not in RECEIPT_STATUSES:
        errors.append(f"status is unsupported: {status}")
    exit_code = payload.get("exitCode")
    if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
        errors.append("exitCode must be an integer or null")
    artifacts = payload.get("artifacts", [])
    if not isinstance(artifacts, list):
        errors.append("artifacts must be an array")
        artifacts = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            errors.append(f"artifacts[{index}] must be an object")
            continue
        _required_string(errors, artifact, f"artifacts[{index}].id", "id")
        _required_string(errors, artifact, f"artifacts[{index}].kind", "kind")
    return {
        "ok": not errors,
        "kind": RECEIPT_KIND,
        "errors": errors,
        "status": status,
        "artifact_count": len(artifacts),
    }


def _require_const(errors: list[str], payload: dict[str, Any], key: str, expected: str) -> None:
    if payload.get(key) != expected:
        errors.append(f"{key} must be {expected}")


def _object(errors: list[str], payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        errors.append(f"{key} must be an object")
        return {}
    return value


def _required_string(errors: list[str], payload: dict[str, Any], label: str, key: str) -> None:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        errors.append(f"{label} must be a non-empty string")
