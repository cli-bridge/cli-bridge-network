"""BridgeMessage protocol lab for CLI-to-CLI communication research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.acceptance_queue import cli_to_cli_acceptance_queue
from cbn_core.bridge_contract import bridge_message_contract, workflow_bridge_contract_report
from cbn_protocol.conformance import protocol_conformance_plan
from cbn_protocol.lifecycle_suite import protocol_lifecycle_suite
from cbn_protocol.readiness import protocol_readiness_report
from cbn_protocol.smoke_suite import protocol_smoke_suite
from cbn_protocol.wire_conformance import protocol_wire_conformance_suite
from cbn_workflow.runner import WorkflowRunner


_BRIDGE_LAB_OPTION_NAMES = (
    "workflow_paths",
    "max_workflows",
    "run",
    "dry_run",
    "confirmed",
    "include_payloads",
    "run_smoke_suite",
)


@dataclass(frozen=True)
class BridgeLabOptions:
    workflow_paths: tuple[str, ...]
    max_workflows: int
    run: bool
    dry_run: bool
    confirmed: bool
    include_payloads: bool
    run_smoke_suite: bool

    @property
    def selected_workflow_path(self) -> str | None:
        return self.workflow_paths[0] if len(self.workflow_paths) == 1 else None

    @property
    def bounded_max_workflows(self) -> int:
        return max(1, min(self.max_workflows, 50))


def bridge_lab_report(
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner | None = None,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return one bounded report for internal CLI-to-CLI protocol research."""

    options = _bridge_lab_options(args, kwargs)
    reports = _lab_reports(registry, workflow_runner, options)
    route_catalog = _route_catalog(reports["contract"])
    summary = _summary(reports, route_catalog)
    return _lab_payload(options, route_catalog, summary, reports)


def _bridge_lab_options(args: tuple[Any, ...], kwargs: dict[str, Any]) -> BridgeLabOptions:
    if len(args) > len(_BRIDGE_LAB_OPTION_NAMES):
        raise TypeError(f"bridge_lab_report expected at most {len(_BRIDGE_LAB_OPTION_NAMES) + 2} arguments")
    values = {
        "workflow_paths": (),
        "max_workflows": 10,
        "run": False,
        "dry_run": True,
        "confirmed": False,
        "include_payloads": False,
        "run_smoke_suite": False,
    }
    for name, value in zip(_BRIDGE_LAB_OPTION_NAMES, args):
        if name in kwargs:
            raise TypeError(f"bridge_lab_report got multiple values for argument '{name}'")
        values[name] = value
    unknown = sorted(set(kwargs) - set(_BRIDGE_LAB_OPTION_NAMES))
    if unknown:
        raise TypeError(f"unknown bridge lab option(s): {', '.join(unknown)}")
    values.update(kwargs)
    values["workflow_paths"] = tuple(values["workflow_paths"])
    return BridgeLabOptions(**values)


def _lab_reports(
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner | None,
    options: BridgeLabOptions,
) -> dict[str, Any]:
    selected_path = options.selected_workflow_path
    return {
        "contract": workflow_bridge_contract_report(registry, workflow_path=selected_path),
        "acceptance": _acceptance_report(registry, workflow_runner, options),
        "readiness": protocol_readiness_report(
            registry,
            workflow_path=selected_path,
            include_workflows=True,
        ),
        "lifecycle": protocol_lifecycle_suite(
            capability_id="git.version",
            workflow_path=selected_path or "workflows/example.json",
        ),
        "smoke": _smoke_report(registry, options),
        "conformance": protocol_conformance_plan(
            registry,
            target="all",
            workflow_path=selected_path,
        ),
        "wire_conformance": protocol_wire_conformance_suite(),
    }


def _acceptance_report(
    registry: ManifestRegistry,
    workflow_runner: WorkflowRunner | None,
    options: BridgeLabOptions,
) -> dict[str, Any]:
    if workflow_runner is None:
        return _skipped_acceptance(max_workflows=options.max_workflows)
    return cli_to_cli_acceptance_queue(
        registry,
        workflow_runner,
        workflow_paths=options.workflow_paths or None,
        max_workflows=options.bounded_max_workflows,
        run=options.run,
        dry_run=options.dry_run,
        confirmed=options.confirmed,
        include_payloads=options.include_payloads,
    )


def _smoke_report(
    registry: ManifestRegistry,
    options: BridgeLabOptions,
) -> dict[str, Any]:
    if not options.run_smoke_suite:
        return {
            "ok": None,
            "run": False,
            "status": "not_run",
            "reason": "pass --smoke-suite to run protocol facade smoke checks",
        }
    return protocol_smoke_suite(
        registry,
        workflow_paths=options.workflow_paths or None,
        workflow_dry_run=True,
        workflow_confirmed=options.confirmed,
        include_payloads=options.include_payloads,
    )


