"""Protocol conformance planning for external MCP/A2A/ACP facades.

This module turns the existing descriptor checks into a product-facing plan for
when CBN can eventually claim wire compatibility. It is intentionally
conservative: current MVP facades remain non-conformant until lifecycle,
transport, auth, and SDK/conformance gates are implemented and verified.
"""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.compatibility import PROTOCOLS, PROTOCOL_SOURCES, check_protocol


def protocol_conformance_plan(
    registry: ManifestRegistry,
    target: str = "all",
    capability_id: str | None = None,
    workflow_path: str | None = None,
) -> dict[str, Any]:
    """Return the conservative conformance plan for MCP/A2A/ACP."""

    protocols = list(PROTOCOLS) if target == "all" else [target]
    unknown = [protocol for protocol in protocols if protocol not in PROTOCOLS]
    if unknown:
        raise KeyError(f"unknown protocol conformance target: {unknown[0]}")
    if capability_id and workflow_path:
        raise ValueError("protocol conformance-plan accepts capability_id or workflow_path, not both")
    reports = {
        protocol: _protocol_report(
            protocol,
            check_protocol(
                registry,
                protocol,
                capability_id=capability_id,
                workflow_path=workflow_path,
            ),
        )
        for protocol in protocols
    }
    summary = _summary(reports)
    return {
        "ok": True,
        "kind": "ProtocolConformancePlan",
        "scope": "workflow" if workflow_path else "capability",
        "target": target,
        "capability_id": capability_id,
        "workflow_path": workflow_path,
        "wire_compatible": False,
        "source_anchors": {protocol: PROTOCOL_SOURCES[protocol] for protocol in protocols},
        "summary": summary,
        "protocols": reports,
        "next_steps": _next_steps(summary),
    }


def _protocol_report(protocol: str, compatibility: dict[str, Any]) -> dict[str, Any]:
    gates = _base_gates(protocol, compatibility)
    gate_counts = _gate_counts(gates)
    return {
        "protocol": protocol,
        "source": compatibility["source"],
        "scope": compatibility["scope"],
        "wire_compatible": False,
        "compatibility_status_counts": compatibility["status_counts"],
        "gate_counts": gate_counts,
        "gates": gates,
        "ready_to_claim_wire_compatibility": False,
        "recommended_next_action": _protocol_next_action(protocol, gates),
    }


def _base_gates(protocol: str, compatibility: dict[str, Any]) -> list[dict[str, Any]]:
    checks = compatibility.get("checks", [])
    if protocol == "mcp":
        return _mcp_gates(checks)
    if protocol == "a2a":
        return _a2a_gates(checks)
    return _acp_gates(checks)


def _mcp_gates(checks: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        _gate(
            "descriptor_shape",
            "MCP descriptor shape",
            _requirement_status(checks, "tools/list descriptor shape", "workflow tools/list descriptor shape"),
            "MCP exports must preserve tool names, input schemas, and CBN metadata.",
            "python -m cbn protocol check mcp --capability-id git.version",
        ),
        _gate(
            "stdio_smoke",
            "MCP stdio smoke",
            _requirement_status(checks, "MCP stdio initialize/tools/list/tools/call smoke", "MCP workflow tools/call smoke"),
            "Current smoke covers a narrow initialize/tools/list/tools/call path over stdio.",
            "python -m cbn mcp smoke --capability-id git.version",
        ),
        _gate(
            "jsonrpc_lifecycle",
            "MCP JSON-RPC lifecycle",
            "partial",
            "protocol lifecycle-suite covers initialize, initialized notification, ping, tools/list, and JSON-RPC error boundaries; cancellation, pagination, progress, and HTTP lifecycle remain missing.",
            "Expand MCP lifecycle fixtures before changing wire_compatible.",
        ),
        _gate(
            "http_transport",
            "MCP streamable HTTP transport",
            "missing",
            "Current MVP has stdio smoke only; HTTP transport is not implemented as a conformance surface.",
            "Implement and test MCP HTTP only after stdio lifecycle is stable.",
        ),
        _gate(
            "sdk_conformance",
            "MCP SDK/conformance suite",
            "missing",
            "Wire compatibility requires official or equivalent MCP client/server conformance coverage.",
            "Run official SDK/conformance tests against the CBN MCP facade.",
        ),
    ]


