"""Batch CLI-to-CLI workflow acceptance queue reporting."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.acceptance import cli_to_cli_acceptance_report
from cbn_workflow.catalog import list_workflows
from cbn_workflow.runner import WorkflowRunner


DEFAULT_MAX_WORKFLOWS = 50


def cli_to_cli_acceptance_queue(
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner,
    workflow_paths: Iterable[str] | None = None,
    max_workflows: int = DEFAULT_MAX_WORKFLOWS,
    run: bool = False,
    dry_run: bool = False,
    confirmed: bool = False,
    include_payloads: bool = False,
) -> dict[str, Any]:
    """Return a bounded acceptance matrix for multiple BridgeMessage workflows."""

    selected_paths = _select_workflow_paths(registry, workflow_paths, max_workflows=max_workflows)
    reports = [
        cli_to_cli_acceptance_report(
            registry,
            workflow_runner,
            workflow_path,
            run=run,
            dry_run=dry_run,
            confirmed=confirmed,
            include_payloads=include_payloads,
        )
        for workflow_path in selected_paths
    ]
    rows = [_matrix_row(report) for report in reports]
    summary = _summary(rows)
    ok = bool(rows and summary["blocked_workflow_count"] == 0)
    return {
        "ok": ok,
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "CliToCliAcceptanceQueue",
        "scope": "selected" if workflow_paths else "project",
        "workflow_paths": selected_paths,
        "max_workflows": max_workflows,
        "run": run,
        "dry_run": dry_run,
        "confirmed": confirmed,
        "include_payloads": include_payloads,
        "wire_compatible": False,
        "external_protocol_boundary": (
            "This queue accepts internal BridgeMessage workflow routing only; "
            "MCP/A2A/ACP wire conformance remains a separate smoke/conformance gate."
        ),
        "summary": summary,
        "rows": rows,
        "reports": reports,
        "failures": [row for row in rows if not row["ok"]],
        "next_steps": _next_steps(ok, rows, run),
    }


def _select_workflow_paths(
    registry: ManifestRegistry,
    workflow_paths: Iterable[str] | None,
    max_workflows: int,
) -> list[str]:
    if max_workflows < 1:
        raise ValueError("max_workflows must be greater than zero")
    if workflow_paths:
        paths = [path for path in dict.fromkeys(workflow_paths) if path]
    else:
        paths = [item["path"] for item in list_workflows(registry=registry) if item.get("path")]
    return paths[:max_workflows]


def _matrix_row(report: dict[str, Any]) -> dict[str, Any]:
    contract_workflow = (report.get("contract", {}).get("workflows") or [{}])[0]
    readiness = report.get("readiness", {}).get("readiness") or {}
    summary = report.get("summary", {})
    gates = report.get("gates", {})
    return {
        "workflow_path": report.get("workflow_path"),
        "workflow_id": contract_workflow.get("workflow_id"),
        "title": contract_workflow.get("title"),
        "ok": bool(report.get("ok")),
        "wire_compatible": bool(report.get("wire_compatible")),
        "recommended_next_action": _recommended_next_action(report),
        "route_count": int(summary.get("route_count", 0)),
        "route_ready_count": int(summary.get("route_ready_count", 0)),
        "blocked_route_count": int(summary.get("blocked_route_count", 0)),
        "runtime_route_count": int(summary.get("runtime_route_count", 0)),
        "runtime_route_failed_count": int(summary.get("runtime_route_failed_count", 0)),
        "run_status": summary.get("run_status"),
        "gates": {
            "workflow_contract_ready": bool(gates.get("workflow_contract_ready")),
            "readiness_internal_bridge_ready": bool(gates.get("readiness_internal_bridge_ready")),
            "selector_routes_ready": bool(gates.get("selector_routes_ready")),
            "runtime_execution_completed": gates.get("runtime_execution_completed"),
            "runtime_route_mapping_ready": gates.get("runtime_route_mapping_ready"),
            "external_protocol_wire_compatible": bool(gates.get("external_protocol_wire_compatible")),
        },
        "readiness": {
            "internal_bridge_ready": bool(readiness.get("internal_bridge_ready")),
            "external_protocol_wire_compatible": bool(readiness.get("external_protocol_wire_compatible")),
        },
        "next_steps": list(report.get("next_steps", [])),
    }


def _recommended_next_action(report: dict[str, Any]) -> str:
    if report.get("ok"):
        if report.get("run"):
            return "use_as_runtime_cli_to_cli_fixture"
        return "run_acceptance_with_dry_run_or_protocol_smoke"
    gates = report.get("gates", {})
    if gates.get("workflow_contract_ready") is False or gates.get("selector_routes_ready") is False:
        return "fix_workflow_bridge_contract"
    if gates.get("readiness_internal_bridge_ready") is False:
        return "fix_protocol_readiness_blockers"
    if gates.get("runtime_execution_completed") is False:
        return "inspect_workflow_runtime_failure"
    if gates.get("runtime_route_mapping_ready") is False:
        return "inspect_runtime_route_mapping"
    return "inspect_acceptance_report"


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_action: dict[str, int] = {}
    for row in rows:
        action = row["recommended_next_action"]
        by_action[action] = by_action.get(action, 0) + 1
    return {
        "workflow_count": len(rows),
        "accepted_workflow_count": sum(1 for row in rows if row["ok"]),
        "blocked_workflow_count": sum(1 for row in rows if not row["ok"]),
        "route_count": sum(row["route_count"] for row in rows),
        "route_ready_count": sum(row["route_ready_count"] for row in rows),
        "blocked_route_count": sum(row["blocked_route_count"] for row in rows),
        "runtime_route_count": sum(row["runtime_route_count"] for row in rows),
        "runtime_route_failed_count": sum(row["runtime_route_failed_count"] for row in rows),
        "external_protocol_wire_compatible_count": sum(
            1 for row in rows if row["readiness"]["external_protocol_wire_compatible"]
        ),
        "by_recommended_next_action": dict(sorted(by_action.items())),
    }


def _next_steps(ok: bool, rows: list[dict[str, Any]], run: bool) -> list[str]:
    if not rows:
        return ["Add workflow descriptors before accepting CLI-to-CLI routing."]
    if not ok:
        return [
            "Inspect failures[].next_steps and repair blocked workflow selectors or parser verification.",
            "Re-run this queue before exposing blocked workflows through external protocol facades.",
        ]
    if not run:
        return [
            "Re-run with --run --dry-run to attach runtime route mapping evidence.",
            "Run protocol smoke-suite for accepted workflows before treating MCP/A2A/ACP facades as adapter-ready.",
        ]
    return [
        "Use accepted rows as CLI-to-CLI BridgeMessage routing fixtures.",
        "Keep wire_compatible=false until official MCP/A2A/ACP conformance coverage is added.",
    ]
