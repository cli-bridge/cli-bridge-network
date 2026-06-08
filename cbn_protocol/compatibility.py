"""Protocol compatibility reporting for descriptor exports.

The checks here are intentionally conservative. They prove local descriptor
shape and document wire gaps; they do not certify full protocol servers.
"""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.exports import export_protocol


PROTOCOL_SOURCES: dict[str, dict[str, str]] = {
    "mcp": {
        "name": "Model Context Protocol Schema Reference",
        "url": "https://modelcontextprotocol.io/specification/2025-11-25/schema",
        "notes": "MCP is JSON-RPC based and exposes initialize plus tools/list and tools/call.",
    },
    "a2a": {
        "name": "Agent2Agent Core Protocol Specification",
        "url": "https://agent2agent.info/specification/core/",
        "notes": "A2A starts with AgentCard discovery and maps operations to JSON-RPC over HTTP, gRPC, or REST bindings.",
    },
    "acp": {
        "name": "Agent Client Protocol v1 Overview and Transports",
        "url": "https://agentclientprotocol.com/protocol/v1/overview",
        "notes": "ACP is JSON-RPC based; stdio messages must be UTF-8 JSON-RPC messages delimited by newlines.",
    },
}

PROTOCOLS = tuple(sorted(PROTOCOL_SOURCES))


def check_protocol(
    registry: ManifestRegistry,
    protocol: str,
    capability_id: str | None = None,
) -> dict[str, Any]:
    if protocol == "all":
        return check_all_protocols(registry, capability_id=capability_id)
    if protocol not in PROTOCOL_SOURCES:
        raise KeyError(f"unknown protocol check: {protocol}")
    descriptor = export_protocol(registry, protocol, capability_id=capability_id)
    if protocol == "mcp":
        checks = _check_mcp(descriptor)
    elif protocol == "a2a":
        checks = _check_a2a(descriptor)
    else:
        checks = _check_acp(descriptor)
    status_counts = _status_counts(checks)
    return {
        "protocol": protocol,
        "capability_id": capability_id,
        "wire_compatible": False,
        "source": PROTOCOL_SOURCES[protocol],
        "status_counts": status_counts,
        "checks": checks,
        "next_steps": _next_steps(protocol),
    }


def check_all_protocols(
    registry: ManifestRegistry,
    capability_id: str | None = None,
) -> dict[str, Any]:
    return {
        "checks": {
            protocol: check_protocol(registry, protocol, capability_id=capability_id)
            for protocol in PROTOCOLS
        }
    }


def _check_mcp(descriptor: dict[str, Any]) -> list[dict[str, str]]:
    tools = descriptor.get("tools")
    first_tool = tools[0] if isinstance(tools, list) and tools else {}
    cbn = first_tool.get("_meta", {}).get("cbn") if isinstance(first_tool, dict) else None
    return [
        _check(
            "descriptor declares MCP target",
            descriptor.get("protocol") == "mcp" and descriptor.get("wire_compatible") is False,
            "protocol=mcp and wire_compatible=false",
        ),
        _check(
            "tools/list descriptor shape",
            isinstance(tools, list) and all(isinstance(tool.get("name"), str) for tool in tools),
            "export includes a tools array with stable tool names",
        ),
        _check(
            "tool input schema is JSON object",
            isinstance(first_tool.get("inputSchema"), dict)
            and first_tool["inputSchema"].get("type") == "object",
            "first tool exposes an object inputSchema",
        ),
        _check(
            "CBN descriptor is preserved in _meta",
            isinstance(cbn, dict) and cbn.get("output", {}).get("message_kind") == "BridgeMessage",
            "tool _meta.cbn carries the BridgeMessage output contract",
        ),
        _partial(
            "MCP stdio initialize/tools/list/tools/call smoke",
            "python -m cbn mcp smoke exercises initialize, notifications/initialized, tools/list, and tools/call over newline-delimited stdio JSON-RPC",
        ),
        _gap(
            "MCP full conformance",
            "MCP stdio is an MVP facade; official SDK/conformance coverage, pagination, cancellation, progress, and HTTP transport are not implemented yet",
        ),
    ]


