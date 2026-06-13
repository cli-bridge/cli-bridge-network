"""Live verification summary helpers for CLI-Anything."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PLUGIN_ID = "cli-anything"
LIVE_WORKFLOW_PATH = "workflows/cli-anything-macrocli-mermaid-routing.example.json"
_LIVE_OPTION_NAMES = (
    "harnesses",
    "candidate_query",
    "candidate_limit",
    "include_candidates",
    "include_workflows",
    "run_smoke_suite",
    "smoke_extra_args",
)


@dataclass(frozen=True)
class LiveVerificationRequest:
    harnesses: tuple[str, ...]
    candidate_query: str | None
    candidate_limit: int
    include_candidates: bool
    include_workflows: bool
    run_smoke_suite: bool
    smoke_extra_args: tuple[str, ...]


@dataclass(frozen=True)
class LiveVerificationReportInput:
    request: LiveVerificationRequest
    status: dict[str, Any]
    environment: dict[str, Any]
    harness_summary: list[dict[str, Any]]
    harness_reports: list[dict[str, Any]]
    candidates: dict[str, Any] | None
    workflow_readiness: dict[str, Any] | None
    summary: dict[str, Any]


def live_verification(
    hub: Any,
    *args: Any,
    **options: Any,
) -> dict[str, Any]:
    request = live_verification_request(args, options)
    status = hub.status()
    environment = hub._environment_verification()
    harness_reports = live_harness_reports(
        hub,
        harnesses=request.harnesses,
        include_workflows=request.include_workflows,
        run_smoke_suite=request.run_smoke_suite,
        smoke_extra_args=request.smoke_extra_args,
    )
    harness_summary = [harness_live_summary(report) for report in harness_reports]
    candidates = live_candidate_scan(hub, request.candidate_query, request.candidate_limit, request.include_candidates)
    workflow_readiness = live_workflow_readiness(hub, request.include_workflows)
    summary = live_verification_summary(
        status=status,
        environment=environment,
        harness_summary=harness_summary,
        candidates=candidates,
        workflow_readiness=workflow_readiness,
    )
    return live_verification_report(LiveVerificationReportInput(
        request=request,
        status=status,
        environment=environment,
        harness_summary=harness_summary,
        harness_reports=harness_reports,
        candidates=candidates,
        workflow_readiness=workflow_readiness,
        summary=summary,
    ))


def live_verification_request(args: tuple[Any, ...], options: dict[str, Any]) -> LiveVerificationRequest:
    if len(args) > len(_LIVE_OPTION_NAMES):
        raise TypeError(f"live_verification expected at most {len(_LIVE_OPTION_NAMES) + 1} arguments")
    values = {
        "harnesses": ("mermaid", "macrocli"),
        "candidate_query": "image",
        "candidate_limit": 10,
        "include_candidates": True,
        "include_workflows": True,
        "run_smoke_suite": False,
        "smoke_extra_args": (),
    }
    for name, value in zip(_LIVE_OPTION_NAMES, args):
        if name in options:
            raise TypeError(f"live_verification got multiple values for argument '{name}'")
        values[name] = value
    unknown = sorted(set(options) - set(_LIVE_OPTION_NAMES))
    if unknown:
        raise TypeError(f"unknown live verification option(s): {', '.join(unknown)}")
    values.update(options)
    values["harnesses"] = tuple(values["harnesses"])
    values["smoke_extra_args"] = tuple(values["smoke_extra_args"])
    return LiveVerificationRequest(**values)


def live_harness_reports(
    hub: Any,
    *,
    harnesses: tuple[str, ...],
    include_workflows: bool,
    run_smoke_suite: bool,
    smoke_extra_args: tuple[str, ...],
) -> list[dict[str, Any]]:
    return [
        hub.verify_harness(
            harness,
            from_market=True,
            include_workflows=include_workflows,
            run_smoke_suite=run_smoke_suite,
            smoke_extra_args=smoke_extra_args,
        )
        for harness in harnesses
    ]


def live_candidate_scan(
    hub: Any,
    candidate_query: str | None,
    candidate_limit: int,
    include_candidates: bool,
) -> dict[str, Any] | None:
    if not include_candidates:
        return None
    return hub.candidate_harnesses(
        query=candidate_query,
        limit=candidate_limit,
        with_probes=True,
        compact=True,
    )


def live_workflow_readiness(hub: Any, include_workflows: bool) -> dict[str, Any] | None:
    if not include_workflows:
        return None
    return hub._workflow_readiness(LIVE_WORKFLOW_PATH)


def live_verification_report(report: LiveVerificationReportInput) -> dict[str, Any]:
    return {
        "ok": live_verification_ok(report.summary, report.harness_summary),
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingLiveVerification",
        "run_smoke_suite": report.request.run_smoke_suite,
        "status": report.status,
        "environment": report.environment,
        "harnesses": report.harness_summary,
        "candidate_scan": candidate_live_summary(report.candidates) if report.candidates else None,
        "workflow_readiness": workflow_live_summary(report.workflow_readiness) if report.workflow_readiness else None,
        "summary": report.summary,
        "reports": {
            "harness_verifications": report.harness_reports,
            "candidates": report.candidates,
            "workflow_readiness": report.workflow_readiness,
        },
        "next_commands": live_verification_next_commands(),
    }


def live_verification_ok(
    summary: dict[str, Any],
    harness_summary: list[dict[str, Any]],
) -> bool:
    return (
        summary["entrypoint_available"]
        and summary["verified_harness_count"] == len(harness_summary)
        and summary["workflow_internal_bridge_ready"] is not False
    )


def live_verification_next_commands() -> list[str]:
    return [
        "python -m cbn plugin live-verification cli-anything",
        "python -m cbn plugin candidates cli-anything --query image --limit 10 --with-probes --compact",
        "python -m cbn plugin verify-harness cli-anything mermaid",
        "python -m cbn plugin verify-harness cli-anything macrocli",
        "python -m cbn plugin verify-harness cli-anything 3mf --smoke-suite --smoke-extra-arg=--help --no-workflows",
        "python -m cbn call cli-anything.macrocli.backends",
        f"python -m cbn workflow run {LIVE_WORKFLOW_PATH}",
        f"python -m cbn protocol readiness --workflow-path {LIVE_WORKFLOW_PATH}",
    ]


def harness_live_summary(report: dict[str, Any]) -> dict[str, Any]:
    evaluation = report.get("evaluation") if isinstance(report.get("evaluation"), dict) else {}
    gates = evaluation.get("gates") if isinstance(evaluation.get("gates"), dict) else {}
    parser_contract = report.get("parser_contract") if isinstance(report.get("parser_contract"), dict) else {}
    smoke_suite = report.get("protocol_smoke_suite") if isinstance(report.get("protocol_smoke_suite"), dict) else {}
    return {
        "harness_name": report.get("harness_name"),
        "capability_id": report.get("capability_id"),
        "ok": bool(report.get("ok")),
        "ready_for_manifest_write": bool(report.get("ready_for_manifest_write")),
        "ready_for_runtime_verification": bool(report.get("ready_for_runtime_verification")),
        "verification_blockers": report.get("verification_blockers", []),
        "readiness_ready": bool((report.get("readiness") or {}).get("ready")),
        "manifest_imported": bool(gates.get("manifest_imported")),
        "installed": bool(gates.get("installed")),
        "entrypoint_available": bool((evaluation.get("status") or {}).get("entrypoint_available")),
        "launch_ready": bool(gates.get("launch_ready")),
        "parser_ref": parser_contract.get("parser_ref"),
        "parser_verified": bool(parser_contract.get("verified")),
        "protocol_smoke_suite_run": bool(smoke_suite.get("run")),
        "protocol_smoke_suite_ok": smoke_suite.get("ok"),
        "protocol_wire_compatible": any(
            protocol.get("wire_compatible")
            for protocol in (report.get("protocols") or {}).values()
            if isinstance(protocol, dict)
        ),
    }


def candidate_live_summary(candidates: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(candidates.get("ok")),
        "query": candidates.get("query"),
        "market_count": candidates.get("market_count"),
        "evaluated_count": candidates.get("evaluated_count"),
        "selected_count": candidates.get("selected_count"),
        "install_candidate_count": candidates.get("install_candidate_count"),
        "blocked_count": candidates.get("blocked_count"),
        "probe_ready_count": candidates.get("probe_ready_count"),
        "probe_blocked_count": candidates.get("probe_blocked_count"),
        "candidate_summary": candidates.get("candidate_summary", []),
        "market": candidates.get("market"),
    }


def workflow_live_summary(workflow_readiness: dict[str, Any]) -> dict[str, Any]:
    readiness = workflow_readiness.get("readiness") if isinstance(workflow_readiness.get("readiness"), dict) else {}
    summary = workflow_readiness.get("summary") if isinstance(workflow_readiness.get("summary"), dict) else {}
    return {
        "ok": bool(workflow_readiness.get("ok")),
        "workflow_path": workflow_readiness.get("workflow_path"),
        "route_count": summary.get("route_count"),
        "routed_workflow_count": summary.get("routed_workflow_count"),
        "internal_bridge_ready": readiness.get("internal_bridge_ready"),
        "external_protocol_wire_compatible": readiness.get("external_protocol_wire_compatible"),
        "protocol_gaps": workflow_readiness.get("protocol_gaps", {}),
        "next_steps": workflow_readiness.get("next_steps", []),
    }


def live_verification_summary(
    status: dict[str, Any],
    environment: dict[str, Any],
    harness_summary: list[dict[str, Any]],
    candidates: dict[str, Any] | None,
    workflow_readiness: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "entrypoint_available": bool(status.get("entrypoint_available")),
        "source_trusted": environment.get("source_trusted"),
        "ready_for_update": environment.get("ready_for_update"),
        **live_harness_summary_counts(harness_summary),
        **live_candidate_summary_counts(candidates),
        **live_workflow_summary_counts(workflow_readiness),
    }


def live_harness_summary_counts(harness_summary: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "harness_count": len(harness_summary),
        "verified_harness_count": sum(1 for item in harness_summary if _harness_verified(item)),
        "launch_ready_harness_count": sum(1 for item in harness_summary if item["launch_ready"]),
        "unverified_parser_count": sum(1 for item in harness_summary if not item["parser_verified"]),
        "protocol_smoke_suite_run_count": sum(1 for item in harness_summary if item["protocol_smoke_suite_run"]),
        "protocol_smoke_suite_passed_count": sum(1 for item in harness_summary if _smoke_suite_passed(item)),
    }


def _harness_verified(item: dict[str, Any]) -> bool:
    return bool(item["ok"] and item["ready_for_runtime_verification"])


def _smoke_suite_passed(item: dict[str, Any]) -> bool:
    return bool(item["protocol_smoke_suite_run"] and item["protocol_smoke_suite_ok"])


def live_candidate_summary_counts(candidates: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "candidate_query": candidates.get("query") if candidates else None,
        "candidate_market_count": candidates.get("market_count") if candidates else None,
        "candidate_blocked_count": candidates.get("blocked_count") if candidates else None,
        "candidate_install_candidate_count": candidates.get("install_candidate_count") if candidates else None,
    }


def live_workflow_summary_counts(workflow_readiness: dict[str, Any] | None) -> dict[str, Any]:
    readiness = workflow_readiness.get("readiness") if workflow_readiness else {}
    readiness = readiness if isinstance(readiness, dict) else {}
    return {
        "workflow_internal_bridge_ready": readiness.get("internal_bridge_ready") if workflow_readiness else None,
        "external_protocol_wire_compatible": bool(readiness.get("external_protocol_wire_compatible")),
    }
