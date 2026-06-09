"""Protocol compatibility reporting for descriptor exports.

The checks here are intentionally conservative. They prove local descriptor
shape and document wire gaps; they do not certify full protocol servers.
"""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.exports import export_protocol, export_workflow_protocol
from cbn_workflow.catalog import list_workflows


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
    workflow_path: str | None = None,
) -> dict[str, Any]:
    if capability_id and workflow_path:
        raise ValueError("protocol check accepts capability_id or workflow_path, not both")
    if protocol == "all":
        return check_all_protocols(registry, capability_id=capability_id, workflow_path=workflow_path)
    if protocol not in PROTOCOL_SOURCES:
        raise KeyError(f"unknown protocol check: {protocol}")
    if workflow_path:
        descriptor = export_workflow_protocol(registry, protocol, workflow_path=workflow_path)
        if protocol == "mcp":
            checks = _check_mcp_workflow(descriptor)
        elif protocol == "a2a":
            checks = _check_a2a_workflow(descriptor)
        else:
            checks = _check_acp_workflow(descriptor)
    else:
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
        "scope": "workflow" if workflow_path else "capability",
        "capability_id": capability_id,
        "workflow_path": workflow_path,
        "wire_compatible": False,
        "source": PROTOCOL_SOURCES[protocol],
        "status_counts": status_counts,
        "checks": checks,
        "next_steps": _next_steps(protocol),
    }


def check_all_protocols(
    registry: ManifestRegistry,
    capability_id: str | None = None,
    workflow_path: str | None = None,
) -> dict[str, Any]:
    return {
        "checks": {
            protocol: check_protocol(
                registry,
                protocol,
                capability_id=capability_id,
                workflow_path=workflow_path,
            )
            for protocol in PROTOCOLS
        }
    }


def protocol_matrix(
    registry: ManifestRegistry,
    include_workflows: bool = False,
) -> dict[str, Any]:
    capability_rows = [
        _matrix_row(
            kind="capability",
            item_id=manifest.capability_id,
            title=manifest.title,
            checks=check_all_protocols(registry, capability_id=manifest.capability_id)["checks"],
            path=None,
        )
        for manifest in sorted(registry.list(), key=lambda item: item.capability_id)
    ]
    workflow_rows = []
    if include_workflows:
        for workflow in list_workflows(registry=registry):
            path = workflow.get("path")
            workflow_id = workflow.get("workflow_id") or path
            if not isinstance(path, str) or not workflow.get("valid"):
                workflow_rows.append(
                    {
                        "kind": "workflow",
                        "id": str(workflow_id),
                        "title": workflow.get("title"),
                        "path": path,
                        "valid": False,
                        "errors": workflow.get("errors", []),
                        "protocols": {},
                    }
                )
                continue
            workflow_rows.append(
                _matrix_row(
                    kind="workflow",
                    item_id=str(workflow_id),
                    title=workflow.get("title"),
                    checks=check_all_protocols(registry, workflow_path=path)["checks"],
                    path=path,
                )
            )
    return {
        "ok": True,
        "protocols": list(PROTOCOLS),
        "include_workflows": include_workflows,
        "capability_count": len(capability_rows),
        "workflow_count": len(workflow_rows),
        "rows": capability_rows + workflow_rows,
        "summary": _matrix_summary(capability_rows + workflow_rows),
    }


def _matrix_row(
    kind: str,
    item_id: str,
    title: Any,
    checks: dict[str, dict[str, Any]],
    path: str | None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": item_id,
        "title": title,
        "path": path,
        "wire_compatible": False,
        "protocols": {
            protocol: {
                "scope": report["scope"],
                "status_counts": report["status_counts"],
                "wire_compatible": report["wire_compatible"],
                "missing": [
                    item["requirement"]
                    for item in report["checks"]
                    if item["status"] == "missing"
                ],
                "partial": [
                    item["requirement"]
                    for item in report["checks"]
                    if item["status"] == "partial"
                ],
            }
            for protocol, report in checks.items()
        },
    }


