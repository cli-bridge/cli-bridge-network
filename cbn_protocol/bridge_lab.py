"""BridgeMessage protocol lab for CLI-to-CLI communication research."""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.acceptance_queue import cli_to_cli_acceptance_queue
from cbn_protocol.bridge_contract import bridge_message_contract, workflow_bridge_contract_report
from cbn_protocol.conformance import protocol_conformance_plan
from cbn_protocol.lifecycle_suite import protocol_lifecycle_suite
from cbn_protocol.readiness import protocol_readiness_report
from cbn_protocol.smoke_suite import protocol_smoke_suite
from cbn_workflow.runner import WorkflowRunner


def bridge_lab_report(
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner | None = None,
    workflow_paths: tuple[str, ...] = (),
    max_workflows: int = 10,
    run: bool = False,
    dry_run: bool = True,
    confirmed: bool = False,
    include_payloads: bool = False,
    run_smoke_suite: bool = False,
) -> dict[str, Any]:
    """Return one bounded report for internal CLI-to-CLI protocol research."""

    selected_path = workflow_paths[0] if len(workflow_paths) == 1 else None
    contract = workflow_bridge_contract_report(registry, workflow_path=selected_path)
    readiness = protocol_readiness_report(
        registry,
        workflow_path=selected_path,
        include_workflows=True,
    )
    acceptance = (
        cli_to_cli_acceptance_queue(
            registry,
            workflow_runner,
            workflow_paths=workflow_paths or None,
            max_workflows=max(1, min(max_workflows, 50)),
            run=run,
            dry_run=dry_run,
            confirmed=confirmed,
            include_payloads=include_payloads,
        )
        if workflow_runner is not None
        else _skipped_acceptance(max_workflows=max_workflows)
    )
    lifecycle = protocol_lifecycle_suite(
        capability_id="git.version",
        workflow_path=selected_path or "workflows/example.json",
    )
    smoke = (
        protocol_smoke_suite(
            registry,
            workflow_paths=workflow_paths or None,
            workflow_dry_run=True,
            workflow_confirmed=confirmed,
            include_payloads=include_payloads,
        )
        if run_smoke_suite
        else {
            "ok": None,
            "run": False,
            "status": "not_run",
            "reason": "pass --smoke-suite to run protocol facade smoke checks",
        }
    )
    conformance = protocol_conformance_plan(
        registry,
        target="all",
        workflow_path=selected_path,
    )
    route_catalog = _route_catalog(contract)
    summary = _summary(
        contract=contract,
        acceptance=acceptance,
        readiness=readiness,
        lifecycle=lifecycle,
        smoke=smoke,
        conformance=conformance,
        route_catalog=route_catalog,
    )
    return {
        "ok": bool(
            summary["bridge_contract_ok"]
            and summary["acceptance_ok"]
            and summary["protocol_lifecycle_ok"]
            and summary["smoke_ok"] is not False
        ),
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "BridgeMessageProtocolLab",
        "workflow_paths": list(workflow_paths),
        "max_workflows": max(1, min(max_workflows, 50)),
        "run": run,
        "dry_run": dry_run,
        "confirmed": confirmed,
        "include_payloads": include_payloads,
        "run_smoke_suite": run_smoke_suite,
        "wire_compatible": False,
        "internal_protocol": bridge_message_contract(),
        "summary": summary,
        "route_catalog": route_catalog,
        "reports": {
            "contract": contract,
            "acceptance_queue": acceptance,
            "readiness": readiness,
            "protocol_lifecycle_suite": lifecycle,
            "protocol_smoke_suite": smoke,
            "conformance_plan": conformance,
        },
        "next_commands": _next_commands(workflow_paths, run_smoke_suite),
    }


def _skipped_acceptance(max_workflows: int) -> dict[str, Any]:
    return {
        "ok": False,
        "skipped": True,
        "kind": "CliToCliAcceptanceQueue",
        "reason": "workflow_runner was not provided",
        "max_workflows": max(1, min(max_workflows, 50)),
        "summary": {
            "workflow_count": 0,
            "accepted_workflow_count": 0,
            "blocked_workflow_count": 0,
            "route_count": 0,
            "route_ready_count": 0,
            "blocked_route_count": 0,
            "runtime_route_count": 0,
            "runtime_route_failed_count": 0,
            "external_protocol_wire_compatible_count": 0,
        },
        "rows": [],
        "failures": [],
    }


