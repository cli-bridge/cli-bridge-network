"""Onboarding report assembly for CLI-Anything harnesses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PLUGIN_ID = "cli-anything"


@dataclass(frozen=True)
class OnboardingRequest:
    harness_name: str
    title: str | None
    from_market: bool
    write: bool
    confirmed: bool
    install: bool
    allow_blocked: bool
    include_workflows: bool
    run_smoke_suite: bool
    smoke_extra_args: tuple[str, ...]


@dataclass(frozen=True)
class OnboardingContext:
    capability_id: str
    evaluation: dict[str, Any]
    adaptation: dict[str, Any]
    install_plan: dict[str, Any]
    install_gate: dict[str, Any]
    install_execution: dict[str, Any]
    verification: dict[str, Any]
    readiness: dict[str, Any]
    write_gate: dict[str, Any]
    stage_results: list[dict[str, Any]]


@dataclass(frozen=True)
class OnboardingStageResultContext:
    evaluation: dict[str, Any]
    probe: dict[str, Any]
    adaptation: dict[str, Any]
    install_gate: dict[str, Any]
    verification_blockers: list[str]
    ready_for_manifest_write: bool
    ready_for_install: bool
    ready_for_runtime_verification: bool
    manifest_written: bool
    manifest_already_imported: bool
    harness_already_installed: bool
    write: bool
    confirmed: bool
    install: bool
    allow_blocked: bool
    write_blocked_by_gate: bool
    install_execution_status: str
    install_execution_blockers: list[str]
    smoke_suite: dict[str, Any]


@dataclass(frozen=True)
class OnboardingStageResultsInput:
    request: OnboardingRequest
    probe: dict[str, Any]
    evaluation: dict[str, Any]
    adaptation: dict[str, Any]
    install_gate: dict[str, Any]
    install_execution: dict[str, Any]
    readiness: dict[str, Any]
    write_gate: dict[str, Any]


@dataclass(frozen=True)
class OnboardingBuildArtifacts:
    evaluation: dict[str, Any]
    adaptation: dict[str, Any]
    install_plan: dict[str, Any]
    install_gate: dict[str, Any]
    install_execution: dict[str, Any]
    verification: dict[str, Any]
    readiness: dict[str, Any]
    write_gate: dict[str, Any]


@dataclass(frozen=True)
class OnboardingInstallExecutionRequest:
    install: bool
    confirmed: bool
    allow_blocked: bool
    install_gate: dict[str, Any]
    install_plan_obj: Any
    operation_runner: Any | None


@dataclass(frozen=True)
class OnboardingSummaryInput:
    ready_for_manifest_write: bool
    manifest_written: bool
    write_blocked_by_gate: bool
    write_requested_without_confirmation: bool
    ready_for_install: bool
    install_requested_without_confirmation: bool
    install_execution_status: str
    ready_for_runtime_verification: bool
    smoke_suite: dict[str, Any]
    recommended_next_action: str


_ONBOARD_OPTION_NAMES = (
    "title",
    "from_market",
    "write",
    "confirmed",
    "install",
    "allow_blocked",
    "include_workflows",
    "run_smoke_suite",
    "smoke_extra_args",
    "operation_runner",
)


def onboard_harness(
    hub: Any,
    harness_name: str,
    *args: Any,
    **options: Any,
) -> dict[str, Any]:
    request, operation_runner = onboard_harness_request(harness_name, args, options)
    probe = onboarding_probe(hub, request)
    if not probe["ok"]:
        return probe_blocked_onboarding_report_for_request(request, probe)
    context = build_onboarding_context(
        hub,
        request=request,
        probe=probe,
        operation_runner=operation_runner,
    )
    return successful_onboarding_report_for_request(request, probe, context)


def onboard_harness_request(
    harness_name: str,
    args: tuple[Any, ...],
    options: dict[str, Any],
) -> tuple[OnboardingRequest, Any | None]:
    values = _onboard_options(args, options)
    operation_runner = values.pop("operation_runner")
    return OnboardingRequest(harness_name=harness_name, **values), operation_runner


def _onboard_options(args: tuple[Any, ...], options: dict[str, Any]) -> dict[str, Any]:
    if len(args) > len(_ONBOARD_OPTION_NAMES):
        raise TypeError(f"onboard_harness expected at most {len(_ONBOARD_OPTION_NAMES) + 2} arguments")
    values = _default_onboard_options()
    for name, value in zip(_ONBOARD_OPTION_NAMES, args):
        if name in options:
            raise TypeError(f"onboard_harness got multiple values for argument '{name}'")
        values[name] = value
    unknown = sorted(set(options) - set(_ONBOARD_OPTION_NAMES))
    if unknown:
        raise TypeError(f"unknown onboarding option(s): {', '.join(unknown)}")
    values.update(options)
    return values


def _default_onboard_options() -> dict[str, Any]:
    return {
        "title": None,
        "from_market": True,
        "write": False,
        "confirmed": False,
        "install": False,
        "allow_blocked": False,
        "include_workflows": True,
        "run_smoke_suite": False,
        "smoke_extra_args": (),
        "operation_runner": None,
    }


def onboarding_probe(hub: Any, request: OnboardingRequest) -> dict[str, Any]:
    return hub.probe_harness(
        request.harness_name,
        title=request.title,
        from_market=request.from_market,
    )


def probe_blocked_onboarding_report_for_request(
    request: OnboardingRequest,
    probe: dict[str, Any],
) -> dict[str, Any]:
    return probe_blocked_onboarding_report(request=request, probe=probe)


def build_onboarding_context(
    hub: Any,
    *,
    request: OnboardingRequest,
    probe: dict[str, Any],
    operation_runner: Any | None,
) -> OnboardingContext:
    artifacts = onboarding_build_artifacts(
        hub,
        request=request,
        probe=probe,
        operation_runner=operation_runner,
    )
    return onboarding_context_from_artifacts(request, probe, artifacts)


def onboarding_build_artifacts(
    hub: Any,
    *,
    request: OnboardingRequest,
    probe: dict[str, Any],
    operation_runner: Any | None,
) -> OnboardingBuildArtifacts:
    evaluation = probe["evaluation"]
    adaptation, write_gate = onboarding_adaptation(
        hub,
        request=request,
        evaluation=evaluation,
    )
    install_plan, install_gate, install_execution = onboarding_install_state(
        hub,
        request=request,
        operation_runner=operation_runner,
    )
    verification = onboarding_verification(hub, request)
    readiness = onboarding_readiness_state(
        verification=verification,
        evaluation=evaluation,
        adaptation=adaptation,
        install_gate=install_gate,
    )
    artifacts = OnboardingBuildArtifacts(
        evaluation=evaluation,
        adaptation=adaptation,
        install_plan=install_plan,
        install_gate=install_gate,
        install_execution=install_execution,
        verification=verification,
        readiness=readiness,
        write_gate=write_gate,
    )
    return artifacts


def onboarding_context_from_artifacts(
    request: OnboardingRequest,
    probe: dict[str, Any],
    artifacts: OnboardingBuildArtifacts,
) -> OnboardingContext:
    stage_results = onboarding_stage_results_for_context(onboarding_stage_input(request, probe, artifacts))
    return OnboardingContext(
        capability_id=artifacts.evaluation["capability_id"],
        evaluation=artifacts.evaluation,
        adaptation=artifacts.adaptation,
        install_plan=artifacts.install_plan,
        install_gate=artifacts.install_gate,
        install_execution=artifacts.install_execution,
        verification=artifacts.verification,
        readiness=artifacts.readiness,
        write_gate=artifacts.write_gate,
        stage_results=stage_results,
    )


def onboarding_stage_input(
    request: OnboardingRequest,
    probe: dict[str, Any],
    artifacts: OnboardingBuildArtifacts,
) -> OnboardingStageResultsInput:
    return OnboardingStageResultsInput(
        request=request,
        probe=probe,
        evaluation=artifacts.evaluation,
        adaptation=artifacts.adaptation,
        install_gate=artifacts.install_gate,
        install_execution=artifacts.install_execution,
        readiness=artifacts.readiness,
        write_gate=artifacts.write_gate,
    )


def onboarding_install_state(
    hub: Any,
    *,
    request: OnboardingRequest,
    operation_runner: Any | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    install_plan_obj = hub.harness_plan("install", request.harness_name)
    install_gate = hub.harness_operation_gate(
        "install",
        request.harness_name,
        from_market=request.from_market,
    )
    install_execution = onboarding_install_execution(
        OnboardingInstallExecutionRequest(
            install=request.install,
            confirmed=request.confirmed,
            allow_blocked=request.allow_blocked,
            install_gate=install_gate,
            install_plan_obj=install_plan_obj,
            operation_runner=operation_runner,
        )
    )
    return install_plan_obj.as_dict(), install_gate, install_execution


def onboarding_adaptation(
    hub: Any,
    *,
    request: OnboardingRequest,
    evaluation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    adaptation = evaluation["adaptation"]
    write_gate = onboarding_write_gate(
        write=request.write,
        confirmed=request.confirmed,
        allow_blocked=request.allow_blocked,
        evaluation=evaluation,
    )
    if request.write and request.confirmed and not write_gate["blocked_by_gate"]:
        adaptation = hub.adapt_harness(
            request.harness_name,
            title=request.title,
            from_market=request.from_market,
            write=True,
        )
    return adaptation, write_gate


def onboarding_verification(hub: Any, request: OnboardingRequest) -> dict[str, Any]:
    return hub.verify_harness(
        request.harness_name,
        title=request.title,
        from_market=request.from_market,
        include_workflows=request.include_workflows,
        run_smoke_suite=request.run_smoke_suite,
        smoke_extra_args=request.smoke_extra_args,
    )


def onboarding_stage_results_for_context(params: OnboardingStageResultsInput) -> list[dict[str, Any]]:
    return onboarding_stage_results(OnboardingStageResultContext(
        evaluation=params.evaluation,
        probe=params.probe,
        adaptation=params.adaptation,
        install_gate=params.install_gate,
        verification_blockers=params.readiness["verification_blockers"],
        ready_for_manifest_write=params.readiness["ready_for_manifest_write"],
        ready_for_install=params.readiness["ready_for_install"],
        ready_for_runtime_verification=params.readiness["ready_for_runtime_verification"],
        manifest_written=params.readiness["manifest_written"],
        manifest_already_imported=params.readiness["manifest_already_imported"],
        harness_already_installed=params.readiness["harness_already_installed"],
        write=params.request.write,
        confirmed=params.request.confirmed,
        install=params.request.install,
        allow_blocked=params.request.allow_blocked,
        write_blocked_by_gate=params.write_gate["blocked_by_gate"],
        install_execution_status=params.install_execution["status"],
        install_execution_blockers=params.install_execution["blockers"],
        smoke_suite=params.readiness["smoke_suite"],
    ))


def successful_onboarding_report_for_request(
    request: OnboardingRequest,
    probe: dict[str, Any],
    context: OnboardingContext,
) -> dict[str, Any]:
    return successful_onboarding_report(
        request=request,
        probe=probe,
        context=context,
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
    request: OnboardingRequest,
    probe: dict[str, Any],
    context: OnboardingContext,
) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingHarnessOnboarding",
        "harness_name": request.harness_name,
        "from_market": request.from_market,
        "write": request.write,
        "confirmed": request.confirmed,
        "install": request.install,
        "allow_blocked": request.allow_blocked,
        "include_workflows": request.include_workflows,
        "run_smoke_suite": request.run_smoke_suite,
        "capability_id": context.capability_id,
        "summary": successful_onboarding_summary(context),
        "stage_results": context.stage_results,
        "reports": onboarding_reports(probe, context),
        "next_commands": onboarding_next_commands(request.harness_name, context.capability_id),
    }


def successful_onboarding_summary(context: OnboardingContext) -> dict[str, Any]:
    return onboarding_summary(OnboardingSummaryInput(
        ready_for_manifest_write=context.readiness["ready_for_manifest_write"],
        manifest_written=context.readiness["manifest_written"],
        write_blocked_by_gate=context.write_gate["blocked_by_gate"],
        write_requested_without_confirmation=context.write_gate["requires_confirmation"],
        ready_for_install=context.readiness["ready_for_install"],
        install_requested_without_confirmation=context.install_execution["requires_confirmation"],
        install_execution_status=context.install_execution["status"],
        ready_for_runtime_verification=context.readiness["ready_for_runtime_verification"],
        smoke_suite=context.readiness["smoke_suite"],
        recommended_next_action=context.evaluation["recommended_next_action"],
    ))


def onboarding_reports(probe: dict[str, Any], context: OnboardingContext) -> dict[str, Any]:
    return {
        "evaluation": context.evaluation,
        "probe": probe,
        "adaptation": context.adaptation,
        "install_plan": context.install_plan,
        "install_gate": context.install_gate,
        "install_result": context.install_execution["result"],
        "verification": context.verification,
    }


def onboarding_install_execution(request: OnboardingInstallExecutionRequest) -> dict[str, Any]:
    result = None
    status = "not_requested"
    blockers: list[str] = []
    blocked = onboarding_install_blocker(request)
    if blocked:
        status = blocked["status"]
        blockers = blocked["blockers"]
    elif request.install and request.confirmed:
        result = request.operation_runner.execute(request.install_plan_obj)
        status = str(result.get("status", "unknown"))
        if status != "completed":
            blockers = list(result.get("blockers", [])) or [f"harness install operation {status}"]
    return {
        "result": result,
        "status": status,
        "blockers": blockers,
        "requires_confirmation": bool(request.install and not request.confirmed),
    }


def onboarding_install_blocker(request: OnboardingInstallExecutionRequest) -> dict[str, Any] | None:
    if not request.install:
        return None
    if not request.confirmed:
        return {"status": "requires_confirmation", "blockers": []}
    if not request.allow_blocked and not request.install_gate.get("ok"):
        return {"status": "blocked", "blockers": list(request.install_gate.get("blockers", []))}
    if request.operation_runner is None:
        return {"status": "blocked", "blockers": ["operation runner is required for confirmed install"]}
    return None


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
    request: OnboardingRequest | None = None,
    probe: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    request = request or _onboarding_request_from_report_kwargs(kwargs)
    probe = probe or kwargs["probe"]
    error = probe["error"]
    return {
        "ok": False,
        "plugin_id": kwargs.get("plugin_id", PLUGIN_ID),
        "kind": "CliAnythingHarnessOnboarding",
        "harness_name": request.harness_name,
        "from_market": request.from_market,
        "write": request.write,
        "confirmed": request.confirmed,
        "install": request.install,
        "allow_blocked": request.allow_blocked,
        "include_workflows": request.include_workflows,
        "run_smoke_suite": request.run_smoke_suite,
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
            f"python -m cbn plugin market cli-anything info {request.harness_name}",
            f"python -m cbn plugin onboard-harness cli-anything {request.harness_name} --offline",
        ],
    }


def _onboarding_request_from_report_kwargs(kwargs: dict[str, Any]) -> OnboardingRequest:
    return OnboardingRequest(
        harness_name=kwargs["harness_name"],
        title=None,
        from_market=kwargs["from_market"],
        write=kwargs["write"],
        confirmed=kwargs["confirmed"],
        install=kwargs["install"],
        allow_blocked=kwargs["allow_blocked"],
        include_workflows=kwargs["include_workflows"],
        run_smoke_suite=kwargs["run_smoke_suite"],
        smoke_extra_args=(),
    )


def onboarding_summary(summary: OnboardingSummaryInput | None = None, **kwargs: Any) -> dict[str, Any]:
    summary = summary or OnboardingSummaryInput(**kwargs)
    return {
        "ready_for_manifest_write": summary.ready_for_manifest_write,
        "manifest_written": summary.manifest_written,
        "manifest_write_status": (
            "blocked"
            if summary.write_blocked_by_gate
            else "completed"
            if summary.manifest_written
            else "requires_confirmation"
            if summary.write_requested_without_confirmation
            else "ready"
            if summary.ready_for_manifest_write
            else "blocked"
        ),
        "write_requires_confirmation": summary.write_requested_without_confirmation,
        "ready_for_install": summary.ready_for_install,
        "install_requires_confirmation": summary.install_requested_without_confirmation,
        "install_executed": summary.install_execution_status == "completed",
        "install_execution_status": summary.install_execution_status,
        "ready_for_runtime_verification": summary.ready_for_runtime_verification,
        "smoke_suite_ready": bool(summary.smoke_suite.get("ok")) if summary.smoke_suite.get("run") else None,
        "recommended_next_action": summary.recommended_next_action,
    }


def onboarding_stage_results(
    context: OnboardingStageResultContext | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    return _onboarding_stage_results_payload(context or onboarding_stage_result_context(**kwargs))


def onboarding_stage_result_context(**kwargs: Any) -> OnboardingStageResultContext:
    unknown = sorted(set(kwargs) - set(OnboardingStageResultContext.__dataclass_fields__))
    if unknown:
        raise TypeError(f"unknown onboarding stage option(s): {', '.join(unknown)}")
    return OnboardingStageResultContext(**kwargs)


def _onboarding_stage_results_payload(context: OnboardingStageResultContext) -> list[dict[str, Any]]:
    manifest_stage = onboarding_adapt_manifest_stage(context)
    install_stage = onboarding_install_stage(
        install_gate=context.install_gate,
        ready_for_install=context.ready_for_install,
        harness_already_installed=context.harness_already_installed,
        install=context.install,
        allow_blocked=context.allow_blocked,
        install_execution_status=context.install_execution_status,
        install_execution_blockers=context.install_execution_blockers,
    )
    runtime_stage = onboarding_verify_runtime_stage(
        ready_for_runtime_verification=context.ready_for_runtime_verification,
        verification_blockers=context.verification_blockers,
    )
    return [
        onboarding_evaluate_stage(context.evaluation),
        onboarding_probe_stage(context.probe),
        manifest_stage,
        install_stage,
        runtime_stage,
        onboarding_smoke_protocol_stage(context.smoke_suite),
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


def onboarding_adapt_manifest_stage(context: OnboardingStageResultContext) -> dict[str, Any]:
    return {
        "id": "adapt_manifest",
        "status": (
            "completed"
            if context.manifest_written or context.manifest_already_imported
            else "ready"
            if context.ready_for_manifest_write
            else "blocked"
        ),
        "write_requested": context.write,
        "write_confirmed": context.confirmed,
        "written": context.adaptation.get("written"),
        "blockers": (
            ["manifest write blocked by harness evaluation"]
            if context.write_blocked_by_gate
            else [] if context.ready_for_manifest_write else context.evaluation["blockers"]
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