def _lab_payload(
    options: BridgeLabOptions,
    route_catalog: list[dict[str, Any]],
    summary: dict[str, Any],
    reports: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": bool(
            summary["bridge_contract_ok"]
            and summary["acceptance_ok"]
            and summary["protocol_lifecycle_ok"]
            and summary["smoke_ok"] is not False
        ),
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "BridgeMessageProtocolLab",
        "workflow_paths": list(options.workflow_paths),
        "max_workflows": options.bounded_max_workflows,
        "run": options.run,
        "dry_run": options.dry_run,
        "confirmed": options.confirmed,
        "include_payloads": options.include_payloads,
        "run_smoke_suite": options.run_smoke_suite,
        "wire_compatible": bool(reports["wire_conformance"].get("wire_compatible")),
        "internal_protocol": bridge_message_contract(),
        "summary": summary,
        "route_catalog": route_catalog,
        "reports": {
            "contract": reports["contract"],
            "acceptance_queue": reports["acceptance"],
            "readiness": reports["readiness"],
            "protocol_lifecycle_suite": reports["lifecycle"],
            "protocol_smoke_suite": reports["smoke"],
            "conformance_plan": reports["conformance"],
            "wire_conformance": reports["wire_conformance"],
        },
        "next_commands": _next_commands(options.workflow_paths, options.run_smoke_suite),
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


def _summary(reports: dict[str, Any], route_catalog: list[dict[str, Any]]) -> dict[str, Any]:
    sources = _summary_sources(reports)
    contract = sources["contract"]
    acceptance = sources["acceptance"]
    lifecycle = sources["lifecycle"]
    smoke = sources["smoke"]
    contract_summary = contract.get("summary") if isinstance(contract.get("summary"), dict) else {}
    acceptance_summary = sources["acceptance_summary"]
    readiness_gates = sources["readiness_gates"]
    conformance_summary = sources["conformance_summary"]
    wire_summary = sources["wire_summary"]
    smoke_ok = smoke.get("ok") if smoke.get("run") or smoke.get("status") != "not_run" else None
    counts = _summary_counts(contract_summary, acceptance_summary, route_catalog)
    return {
        **counts,
        "bridge_contract_ok": bool(contract.get("ok")),
        "acceptance_ok": bool(acceptance.get("ok")),
        "acceptance_skipped": bool(acceptance.get("skipped")),
        "internal_bridge_ready": bool(readiness_gates.get("internal_bridge_ready")),
        "external_protocol_wire_compatible": bool(readiness_gates.get("external_protocol_wire_compatible")),
        "protocol_lifecycle_ok": bool(lifecycle.get("ok")),
        "smoke_ok": smoke_ok,
        "conformance_ready_protocol_count": int(conformance_summary.get("ready_protocol_count", 0)),
        "wire_compatible_protocol_count": int(wire_summary.get("wire_compatible_protocol_count", 0)),
        "recommended_next_action": _recommended_next_action(
            contract_ok=bool(contract.get("ok")),
            acceptance_ok=bool(acceptance.get("ok")),
            acceptance_skipped=bool(acceptance.get("skipped")),
            blocked_workflow_count=counts["blocked_workflow_count"],
            lifecycle_ok=bool(lifecycle.get("ok")),
            smoke_ok=smoke_ok,
        ),
    }


def _summary_counts(
    contract_summary: dict[str, Any],
    acceptance_summary: dict[str, Any],
    route_catalog: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "workflow_count": int(contract_summary.get("workflow_count", 0)),
        "routed_workflow_count": int(contract_summary.get("routed_workflow_count", 0)),
        "route_count": len(route_catalog),
        "route_ready_count": sum(1 for route in route_catalog if route["ready"]),
        "blocked_route_count": sum(1 for route in route_catalog if not route["ready"]),
        "accepted_workflow_count": int(acceptance_summary.get("accepted_workflow_count", 0)),
        "blocked_workflow_count": int(acceptance_summary.get("blocked_workflow_count", 0)),
        "runtime_route_count": int(acceptance_summary.get("runtime_route_count", 0)),
        "runtime_route_failed_count": int(acceptance_summary.get("runtime_route_failed_count", 0)),
    }


def _summary_sources(reports: dict[str, Any]) -> dict[str, Any]:
    readiness = reports["readiness"]
    conformance = reports["conformance"]
    wire_conformance = reports["wire_conformance"]
    return {
        "contract": reports["contract"],
        "acceptance": reports["acceptance"],
        "readiness": readiness,
        "lifecycle": reports["lifecycle"],
        "smoke": reports["smoke"],
        "conformance": conformance,
        "wire_conformance": wire_conformance,
        "acceptance_summary": _dict_field(reports["acceptance"], "summary"),
        "readiness_gates": _dict_field(readiness, "readiness"),
        "conformance_summary": _dict_field(conformance, "summary"),
        "wire_summary": _dict_field(wire_conformance, "summary"),
    }


def _dict_field(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


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