def _route_catalog(contract: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for workflow in contract.get("workflows", []):
        if not isinstance(workflow, dict):
            continue
        for route in workflow.get("routes", []):
            if not isinstance(route, dict):
                continue
            rows.append(
                {
                    "workflow_path": workflow.get("path"),
                    "workflow_id": workflow.get("workflow_id"),
                    "source_task": route.get("source_task"),
                    "source_capability": route.get("source_capability"),
                    "consumer_task": route.get("consumer_task"),
                    "consumer_capability": route.get("consumer_capability"),
                    "selector": route.get("selector"),
                    "route_kind": route.get("route_kind"),
                    "source_parser_ref": route.get("source_parser_ref"),
                    "source_output_verified": route.get("source_output_verified"),
                    "argv_mapping_ready": (route.get("argv_mapping") or {}).get("ready"),
                    "ready": bool(route.get("ready")),
                    "blockers": list(route.get("blockers", [])),
                }
            )
    return rows


def _summary(
    contract: dict[str, Any],
    acceptance: dict[str, Any],
    readiness: dict[str, Any],
    lifecycle: dict[str, Any],
    smoke: dict[str, Any],
    conformance: dict[str, Any],
    route_catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    contract_summary = contract.get("summary") if isinstance(contract.get("summary"), dict) else {}
    acceptance_summary = acceptance.get("summary") if isinstance(acceptance.get("summary"), dict) else {}
    readiness_gates = readiness.get("readiness") if isinstance(readiness.get("readiness"), dict) else {}
    conformance_summary = conformance.get("summary") if isinstance(conformance.get("summary"), dict) else {}
    smoke_ok = smoke.get("ok") if smoke.get("run") or smoke.get("status") != "not_run" else None
    accepted_workflow_count = int(acceptance_summary.get("accepted_workflow_count", 0))
    blocked_workflow_count = int(acceptance_summary.get("blocked_workflow_count", 0))
    return {
        "workflow_count": int(contract_summary.get("workflow_count", 0)),
        "routed_workflow_count": int(contract_summary.get("routed_workflow_count", 0)),
        "route_count": len(route_catalog),
        "route_ready_count": sum(1 for route in route_catalog if route["ready"]),
        "blocked_route_count": sum(1 for route in route_catalog if not route["ready"]),
        "accepted_workflow_count": accepted_workflow_count,
        "blocked_workflow_count": blocked_workflow_count,
        "runtime_route_count": int(acceptance_summary.get("runtime_route_count", 0)),
        "runtime_route_failed_count": int(acceptance_summary.get("runtime_route_failed_count", 0)),
        "bridge_contract_ok": bool(contract.get("ok")),
        "acceptance_ok": bool(acceptance.get("ok")),
        "acceptance_skipped": bool(acceptance.get("skipped")),
        "internal_bridge_ready": bool(readiness_gates.get("internal_bridge_ready")),
        "external_protocol_wire_compatible": bool(readiness_gates.get("external_protocol_wire_compatible")),
        "protocol_lifecycle_ok": bool(lifecycle.get("ok")),
        "smoke_ok": smoke_ok,
        "conformance_ready_protocol_count": int(conformance_summary.get("ready_protocol_count", 0)),
        "wire_compatible_protocol_count": int(conformance_summary.get("wire_compatible_protocol_count", 0)),
        "recommended_next_action": _recommended_next_action(
            contract_ok=bool(contract.get("ok")),
            acceptance_ok=bool(acceptance.get("ok")),
            acceptance_skipped=bool(acceptance.get("skipped")),
            blocked_workflow_count=blocked_workflow_count,
            lifecycle_ok=bool(lifecycle.get("ok")),
            smoke_ok=smoke_ok,
        ),
    }


def _recommended_next_action(
    contract_ok: bool,
    acceptance_ok: bool,
    acceptance_skipped: bool,
    blocked_workflow_count: int,
    lifecycle_ok: bool,
    smoke_ok: bool | None,
) -> str:
    if not contract_ok:
        return "fix_bridge_message_contract_routes"
    if acceptance_skipped:
        return "run_bridge_lab_through_runtime"
    if not acceptance_ok or blocked_workflow_count:
        return "fix_cli_to_cli_acceptance_queue"
    if not lifecycle_ok:
        return "fix_protocol_lifecycle_suite"
    if smoke_ok is None:
        return "run_protocol_smoke_suite"
    if smoke_ok is False:
        return "fix_protocol_smoke_suite"
    return "use_routes_as_cli_to_cli_protocol_fixtures"


def _next_commands(workflow_paths: tuple[str, ...], run_smoke_suite: bool) -> list[str]:
    workflow_args = " ".join(f"--workflow-path {path}" for path in workflow_paths)
    commands = [
        f"python -m cbn protocol bridge-lab {workflow_args}".strip(),
        f"python -m cbn protocol bridge-lab {workflow_args} --run --dry-run".strip(),
        f"python -m cbn protocol acceptance-queue {workflow_args} --run --dry-run".strip(),
        "python -m cbn message contract",
        "python -m cbn protocol lifecycle-suite --capability-id git.version --workflow-path workflows/example.json",
    ]
    if not run_smoke_suite:
        commands.append(f"python -m cbn protocol bridge-lab {workflow_args} --smoke-suite".strip())
    return commands
