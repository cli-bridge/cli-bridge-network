"""MVP and first-run planning helpers for CLI-Anything."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cbn_plugins.manager import PluginManager
from cbn_plugins.cli_anything_parts.verification import load_manifest_registry
from cbn_protocol.acceptance_queue import cli_to_cli_acceptance_queue
from cbn_protocol.lifecycle_suite import protocol_lifecycle_suite
from cbn_protocol.readiness import protocol_readiness_report


PLUGIN_ID = "cli-anything"
_MVP_PLAN_OPTION_NAMES = (
    "query",
    "limit",
    "max_harnesses",
    "include_blocked",
    "workflow_paths",
    "max_workflows",
    "registry",
    "workflow_runner",
)


@dataclass(frozen=True)
class MvpPlanRequest:
    query: str | None
    limit: int
    max_harnesses: int
    include_blocked: bool
    workflow_paths: tuple[str, ...]
    max_workflows: int
    registry: Any | None
    workflow_runner: Any | None


@dataclass(frozen=True)
class MvpPlanReportInput:
    request: MvpPlanRequest
    summary: dict[str, Any]
    reports: dict[str, Any]


@dataclass(frozen=True)
class MvpPlanNextActionInput:
    source_downloaded: bool
    plugin_install_ready: bool
    queued_count: int
    ready_for_repair_write_count: int
    smoke_ready_count: int
    adaptation_blocked_count: int
    internal_bridge_ready: bool
    blocked_workflow_count: int


@dataclass(frozen=True)
class MvpPlanSummaryContext:
    install_summary: dict[str, Any]
    adaptation_summary: dict[str, Any]
    protocol_gates: dict[str, Any]
    acceptance_summary: dict[str, Any]
    counts: dict[str, int]
    state: dict[str, bool]


@dataclass(frozen=True)
class BootstrapPlanContext:
    reports: dict[str, Any]
    environment: dict[str, Any]
    market_scan: dict[str, Any]
    onboarding: dict[str, Any]
    lifecycle_suite: dict[str, Any]
    summary: dict[str, Any]


def safe_plugin_report(builder: Any) -> dict[str, Any]:
    try:
        return builder()
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def mvp_plan_summary(
    environment: dict[str, Any],
    install_gate: dict[str, Any],
    install_queue: dict[str, Any],
    adaptation_queue: dict[str, Any],
    protocol_readiness: dict[str, Any],
    acceptance_queue: dict[str, Any],
) -> dict[str, Any]:
    context = mvp_plan_summary_context(
        environment=environment,
        install_gate=install_gate,
        install_queue=install_queue,
        adaptation_queue=adaptation_queue,
        protocol_readiness=protocol_readiness,
        acceptance_queue=acceptance_queue,
    )
    return mvp_plan_summary_payload(context, environment, install_gate, install_queue)


def mvp_plan_summary_payload(
    context: MvpPlanSummaryContext,
    environment: dict[str, Any],
    install_gate: dict[str, Any],
    install_queue: dict[str, Any],
) -> dict[str, Any]:
    return {
        **mvp_plan_base_summary(
            environment=environment,
            install_gate=install_gate,
            install_queue=install_queue,
            adaptation_summary=context.adaptation_summary,
            protocol_gates=context.protocol_gates,
            counts=context.counts,
            state=context.state,
        ),
        **mvp_plan_readiness(
            counts=context.counts,
            plugin_install_ready=context.state["plugin_install_ready"],
            internal_bridge_ready=context.state["internal_bridge_ready"],
            acceptance_skipped=context.state["acceptance_skipped"],
        ),
        "recommended_next_action": mvp_plan_recommended_next_action(
            source_downloaded=context.state["source_downloaded"],
            plugin_install_ready=context.state["plugin_install_ready"],
            counts=context.counts,
            internal_bridge_ready=context.state["internal_bridge_ready"],
        ),
    }


def mvp_plan_summary_context(
    *,
    environment: dict[str, Any],
    install_gate: dict[str, Any],
    install_queue: dict[str, Any],
    adaptation_queue: dict[str, Any],
    protocol_readiness: dict[str, Any],
    acceptance_queue: dict[str, Any],
) -> MvpPlanSummaryContext:
    install_summary, adaptation_summary, protocol_gates, acceptance_summary = mvp_plan_source_summaries(
        install_queue=install_queue,
        adaptation_queue=adaptation_queue,
        protocol_readiness=protocol_readiness,
        acceptance_queue=acceptance_queue,
    )
    counts = mvp_plan_counts(
        install_summary=install_summary,
        adaptation_summary=adaptation_summary,
        acceptance_summary=acceptance_summary,
    )
    state = mvp_plan_state(environment, install_gate, protocol_gates, acceptance_queue)
    return MvpPlanSummaryContext(
        install_summary,
        adaptation_summary,
        protocol_gates,
        acceptance_summary,
        counts,
        state,
    )


def mvp_plan_state(
    environment: dict[str, Any],
    install_gate: dict[str, Any],
    protocol_gates: dict[str, Any],
    acceptance_queue: dict[str, Any],
) -> dict[str, bool]:
    source_downloaded = bool(environment.get("source_downloaded"))
    return {
        "source_downloaded": source_downloaded,
        "entrypoint_available": environment_entrypoint_available(environment),
        "plugin_install_ready": bool(install_gate.get("ok") or source_downloaded),
        "internal_bridge_ready": bool(protocol_gates.get("internal_bridge_ready")),
        "acceptance_skipped": bool(acceptance_queue.get("skipped")),
    }


def mvp_plan_base_summary(
    *,
    environment: dict[str, Any],
    install_gate: dict[str, Any],
    install_queue: dict[str, Any],
    adaptation_summary: dict[str, Any],
    protocol_gates: dict[str, Any],
    counts: dict[str, int],
    state: dict[str, bool],
) -> dict[str, Any]:
    return {
        "source_downloaded": state["source_downloaded"],
        "source_trusted": environment.get("source_trusted"),
        "entrypoint_available": state["entrypoint_available"],
        "plugin_install_gate_ok": bool(install_gate.get("ok")),
        "plugin_install_ready": state["plugin_install_ready"],
        "install_queue_ok": bool(install_queue.get("ok")),
        "queued_harness_count": counts["queued_count"],
        "blocked_install_count": counts["blocked_install_count"],
        "adaptation_harness_count": int(adaptation_summary.get("harness_count", 0)),
        "native_ready_count": counts["native_ready_count"],
        "ready_for_repair_write_count": counts["ready_for_repair_write_count"],
        "smoke_ready_count": counts["smoke_ready_count"],
        "adaptation_blocked_count": counts["adaptation_blocked_count"],
        "protocol_internal_bridge_ready": state["internal_bridge_ready"],
        "external_protocol_wire_compatible": bool(protocol_gates.get("external_protocol_wire_compatible")),
        "accepted_workflow_count": counts["accepted_workflow_count"],
        "blocked_workflow_count": counts["blocked_workflow_count"],
        "acceptance_queue_skipped": state["acceptance_skipped"],
    }


def mvp_plan_source_summaries(
    *,
    install_queue: dict[str, Any],
    adaptation_queue: dict[str, Any],
    protocol_readiness: dict[str, Any],
    acceptance_queue: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        nested_dict(install_queue, "summary"),
        nested_dict(adaptation_queue, "summary"),
        nested_dict(protocol_readiness, "readiness"),
        nested_dict(acceptance_queue, "summary"),
    )


def nested_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    return value if isinstance(value, dict) else {}


def mvp_plan_counts(
    *,
    install_summary: dict[str, Any],
    adaptation_summary: dict[str, Any],
    acceptance_summary: dict[str, Any],
) -> dict[str, int]:
    return {
        "queued_count": int(install_summary.get("queued_count", 0)),
        "blocked_install_count": int(install_summary.get("blocked_count", 0)),
        "native_ready_count": int(adaptation_summary.get("native_ready_count", 0)),
        "ready_for_repair_write_count": int(adaptation_summary.get("ready_for_repair_write_count", 0)),
        "smoke_ready_count": int(adaptation_summary.get("smoke_ready_count", 0)),
        "adaptation_blocked_count": int(adaptation_summary.get("blocked_count", 0)),
        "accepted_workflow_count": int(acceptance_summary.get("accepted_workflow_count", 0)),
        "blocked_workflow_count": int(acceptance_summary.get("blocked_workflow_count", 0)),
    }


def mvp_plan_readiness(
    *,
    counts: dict[str, int],
    plugin_install_ready: bool,
    internal_bridge_ready: bool,
    acceptance_skipped: bool,
) -> dict[str, bool]:
    return {
        "ready_for_next_market_download": bool(plugin_install_ready and counts["queued_count"] > 0),
        "ready_for_harness_adaptation": bool(
            counts["native_ready_count"] > 0
            or counts["ready_for_repair_write_count"] > 0
            or counts["smoke_ready_count"] > 0
        ),
        "ready_for_cli_to_cli_protocol_study": bool(
            internal_bridge_ready
            and not acceptance_skipped
            and counts["blocked_workflow_count"] == 0
        ),
    }


def mvp_plan_recommended_next_action(
    *,
    source_downloaded: bool,
    plugin_install_ready: bool,
    counts: dict[str, int],
    internal_bridge_ready: bool,
) -> str:
    return mvp_plan_next_action(MvpPlanNextActionInput(
        source_downloaded=source_downloaded,
        plugin_install_ready=plugin_install_ready,
        queued_count=counts["queued_count"],
        ready_for_repair_write_count=counts["ready_for_repair_write_count"],
        smoke_ready_count=counts["smoke_ready_count"],
        adaptation_blocked_count=counts["adaptation_blocked_count"],
        internal_bridge_ready=internal_bridge_ready,
        blocked_workflow_count=counts["blocked_workflow_count"],
    ))


def mvp_plan_next_action(state: MvpPlanNextActionInput) -> str:
    if not state.source_downloaded:
        return "install_cli_anything_external_plugin"
    if not state.plugin_install_ready:
        return "fix_cli_anything_install_gate"
    if state.queued_count > 0:
        return "install_next_market_harness"
    if state.smoke_ready_count > 0:
        return "run_adapter_smoke"
    if state.ready_for_repair_write_count > 0:
        return "repair_entrypoint_with_smoke_evidence"
    if state.adaptation_blocked_count > 0:
        return "inspect_adaptation_blockers"
    if not state.internal_bridge_ready or state.blocked_workflow_count > 0:
        return "fix_cli_to_cli_acceptance"
    return "start_external_protocol_conformance_research"


def environment_entrypoint_available(environment: dict[str, Any]) -> bool:
    return bool(
        any(item.get("available") for item in environment.get("entrypoints", []) if isinstance(item, dict))
    )


def mvp_plan_stages(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        mvp_download_stage(summary),
        mvp_install_market_stage(summary),
        mvp_adapt_harnesses_stage(summary),
        mvp_accept_routes_stage(summary),
        mvp_external_protocol_stage(summary),
    ]


def mvp_download_stage(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "download_cli_anything",
        "title": "Download CLI-Anything",
        "status": "ready" if summary["source_downloaded"] else "next",
        "ready": bool(summary["plugin_install_ready"]),
        "recommended_next_action": (
            "verify_or_update_cli_anything"
            if summary["source_downloaded"]
            else "install_cli_anything_external_plugin"
        ),
    }


def mvp_install_market_stage(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "install_market_harnesses",
        "title": "Install Market Harnesses",
        "status": mvp_install_market_stage_status(summary),
        "ready": bool(summary["ready_for_next_market_download"]),
        "queued_count": summary["queued_harness_count"],
        "blocked_count": summary["blocked_install_count"],
        "recommended_next_action": (
            "install_next_market_harness"
            if summary["ready_for_next_market_download"]
            else "inspect_market_install_queue"
        ),
    }


def mvp_install_market_stage_status(summary: dict[str, Any]) -> str:
    if summary["ready_for_next_market_download"]:
        return "next"
    if (
        summary["queued_harness_count"] == 0
        and summary["blocked_install_count"] == 0
        and summary["adaptation_harness_count"] > 0
    ):
        return "complete"
    return "blocked"


def mvp_adapt_harnesses_stage(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "adapt_harnesses",
        "title": "Adapt Harnesses",
        "status": "ready" if summary["ready_for_harness_adaptation"] else "blocked",
        "ready": bool(summary["ready_for_harness_adaptation"]),
        "native_ready_count": summary["native_ready_count"],
        "smoke_ready_count": summary["smoke_ready_count"],
        "ready_for_repair_write_count": summary["ready_for_repair_write_count"],
        "blocked_count": summary["adaptation_blocked_count"],
        "recommended_next_action": (
            "run_adapter_smoke_or_repair_entrypoint"
            if summary["ready_for_harness_adaptation"]
            else "inspect_adaptation_queue"
        ),
    }


def mvp_accept_routes_stage(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "accept_cli_to_cli_routes",
        "title": "Accept CLI-to-CLI Routes",
        "status": "ready" if summary["ready_for_cli_to_cli_protocol_study"] else "blocked",
        "ready": bool(summary["ready_for_cli_to_cli_protocol_study"]),
        "accepted_workflow_count": summary["accepted_workflow_count"],
        "blocked_workflow_count": summary["blocked_workflow_count"],
        "recommended_next_action": (
            "use_acceptance_rows_as_bridge_fixtures"
            if summary["ready_for_cli_to_cli_protocol_study"]
            else "fix_cli_to_cli_acceptance"
        ),
    }


def mvp_external_protocol_stage(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "external_protocol_facades",
        "title": "External Protocol Facades",
        "status": "partial",
        "ready": bool(summary["protocol_internal_bridge_ready"]),
        "wire_compatible": bool(summary["external_protocol_wire_compatible"]),
        "recommended_next_action": "run_protocol_smoke_then_add_conformance_coverage",
    }


def mvp_plan(
    hub: Any,
    *args: Any,
    **options: Any,
) -> dict[str, Any]:
    request = mvp_plan_request(args, options)
    reports = mvp_plan_reports(hub, request)
    summary = mvp_plan_summary(
        environment=reports["environment"],
        install_gate=reports["install_gate"],
        install_queue=reports["install_queue"],
        adaptation_queue=reports["adaptation_queue"],
        protocol_readiness=reports["protocol_readiness"],
        acceptance_queue=reports["acceptance_queue"],
    )
    return mvp_plan_report(MvpPlanReportInput(request=request, summary=summary, reports=reports))


def mvp_plan_request(args: tuple[Any, ...], options: dict[str, Any]) -> MvpPlanRequest:
    values = mvp_plan_options(args, options)
    bounded_limit, bounded_max_harnesses, bounded_max_workflows = mvp_plan_bounds(
        limit=values["limit"],
        max_harnesses=values["max_harnesses"],
        max_workflows=values["max_workflows"],
    )
    return MvpPlanRequest(
        query=values["query"],
        limit=bounded_limit,
        max_harnesses=bounded_max_harnesses,
        include_blocked=values["include_blocked"],
        workflow_paths=tuple(values["workflow_paths"]),
        max_workflows=bounded_max_workflows,
        registry=values["registry"],
        workflow_runner=values["workflow_runner"],
    )


def mvp_plan_options(args: tuple[Any, ...], options: dict[str, Any]) -> dict[str, Any]:
    if len(args) > len(_MVP_PLAN_OPTION_NAMES):
        raise TypeError(f"mvp_plan expected at most {len(_MVP_PLAN_OPTION_NAMES) + 1} arguments")
    values = {
        "query": "file",
        "limit": 20,
        "max_harnesses": 5,
        "include_blocked": True,
        "workflow_paths": (),
        "max_workflows": 10,
        "registry": None,
        "workflow_runner": None,
    }
    for name, value in zip(_MVP_PLAN_OPTION_NAMES, args):
        if name in options:
            raise TypeError(f"mvp_plan got multiple values for argument '{name}'")
        values[name] = value
    unknown = sorted(set(options) - set(_MVP_PLAN_OPTION_NAMES))
    if unknown:
        raise TypeError(f"unknown MVP plan option(s): {', '.join(unknown)}")
    values.update(options)
    return values


def mvp_plan_bounds(
    *,
    limit: int,
    max_harnesses: int,
    max_workflows: int,
) -> tuple[int, int, int]:
    return (
        max(0, min(limit, 500)),
        max(0, min(max_harnesses, 50)),
        max(1, min(max_workflows, 50)),
    )


def mvp_plan_reports(hub: Any, request: MvpPlanRequest) -> dict[str, Any]:
    environment = hub._environment_verification()
    install_gate = safe_plugin_report(lambda: PluginManager(root=hub.paths.root).operation_gate(PLUGIN_ID, "install"))
    install_queue = hub.market_install_queue(
        query=request.query,
        limit=request.limit,
        max_installs=request.max_harnesses,
        include_blocked=request.include_blocked,
    )
    adaptation_queue = hub.adaptation_queue(
        query=request.query,
        limit=request.limit,
        max_harnesses=request.max_harnesses,
        include_blocked=request.include_blocked,
        require_smoke=True,
        run_smoke=False,
        confirmed=False,
    )
    registry = request.registry or load_manifest_registry(hub.paths.manifests)
    protocol_readiness = protocol_readiness_report(registry, include_workflows=True)
    acceptance_queue = mvp_acceptance_queue(
        registry=registry,
        workflow_runner=request.workflow_runner,
        workflow_paths=request.workflow_paths,
        max_workflows=request.max_workflows,
    )
    return {
        "environment": environment,
        "install_gate": install_gate,
        "install_queue": install_queue,
        "adaptation_queue": adaptation_queue,
        "protocol_readiness": protocol_readiness,
        "acceptance_queue": acceptance_queue,
    }


def mvp_acceptance_queue(
    *,
    registry: Any,
    workflow_runner: Any | None,
    workflow_paths: tuple[str, ...],
    max_workflows: int,
) -> dict[str, Any]:
    if workflow_runner is None:
        return skipped_mvp_acceptance_queue()
    return cli_to_cli_acceptance_queue(
        registry,
        workflow_runner,
        workflow_paths=workflow_paths or None,
        max_workflows=max_workflows,
        run=False,
        dry_run=True,
        confirmed=False,
        include_payloads=False,
    )


def skipped_mvp_acceptance_queue() -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "CliToCliAcceptanceQueue",
        "skipped": True,
        "reason": "workflow_runner was not provided",
        "summary": {
            "workflow_count": 0,
            "accepted_workflow_count": 0,
            "blocked_workflow_count": 0,
            "route_count": 0,
            "route_ready_count": 0,
            "blocked_route_count": 0,
        },
        "rows": [],
        "failures": [],
        "next_steps": ["Call mvp-plan through the CLI or daemon runtime to include acceptance evidence."],
    }


def mvp_plan_report(report: MvpPlanReportInput) -> dict[str, Any]:
    request = report.request
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingMvpPlan",
        "query": request.query,
        "limit": request.limit,
        "max_harnesses": request.max_harnesses,
        "include_blocked": request.include_blocked,
        "workflow_paths": list(request.workflow_paths),
        "max_workflows": request.max_workflows,
        "summary": report.summary,
        "stages": mvp_plan_stages(report.summary),
        "reports": report.reports,
        "next_commands": mvp_plan_next_commands(request.query, request.limit, request.max_harnesses),
    }


def mvp_plan_next_commands(query: str | None, limit: int, max_harnesses: int) -> list[str]:
    query_arg = query or "<query>"
    return [
        "python -m cbn plugin preflight cli-anything",
        "python -m cbn plugin install cli-anything --yes",
        (
            f"python -m cbn plugin install-queue cli-anything --query {query_arg} "
            f"--limit {limit} --max-installs {max_harnesses}"
        ),
        (
            f"python -m cbn plugin adaptation-queue cli-anything --query {query_arg} "
            f"--limit {limit} --max-harnesses {max_harnesses}"
        ),
        "python -m cbn protocol acceptance-queue --run --dry-run",
        "python -m cbn protocol readiness --include-workflows",
        "python -m cbn protocol smoke-suite --workflow-dry-run",
    ]


def bootstrap_plan(
    hub: Any,
    harness_name: str = "mermaid",
    query: str | None = "file",
    include_workflows: bool = True,
    workflow_path: str = "workflows/cli-anything-macrocli-mermaid-routing.example.json",
) -> dict[str, Any]:
    context = bootstrap_plan_context(
        hub,
        harness_name=harness_name,
        query=query,
        include_workflows=include_workflows,
        workflow_path=workflow_path,
    )
    return bootstrap_plan_report(
        harness_name=harness_name,
        query=query,
        include_workflows=include_workflows,
        workflow_path=workflow_path,
        summary=context.summary,
        plans=bootstrap_plan_plans(context.reports),
        reports=bootstrap_plan_reports(context),
    )


def bootstrap_plan_context(
    hub: Any,
    *,
    harness_name: str,
    query: str | None,
    include_workflows: bool,
    workflow_path: str,
) -> BootstrapPlanContext:
    reports = bootstrap_plugin_reports(hub)
    environment = reports["environment"]
    entrypoint_available = environment_entrypoint_available(environment)
    market_scan = bootstrap_market_scan(hub, query, entrypoint_available)
    onboarding = bootstrap_onboarding(
        hub,
        harness_name=harness_name,
        include_workflows=include_workflows,
        entrypoint_available=entrypoint_available,
    )
    lifecycle_suite = protocol_lifecycle_suite(
        capability_id="git.version",
        workflow_path=workflow_path,
    )
    summary = bootstrap_summary(
        environment=environment,
        install_gate=reports["install_gate"],
        update_gate=reports["update_gate"],
        entrypoint_available=entrypoint_available,
        market_scan=market_scan,
        onboarding=onboarding,
        lifecycle_suite=lifecycle_suite,
    )
    return BootstrapPlanContext(
        reports=reports,
        environment=environment,
        market_scan=market_scan,
        onboarding=onboarding,
        lifecycle_suite=lifecycle_suite,
        summary=summary,
    )


def bootstrap_plan_plans(reports: dict[str, Any]) -> dict[str, Any]:
    return {
        "install": reports["install_plan"],
        "update": reports["update_plan"],
    }


def bootstrap_plan_reports(context: BootstrapPlanContext) -> dict[str, Any]:
    return {
        "environment": context.environment,
        "install_gate": context.reports["install_gate"],
        "update_gate": context.reports["update_gate"],
        "market_scan": context.market_scan,
        "onboarding": context.onboarding,
        "protocol_lifecycle_suite": context.lifecycle_suite,
    }


def bootstrap_plugin_reports(hub: Any) -> dict[str, Any]:
    manager = PluginManager(root=hub.paths.root)
    environment = hub._environment_verification()
    return {
        "environment": environment,
        "install_plan": safe_plugin_report(lambda: manager.plan(PLUGIN_ID, "install").as_dict()),
        "update_plan": safe_plugin_report(lambda: manager.plan(PLUGIN_ID, "update").as_dict()),
        "install_gate": safe_plugin_report(lambda: manager.operation_gate(PLUGIN_ID, "install")),
        "update_gate": safe_plugin_report(lambda: manager.operation_gate(PLUGIN_ID, "update")),
    }


def bootstrap_market_scan(
    hub: Any,
    query: str | None,
    entrypoint_available: bool,
) -> dict[str, Any]:
    if entrypoint_available:
        return hub.candidate_harnesses(query=query, limit=10, with_probes=True, compact=True)
    return {
        "ok": False,
        "skipped": True,
        "reason": "cli-hub entrypoint is not available yet",
        "query": query,
        "candidate_summary": [],
    }


def bootstrap_onboarding(
    hub: Any,
    *,
    harness_name: str,
    include_workflows: bool,
    entrypoint_available: bool,
) -> dict[str, Any]:
    return hub.onboard_harness(
        harness_name,
        from_market=entrypoint_available,
        write=False,
        confirmed=False,
        install=False,
        include_workflows=include_workflows,
        run_smoke_suite=False,
    )


def bootstrap_summary(
    *,
    environment: dict[str, Any],
    install_gate: dict[str, Any],
    update_gate: dict[str, Any],
    entrypoint_available: bool,
    market_scan: dict[str, Any],
    onboarding: dict[str, Any],
    lifecycle_suite: dict[str, Any],
) -> dict[str, Any]:
    source_downloaded = bool(environment.get("source_downloaded"))
    source_trusted = environment.get("source_trusted")
    return {
        "source_downloaded": source_downloaded,
        "source_trusted": source_trusted,
        "entrypoint_available": entrypoint_available,
        "install_gate_ok": bool(install_gate.get("ok")),
        "update_gate_ok": bool(update_gate.get("ok")),
        "market_scan_ok": bool(market_scan.get("ok")),
        "market_scan_skipped": bool(market_scan.get("skipped")),
        "onboarding_ok": bool(onboarding.get("ok")),
        "onboarding_stage_count": len(onboarding.get("stage_results", []))
        if isinstance(onboarding.get("stage_results"), list)
        else 0,
        "protocol_lifecycle_ok": bool(lifecycle_suite.get("ok")),
        "recommended_next_action": bootstrap_next_action(
            source_downloaded=source_downloaded,
            source_trusted=source_trusted,
            entrypoint_available=entrypoint_available,
            install_gate_ok=bool(install_gate.get("ok")),
            market_scan_ok=bool(market_scan.get("ok")),
            onboarding_ok=bool(onboarding.get("ok")),
            protocol_lifecycle_ok=bool(lifecycle_suite.get("ok")),
        ),
    }


def bootstrap_plan_report(
    *,
    harness_name: str,
    query: str | None,
    include_workflows: bool,
    workflow_path: str,
    summary: dict[str, Any],
    plans: dict[str, Any],
    reports: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingBootstrapPlan",
        "harness_name": harness_name,
        "query": query,
        "include_workflows": include_workflows,
        "workflow_path": workflow_path,
        "summary": summary,
        "stages": bootstrap_stages(summary, harness_name, query, workflow_path),
        "plans": plans,
        "reports": reports,
        "next_commands": bootstrap_next_commands(harness_name, query, workflow_path),
    }


def bootstrap_next_commands(
    harness_name: str,
    query: str | None,
    workflow_path: str,
) -> list[str]:
    query_arg = query or "<query>"
    return [
        "python -m cbn plugin bootstrap-plan cli-anything",
        "python -m cbn plugin preflight cli-anything",
        "python -m cbn plugin install cli-anything --yes",
        "python -m cbn plugin provenance cli-anything",
        "python -m cbn plugin check-update cli-anything --remote",
        (
            "python -m cbn plugin candidates cli-anything "
            f"--query {query_arg} --limit 10 --with-probes --compact"
        ),
        f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market",
        f"python -m cbn protocol lifecycle-suite --capability-id git.version --workflow-path {workflow_path}",
    ]


def bootstrap_next_action(
    source_downloaded: bool,
    source_trusted: Any,
    entrypoint_available: bool,
    install_gate_ok: bool,
    market_scan_ok: bool,
    onboarding_ok: bool,
    protocol_lifecycle_ok: bool,
) -> str:
    if not source_downloaded:
        return "install_cli_anything_external_plugin"
    if source_trusted is False:
        return "fix_cli_anything_source_provenance"
    if not entrypoint_available:
        return "repair_or_reinstall_cli_hub_entrypoint"
    if not install_gate_ok:
        return "fix_cli_anything_install_gate"
    if not market_scan_ok:
        return "inspect_cli_hub_market"
    if not onboarding_ok:
        return "inspect_harness_onboarding"
    if not protocol_lifecycle_ok:
        return "fix_protocol_lifecycle_suite"
    return "onboard_first_market_harness"


def bootstrap_stages(
    summary: dict[str, Any],
    harness_name: str,
    query: str | None,
    workflow_path: str,
) -> list[dict[str, Any]]:
    query_arg = query or "<query>"
    return [
        bootstrap_preflight_stage(summary),
        bootstrap_download_stage(summary),
        bootstrap_provenance_stage(summary),
        bootstrap_update_stage(summary),
        bootstrap_market_stage(summary, query_arg),
        bootstrap_onboard_stage(summary, harness_name),
        bootstrap_protocol_stage(summary, workflow_path),
    ]


def bootstrap_preflight_stage(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "preflight",
        "title": "Preflight CLI-Anything Plugin",
        "status": "complete" if summary["install_gate_ok"] else "blocked",
        "ready": bool(summary["install_gate_ok"]),
        "command": "python -m cbn plugin preflight cli-anything",
    }


def bootstrap_download_stage(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "download_plugin",
        "title": "Download External Plugin Source",
        "status": "complete" if summary["source_downloaded"] else "next",
        "ready": bool(summary["install_gate_ok"]),
        "command": "python -m cbn plugin install cli-anything --yes",
    }


def bootstrap_provenance_stage(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "verify_provenance",
        "title": "Verify Source And Entrypoint Provenance",
        "status": bootstrap_provenance_status(summary),
        "ready": bool(summary["source_downloaded"]),
        "command": "python -m cbn plugin provenance cli-anything",
    }


def bootstrap_provenance_status(summary: dict[str, Any]) -> str:
    if summary["source_trusted"] is not False and summary["entrypoint_available"]:
        return "complete"
    if summary["source_trusted"] is False:
        return "blocked"
    return "pending"


def bootstrap_update_stage(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "check_updates",
        "title": "Check External Plugin Updates",
        "status": "ready" if summary["source_downloaded"] else "pending",
        "ready": bool(summary["source_downloaded"]),
        "command": "python -m cbn plugin check-update cli-anything --remote",
    }


def bootstrap_market_stage(summary: dict[str, Any], query_arg: str) -> dict[str, Any]:
    return {
        "id": "sync_market",
        "title": "Inspect CLI-Anything Market",
        "status": bootstrap_market_status(summary),
        "ready": bool(summary["entrypoint_available"]),
        "command": (
            "python -m cbn plugin candidates cli-anything "
            f"--query {query_arg} --limit 10 --with-probes --compact"
        ),
    }


def bootstrap_market_status(summary: dict[str, Any]) -> str:
    if summary["market_scan_ok"]:
        return "complete"
    if summary["market_scan_skipped"]:
        return "pending"
    return "blocked"


def bootstrap_onboard_stage(summary: dict[str, Any], harness_name: str) -> dict[str, Any]:
    return {
        "id": "onboard_harness",
        "title": "Onboard First Market Harness",
        "status": "ready" if summary["onboarding_ok"] else "blocked",
        "ready": bool(summary["entrypoint_available"] and summary["market_scan_ok"]),
        "command": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market",
    }


def bootstrap_protocol_stage(summary: dict[str, Any], workflow_path: str) -> dict[str, Any]:
    return {
        "id": "protocol_lifecycle",
        "title": "Run Local Protocol Lifecycle Gate",
        "status": "complete" if summary["protocol_lifecycle_ok"] else "blocked",
        "ready": True,
        "command": (
            "python -m cbn protocol lifecycle-suite "
            f"--capability-id git.version --workflow-path {workflow_path}"
        ),
    }