def _a2a_gates(checks: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        _gate(
            "agent_card",
            "A2A AgentCard discovery",
            _requirement_status(checks, "AgentCard-like descriptor exists", "AgentCard workflow skill exists"),
            "A2A agents must expose discoverable AgentCard skills and CBN metadata.",
            "python -m cbn a2a agent-card",
        ),
        _gate(
            "message_send_smoke",
            "A2A SendMessage smoke",
            _requirement_status(checks, "A2A AgentCard and SendMessage smoke", "A2A workflow SendMessage smoke"),
            "Current smoke covers synchronous local JSON-RPC SendMessage plus task polling/error mappings.",
            "python -m cbn a2a smoke --capability-id git.version",
        ),
        _gate(
            "task_lifecycle",
            "A2A task lifecycle",
            "missing",
            "Add streaming, push notifications, authentication, and broader task lifecycle fixtures.",
            "Run wire-conformance plus SDK/client conformance before release certification.",
        ),
        _gate(
            "auth_and_transport",
            "A2A auth and transport bindings",
            "missing",
            "Local HTTP smoke does not prove auth, remote transport hardening, or client interoperability.",
            "Add auth/session and transport compatibility tests.",
        ),
        _gate(
            "sdk_conformance",
            "A2A SDK/conformance suite",
            "missing",
            "Wire compatibility requires official or equivalent A2A client/server conformance coverage.",
            "Run SDK/conformance tests against the CBN A2A facade.",
        ),
    ]


def _acp_gates(checks: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        _gate(
            "stdio_transport",
            "ACP stdio JSON-RPC transport",
            _requirement_status(checks, "ACP stdio initialize/session/new/session/prompt smoke", "ACP workflow session/prompt smoke"),
            "Current smoke covers newline-delimited UTF-8 stdio JSON-RPC for initialize/session/new/session/prompt.",
            "python -m cbn acp smoke --capability-id git.version",
        ),
        _gate(
            "session_lifecycle",
            "ACP session lifecycle",
            "missing",
            "Add session/load/list/delete/close/resume and prompt turn lifecycle coverage.",
            "Build ACP session lifecycle fixtures before marking wire_compatible.",
        ),
        _gate(
            "streaming_and_cancel",
            "ACP streaming, cancellation, and permission requests",
            "missing",
            "Add session/update notifications, session/cancel, permission requests, and callbacks.",
            "Map ACP permission/callback flows into CBN policy and approval queues.",
        ),
        _gate(
            "file_terminal_callbacks",
            "ACP file and terminal callbacks",
            "missing",
            "CBN must map client file/terminal operations into audited local capabilities.",
            "Add callback fixtures with approval and audit evidence.",
        ),
        _gate(
            "sdk_conformance",
            "ACP SDK/conformance suite",
            "missing",
            "Wire compatibility requires official or equivalent ACP client/server conformance coverage.",
            "Run SDK/conformance tests against the CBN ACP facade.",
        ),
    ]


def _requirement_status(checks: list[dict[str, str]], *requirements: str) -> str:
    wanted = set(requirements)
    for item in checks:
        if item.get("requirement") in wanted:
            return str(item.get("status") or "missing")
    return "missing"


def _gate(
    gate_id: str,
    title: str,
    status: str,
    evidence: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "title": title,
        "status": status,
        "evidence": evidence,
        "next_action": next_action,
        "blocks_wire_compatible": status != "present",
    }


def _gate_counts(gates: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"present": 0, "partial": 0, "missing": 0}
    for gate in gates:
        status = str(gate.get("status") or "missing")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _summary(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total = {"present": 0, "partial": 0, "missing": 0}
    by_protocol = {}
    for protocol, report in reports.items():
        counts = report["gate_counts"]
        by_protocol[protocol] = counts
        for key in total:
            total[key] += int(counts.get(key, 0))
    return {
        "protocol_count": len(reports),
        "gate_count": sum(total.values()),
        "present_gate_count": total["present"],
        "partial_gate_count": total["partial"],
        "missing_gate_count": total["missing"],
        "wire_compatible_protocol_count": 0,
        "by_protocol": by_protocol,
        "recommended_next_action": (
            "implement_protocol_lifecycle_gates"
            if total["missing"]
            else "run_official_conformance_before_wire_compatible"
        ),
    }


def _protocol_next_action(protocol: str, gates: list[dict[str, Any]]) -> str:
    for gate in gates:
        if gate["status"] == "missing":
            return f"implement_{protocol}_{gate['id']}"
    if any(gate["status"] == "partial" for gate in gates):
        return f"harden_{protocol}_partial_smoke_gates"
    return f"run_{protocol}_official_conformance"


def _next_steps(summary: dict[str, Any]) -> list[str]:
    if summary["missing_gate_count"] > 0:
        return [
            "Implement missing lifecycle, transport, auth, callback, and SDK/conformance gates before changing wire_compatible.",
            "Keep BridgeMessage as the internal CLI-to-CLI protocol and treat MCP/A2A/ACP as external facades.",
        ]
    return [
        "Run official or equivalent protocol conformance suites before setting any protocol wire_compatible=true.",
        "Keep per-protocol compatibility flags independent; do not promote all protocols from one passing suite.",
    ]
