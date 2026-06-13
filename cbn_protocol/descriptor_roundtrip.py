"""Descriptor-native workflow call roundtrip checks for protocol facades."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.workflow_calls import resolve_workflow_path


@dataclass(frozen=True)
class RoundtripResolutionRequest:
    registry: ManifestRegistry
    protocol: str
    cbn: Any
    input_descriptor: Any
    generated_call: dict[str, Any]
    cbn_meta: dict[str, Any]
    workflow_tool: Any
    declared_handle: str


def workflow_descriptor_roundtrip(
    registry: ManifestRegistry,
    protocol: str,
    descriptor: dict[str, Any],
) -> dict[str, Any]:
    """Build a minimal protocol-native workflow call and resolve it in CBN."""

    if protocol == "mcp":
        return _mcp_workflow_roundtrip(registry, descriptor)
    if protocol == "a2a":
        return _a2a_workflow_roundtrip(registry, descriptor)
    if protocol == "acp":
        return _acp_workflow_roundtrip(registry, descriptor)
    raise KeyError(f"unknown workflow descriptor protocol: {protocol}")


def _mcp_workflow_roundtrip(registry: ManifestRegistry, descriptor: dict[str, Any]) -> dict[str, Any]:
    tools = descriptor.get("workflowTools")
    tool = tools[0] if isinstance(tools, list) and tools else {}
    cbn = tool.get("_meta", {}).get("cbn") if isinstance(tool, dict) else {}
    schema = tool.get("inputSchema") if isinstance(tool, dict) else {}
    tool_name = tool.get("name") if isinstance(tool, dict) else None
    workflow_id = cbn.get("workflow_id") if isinstance(cbn, dict) else None
    arguments = {
        "workflow_id": workflow_id,
        "dry_run": True,
        "confirmed": False,
    }
    request = {
        "jsonrpc": "2.0",
        "id": "descriptor-roundtrip",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }
    return _resolve_roundtrip(RoundtripResolutionRequest(
        registry=registry,
        protocol="mcp",
        cbn=cbn,
        input_descriptor=schema,
        generated_call=request,
        cbn_meta=arguments,
        workflow_tool=tool_name,
        declared_handle="workflow_id",
    ))


def _a2a_workflow_roundtrip(registry: ManifestRegistry, descriptor: dict[str, Any]) -> dict[str, Any]:
    agent_card = descriptor.get("agentCard")
    skills = agent_card.get("skills") if isinstance(agent_card, dict) else None
    skill = skills[0] if isinstance(skills, list) and skills else {}
    cbn = skill.get("cbn") if isinstance(skill, dict) else {}
    metadata = skill.get("metadata", {}) if isinstance(skill, dict) else {}
    input_descriptor = metadata.get("cbn_input") if isinstance(metadata, dict) else {}
    skill_id = skill.get("id") if isinstance(skill, dict) else None
    workflow_id = cbn.get("workflow_id") if isinstance(cbn, dict) else None
    cbn_meta = {
        "workflow_id": workflow_id,
        "dry_run": True,
        "confirmed": False,
    }
    request = {
        "jsonrpc": "2.0",
        "id": "descriptor-roundtrip",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "descriptor-roundtrip",
                "role": "ROLE_USER",
                "parts": [{"text": "Run CBN workflow"}],
            },
            "metadata": {"cbn": cbn_meta},
        },
    }
    return _resolve_roundtrip(RoundtripResolutionRequest(
        registry=registry,
        protocol="a2a",
        cbn=cbn,
        input_descriptor=input_descriptor,
        generated_call=request,
        cbn_meta=cbn_meta,
        workflow_tool=skill_id,
        declared_handle="metadata.cbn.workflow_id",
    ))


def _acp_workflow_roundtrip(registry: ManifestRegistry, descriptor: dict[str, Any]) -> dict[str, Any]:
    workflows = descriptor.get("workflows")
    workflow = workflows[0] if isinstance(workflows, list) and workflows else {}
    cbn = workflow.get("cbn") if isinstance(workflow, dict) else {}
    input_descriptor = workflow.get("input") if isinstance(workflow, dict) else {}
    workflow_id = cbn.get("workflow_id") if isinstance(cbn, dict) else None
    cbn_meta = {
        "workflow_id": workflow_id,
        "dry_run": True,
        "confirmed": False,
    }
    request = {
        "jsonrpc": "2.0",
        "id": "descriptor-roundtrip",
        "method": "session/prompt",
        "params": {
            "sessionId": "<session-id>",
            "prompt": [{"type": "text", "text": "Run CBN workflow"}],
            "_meta": {"cbn": cbn_meta},
        },
    }
    return _resolve_roundtrip(RoundtripResolutionRequest(
        registry=registry,
        protocol="acp",
        cbn=cbn,
        input_descriptor=input_descriptor,
        generated_call=request,
        cbn_meta=cbn_meta,
        workflow_tool=None,
        declared_handle="workflow_id",
    ))


def _resolve_roundtrip(request: RoundtripResolutionRequest) -> dict[str, Any]:
    expected_path = request.cbn.get("path") if isinstance(request.cbn, dict) else None
    workflow_id = request.cbn.get("workflow_id") if isinstance(request.cbn, dict) else None
    resolved_path, error = _resolve_descriptor_path(request.registry, request.cbn_meta, request.workflow_tool)
    uses_path = bool(request.cbn_meta.get("workflow_path"))
    input_declares_handle = _descriptor_declares(request.input_descriptor, request.declared_handle)
    return {
        "ok": _roundtrip_ok(
            workflow_id=workflow_id,
            uses_path=uses_path,
            input_declares_handle=input_declares_handle,
            expected_path=expected_path,
            resolved_path=resolved_path,
            error=error,
        ),
        "protocol": request.protocol,
        "declared_handle": request.declared_handle,
        "workflow_id": workflow_id,
        "expected_path": expected_path,
        "resolved_path": resolved_path,
        "uses_workflow_path": uses_path,
        "input_declares_handle": input_declares_handle,
        "generated_call": request.generated_call,
        "error": error,
    }


def _resolve_descriptor_path(
    registry: ManifestRegistry,
    cbn_meta: dict[str, Any],
    workflow_tool: Any,
) -> tuple[str | None, str | None]:
    try:
        return (
            resolve_workflow_path(
                SimpleNamespace(registry=registry),
                cbn_meta,
                workflow_tool=workflow_tool if isinstance(workflow_tool, str) else None,
            ),
            None,
        )
    except Exception as exc:
        return None, str(exc)


def _roundtrip_ok(
    *,
    workflow_id: Any,
    uses_path: bool,
    input_declares_handle: bool,
    expected_path: Any,
    resolved_path: Any,
    error: str | None,
) -> bool:
    return (
        isinstance(workflow_id, str)
        and bool(workflow_id)
        and not uses_path
        and input_declares_handle
        and isinstance(expected_path, str)
        and resolved_path == expected_path
        and error is None
    )


def _descriptor_declares(input_descriptor: Any, handle: str) -> bool:
    if not isinstance(input_descriptor, dict):
        return False
    if handle in input_descriptor:
        return True
    properties = input_descriptor.get("properties")
    if isinstance(properties, dict) and handle in properties:
        return True
    return False
