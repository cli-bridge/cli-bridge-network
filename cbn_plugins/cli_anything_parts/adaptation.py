"""Adaptation gate and queue helpers for CLI-Anything harnesses."""

from __future__ import annotations

from typing import Any

from cbn_plugins.cli_anything_parts.adapter_targets import repair_entrypoint_smoke_gate


PLUGIN_ID = "cli-anything"
REPAIRABLE_ENTRYPOINT_BLOCKER = "installed harness entrypoint is missing from PATH"


def adaptation_gate(
    hub: Any,
    harness_name: str,
    from_market: bool = True,
    module: str | None = None,
    require_smoke: bool = True,
    run_smoke: bool = False,
    confirmed: bool = False,
    smoke_args: tuple[str, ...] = ("--help",),
    smoke_timeout_seconds: int = 10,
) -> dict[str, Any]:
    evaluation = hub.evaluate_harness(harness_name, from_market=from_market)
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    native_launch_ready = bool(gates.get("launch_ready"))
    repair_plan = None
    adapter_targets = None
    selected_target = None
    selected_module = module
    smoke_report = None
    repair_scan = adaptation_gate_repair_scan_decision(evaluation, native_launch_ready, module)
    if repair_scan["scan"]:
        repair_plan = hub.entrypoint_repair_plan(harness_name, from_market=from_market)
        diagnosis = repair_plan.get("diagnosis") if isinstance(repair_plan.get("diagnosis"), dict) else {}
        if diagnosis.get("repair_required"):
            adapter_targets = hub.adapter_targets(harness_name, from_market=from_market, limit=20)
            targets = adapter_targets.get("targets", [])
            selected_target = next(
                (target for target in targets if target.get("module") == module),
                None,
            )
            if selected_target is None and module is None and targets:
                selected_target = targets[0]
                selected_module = str(selected_target.get("module"))
            if selected_module:
                smoke_report = hub.adapter_target_smoke(
                    harness_name,
                    module=selected_module,
                    from_market=from_market,
                    smoke_args=smoke_args,
                    timeout_seconds=smoke_timeout_seconds,
                    run=run_smoke,
                    confirmed=confirmed,
                )
    smoke_gate = repair_entrypoint_smoke_gate(require_smoke, smoke_report)
    summary = adaptation_gate_summary(
        evaluation=evaluation,
        native_launch_ready=native_launch_ready,
        repair_plan=repair_plan,
        selected_module=selected_module,
        smoke_gate=smoke_gate,
        smoke_report=smoke_report,
        require_smoke=require_smoke,
        repair_scan=repair_scan,
    )
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingHarnessAdaptationGate",
        "harness_name": harness_name,
        "from_market": from_market,
        "module": module,
        "selected_module": selected_module,
        "require_smoke": require_smoke,
        "run_smoke": run_smoke,
        "confirmed": confirmed,
        "smoke_args": list(smoke_args),
        "smoke_timeout_seconds": smoke_timeout_seconds,
        "summary": summary,
        "repair_scan": repair_scan,
        "stages": adaptation_gate_stages(
            evaluation=evaluation,
            repair_plan=repair_plan,
            adapter_targets=adapter_targets,
            selected_module=selected_module,
            smoke_gate=smoke_gate,
            smoke_report=smoke_report,
            summary=summary,
            repair_scan=repair_scan,
        ),
        "evaluation": evaluation,
        "repair_plan": repair_plan,
        "adapter_targets": adapter_targets,
        "selected_target": selected_target,
        "smoke_report": smoke_report,
        "next_commands": [
            f"python -m cbn plugin adaptation-gate cli-anything {harness_name} --from-market",
            f"python -m cbn plugin adapter-targets cli-anything {harness_name} --from-market --limit 10",
            (
                f"python -m cbn plugin adapter-smoke cli-anything {harness_name} "
                f"--from-market --module {selected_module} --run --yes"
                if selected_module
                else None
            ),
            (
                f"python -m cbn plugin repair-entrypoint cli-anything {harness_name} "
                f"--from-market --module {selected_module} --require-smoke --write --yes"
                if selected_module
                else None
            ),
        ],
    }


