"""Live verification summary helpers for CLI-Anything."""

from __future__ import annotations

from typing import Any


PLUGIN_ID = "cli-anything"


def live_verification(
    hub: Any,
    harnesses: tuple[str, ...] = ("mermaid", "macrocli"),
    candidate_query: str | None = "image",
    candidate_limit: int = 10,
    include_candidates: bool = True,
    include_workflows: bool = True,
    run_smoke_suite: bool = False,
    smoke_extra_args: tuple[str, ...] = (),
) -> dict[str, Any]:
    status = hub.status()
    environment = hub._environment_verification()
    harness_reports = [
        hub.verify_harness(
            harness,
            from_market=True,
            include_workflows=include_workflows,
            run_smoke_suite=run_smoke_suite,
            smoke_extra_args=smoke_extra_args,
        )
        for harness in harnesses
    ]
    harness_summary = [harness_live_summary(report) for report in harness_reports]
    candidates = (
        hub.candidate_harnesses(
            query=candidate_query,
            limit=candidate_limit,
            with_probes=True,
            compact=True,
        )
        if include_candidates
        else None
    )
    workflow_readiness = (
        hub._workflow_readiness("workflows/cli-anything-macrocli-mermaid-routing.example.json")
        if include_workflows
        else None
    )
    summary = live_verification_summary(
        status=status,
        environment=environment,
        harness_summary=harness_summary,
        candidates=candidates,
        workflow_readiness=workflow_readiness,
    )
    return {
        "ok": summary["entrypoint_available"]
        and summary["verified_harness_count"] == len(harness_summary)
        and summary["workflow_internal_bridge_ready"] is not False,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingLiveVerification",
        "run_smoke_suite": run_smoke_suite,
        "status": status,
        "environment": environment,
        "harnesses": harness_summary,
        "candidate_scan": candidate_live_summary(candidates) if candidates else None,
        "workflow_readiness": workflow_live_summary(workflow_readiness) if workflow_readiness else None,
        "summary": summary,
        "reports": {
            "harness_verifications": harness_reports,
            "candidates": candidates,
            "workflow_readiness": workflow_readiness,
        },
        "next_commands": [
            "python -m cbn plugin live-verification cli-anything",
            "python -m cbn plugin candidates cli-anything --query image --limit 10 --with-probes --compact",
            "python -m cbn plugin verify-harness cli-anything mermaid",
            "python -m cbn plugin verify-harness cli-anything macrocli",
            "python -m cbn plugin verify-harness cli-anything 3mf --smoke-suite --smoke-extra-arg=--help --no-workflows",
            "python -m cbn call cli-anything.macrocli.backends",
            "python -m cbn workflow run workflows/cli-anything-macrocli-mermaid-routing.example.json",
            "python -m cbn protocol readiness --workflow-path workflows/cli-anything-macrocli-mermaid-routing.example.json",
        ],
    }


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
    workflow_gate = None
    if workflow_readiness is not None:
        readiness = workflow_readiness.get("readiness") if isinstance(workflow_readiness.get("readiness"), dict) else {}
        workflow_gate = readiness.get("internal_bridge_ready")
    return {
        "entrypoint_available": bool(status.get("entrypoint_available")),
        "source_trusted": environment.get("source_trusted"),
        "ready_for_update": environment.get("ready_for_update"),
        "harness_count": len(harness_summary),
        "verified_harness_count": sum(
            1
            for item in harness_summary
            if item["ok"] and item["ready_for_runtime_verification"]
        ),
        "launch_ready_harness_count": sum(1 for item in harness_summary if item["launch_ready"]),
        "unverified_parser_count": sum(1 for item in harness_summary if not item["parser_verified"]),
        "protocol_smoke_suite_run_count": sum(1 for item in harness_summary if item["protocol_smoke_suite_run"]),
        "protocol_smoke_suite_passed_count": sum(
            1
            for item in harness_summary
            if item["protocol_smoke_suite_run"] and item["protocol_smoke_suite_ok"]
        ),
        "candidate_query": candidates.get("query") if candidates else None,
        "candidate_market_count": candidates.get("market_count") if candidates else None,
        "candidate_blocked_count": candidates.get("blocked_count") if candidates else None,
        "candidate_install_candidate_count": candidates.get("install_candidate_count") if candidates else None,
        "workflow_internal_bridge_ready": workflow_gate,
        "external_protocol_wire_compatible": bool(
            workflow_readiness
            and (workflow_readiness.get("readiness") or {}).get("external_protocol_wire_compatible")
        ),
    }