def _check_a2a(descriptor: dict[str, Any]) -> list[dict[str, str]]:
    agent_card = descriptor.get("agentCard")
    skills = agent_card.get("skills") if isinstance(agent_card, dict) else None
    first_skill = skills[0] if isinstance(skills, list) and skills else {}
    return [
        _check(
            "descriptor declares A2A target",
            descriptor.get("protocol") == "a2a" and descriptor.get("wire_compatible") is False,
            "protocol=a2a and wire_compatible=false",
        ),
        _check(
            "AgentCard-like descriptor exists",
            isinstance(agent_card, dict)
            and isinstance(agent_card.get("name"), str)
            and isinstance(agent_card.get("description"), str),
            "export includes name, description, and skills container",
        ),
        _check(
            "skills preserve CBN capability identity",
            isinstance(skills, list)
            and all(isinstance(skill.get("id"), str) and isinstance(skill.get("name"), str) for skill in skills),
            "skills include id/name fields and embedded CBN descriptors",
        ),
        _check(
            "input/output modes are explicit",
            isinstance(first_skill.get("inputModes"), list)
            and isinstance(first_skill.get("outputModes"), list),
            "skill declares JSON-oriented input and output modes",
        ),
        _gap(
            "A2A discovery and task wire lifecycle",
            "no AgentCard URL, SendMessage, task polling, streaming, or auth binding is implemented yet",
        ),
    ]


def _check_acp(descriptor: dict[str, Any]) -> list[dict[str, str]]:
    tools = descriptor.get("tools")
    first_tool = tools[0] if isinstance(tools, list) and tools else {}
    cbn = first_tool.get("cbn") if isinstance(first_tool, dict) else None
    return [
        _check(
            "descriptor declares ACP target",
            descriptor.get("protocol") == "acp" and descriptor.get("wire_compatible") is False,
            "protocol=acp and wire_compatible=false",
        ),
        _check(
            "tool descriptors preserve transport and policy",
            isinstance(tools, list)
            and all(isinstance(tool.get("id"), str) and isinstance(tool.get("transport"), str) for tool in tools),
            "tools include id, transport, policy, and output summaries",
        ),
        _check(
            "BridgeMessage output mapping is explicit",
            isinstance(first_tool.get("output"), dict)
            and first_tool["output"].get("message") == "BridgeMessage"
            and isinstance(cbn, dict),
            "tool output references BridgeMessage and embeds cbn metadata",
        ),
        _gap(
            "ACP initialize/session stdio wire lifecycle",
            "no newline-delimited UTF-8 JSON-RPC ACP agent process is implemented yet",
        ),
    ]


def _check(requirement: str, passed: bool, evidence: str) -> dict[str, str]:
    return {
        "requirement": requirement,
        "status": "present" if passed else "missing",
        "evidence": evidence if passed else f"not proven: {evidence}",
    }


def _gap(requirement: str, evidence: str) -> dict[str, str]:
    return {
        "requirement": requirement,
        "status": "missing",
        "evidence": evidence,
    }


def _partial(requirement: str, evidence: str) -> dict[str, str]:
    return {
        "requirement": requirement,
        "status": "partial",
        "evidence": evidence,
    }


def _status_counts(checks: list[dict[str, str]]) -> dict[str, int]:
    counts = {"present": 0, "partial": 0, "missing": 0}
    for item in checks:
        status = item["status"]
        counts[status] = counts.get(status, 0) + 1
    return counts


def _next_steps(protocol: str) -> list[str]:
    if protocol == "mcp":
        return [
            "Run MCP smoke for each verified capability that will be exposed to clients.",
            "Add official SDK/conformance coverage before setting wire_compatible=true.",
        ]
    if protocol == "a2a":
        return [
            "Expose AgentCard discovery with endpoint, auth, and version fields.",
            "Implement a minimal SendMessage to task lifecycle bridge backed by CBN workflow/call runs.",
        ]
    return [
        "Implement an ACP stdio agent process using newline-delimited UTF-8 JSON-RPC messages.",
        "Map initialize, session/new, session/prompt, cancellation, and permission requests to CBN runtime primitives.",
    ]
