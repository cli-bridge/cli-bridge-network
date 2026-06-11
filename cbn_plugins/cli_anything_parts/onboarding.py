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
    write_requested_without_confirmation = bool(write and not confirmed)
    write_blocked_by_gate = bool(
        write
        and confirmed
        and not allow_blocked
        and not (
            evaluation["gates"]["manifest_valid"]
            and not evaluation["blockers"]
        )
    )
    install_requested_without_confirmation = bool(install and not confirmed)
    if write and confirmed and not write_blocked_by_gate:
        adaptation = hub.adapt_harness(
            harness_name,
            title=title,
            from_market=from_market,
            write=True,
        )
    install_plan_obj = hub.harness_plan("install", harness_name)
    install_plan = install_plan_obj.as_dict()
    install_gate = hub.harness_operation_gate(
        "install",
        harness_name,
        from_market=from_market,
    )
    install_result = None
    install_execution_status = "not_requested"
    install_execution_blockers: list[str] = []
    if install and not confirmed:
        install_execution_status = "requires_confirmation"
    elif install and confirmed and not allow_blocked and not install_gate.get("ok"):
        install_execution_status = "blocked"
        install_execution_blockers = list(install_gate.get("blockers", []))
    elif install and confirmed and operation_runner is None:
        install_execution_status = "blocked"
        install_execution_blockers = ["operation runner is required for confirmed install"]
    elif install and confirmed:
        install_result = operation_runner.execute(install_plan_obj)
        install_execution_status = str(install_result.get("status", "unknown"))
        if install_execution_status != "completed":
            install_execution_blockers = list(install_result.get("blockers", [])) or [
                f"harness install operation {install_execution_status}"
            ]
    verification = hub.verify_harness(
        harness_name,
        title=title,
        from_market=from_market,
        include_workflows=include_workflows,
        run_smoke_suite=run_smoke_suite,
        smoke_extra_args=smoke_extra_args,
    )
    verification_blockers = (
        verification.get("verification_blockers", [])
        if verification.get("ok")
        else [verification.get("error", "verification failed")]
    )
    manifest_written = bool(adaptation.get("written"))
    ready_for_manifest_write = bool(
        verification.get("ready_for_manifest_write")
        if verification.get("ok")
        else evaluation["gates"]["manifest_valid"] and not evaluation["blockers"]
    )
    ready_for_install = bool(install_gate.get("ok"))
    ready_for_runtime_verification = bool(
        verification.get("ready_for_runtime_verification")
        if verification.get("ok")
        else False
    )
    effective_evaluation = verification.get("evaluation", evaluation) if verification.get("ok") else evaluation
    manifest_already_imported = bool(effective_evaluation["gates"].get("manifest_imported"))
    harness_already_installed = bool(effective_evaluation["gates"].get("installed"))
    smoke_suite = verification.get("protocol_smoke_suite", {}) if verification.get("ok") else {}
    stage_results = onboarding_stage_results(
        evaluation=evaluation,
        probe=probe,
        adaptation=adaptation,
        install_gate=install_gate,
        verification_blockers=verification_blockers,
        ready_for_manifest_write=ready_for_manifest_write,
        ready_for_install=ready_for_install,
        ready_for_runtime_verification=ready_for_runtime_verification,
        manifest_written=manifest_written,
        manifest_already_imported=manifest_already_imported,
        harness_already_installed=harness_already_installed,
        write=write,
        confirmed=confirmed,
        install=install,
        allow_blocked=allow_blocked,
        write_blocked_by_gate=write_blocked_by_gate,
        install_execution_status=install_execution_status,
        install_execution_blockers=install_execution_blockers,
        smoke_suite=smoke_suite,
    )
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
            ready_for_manifest_write=ready_for_manifest_write,
            manifest_written=manifest_written,
            write_blocked_by_gate=write_blocked_by_gate,
            write_requested_without_confirmation=write_requested_without_confirmation,
            ready_for_install=ready_for_install,
            install_requested_without_confirmation=install_requested_without_confirmation,
            install_execution_status=install_execution_status,
            ready_for_runtime_verification=ready_for_runtime_verification,
            smoke_suite=smoke_suite,
            recommended_next_action=evaluation["recommended_next_action"],
        ),
        "stage_results": stage_results,
        "reports": {
            "evaluation": evaluation,
            "probe": probe,
            "adaptation": adaptation,
            "install_plan": install_plan,
            "install_gate": install_gate,
            "install_result": install_result,
            "verification": verification,
        },
        "next_commands": onboarding_next_commands(harness_name, capability_id),
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
        {
            "id": "evaluate",
            "status": "completed",
            "blockers": evaluation["blockers"],
            "recommended_next_action": evaluation["recommended_next_action"],
        },
        {
            "id": "probe_dependencies",
            "status": "completed" if probe["ready"] else "blocked",
            "blockers": [
                item["id"]
                for item in probe["probes"]
                if item.get("severity") == "blocker" and item.get("status") != "available"
            ],
        },
        {
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
        },
        {
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
        },
        {
            "id": "verify_runtime",
            "status": "completed" if ready_for_runtime_verification else "blocked",
            "blockers": verification_blockers,
        },
        {
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
        },
    ]


def onboarding_next_commands(harness_name: str, capability_id: str) -> list[str]:
    return [
        f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market",
        f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market --write --yes",
        f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
        "python -m cbn registry validate manifests",
        f"python -m cbn plugin verify-harness cli-anything {harness_name} --smoke-suite --smoke-extra-arg=--help --no-workflows",
        f"python -m cbn call {capability_id} --dry-run",
    ]
