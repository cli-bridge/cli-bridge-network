"""Onboarding report assembly for CLI-Anything harnesses."""

from __future__ import annotations

from typing import Any


PLUGIN_ID = "cli-anything"


def onboard_harness(
    hub: Any,
    harness_name: str,
    title: str | None = None,
    from_market: bool = True,
    write: bool = False,
    confirmed: bool = False,
    install: bool = False,
    allow_blocked: bool = False,
    include_workflows: bool = True,
    run_smoke_suite: bool = False,
    smoke_extra_args: tuple[str, ...] = (),
    operation_runner: Any | None = None,
) -> dict[str, Any]:
    probe = hub.probe_harness(
        harness_name,
        title=title,
        from_market=from_market,
    )
    if not probe["ok"]:
        return probe_blocked_onboarding_report(
            plugin_id=PLUGIN_ID,
            harness_name=harness_name,
            from_market=from_market,
            write=write,
            confirmed=confirmed,
            install=install,
            allow_blocked=allow_blocked,
            include_workflows=include_workflows,
            run_smoke_suite=run_smoke_suite,
            probe=probe,
        )

    evaluation = probe["evaluation"]
    capability_id = evaluation["capability_id"]
    adaptation = evaluation["adaptation"]
    write_gate = onboarding_write_gate(
        write=write,
        confirmed=confirmed,
        allow_blocked=allow_blocked,
        evaluation=evaluation,
    )
    if write and confirmed and not write_gate["blocked_by_gate"]:
        adaptation = hub.adapt_harness(
            harness_name,
            title=title,
            from_market=from_market,
            write=True,
        )
    install_plan_obj = hub.harness_plan("install", harness_name)
    install_plan = install_plan_obj.as_dict()
    install_gate = hub.harness_operation_gate("install", harness_name, from_market=from_market)
    install_execution = onboarding_install_execution(
        install=install,
        confirmed=confirmed,
        allow_blocked=allow_blocked,
        install_gate=install_gate,
        install_plan_obj=install_plan_obj,
        operation_runner=operation_runner,
    )
    verification = hub.verify_harness(
        harness_name,
        title=title,
        from_market=from_market,
        include_workflows=include_workflows,
        run_smoke_suite=run_smoke_suite,
        smoke_extra_args=smoke_extra_args,
    )
    readiness = onboarding_readiness_state(
        verification=verification,
        evaluation=evaluation,
        adaptation=adaptation,
        install_gate=install_gate,
    )
    stage_results = onboarding_stage_results(
        evaluation=evaluation,
        probe=probe,
        adaptation=adaptation,
        install_gate=install_gate,
        verification_blockers=readiness["verification_blockers"],
        ready_for_manifest_write=readiness["ready_for_manifest_write"],
        ready_for_install=readiness["ready_for_install"],
        ready_for_runtime_verification=readiness["ready_for_runtime_verification"],
        manifest_written=readiness["manifest_written"],
        manifest_already_imported=readiness["manifest_already_imported"],
        harness_already_installed=readiness["harness_already_installed"],
        write=write,
        confirmed=confirmed,
        install=install,
        allow_blocked=allow_blocked,
        write_blocked_by_gate=write_gate["blocked_by_gate"],
        install_execution_status=install_execution["status"],
        install_execution_blockers=install_execution["blockers"],
        smoke_suite=readiness["smoke_suite"],
    )
    return successful_onboarding_report(
        harness_name=harness_name,
        from_market=from_market,
        write=write,
        confirmed=confirmed,
        install=install,
        allow_blocked=allow_blocked,
        include_workflows=include_workflows,
        run_smoke_suite=run_smoke_suite,
        capability_id=capability_id,
        evaluation=evaluation,
        probe=probe,
        adaptation=adaptation,
        install_plan=install_plan,
        install_gate=install_gate,
        install_execution=install_execution,
        verification=verification,
        readiness=readiness,
        write_gate=write_gate,
        stage_results=stage_results,
    )


