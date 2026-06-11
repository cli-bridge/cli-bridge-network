"""Batch smoke suite for protocol facades.

The suite runs CBN's local adapter baseline plus readiness gates. Protocol wire
compatibility is sourced from the dedicated wire-conformance suite.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.a2a_http import smoke_a2a_http, smoke_a2a_workflow_http
from cbn_protocol.acp_stdio import smoke_acp_stdio, smoke_acp_workflow_stdio
from cbn_core.bridge_contract import workflow_bridge_contract_report
from cbn_protocol.compatibility import PROTOCOLS
from cbn_protocol.mcp_stdio import smoke_mcp_stdio, smoke_mcp_workflow_stdio
from cbn_protocol.readiness import protocol_readiness_report


DEFAULT_SMOKE_CAPABILITIES = ("git.version",)
DEFAULT_SMOKE_WORKFLOWS = ("workflows/example.json",)


def protocol_smoke_suite(
    registry: ManifestRegistry,
    capability_ids: Iterable[str] | None = None,
    workflow_paths: Iterable[str] | None = None,
    extra_args: Iterable[str] = (),
    dry_run: bool = False,
    workflow_dry_run: bool = False,
    workflow_confirmed: bool = False,
    include_payloads: bool = False,
) -> dict[str, Any]:
    """Run a bounded MCP/A2A/ACP smoke suite for selected CBN surfaces."""

    selected_capabilities = tuple(DEFAULT_SMOKE_CAPABILITIES if capability_ids is None else capability_ids)
    selected_workflows = tuple(DEFAULT_SMOKE_WORKFLOWS if workflow_paths is None else workflow_paths)
    checks: list[dict[str, Any]] = []

    for capability_id in selected_capabilities:
        checks.extend(
            [
                _capability_check(
                    "mcp",
                    capability_id,
                    smoke_mcp_stdio(capability_id, extra_args=extra_args, dry_run=dry_run),
                    include_payloads=include_payloads,
                ),
                _capability_check(
                    "a2a",
                    capability_id,
                    smoke_a2a_http(capability_id, extra_args=list(extra_args), dry_run=dry_run),
                    include_payloads=include_payloads,
                ),
                _capability_check(
                    "acp",
                    capability_id,
                    smoke_acp_stdio(capability_id, extra_args=extra_args, dry_run=dry_run),
                    include_payloads=include_payloads,
                ),
            ]
        )

    for workflow_path in selected_workflows:
        checks.extend(
            [
                _workflow_check(
                    "mcp",
                    workflow_path,
                    smoke_mcp_workflow_stdio(
                        workflow_path,
                        dry_run=workflow_dry_run,
                        confirmed=workflow_confirmed,
                    ),
                    include_payloads=include_payloads,
                ),
                _workflow_check(
                    "a2a",
                    workflow_path,
                    smoke_a2a_workflow_http(
                        workflow_path,
                        dry_run=workflow_dry_run,
                        confirmed=workflow_confirmed,
                    ),
                    include_payloads=include_payloads,
                ),
                _workflow_check(
                    "acp",
                    workflow_path,
                    smoke_acp_workflow_stdio(
                        workflow_path,
                        dry_run=workflow_dry_run,
                        confirmed=workflow_confirmed,
                    ),
                    include_payloads=include_payloads,
                ),
            ]
        )

    readiness = protocol_readiness_report(registry)
    contract = workflow_bridge_contract_report(registry)
    summary = _summary(checks)
    ok = bool(
        checks
        and summary["failed_count"] == 0
        and readiness["readiness"]["internal_bridge_ready"]
        and contract["ok"]
    )

    return {
        "ok": ok,
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "ProtocolSmokeSuiteReport",
        "scope": "project",
        "wire_compatible": bool(readiness["wire_compatible"]),
        "external_protocol_boundary": readiness["readiness"]["external_protocol_boundary"],
        "capability_ids": list(selected_capabilities),
        "workflow_paths": list(selected_workflows),
        "dry_run": dry_run,
        "workflow_dry_run": workflow_dry_run,
        "workflow_confirmed": workflow_confirmed,
        "include_payloads": include_payloads,
        "summary": summary,
        "readiness": {
            "ok": readiness["ok"],
            "internal_bridge_ready": readiness["readiness"]["internal_bridge_ready"],
            "bridge_message_contract_ready": readiness["readiness"]["bridge_message_contract_ready"],
            "verified_parser_coverage": readiness["readiness"]["verified_parser_coverage"],
            "external_protocol_wire_compatible": readiness["readiness"]["external_protocol_wire_compatible"],
            "route_count": readiness["summary"]["route_count"],
            "unverified_output_count": readiness["parser_coverage"]["unverified_output_count"],
            "portable_manifest_count": readiness["manifest_sources"]["portable_manifest_count"],
            "runtime_local_overlay_count": readiness["manifest_sources"]["runtime_local_overlay_count"],
        },
        "bridge_contract": {
            "ok": contract["ok"],
            "route_count": contract["summary"]["route_count"],
            "route_ready_count": contract["summary"].get("route_ready_count", 0),
            "blocked_route_count": contract["summary"].get("blocked_route_count", 0),
        },
        "checks": checks,
        "failures": [check for check in checks if not check["ok"]],
        "next_steps": _next_steps(ok),
    }


def _capability_check(
    protocol: str,
    capability_id: str,
    payload: dict[str, Any],
    include_payloads: bool,
) -> dict[str, Any]:
    check = {
        "kind": "capability",
        "protocol": protocol,
        "target": capability_id,
        "ok": bool(payload.get("ok")),
        "return_code": payload.get("return_code"),
        "evidence": _capability_evidence(protocol, payload),
    }
    if include_payloads:
        check["payload"] = payload
    return check


def _workflow_check(
    protocol: str,
    workflow_path: str,
    payload: dict[str, Any],
    include_payloads: bool,
) -> dict[str, Any]:
    check = {
        "kind": "workflow",
        "protocol": protocol,
        "target": workflow_path,
        "ok": bool(payload.get("ok")),
        "return_code": payload.get("return_code"),
        "evidence": _workflow_evidence(protocol, payload),
    }
    if include_payloads:
        check["payload"] = payload
    return check


def _capability_evidence(protocol: str, payload: dict[str, Any]) -> dict[str, Any]:
    if protocol == "mcp":
        responses = payload.get("responses", [])
        tool_call = responses[2].get("result", {}) if len(responses) > 2 else {}
        structured = tool_call.get("structuredContent", {})
        return {
            "response_count": len(responses),
            "capability_listed": _mcp_tool_listed(payload.get("capability_id"), responses),
            "is_error": tool_call.get("isError"),
            "allowed": structured.get("allowed"),
            "exit_code": structured.get("exit_code"),
        }
    if protocol == "a2a":
        task = payload.get("response", {}).get("result", {})
        cbn = task.get("metadata", {}).get("cbn", {})
        return {
            "agent_card_skill_listed": _a2a_skill_listed(payload.get("capability_id"), payload.get("agent_card", {})),
            "task_state": task.get("status", {}).get("state"),
            "allowed": cbn.get("allowed"),
            "exit_code": cbn.get("exit_code"),
        }
    responses = payload.get("responses", [])
    prompt = responses[2].get("result", {}) if len(responses) > 2 else {}
    cbn = prompt.get("_meta", {}).get("cbn", {})
    return {
        "response_count": len(responses),
        "stop_reason": prompt.get("stopReason"),
        "allowed": cbn.get("allowed"),
        "exit_code": cbn.get("exit_code"),
    }


def _workflow_evidence(protocol: str, payload: dict[str, Any]) -> dict[str, Any]:
    if protocol == "mcp":
        responses = payload.get("responses", [])
        tool_call = responses[2].get("result", {}) if len(responses) > 2 else {}
        structured = tool_call.get("structuredContent", {})
        return {
            "response_count": len(responses),
            "tool_name": payload.get("tool_name"),
            "is_error": tool_call.get("isError"),
            "run_status": structured.get("run", {}).get("status"),
        }
    if protocol == "a2a":
        task = payload.get("response", {}).get("result", {})
        cbn = task.get("metadata", {}).get("cbn", {})
        return {
            "workflow_id": payload.get("workflow_id"),
            "task_state": task.get("status", {}).get("state"),
            "run_status": cbn.get("status"),
        }
    responses = payload.get("responses", [])
    prompt = responses[2].get("result", {}) if len(responses) > 2 else {}
    cbn = prompt.get("_meta", {}).get("cbn", {})
    return {
        "response_count": len(responses),
        "stop_reason": prompt.get("stopReason"),
        "run_status": cbn.get("status"),
    }


def _summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    by_protocol = {protocol: {"passed": 0, "failed": 0} for protocol in PROTOCOLS}
    by_kind = {"capability": {"passed": 0, "failed": 0}, "workflow": {"passed": 0, "failed": 0}}
    for check in checks:
        bucket = "passed" if check["ok"] else "failed"
        by_protocol[check["protocol"]][bucket] += 1
        by_kind[check["kind"]][bucket] += 1
    return {
        "check_count": len(checks),
        "passed_count": sum(1 for check in checks if check["ok"]),
        "failed_count": sum(1 for check in checks if not check["ok"]),
        "by_protocol": by_protocol,
        "by_kind": by_kind,
    }


def _mcp_tool_listed(capability_id: Any, responses: list[Any]) -> bool:
    tools = responses[1].get("result", {}).get("tools", []) if len(responses) > 1 else []
    return any(tool.get("name") == capability_id for tool in tools if isinstance(tool, dict))


def _a2a_skill_listed(capability_id: Any, agent_card: dict[str, Any]) -> bool:
    return any(skill.get("id") == capability_id for skill in agent_card.get("skills", []) if isinstance(skill, dict))


def _next_steps(ok: bool) -> list[str]:
    if not ok:
        return [
            "Inspect failures[].evidence and rerun the failing protocol/capability pair directly.",
            "Keep wire_compatible=false until protocol wire-conformance checks pass.",
        ]
    return [
        "Use this suite as the repeatable gate when adapting additional CLI-Anything harnesses.",
        "Run third-party SDK/client conformance before release certification.",
    ]
