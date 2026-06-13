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
    _validate_card_metadata(errors, payload)
    spec = _validate_card_spec(errors, payload)
    commands = _card_commands(errors, spec)
    command_ids = _validate_card_commands(errors, commands)
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
    artifacts = _receipt_artifacts(errors, payload)
    _validate_receipt_artifacts(errors, artifacts)
    return {
        "ok": not errors,
        "kind": RECEIPT_KIND,
        "errors": errors,
        "status": status,
        "artifact_count": len(artifacts),
    }


def _validate_card_metadata(errors: list[str], payload: dict[str, Any]) -> None:
    metadata = _object(errors, payload, "metadata")
    for key in ("id", "name", "version"):
        _required_string(errors, metadata, f"metadata.{key}", key)


def _validate_card_spec(errors: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    spec = _object(errors, payload, "spec")
    runtime = spec.get("runtime")
    if isinstance(runtime, dict) and runtime.get("kind") not in (None, *RUNTIME_KINDS):
        errors.append(f"spec.runtime.kind is unsupported: {runtime.get('kind')}")
    return spec


def _card_commands(errors: list[str], spec: dict[str, Any]) -> list[Any]:
    commands = spec.get("commands")
    if isinstance(commands, list) and commands:
        return commands
    errors.append("spec.commands must be a non-empty array")
    return []


def _validate_card_commands(errors: list[str], commands: list[Any]) -> set[str]:
    command_ids: set[str] = set()
    for index, command in enumerate(commands):
        _validate_card_command(errors, command_ids, index, command)
    return command_ids


def _validate_card_command(
    errors: list[str],
    command_ids: set[str],
    index: int,
    command: Any,
) -> None:
    if not isinstance(command, dict):
        errors.append(f"spec.commands[{index}] must be an object")
        return
    _required_string(errors, command, f"spec.commands[{index}].id", "id")
    _required_string(errors, command, f"spec.commands[{index}].title", "title")
    _validate_command_id(errors, command_ids, command)
    _validate_command_argv(errors, index, command)
    _validate_command_policy(errors, index, command)


def _validate_command_id(errors: list[str], command_ids: set[str], command: dict[str, Any]) -> None:
    command_id = command.get("id")
    if not isinstance(command_id, str):
        return
    if command_id in command_ids:
        errors.append(f"duplicate command id: {command_id}")
    command_ids.add(command_id)


def _validate_command_argv(errors: list[str], index: int, command: dict[str, Any]) -> None:
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        errors.append(f"spec.commands[{index}].argv must be a non-empty string array")


def _validate_command_policy(errors: list[str], index: int, command: dict[str, Any]) -> None:
    policy = command.get("policy")
    if isinstance(policy, dict) and policy.get("risk") not in (None, *RISKS):
        errors.append(f"spec.commands[{index}].policy.risk is unsupported: {policy.get('risk')}")


def _receipt_artifacts(errors: list[str], payload: dict[str, Any]) -> list[Any]:
    artifacts = payload.get("artifacts", [])
    if isinstance(artifacts, list):
        return artifacts
    errors.append("artifacts must be an array")
    return []


def _validate_receipt_artifacts(errors: list[str], artifacts: list[Any]) -> None:
    for index, artifact in enumerate(artifacts):
        _validate_receipt_artifact(errors, index, artifact)


def _validate_receipt_artifact(errors: list[str], index: int, artifact: Any) -> None:
    if not isinstance(artifact, dict):
        errors.append(f"artifacts[{index}] must be an object")
        return
    _required_string(errors, artifact, f"artifacts[{index}].id", "id")
    _required_string(errors, artifact, f"artifacts[{index}].kind", "kind")


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