def onboarding_write_gate(
    *,
    write: bool,
    confirmed: bool,
    allow_blocked: bool,
    evaluation: dict[str, Any],
) -> dict[str, bool]:
    return {
        "requires_confirmation": bool(write and not confirmed),
        "blocked_by_gate": bool(
            write
            and confirmed
            and not allow_blocked
            and not (evaluation["gates"]["manifest_valid"] and not evaluation["blockers"])
        ),
    }


def successful_onboarding_report(
    *,
    harness_name: str,
    from_market: bool,
    write: bool,
    confirmed: bool,
    install: bool,
    allow_blocked: bool,
    include_workflows: bool,
    run_smoke_suite: bool,
    capability_id: str,
    evaluation: dict[str, Any],
    probe: dict[str, Any],
    adaptation: dict[str, Any],
    install_plan: dict[str, Any],
    install_gate: dict[str, Any],
    install_execution: dict[str, Any],
    verification: dict[str, Any],
    readiness: dict[str, Any],
    write_gate: dict[str, Any],
    stage_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingHarnessOnboarding",
        "harness_name": harness_name,
        "from_market": from_market,
        "write": write,
        "confirmed": confirmed,
        "install": install,
        "allow_blocked": allow_blocked,
        "include_workflows": include_workflows,
        "run_smoke_suite": run_smoke_suite,
        "capability_id": capability_id,
        "summary": onboarding_summary(
            ready_for_manifest_write=readiness["ready_for_manifest_write"],
            manifest_written=readiness["manifest_written"],
            write_blocked_by_gate=write_gate["blocked_by_gate"],
            write_requested_without_confirmation=write_gate["requires_confirmation"],
            ready_for_install=readiness["ready_for_install"],
            install_requested_without_confirmation=install_execution["requires_confirmation"],
            install_execution_status=install_execution["status"],
            ready_for_runtime_verification=readiness["ready_for_runtime_verification"],
            smoke_suite=readiness["smoke_suite"],
            recommended_next_action=evaluation["recommended_next_action"],
        ),
        "stage_results": stage_results,
        "reports": {
            "evaluation": evaluation,
            "probe": probe,
            "adaptation": adaptation,
            "install_plan": install_plan,
            "install_gate": install_gate,
            "install_result": install_execution["result"],
            "verification": verification,
        },
        "next_commands": onboarding_next_commands(harness_name, capability_id),
    }


def onboarding_install_execution(
    *,
    install: bool,
    confirmed: bool,
    allow_blocked: bool,
    install_gate: dict[str, Any],
    install_plan_obj: Any,
    operation_runner: Any | None,
) -> dict[str, Any]:
    result = None
    status = "not_requested"
    blockers: list[str] = []
    if install and not confirmed:
        status = "requires_confirmation"
    elif install and confirmed and not allow_blocked and not install_gate.get("ok"):
        status = "blocked"
        blockers = list(install_gate.get("blockers", []))
    elif install and confirmed and operation_runner is None:
        status = "blocked"
        blockers = ["operation runner is required for confirmed install"]
    elif install and confirmed:
        result = operation_runner.execute(install_plan_obj)
        status = str(result.get("status", "unknown"))
        if status != "completed":
            blockers = list(result.get("blockers", [])) or [f"harness install operation {status}"]
    return {
        "result": result,
        "status": status,
        "blockers": blockers,
        "requires_confirmation": bool(install and not confirmed),
    }