def adaptation_queue(
    hub: Any,
    harnesses: tuple[str, ...] = (),
    query: str | None = None,
    limit: int = 20,
    max_harnesses: int = 5,
    include_blocked: bool = True,
    require_smoke: bool = True,
    run_smoke: bool = False,
    confirmed: bool = False,
    smoke_args: tuple[str, ...] = ("--help",),
    smoke_timeout_seconds: int = 10,
) -> dict[str, Any]:
    bounded_limit = max(0, min(limit, 500))
    bounded_max = max(0, min(max_harnesses, 50))
    source_report = None
    source = "explicit_harnesses"
    selected_harnesses = unique_harnesses(harnesses)
    if not selected_harnesses:
        source = "market_install_queue"
        source_report = hub.market_install_queue(
            query=query,
            limit=bounded_limit,
            max_installs=bounded_max,
            include_blocked=include_blocked,
        )
        selected_harnesses = harnesses_from_install_queue(source_report, include_blocked=include_blocked)
    selected_harnesses = selected_harnesses[:bounded_max]
    gates = [
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
    summary = adaptation_queue_summary(gates)
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingHarnessAdaptationQueue",
        "source": source,
        "query": query,
        "limit": bounded_limit,
        "max_harnesses": bounded_max,
        "include_blocked": include_blocked,
        "harnesses": selected_harnesses,
        "require_smoke": require_smoke,
        "run_smoke": run_smoke,
        "confirmed": confirmed,
        "smoke_args": list(smoke_args),
        "smoke_timeout_seconds": smoke_timeout_seconds,
        "summary": summary,
        "gates": gates,
        "source_report": source_report,
        "next_commands": [
            "python -m cbn plugin adaptation-queue cli-anything --query file --limit 20 --max-harnesses 5",
            "python -m cbn plugin adaptation-queue cli-anything --harness py4csr --harness 3mf",
            "python -m cbn plugin adaptation-gate cli-anything <harness> --from-market",
            "python -m cbn plugin adaptation-gate cli-anything <harness> --from-market --run-smoke --yes",
        ],
    }


def adaptation_gate_repair_scan_decision(
    evaluation: dict[str, Any],
    native_launch_ready: bool,
    module: str | None,
) -> dict[str, Any]:
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    blockers = evaluation.get("blockers", []) if isinstance(evaluation.get("blockers"), list) else []
    blocker_texts = [str(item) for item in blockers if str(item)]
    if native_launch_ready:
        return {
            "scan": False,
            "status": "not_needed",
            "reason": "native launch is ready",
            "blockers": [],
        }
    if module:
        return {
            "scan": True,
            "status": "requested",
            "reason": "explicit adapter module requested",
            "blockers": [],
        }
    if not gates.get("installed"):
        return {
            "scan": False,
            "status": "skipped",
            "reason": "harness is not installed",
            "blockers": ["harness is not installed"],
        }
    non_repair_blockers = [
        blocker for blocker in blocker_texts if blocker != REPAIRABLE_ENTRYPOINT_BLOCKER
    ]
    if non_repair_blockers:
        return {
            "scan": False,
            "status": "skipped",
            "reason": "candidate has blockers that entrypoint repair cannot resolve",
            "blockers": non_repair_blockers,
        }
    if REPAIRABLE_ENTRYPOINT_BLOCKER in blocker_texts:
        return {
            "scan": True,
            "status": "allowed",
            "reason": "entrypoint repair may resolve the launch blocker",
            "blockers": [],
        }
    return {
        "scan": True,
        "status": "allowed",
        "reason": "no non-repair blockers were reported",
        "blockers": [],
    }


