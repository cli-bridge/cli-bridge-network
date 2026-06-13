"""Adaptation gate and queue helpers for CLI-Anything harnesses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cbn_plugins.cli_anything_parts.adapter_targets import repair_entrypoint_smoke_gate


PLUGIN_ID = "cli-anything"
REPAIRABLE_ENTRYPOINT_BLOCKER = "installed harness entrypoint is missing from PATH"


@dataclass(frozen=True)
class AdaptationGateRequest:
    harness_name: str
    from_market: bool
    module: str | None
    require_smoke: bool
    run_smoke: bool
    confirmed: bool
    smoke_args: tuple[str, ...]
    smoke_timeout_seconds: int


@dataclass(frozen=True)
class AdaptationRepairContext:
    repair_scan: dict[str, Any]
    repair_plan: dict[str, Any] | None
    adapter_targets: dict[str, Any] | None
    selected_target: dict[str, Any] | None
    selected_module: str | None
    smoke_report: dict[str, Any] | None


@dataclass(frozen=True)
class AdaptationGateSummaryInput:
    evaluation: dict[str, Any]
    native_launch_ready: bool
    repair_plan: dict[str, Any] | None
    selected_module: str | None
    smoke_gate: dict[str, Any]
    smoke_report: dict[str, Any] | None
    require_smoke: bool
    repair_scan: dict[str, Any]


@dataclass(frozen=True)
class AdaptationGateStagesInput:
    evaluation: dict[str, Any]
    repair_context: AdaptationRepairContext
    smoke_gate: dict[str, Any]
    summary: dict[str, Any]


@dataclass(frozen=True)
class AdaptationQueueReportInput:
    source: str
    query: str | None
    bounded_limit: int
    bounded_max: int
    include_blocked: bool
    selected_harnesses: list[str]
    require_smoke: bool
    run_smoke: bool
    confirmed: bool
    smoke_args: tuple[str, ...]
    smoke_timeout_seconds: int
    gates: list[dict[str, Any]]
    source_report: dict[str, Any] | None


@dataclass(frozen=True)
class AdaptationQueueRequest:
    harnesses: tuple[str, ...]
    query: str | None
    limit: int
    max_harnesses: int
    include_blocked: bool
    require_smoke: bool
    run_smoke: bool
    confirmed: bool
    smoke_args: tuple[str, ...]
    smoke_timeout_seconds: int


_ADAPTATION_GATE_OPTION_NAMES = (
    "from_market",
    "module",
    "require_smoke",
    "run_smoke",
    "confirmed",
    "smoke_args",
    "smoke_timeout_seconds",
)


def adaptation_gate(
    hub: Any,
    harness_name: str,
    *args: Any,
    **options: Any,
) -> dict[str, Any]:
    request = adaptation_gate_request(harness_name, args, options)
    evaluation = hub.evaluate_harness(request.harness_name, from_market=request.from_market)
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    native_launch_ready = bool(gates.get("launch_ready"))
    repair_context = adaptation_repair_context(
        hub,
        request=request,
        evaluation=evaluation,
        native_launch_ready=native_launch_ready,
    )
    smoke_gate = repair_entrypoint_smoke_gate(request.require_smoke, repair_context.smoke_report)
    summary = adaptation_gate_summary(AdaptationGateSummaryInput(
        evaluation=evaluation,
        native_launch_ready=native_launch_ready,
        repair_plan=repair_context.repair_plan,
        selected_module=repair_context.selected_module,
        smoke_gate=smoke_gate,
        smoke_report=repair_context.smoke_report,
        require_smoke=request.require_smoke,
        repair_scan=repair_context.repair_scan,
    ))
    return adaptation_gate_report(
        request=request,
        evaluation=evaluation,
        repair_context=repair_context,
        smoke_gate=smoke_gate,
        summary=summary,
    )


def adaptation_gate_request(
    harness_name: str,
    args: tuple[Any, ...],
    options: dict[str, Any],
) -> AdaptationGateRequest:
    values = adaptation_gate_options(args, options)
    return AdaptationGateRequest(harness_name=harness_name, **values)


def adaptation_gate_options(args: tuple[Any, ...], options: dict[str, Any]) -> dict[str, Any]:
    if len(args) > len(_ADAPTATION_GATE_OPTION_NAMES):
        raise TypeError(f"adaptation_gate expected at most {len(_ADAPTATION_GATE_OPTION_NAMES) + 2} arguments")
    values = {
        "from_market": True,
        "module": None,
        "require_smoke": True,
        "run_smoke": False,
        "confirmed": False,
        "smoke_args": ("--help",),
        "smoke_timeout_seconds": 10,
    }
    for name, value in zip(_ADAPTATION_GATE_OPTION_NAMES, args):
        if name in options:
            raise TypeError(f"adaptation_gate got multiple values for argument '{name}'")
        values[name] = value
    unknown = sorted(set(options) - set(_ADAPTATION_GATE_OPTION_NAMES))
    if unknown:
        raise TypeError(f"unknown adaptation gate option(s): {', '.join(unknown)}")
    values.update(options)
    return values


def adaptation_repair_context(
    hub: Any,
    *,
    request: AdaptationGateRequest,
    evaluation: dict[str, Any],
    native_launch_ready: bool,
) -> AdaptationRepairContext:
    repair_scan = adaptation_gate_repair_scan_decision(
        evaluation,
        native_launch_ready,
        request.module,
    )
    if not repair_scan["scan"]:
        return AdaptationRepairContext(repair_scan, None, None, None, request.module, None)

    repair_plan = hub.entrypoint_repair_plan(
        request.harness_name,
        from_market=request.from_market,
    )
    if not repair_plan_requires_adapter(repair_plan):
        return AdaptationRepairContext(repair_scan, repair_plan, None, None, request.module, None)

    adapter_targets = hub.adapter_targets(
        request.harness_name,
        from_market=request.from_market,
        limit=20,
    )
    selected_target, selected_module = select_adapter_target(adapter_targets, request.module)
    smoke_report = adapter_smoke_for_selected_target(hub, request, selected_module)
    return AdaptationRepairContext(
        repair_scan,
        repair_plan,
        adapter_targets,
        selected_target,
        selected_module,
        smoke_report,
    )


def repair_plan_requires_adapter(repair_plan: dict[str, Any]) -> bool:
    diagnosis = repair_plan.get("diagnosis") if isinstance(repair_plan.get("diagnosis"), dict) else {}
    return bool(diagnosis.get("repair_required"))


def select_adapter_target(
    adapter_targets: dict[str, Any],
    requested_module: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    targets = adapter_targets.get("targets", [])
    selected = next(
        (target for target in targets if target.get("module") == requested_module),
        None,
    )
    if selected is None and requested_module is None and targets:
        selected = targets[0]
    selected_module = requested_module or (str(selected.get("module")) if selected else None)
    return selected, selected_module


def adapter_smoke_for_selected_target(
    hub: Any,
    request: AdaptationGateRequest,
    selected_module: str | None,
) -> dict[str, Any] | None:
    if not selected_module:
        return None
    return hub.adapter_target_smoke(
        request.harness_name,
        module=selected_module,
        from_market=request.from_market,
        smoke_args=request.smoke_args,
        timeout_seconds=request.smoke_timeout_seconds,
        run=request.run_smoke,
        confirmed=request.confirmed,
    )


def adaptation_gate_report(
    *,
    request: AdaptationGateRequest,
    evaluation: dict[str, Any],
    repair_context: AdaptationRepairContext,
    smoke_gate: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingHarnessAdaptationGate",
        "harness_name": request.harness_name,
        "from_market": request.from_market,
        "module": request.module,
        "selected_module": repair_context.selected_module,
        "require_smoke": request.require_smoke,
        "run_smoke": request.run_smoke,
        "confirmed": request.confirmed,
        "smoke_args": list(request.smoke_args),
        "smoke_timeout_seconds": request.smoke_timeout_seconds,
        "summary": summary,
        "repair_scan": repair_context.repair_scan,
        "stages": adaptation_gate_stages(AdaptationGateStagesInput(
            evaluation=evaluation,
            repair_context=repair_context,
            smoke_gate=smoke_gate,
            summary=summary,
        )),
        "evaluation": evaluation,
        "repair_plan": repair_context.repair_plan,
        "adapter_targets": repair_context.adapter_targets,
        "selected_target": repair_context.selected_target,
        "smoke_report": repair_context.smoke_report,
        "next_commands": adaptation_gate_next_commands(request, repair_context.selected_module),
    }


def adaptation_gate_next_commands(
    request: AdaptationGateRequest,
    selected_module: str | None,
) -> list[str | None]:
    return [
        f"python -m cbn plugin adaptation-gate cli-anything {request.harness_name} --from-market",
        (
            "python -m cbn plugin adapter-targets cli-anything "
            f"{request.harness_name} --from-market --limit 10"
        ),
        (
            f"python -m cbn plugin adapter-smoke cli-anything {request.harness_name} "
            f"--from-market --module {selected_module} --run --yes"
            if selected_module
            else None
        ),
        (
            f"python -m cbn plugin repair-entrypoint cli-anything {request.harness_name} "
            f"--from-market --module {selected_module} --require-smoke --write --yes"
            if selected_module
            else None
        ),
    ]


def adaptation_queue(
    hub: Any,
    harnesses: tuple[str, ...] = (),
    **options: Any,
) -> dict[str, Any]:
    request = adaptation_queue_request(harnesses, options)
    bounded_limit, bounded_max = adaptation_queue_bounds(request.limit, request.max_harnesses)
    source, source_report, selected_harnesses = adaptation_queue_source(
        hub=hub,
        harnesses=request.harnesses,
        query=request.query,
        bounded_limit=bounded_limit,
        bounded_max=bounded_max,
        include_blocked=request.include_blocked,
    )
    gates = adaptation_queue_gates(
        hub=hub,
        selected_harnesses=selected_harnesses,
        require_smoke=request.require_smoke,
        run_smoke=request.run_smoke,
        confirmed=request.confirmed,
        smoke_args=request.smoke_args,
        smoke_timeout_seconds=request.smoke_timeout_seconds,
    )
    return adaptation_queue_report(AdaptationQueueReportInput(
        source=source,
        query=request.query,
        bounded_limit=bounded_limit,
        bounded_max=bounded_max,
        include_blocked=request.include_blocked,
        selected_harnesses=selected_harnesses,
        require_smoke=request.require_smoke,
        run_smoke=request.run_smoke,
        confirmed=request.confirmed,
        smoke_args=request.smoke_args,
        smoke_timeout_seconds=request.smoke_timeout_seconds,
        gates=gates,
        source_report=source_report,
    ))


def adaptation_queue_request(harnesses: tuple[str, ...], options: dict[str, Any]) -> AdaptationQueueRequest:
    values = {
        "query": None,
        "limit": 20,
        "max_harnesses": 5,
        "include_blocked": True,
        "require_smoke": True,
        "run_smoke": False,
        "confirmed": False,
        "smoke_args": ("--help",),
        "smoke_timeout_seconds": 10,
    }
    unknown = sorted(set(options) - set(values))
    if unknown:
        raise TypeError(f"unknown adaptation queue option(s): {', '.join(unknown)}")
    values.update(options)
    return AdaptationQueueRequest(harnesses=harnesses, **values)


def adaptation_queue_report(report: AdaptationQueueReportInput) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingHarnessAdaptationQueue",
        "source": report.source,
        "query": report.query,
        "limit": report.bounded_limit,
        "max_harnesses": report.bounded_max,
        "include_blocked": report.include_blocked,
        "harnesses": report.selected_harnesses,
        "require_smoke": report.require_smoke,
        "run_smoke": report.run_smoke,
        "confirmed": report.confirmed,
        "smoke_args": list(report.smoke_args),
        "smoke_timeout_seconds": report.smoke_timeout_seconds,
        "summary": adaptation_queue_summary(report.gates),
        "gates": report.gates,
        "source_report": report.source_report,
        "next_commands": adaptation_queue_next_commands(),
    }


def adaptation_queue_bounds(limit: int, max_harnesses: int) -> tuple[int, int]:
    return max(0, min(limit, 500)), max(0, min(max_harnesses, 50))


def adaptation_queue_source(
    *,
    hub: Any,
    harnesses: tuple[str, ...],
    query: str | None,
    bounded_limit: int,
    bounded_max: int,
    include_blocked: bool,
) -> tuple[str, dict[str, Any] | None, list[str]]:
    selected_harnesses = unique_harnesses(harnesses)
    if selected_harnesses:
        return "explicit_harnesses", None, selected_harnesses[:bounded_max]
    source_report = hub.market_install_queue(
        query=query,
        limit=bounded_limit,
        max_installs=bounded_max,
        include_blocked=include_blocked,
    )
    return (
        "market_install_queue",
        source_report,
        harnesses_from_install_queue(source_report, include_blocked=include_blocked)[:bounded_max],
    )


def adaptation_queue_gates(
    *,
    hub: Any,
    selected_harnesses: list[str],
    require_smoke: bool,
    run_smoke: bool,
    confirmed: bool,
    smoke_args: tuple[str, ...],
    smoke_timeout_seconds: int,
) -> list[dict[str, Any]]:
    return [
        hub.adaptation_gate(
            harness,
            from_market=True,
            require_smoke=require_smoke,
            run_smoke=run_smoke,
            confirmed=confirmed,
            smoke_args=smoke_args,
            smoke_timeout_seconds=smoke_timeout_seconds,
        )
        for harness in selected_harnesses
    ]


def adaptation_queue_next_commands() -> list[str]:
    return [
        "python -m cbn plugin adaptation-queue cli-anything --query file --limit 20 --max-harnesses 5",
        "python -m cbn plugin adaptation-queue cli-anything --harness py4csr --harness 3mf",
        "python -m cbn plugin adaptation-gate cli-anything <harness> --from-market",
        "python -m cbn plugin adaptation-gate cli-anything <harness> --from-market --run-smoke --yes",
    ]


def adaptation_gate_repair_scan_decision(
    evaluation: dict[str, Any],
    native_launch_ready: bool,
    module: str | None,
) -> dict[str, Any]:
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    blockers = evaluation.get("blockers", []) if isinstance(evaluation.get("blockers"), list) else []
    blocker_texts = [str(item) for item in blockers if str(item)]
    if native_launch_ready:
        return repair_scan_decision(False, "not_needed", "native launch is ready")
    if module:
        return repair_scan_decision(True, "requested", "explicit adapter module requested")
    if not gates.get("installed"):
        return repair_scan_decision(False, "skipped", "harness is not installed", ["harness is not installed"])
    non_repair_blockers = [
        blocker for blocker in blocker_texts if blocker != REPAIRABLE_ENTRYPOINT_BLOCKER
    ]
    if non_repair_blockers:
        return repair_scan_decision(
            False,
            "skipped",
            "candidate has blockers that entrypoint repair cannot resolve",
            non_repair_blockers,
        )
    if REPAIRABLE_ENTRYPOINT_BLOCKER in blocker_texts:
        return repair_scan_decision(True, "allowed", "entrypoint repair may resolve the launch blocker")
    return repair_scan_decision(True, "allowed", "no non-repair blockers were reported")


def repair_scan_decision(
    scan: bool,
    status: str,
    reason: str,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "scan": scan,
        "status": status,
        "reason": reason,
        "blockers": blockers or [],
    }


def adaptation_gate_summary(params: AdaptationGateSummaryInput) -> dict[str, Any]:
    gates = params.evaluation.get("gates") if isinstance(params.evaluation.get("gates"), dict) else {}
    diagnosis = params.repair_plan.get("diagnosis") if isinstance(params.repair_plan, dict) else {}
    repair_required = bool(diagnosis.get("repair_required")) if diagnosis else False
    smoke_passed = bool(params.smoke_report and params.smoke_report.get("summary", {}).get("smoke_ok"))
    ready_for_repair_write = bool(
        repair_required
        and params.selected_module
        and (not params.require_smoke or params.smoke_gate.get("ok"))
    )
    return {
        "manifest_valid": bool(gates.get("manifest_valid")),
        "installed": bool(gates.get("installed")),
        "native_launch_ready": params.native_launch_ready,
        "repair_required": repair_required,
        "repair_scan_status": params.repair_scan["status"],
        "repair_scan_skipped": not bool(params.repair_scan["scan"]),
        "repair_scan_reason": params.repair_scan["reason"],
        "repair_scan_blockers": params.repair_scan["blockers"],
        "selected_module": params.selected_module,
        "smoke_required": params.require_smoke,
        "smoke_passed": smoke_passed,
        "smoke_gate_status": params.smoke_gate["status"],
        "ready_for_call": params.native_launch_ready,
        "ready_for_repair_write": ready_for_repair_write,
        "recommended_next_action": adaptation_gate_next_action(
            native_launch_ready=params.native_launch_ready,
            repair_required=repair_required,
            selected_module=params.selected_module,
            smoke_gate=params.smoke_gate,
            ready_for_repair_write=ready_for_repair_write,
        ),
    }


def adaptation_gate_next_action(
    native_launch_ready: bool,
    repair_required: bool,
    selected_module: str | None,
    smoke_gate: dict[str, Any],
    ready_for_repair_write: bool,
) -> str:
    if native_launch_ready:
        return "verify_harness_and_protocol_facades"
    if not repair_required:
        return "inspect_harness_blockers"
    if not selected_module:
        return "inspect_adapter_targets"
    if ready_for_repair_write:
        return "write_smoke_gated_repaired_manifest"
    if smoke_gate["status"] == "not_run":
        return "run_adapter_smoke"
    if smoke_gate["status"] == "requires_confirmation":
        return "confirm_adapter_smoke"
    return "choose_another_adapter_target_or_fix_dependencies"


def adaptation_gate_stages(params: AdaptationGateStagesInput) -> list[dict[str, Any]]:
    gates = params.evaluation.get("gates") if isinstance(params.evaluation.get("gates"), dict) else {}
    blockers = params.evaluation.get("blockers", []) if isinstance(params.evaluation.get("blockers"), list) else []
    return [
        adaptation_evaluate_stage(params.evaluation, blockers),
        adaptation_installed_stage(gates),
        adaptation_native_launch_stage(params.summary, blockers),
        adaptation_repair_plan_stage(
            params.repair_context.repair_plan,
            params.summary,
            params.repair_context.repair_scan,
        ),
        adaptation_adapter_target_stage(
            params.repair_context.adapter_targets,
            params.repair_context.selected_module,
            params.summary,
        ),
        adaptation_adapter_smoke_stage(
            params.smoke_gate,
            params.repair_context.smoke_report,
            params.summary,
        ),
        adaptation_repair_write_stage(params.smoke_gate, params.summary),
    ]


def adaptation_evaluate_stage(
    evaluation: dict[str, Any],
    blockers: list[Any],
) -> dict[str, Any]:
    return {
        "id": "evaluate",
        "status": "completed" if evaluation.get("ok") else "blocked",
        "blockers": [] if evaluation.get("ok") else blockers,
    }


def adaptation_installed_stage(gates: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "installed",
        "status": "completed" if gates.get("installed") else "blocked",
        "blockers": [] if gates.get("installed") else ["harness is not installed"],
    }


def adaptation_native_launch_stage(
    summary: dict[str, Any],
    blockers: list[Any],
) -> dict[str, Any]:
    return {
        "id": "native_launch",
        "status": "completed" if summary["native_launch_ready"] else "blocked",
        "blockers": [] if summary["native_launch_ready"] else blockers,
    }


def adaptation_repair_plan_stage(
    repair_plan: dict[str, Any] | None,
    summary: dict[str, Any],
    repair_scan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": "repair_plan",
        "status": adaptation_repair_plan_status(repair_plan, summary, repair_scan),
        "repair_scan_status": repair_scan["status"],
        "blockers": adaptation_repair_plan_blockers(repair_plan, summary, repair_scan),
    }


def adaptation_repair_plan_status(
    repair_plan: dict[str, Any] | None,
    summary: dict[str, Any],
    repair_scan: dict[str, Any],
) -> str:
    if repair_plan and summary["repair_required"]:
        return "completed"
    if summary["native_launch_ready"] or not repair_scan["scan"]:
        return "skipped"
    return "blocked"


def adaptation_repair_plan_blockers(
    repair_plan: dict[str, Any] | None,
    summary: dict[str, Any],
    repair_scan: dict[str, Any],
) -> list[Any]:
    if repair_plan or summary["native_launch_ready"]:
        return []
    if not repair_scan["scan"]:
        return repair_scan["blockers"]
    return ["repair plan is unavailable"]


def adaptation_adapter_target_stage(
    adapter_targets: dict[str, Any] | None,
    selected_module: str | None,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": "adapter_target",
        "status": adaptation_adapter_target_status(selected_module, summary),
        "target_count": adaptation_target_count(adapter_targets),
        "selected_module": selected_module,
        "blockers": adaptation_adapter_target_blockers(selected_module, summary),
    }


def adaptation_target_count(adapter_targets: dict[str, Any] | None) -> int:
    if not isinstance(adapter_targets, dict):
        return 0
    return int(adapter_targets.get("summary", {}).get("target_count", 0))


def adaptation_adapter_target_status(
    selected_module: str | None,
    summary: dict[str, Any],
) -> str:
    if selected_module:
        return "completed"
    if summary["native_launch_ready"] or not summary["repair_required"]:
        return "skipped"
    return "blocked"


def adaptation_adapter_target_blockers(
    selected_module: str | None,
    summary: dict[str, Any],
) -> list[str]:
    if selected_module or summary["native_launch_ready"] or not summary["repair_required"]:
        return []
    return ["no adapter target selected"]


def adaptation_adapter_smoke_stage(
    smoke_gate: dict[str, Any],
    smoke_report: dict[str, Any] | None,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": "adapter_smoke",
        "status": adaptation_adapter_smoke_status(smoke_gate, summary),
        "smoke_status": smoke_gate["status"],
        "exit_code": smoke_exit_code(smoke_report),
        "blockers": smoke_gate["blockers"],
    }


def adaptation_adapter_smoke_status(
    smoke_gate: dict[str, Any],
    summary: dict[str, Any],
) -> str:
    if smoke_gate["status"] == "passed":
        return "completed"
    if not smoke_gate["required"] or not summary["repair_required"]:
        return "skipped"
    if smoke_gate["status"] == "not_run":
        return "ready"
    return "blocked"


def smoke_exit_code(smoke_report: dict[str, Any] | None) -> Any:
    if not isinstance(smoke_report, dict):
        return None
    return smoke_report.get("execution", {}).get("exit_code")


def adaptation_repair_write_stage(
    smoke_gate: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": "repair_write",
        "status": adaptation_repair_write_status(summary),
        "blockers": adaptation_repair_write_blockers(smoke_gate, summary),
    }


def adaptation_repair_write_status(summary: dict[str, Any]) -> str:
    if summary["ready_for_repair_write"]:
        return "ready"
    if summary["native_launch_ready"] or not summary["repair_required"]:
        return "skipped"
    return "blocked"


def adaptation_repair_write_blockers(
    smoke_gate: dict[str, Any],
    summary: dict[str, Any],
) -> list[Any]:
    if (
        summary["ready_for_repair_write"]
        or summary["native_launch_ready"]
        or not summary["repair_required"]
    ):
        return []
    return smoke_gate["blockers"]


def unique_harnesses(harnesses: tuple[str, ...]) -> list[str]:
    selected: list[str] = []
    for harness in harnesses:
        value = str(harness).strip()
        if value and value not in selected:
            selected.append(value)
    return selected


def harnesses_from_install_queue(report: dict[str, Any], include_blocked: bool = True) -> list[str]:
    selected: list[str] = []
    for section in ("queue", "blocked" if include_blocked else "", "skipped"):
        if not section:
            continue
        for item in _install_queue_section_entries(report, section):
            harness = _install_queue_harness_name(item)
            if harness and harness not in selected:
                selected.append(harness)
    return selected


def _install_queue_section_entries(report: dict[str, Any], section: str) -> list[dict[str, Any]]:
    entries = report.get(section, [])
    if not isinstance(entries, list):
        return []
    return [item for item in entries if isinstance(item, dict)]


def _install_queue_harness_name(item: dict[str, Any]) -> str | None:
    harness = item.get("harness_name")
    if isinstance(harness, str) and harness:
        return harness
    candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
    fallback = candidate.get("harness_name")
    return fallback if isinstance(fallback, str) and fallback else None


def adaptation_queue_summary(gates: list[dict[str, Any]]) -> dict[str, Any]:
    action_counts: dict[str, int] = {}
    for gate in gates:
        action = str(gate.get("summary", {}).get("recommended_next_action", "unknown"))
        action_counts[action] = action_counts.get(action, 0) + 1
    return {
        "harness_count": len(gates),
        "native_ready_count": sum(1 for item in gates if item.get("summary", {}).get("native_launch_ready")),
        "ready_for_repair_write_count": sum(
            1 for item in gates if item.get("summary", {}).get("ready_for_repair_write")
        ),
        "smoke_ready_count": sum(
            1 for item in gates if item.get("summary", {}).get("recommended_next_action") == "run_adapter_smoke"
        ),
        "blocked_count": sum(
            1
            for item in gates
            if item.get("summary", {}).get("recommended_next_action")
            in {
                "inspect_harness_blockers",
                "inspect_adapter_targets",
                "choose_another_adapter_target_or_fix_dependencies",
            }
        ),
        "action_counts": action_counts,
    }