def onboarding_readiness_state(
    *,
    verification: dict[str, Any],
    evaluation: dict[str, Any],
    adaptation: dict[str, Any],
    install_gate: dict[str, Any],
) -> dict[str, Any]:
    verification_ok = bool(verification.get("ok"))
    effective_evaluation = verification.get("evaluation", evaluation) if verification_ok else evaluation
    return {
        "verification_blockers": (
            verification.get("verification_blockers", [])
            if verification_ok
            else [verification.get("error", "verification failed")]
        ),
        "manifest_written": bool(adaptation.get("written")),
        "ready_for_manifest_write": bool(
            verification.get("ready_for_manifest_write")
            if verification_ok
            else evaluation["gates"]["manifest_valid"] and not evaluation["blockers"]
        ),
        "ready_for_install": bool(install_gate.get("ok")),
        "ready_for_runtime_verification": bool(
            verification.get("ready_for_runtime_verification") if verification_ok else False
        ),
        "manifest_already_imported": bool(effective_evaluation["gates"].get("manifest_imported")),
        "harness_already_installed": bool(effective_evaluation["gates"].get("installed")),
        "smoke_suite": verification.get("protocol_smoke_suite", {}) if verification_ok else {},
    }


def probe_blocked_onboarding_report(
    *,
    plugin_id: str,
    harness_name: str,
    from_market: bool,
    write: bool,
    confirmed: bool,
    install: bool,
    allow_blocked: bool,
    include_workflows: bool,
    run_smoke_suite: bool,
    probe: dict[str, Any],
) -> dict[str, Any]:
    error = probe["error"]
    return {
        "ok": False,
        "plugin_id": plugin_id,
        "kind": "CliAnythingHarnessOnboarding",
        "harness_name": harness_name,
        "from_market": from_market,
        "write": write,
        "confirmed": confirmed,
        "install": install,
        "allow_blocked": allow_blocked,
        "include_workflows": include_workflows,
        "run_smoke_suite": run_smoke_suite,
        "error": error,
        "stage_results": [
            {
                "id": "probe",
                "status": "blocked",
                "blockers": [error],
            }
        ],
        "reports": {"probe": probe},
        "next_commands": [
            f"python -m cbn plugin market cli-anything info {harness_name}",
            f"python -m cbn plugin onboard-harness cli-anything {harness_name} --offline",
        ],
    }


def onboarding_summary(
    *,
    ready_for_manifest_write: bool,
    manifest_written: bool,
    write_blocked_by_gate: bool,
    write_requested_without_confirmation: bool,
    ready_for_install: bool,
    install_requested_without_confirmation: bool,
    install_execution_status: str,
    ready_for_runtime_verification: bool,
    smoke_suite: dict[str, Any],
    recommended_next_action: str,
) -> dict[str, Any]:
    return {
        "ready_for_manifest_write": ready_for_manifest_write,
        "manifest_written": manifest_written,
        "manifest_write_status": (
            "blocked"
            if write_blocked_by_gate
            else "completed"
            if manifest_written
            else "requires_confirmation"
            if write_requested_without_confirmation
            else "ready"
            if ready_for_manifest_write
            else "blocked"
        ),
        "write_requires_confirmation": write_requested_without_confirmation,
        "ready_for_install": ready_for_install,
        "install_requires_confirmation": install_requested_without_confirmation,
        "install_executed": install_execution_status == "completed",
        "install_execution_status": install_execution_status,
        "ready_for_runtime_verification": ready_for_runtime_verification,
        "smoke_suite_ready": bool(smoke_suite.get("ok")) if smoke_suite.get("run") else None,
        "recommended_next_action": recommended_next_action,
    }


def onboarding_stage_results(
    *,
    evaluation: dict[str, Any],
    probe: dict[str, Any],
    adaptation: dict[str, Any],
    install_gate: dict[str, Any],
    verification_blockers: list[str],
    ready_for_manifest_write: bool,
    ready_for_install: bool,
    ready_for_runtime_verification: bool,
    manifest_written: bool,
    manifest_already_imported: bool,
    harness_already_installed: bool,
    write: bool,
    confirmed: bool,
    install: bool,
    allow_blocked: bool,
    write_blocked_by_gate: bool,
    install_execution_status: str,
    install_execution_blockers: list[str],
    smoke_suite: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        onboarding_evaluate_stage(evaluation),
        onboarding_probe_stage(probe),
        onboarding_adapt_manifest_stage(
            evaluation=evaluation,
            adaptation=adaptation,
            ready_for_manifest_write=ready_for_manifest_write,
            manifest_written=manifest_written,
            manifest_already_imported=manifest_already_imported,
            write=write,
            confirmed=confirmed,
            write_blocked_by_gate=write_blocked_by_gate,
        ),
        onboarding_install_stage(
            install_gate=install_gate,
            ready_for_install=ready_for_install,
            harness_already_installed=harness_already_installed,
            install=install,
            allow_blocked=allow_blocked,
            install_execution_status=install_execution_status,
            install_execution_blockers=install_execution_blockers,
        ),
        onboarding_verify_runtime_stage(
            ready_for_runtime_verification=ready_for_runtime_verification,
            verification_blockers=verification_blockers,
        ),
        onboarding_smoke_protocol_stage(smoke_suite),
    ]