def _matrix_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_protocol = {
        protocol: {"present": 0, "partial": 0, "missing": 0, "wire_compatible": 0}
        for protocol in PROTOCOLS
    }
    for row in rows:
        for protocol, report in row.get("protocols", {}).items():
            if protocol not in by_protocol:
                continue
            counts = report.get("status_counts", {})
            by_protocol[protocol]["present"] += int(counts.get("present", 0))
            by_protocol[protocol]["partial"] += int(counts.get("partial", 0))
            by_protocol[protocol]["missing"] += int(counts.get("missing", 0))
            if report.get("wire_compatible"):
                by_protocol[protocol]["wire_compatible"] += 1
    return {
        "row_count": len(rows),
        "by_protocol": by_protocol,
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
        _partial(
            "MCP workflow tools/call smoke",
            "python -m cbn mcp smoke-workflow --path workflows/example.json --dry-run exercises workflow:<id> discovery and tools/call execution",
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
        _partial(
            "A2A AgentCard and message/send smoke",
            "python -m cbn a2a smoke exercises /.well-known/agent-card.json and message/send over local HTTP JSON-RPC",
        ),
        _partial(
            "A2A workflow message/send smoke",
            "python -m cbn a2a smoke-workflow --path workflows/example.json --dry-run exercises workflow skills and metadata.cbn.workflow_path execution",
        ),
        _gap(
            "A2A full task lifecycle and conformance",
            "A2A HTTP is an MVP facade; task polling, streaming, cancellation, version negotiation, authentication, and SDK/conformance coverage are not implemented yet",
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
        _partial(
            "ACP stdio initialize/session/new/session/prompt smoke",
            "python -m cbn acp smoke exercises initialize, session/new, and session/prompt over newline-delimited UTF-8 stdio JSON-RPC",
        ),
        _partial(
            "ACP workflow session/prompt smoke",
            "python -m cbn acp smoke-workflow --path workflows/example.json --dry-run exercises _meta.cbn.workflow_path execution",
        ),
        _gap(
            "ACP full session lifecycle and conformance",
            "ACP stdio is an MVP facade; authentication, session/load/list/delete/close/resume, streaming session/update notifications, cancellation, permission requests, client FS/terminal callbacks, and SDK/conformance coverage are not implemented yet",
        ),
    ]


def _check_mcp_workflow(descriptor: dict[str, Any]) -> list[dict[str, str]]:
    tools = descriptor.get("workflowTools")
    first_tool = tools[0] if isinstance(tools, list) and tools else {}
    meta = first_tool.get("_meta", {}) if isinstance(first_tool, dict) else {}
    cbn = meta.get("cbn") if isinstance(meta, dict) else None
    workflow = meta.get("cbn_workflow") if isinstance(meta, dict) else None
    return [
        _check(
            "descriptor declares MCP workflow target",
            descriptor.get("protocol") == "mcp" and descriptor.get("wire_compatible") is False,
            "protocol=mcp and wire_compatible=false",
        ),
        _check(
            "workflow tools/list descriptor shape",
            isinstance(tools, list)
            and all(isinstance(tool.get("name"), str) and tool["name"].startswith("workflow:") for tool in tools),
            "export includes workflowTools entries named workflow:<id>",
        ),
        _check(
            "workflow input schema is JSON object",
            isinstance(first_tool.get("inputSchema"), dict)
            and first_tool["inputSchema"].get("type") == "object",
            "workflow tool exposes dry_run/confirmed inputSchema",
        ),
        _workflow_descriptor_check(cbn, workflow),
        _workflow_routing_check(workflow),
        _partial(
            "MCP workflow tools/call smoke",
            _workflow_smoke_command("mcp", workflow),
        ),
        _gap(
            "MCP workflow full conformance",
            "Workflow tools/call is an MVP facade; streaming progress, cancellation, pagination, HTTP transport, and official conformance coverage are not implemented yet",
        ),
    ]


def _check_a2a_workflow(descriptor: dict[str, Any]) -> list[dict[str, str]]:
    agent_card = descriptor.get("agentCard")
    skills = agent_card.get("skills") if isinstance(agent_card, dict) else None
    first_skill = skills[0] if isinstance(skills, list) and skills else {}
    cbn = first_skill.get("cbn") if isinstance(first_skill, dict) else None
    workflow = first_skill.get("cbn_workflow") if isinstance(first_skill, dict) else None
    return [
        _check(
            "descriptor declares A2A workflow target",
            descriptor.get("protocol") == "a2a" and descriptor.get("wire_compatible") is False,
            "protocol=a2a and wire_compatible=false",
        ),
        _check(
            "AgentCard workflow skill exists",
            isinstance(agent_card, dict)
            and isinstance(skills, list)
            and all(isinstance(skill.get("id"), str) and skill["id"].startswith("workflow:") for skill in skills),
            "AgentCard skills include workflow:<id> entries",
        ),
        _check(
            "workflow skill input/output modes are explicit",
            isinstance(first_skill.get("inputModes"), list)
            and isinstance(first_skill.get("outputModes"), list),
            "workflow skill declares JSON input/output modes",
        ),
        _workflow_descriptor_check(cbn, workflow),
        _workflow_routing_check(workflow),
        _partial(
            "A2A workflow message/send smoke",
            _workflow_smoke_command("a2a", workflow),
        ),
        _gap(
            "A2A workflow full task lifecycle and conformance",
            "Workflow message/send is an MVP facade; task polling, streaming, cancellation, authentication, and SDK/conformance coverage are not implemented yet",
        ),
    ]


def _check_acp_workflow(descriptor: dict[str, Any]) -> list[dict[str, str]]:
    workflows = descriptor.get("workflows")
    first_workflow = workflows[0] if isinstance(workflows, list) and workflows else {}
    cbn = first_workflow.get("cbn") if isinstance(first_workflow, dict) else None
    workflow = first_workflow.get("cbn_workflow") if isinstance(first_workflow, dict) else None
    return [
        _check(
            "descriptor declares ACP workflow target",
            descriptor.get("protocol") == "acp" and descriptor.get("wire_compatible") is False,
            "protocol=acp and wire_compatible=false",
        ),
        _check(
            "workflow descriptors preserve identity",
            isinstance(workflows, list)
            and all(isinstance(item.get("id"), str) and item["id"].startswith("workflow:") for item in workflows),
            "ACP workflow descriptors include workflow:<id> ids",
        ),
        _check(
            "workflow output maps WorkflowRun and BridgeMessage",
            isinstance(first_workflow.get("output"), dict)
            and first_workflow["output"].get("run") == "WorkflowRun"
            and first_workflow["output"].get("messages") == "BridgeMessage[]",
            "ACP workflow output declares WorkflowRun plus task BridgeMessages",
        ),
        _workflow_descriptor_check(cbn, workflow),
        _workflow_routing_check(workflow),
        _partial(
            "ACP workflow session/prompt smoke",
            _workflow_smoke_command("acp", workflow),
        ),
        _gap(
            "ACP workflow full session lifecycle and conformance",
            "Workflow session/prompt is an MVP facade; streaming updates, cancellation, permissions, auth, callbacks, and SDK/conformance coverage are not implemented yet",
        ),
    ]


def _workflow_descriptor_check(cbn: Any, workflow: Any) -> dict[str, str]:
    return _check(
        "CBN workflow descriptor is preserved",
        isinstance(cbn, dict)
        and cbn.get("kind") == "WorkflowDescriptor"
        and cbn.get("output", {}).get("task_message_kind") == "BridgeMessage"
        and isinstance(workflow, dict)
        and workflow.get("valid") is True
        and isinstance(workflow.get("tasks"), list)
        and workflow.get("task_count") == len(workflow["tasks"]),
        "descriptor embeds valid cbn WorkflowDescriptor and cbn_workflow task graph",
    )


def _workflow_routing_check(workflow: Any) -> dict[str, str]:
    if not isinstance(workflow, dict):
        return _check("workflow routing metadata is inspectable", False, "workflow descriptor is missing")
    tasks = workflow.get("tasks")
    routed = []
    if isinstance(tasks, list):
        for task in tasks:
            for mapping in task.get("argsFrom", []) if isinstance(task, dict) else []:
                if isinstance(mapping, dict) and isinstance(mapping.get("selector"), str):
                    routed.append(mapping["selector"])
    has_payload = any(selector.startswith("payload.") for selector in routed)
    has_artifact = any(selector.startswith("artifacts[") for selector in routed)
    evidence = "argsFrom selectors: " + (", ".join(routed) if routed else "none")
    return {
        "requirement": "workflow routing metadata is inspectable",
        "status": "present" if routed else "partial",
        "evidence": (
            f"{evidence}; payload routing={str(has_payload).lower()}; "
            f"artifact routing={str(has_artifact).lower()}"
        ),
    }


def _workflow_smoke_command(protocol: str, workflow: Any) -> str:
    path = "<workflow-path>"
    if isinstance(workflow, dict) and isinstance(workflow.get("path"), str):
        path = workflow["path"]
    return f"python -m cbn {protocol} smoke-workflow --path {path} --dry-run exercises local workflow facade execution"


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
            "Run A2A smoke for each verified capability that should be exposed to peer agents.",
            "Add task polling, streaming, cancellation, authentication, and official SDK/conformance coverage before setting wire_compatible=true.",
        ]
    return [
        "Run ACP smoke for each verified capability that should be exposed to coding-agent clients.",
        "Add streaming session/update notifications, cancellation, permission requests, client callbacks, authentication, and official SDK/conformance coverage before setting wire_compatible=true.",
    ]