def adaptation_gate_summary(
    evaluation: dict[str, Any],
    native_launch_ready: bool,
    repair_plan: dict[str, Any] | None,
    selected_module: str | None,
    smoke_gate: dict[str, Any],
    smoke_report: dict[str, Any] | None,
    require_smoke: bool,
    repair_scan: dict[str, Any],
) -> dict[str, Any]:
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    diagnosis = repair_plan.get("diagnosis") if isinstance(repair_plan, dict) else {}
    repair_required = bool(diagnosis.get("repair_required")) if diagnosis else False
    smoke_passed = bool(smoke_report and smoke_report.get("summary", {}).get("smoke_ok"))
    ready_for_repair_write = bool(
        repair_required
        and selected_module
        and (not require_smoke or smoke_gate.get("ok"))
    )
    return {
        "manifest_valid": bool(gates.get("manifest_valid")),
        "installed": bool(gates.get("installed")),
        "native_launch_ready": native_launch_ready,
        "repair_required": repair_required,
        "repair_scan_status": repair_scan["status"],
        "repair_scan_skipped": not bool(repair_scan["scan"]),
        "repair_scan_reason": repair_scan["reason"],
        "repair_scan_blockers": repair_scan["blockers"],
        "selected_module": selected_module,
        "smoke_required": require_smoke,
        "smoke_passed": smoke_passed,
        "smoke_gate_status": smoke_gate["status"],
        "ready_for_call": native_launch_ready,
        "ready_for_repair_write": ready_for_repair_write,
        "recommended_next_action": adaptation_gate_next_action(
            native_launch_ready=native_launch_ready,
            repair_required=repair_required,
            selected_module=selected_module,
            smoke_gate=smoke_gate,
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


def adaptation_gate_stages(
    evaluation: dict[str, Any],
    repair_plan: dict[str, Any] | None,
    adapter_targets: dict[str, Any] | None,
    selected_module: str | None,
    smoke_gate: dict[str, Any],
    smoke_report: dict[str, Any] | None,
    summary: dict[str, Any],
    repair_scan: dict[str, Any],
) -> list[dict[str, Any]]:
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    blockers = evaluation.get("blockers", []) if isinstance(evaluation.get("blockers"), list) else []
    target_count = (
        int(adapter_targets.get("summary", {}).get("target_count", 0))
        if isinstance(adapter_targets, dict)
        else 0
    )
    return [
        {
            "id": "evaluate",
            "status": "completed" if evaluation.get("ok") else "blocked",
            "blockers": [] if evaluation.get("ok") else blockers,
        },
        {
            "id": "installed",
            "status": "completed" if gates.get("installed") else "blocked",
            "blockers": [] if gates.get("installed") else ["harness is not installed"],
        },
        {
            "id": "native_launch",
            "status": "completed" if summary["native_launch_ready"] else "blocked",
            "blockers": [] if summary["native_launch_ready"] else blockers,
        },
        {
            "id": "repair_plan",
            "status": (
                "completed"
                if repair_plan and summary["repair_required"]
                else "skipped"
                if summary["native_launch_ready"] or not repair_scan["scan"]
                else "blocked"
            ),
            "repair_scan_status": repair_scan["status"],
            "blockers": (
                []
                if repair_plan or summary["native_launch_ready"]
                else repair_scan["blockers"]
                if not repair_scan["scan"]
                else ["repair plan is unavailable"]
            ),
        },
        {
            "id": "adapter_target",
            "status": (
                "completed"
                if selected_module
                else "skipped"
                if summary["native_launch_ready"] or not summary["repair_required"]
                else "blocked"
            ),
            "target_count": target_count,
            "selected_module": selected_module,
            "blockers": (
                []
                if selected_module or summary["native_launch_ready"] or not summary["repair_required"]
                else ["no adapter target selected"]
            ),
        },
        {
            "id": "adapter_smoke",
            "status": (
                "completed"
                if smoke_gate["status"] == "passed"
                else "skipped"
                if not smoke_gate["required"] or not summary["repair_required"]
                else "ready"
                if smoke_gate["status"] == "not_run"
                else "blocked"
            ),
            "smoke_status": smoke_gate["status"],
            "exit_code": (
                smoke_report.get("execution", {}).get("exit_code")
                if isinstance(smoke_report, dict)
                else None
            ),
            "blockers": smoke_gate["blockers"],
        },
        {
            "id": "repair_write",
            "status": (
                "ready"
                if summary["ready_for_repair_write"]
                else "skipped"
                if summary["native_launch_ready"] or not summary["repair_required"]
                else "blocked"
            ),
            "blockers": (
                []
                if summary["ready_for_repair_write"]
                or summary["native_launch_ready"]
                or not summary["repair_required"]
                else smoke_gate["blockers"]
            ),
        },
    ]


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
        entries = report.get(section, [])
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            harness = item.get("harness_name")
            if not isinstance(harness, str) or not harness:
                candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
                harness = candidate.get("harness_name")
            if isinstance(harness, str) and harness and harness not in selected:
                selected.append(harness)
    return selected


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