def onboarding_evaluate_stage(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "evaluate",
        "status": "completed",
        "blockers": evaluation["blockers"],
        "recommended_next_action": evaluation["recommended_next_action"],
    }


def onboarding_probe_stage(probe: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "probe_dependencies",
        "status": "completed" if probe["ready"] else "blocked",
        "blockers": [
            item["id"]
            for item in probe["probes"]
            if item.get("severity") == "blocker" and item.get("status") != "available"
        ],
    }


def onboarding_adapt_manifest_stage(
    *,
    evaluation: dict[str, Any],
    adaptation: dict[str, Any],
    ready_for_manifest_write: bool,
    manifest_written: bool,
    manifest_already_imported: bool,
    write: bool,
    confirmed: bool,
    write_blocked_by_gate: bool,
) -> dict[str, Any]:
    return {
        "id": "adapt_manifest",
        "status": (
            "completed"
            if manifest_written or manifest_already_imported
            else "ready"
            if ready_for_manifest_write
            else "blocked"
        ),
        "write_requested": write,
        "write_confirmed": confirmed,
        "written": adaptation.get("written"),
        "blockers": (
            ["manifest write blocked by harness evaluation"]
            if write_blocked_by_gate
            else [] if ready_for_manifest_write else evaluation["blockers"]
        ),
    }


def onboarding_install_stage(
    *,
    install_gate: dict[str, Any],
    ready_for_install: bool,
    harness_already_installed: bool,
    install: bool,
    allow_blocked: bool,
    install_execution_status: str,
    install_execution_blockers: list[str],
) -> dict[str, Any]:
    return {
        "id": "install_harness",
        "status": (
            "completed"
            if harness_already_installed or install_execution_status == "completed"
            else "blocked"
            if install_execution_status == "blocked"
            else "ready"
            if ready_for_install
            else "blocked"
        ),
        "execution": install_execution_status,
        "install_requested": install,
        "allow_blocked": allow_blocked,
        "blockers": install_execution_blockers or install_gate.get("blockers", []),
    }


def onboarding_verify_runtime_stage(
    *,
    ready_for_runtime_verification: bool,
    verification_blockers: list[str],
) -> dict[str, Any]:
    return {
        "id": "verify_runtime",
        "status": "completed" if ready_for_runtime_verification else "blocked",
        "blockers": verification_blockers,
    }


def onboarding_smoke_protocol_stage(smoke_suite: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "smoke_protocol_facades",
        "status": (
            "completed"
            if smoke_suite.get("run") and smoke_suite.get("ok")
            else "blocked"
            if smoke_suite.get("run")
            else "pending"
        ),
        "run": bool(smoke_suite.get("run")),
        "blockers": [] if smoke_suite.get("ok") or not smoke_suite.get("run") else ["protocol smoke suite failed"],
    }


def onboarding_next_commands(harness_name: str, capability_id: str) -> list[str]:
    return [
        f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market",
        f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --write --yes",
        f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
        "python -m cbn registry validate manifests",
        f"python -m cbn plugin verify-harness cli-anything {harness_name} --smoke-suite --smoke-extra-arg=--help --no-workflows",
        f"python -m cbn call {capability_id} --dry-run",
    ]
