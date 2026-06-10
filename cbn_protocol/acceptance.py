"""CLI-to-CLI workflow acceptance reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_execution.graph import WorkflowGraph
from cbn_protocol.bridge_contract import workflow_bridge_contract_report
from cbn_core.selector import bridge_value_to_arg, select_bridge_value
from cbn_protocol.readiness import protocol_readiness_report
from cbn_workflow.runner import WorkflowRunner


def cli_to_cli_acceptance_report(
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner,
    workflow_path: str,
    run: bool = False,
    dry_run: bool = False,
    confirmed: bool = False,
    include_payloads: bool = False,
) -> dict[str, Any]:
    """Return static and optional runtime evidence for one BridgeMessage workflow."""

    contract = workflow_bridge_contract_report(registry, workflow_path=workflow_path)
    readiness = protocol_readiness_report(registry, workflow_path=workflow_path)
    run_result = None
    run_error = None
    runtime_routes: list[dict[str, Any]] = []
    if run:
        try:
            graph = WorkflowGraph.from_file(Path(workflow_path))
            run_result = workflow_runner.run(graph, dry_run=dry_run, confirmed=confirmed)
            runtime_routes = _runtime_route_evidence(
                graph=graph,
                run_result=run_result,
                include_payloads=include_payloads,
            )
        except Exception as exc:  # noqa: BLE001 - report acceptance failure as data.
            run_error = str(exc)

    runtime_summary = _runtime_summary(run, run_result, run_error, runtime_routes)
    gates = {
        "workflow_contract_ready": bool(contract.get("ok")),
        "readiness_internal_bridge_ready": bool(
            readiness.get("readiness", {}).get("internal_bridge_ready")
        ),
        "selector_routes_ready": int(contract.get("summary", {}).get("blocked_route_count", 0)) == 0,
        "runtime_execution_completed": None if not run else runtime_summary["run_status"] == "completed",
        "runtime_route_mapping_ready": None if not run else runtime_summary["runtime_route_failed_count"] == 0,
        "external_protocol_wire_compatible": bool(
            readiness.get("readiness", {}).get("external_protocol_wire_compatible")
        ),
    }
    ok = bool(
        gates["workflow_contract_ready"]
        and gates["readiness_internal_bridge_ready"]
        and gates["selector_routes_ready"]
        and (not run or (gates["runtime_execution_completed"] and gates["runtime_route_mapping_ready"]))
    )
    return {
        "ok": ok,
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "CliToCliWorkflowAcceptance",
        "workflow_path": workflow_path,
        "run": run,
        "dry_run": dry_run,
        "confirmed": confirmed,
        "include_payloads": include_payloads,
        "wire_compatible": False,
        "external_protocol_boundary": (
            "BridgeMessage workflow routing is the internal MVP protocol; "
            "MCP/A2A/ACP wire conformance remains a separate gate."
        ),
        "summary": {
            "workflow_count": contract.get("summary", {}).get("workflow_count", 0),
            "route_count": contract.get("summary", {}).get("route_count", 0),
            "route_ready_count": contract.get("summary", {}).get("route_ready_count", 0),
            "blocked_route_count": contract.get("summary", {}).get("blocked_route_count", 0),
            **runtime_summary,
        },
        "gates": gates,
        "contract": contract,
        "readiness": {
            "ok": readiness.get("ok"),
            "scope": readiness.get("scope"),
            "summary": readiness.get("summary"),
            "readiness": readiness.get("readiness"),
            "routes": readiness.get("routes"),
            "protocol_gaps": readiness.get("protocol_gaps"),
        },
        "runtime_routes": runtime_routes,
        "run_result": run_result if include_payloads else _compact_run_result(run_result),
        "run_error": run_error,
        "next_steps": _next_steps(ok, gates),
    }


def _runtime_route_evidence(
    graph: WorkflowGraph,
    run_result: dict[str, Any],
    include_payloads: bool,
) -> list[dict[str, Any]]:
    task_results = {
        task["task_id"]: task
        for task in run_result.get("tasks", [])
        if isinstance(task, dict) and "task_id" in task
    }
    evidence = []
    for task in graph.topological_order():
        consumer_result = task_results.get(task.task_id, {})
        resolved_args = list(consumer_result.get("resolved_args", []))
        base_arg_count = len(task.args)
        for offset, arg_from in enumerate(task.args_from):
            source_result = task_results.get(arg_from.task_id, {})
            message = ((source_result.get("result") or {}).get("message") or {})
            selected = select_bridge_value(message, arg_from.selector)
            expected_arg = bridge_value_to_arg(selected["value"])
            resolved_index = base_arg_count + offset
            resolved_arg = resolved_args[resolved_index] if resolved_index < len(resolved_args) else None
            item = {
                "consumer_task": task.task_id,
                "source_task": arg_from.task_id,
                "selector": arg_from.selector,
                "message_id": (message.get("metadata") or {}).get("id"),
                "producer": (message.get("metadata") or {}).get("producer"),
                "arg_index": resolved_index,
                "expected_arg": expected_arg,
                "resolved_arg": resolved_arg,
                "matched": expected_arg == resolved_arg,
            }
            if include_payloads:
                item["source_message"] = message
            evidence.append(item)
    return evidence


def _runtime_summary(
    run: bool,
    run_result: dict[str, Any] | None,
    run_error: str | None,
    runtime_routes: list[dict[str, Any]],
) -> dict[str, Any]:
    if not run:
        return {
            "run_requested": False,
            "run_status": None,
            "runtime_route_count": 0,
            "runtime_route_ready_count": 0,
            "runtime_route_failed_count": 0,
        }
    failed_routes = sum(1 for route in runtime_routes if not route["matched"])
    return {
        "run_requested": True,
        "run_status": "error" if run_error else (run_result or {}).get("status"),
        "runtime_route_count": len(runtime_routes),
        "runtime_route_ready_count": len(runtime_routes) - failed_routes,
        "runtime_route_failed_count": failed_routes,
    }


def _compact_run_result(run_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if run_result is None:
        return None
    return {
        "run_id": run_result.get("run_id"),
        "workflow_id": run_result.get("workflow_id"),
        "status": run_result.get("status"),
        "task_count": len(run_result.get("tasks", [])),
        "tasks": [
            {
                "task_id": task.get("task_id"),
                "uses": task.get("uses"),
                "resolved_args": task.get("resolved_args", []),
                "ok": (task.get("result") or {}).get("ok"),
                "allowed": (task.get("result") or {}).get("allowed"),
                "message_id": (((task.get("result") or {}).get("message") or {}).get("metadata") or {}).get("id"),
            }
            for task in run_result.get("tasks", [])
            if isinstance(task, dict)
        ],
    }


def _next_steps(ok: bool, gates: dict[str, Any]) -> list[str]:
    if ok:
        return [
            "Use this workflow as a CLI-to-CLI BridgeMessage routing fixture.",
            "Export or smoke the same workflow through MCP/A2A/ACP facade gates.",
        ]
    steps = []
    if not gates["workflow_contract_ready"]:
        steps.append("Fix workflow argsFrom selectors, dependencies, or manifest registry references.")
    if not gates["readiness_internal_bridge_ready"]:
        steps.append("Resolve internal BridgeMessage readiness blockers before protocol export.")
    if gates["runtime_execution_completed"] is False:
        steps.append("Run the workflow directly and inspect blocked or failed tasks.")
    if gates["runtime_route_mapping_ready"] is False:
        steps.append("Compare runtime route expected_arg and resolved_arg evidence.")
    return steps
