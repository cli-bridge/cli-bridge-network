"""MVP and first-run planning helpers for CLI-Anything."""

from __future__ import annotations

from typing import Any


def mvp_plan_summary(
    environment: dict[str, Any],
    install_gate: dict[str, Any],
    install_queue: dict[str, Any],
    adaptation_queue: dict[str, Any],
    protocol_readiness: dict[str, Any],
    acceptance_queue: dict[str, Any],
) -> dict[str, Any]:
    install_summary = install_queue.get("summary") if isinstance(install_queue.get("summary"), dict) else {}
    adaptation_summary = (
        adaptation_queue.get("summary") if isinstance(adaptation_queue.get("summary"), dict) else {}
    )
    protocol_gates = (
        protocol_readiness.get("readiness") if isinstance(protocol_readiness.get("readiness"), dict) else {}
    )
    acceptance_summary = (
        acceptance_queue.get("summary") if isinstance(acceptance_queue.get("summary"), dict) else {}
    )
    source_downloaded = bool(environment.get("source_downloaded"))
    entrypoint_available = bool(
        any(item.get("available") for item in environment.get("entrypoints", []) if isinstance(item, dict))
    )
    plugin_install_ready = bool(install_gate.get("ok") or source_downloaded)
    queued_count = int(install_summary.get("queued_count", 0))
    blocked_install_count = int(install_summary.get("blocked_count", 0))
    native_ready_count = int(adaptation_summary.get("native_ready_count", 0))
    ready_for_repair_write_count = int(adaptation_summary.get("ready_for_repair_write_count", 0))
    smoke_ready_count = int(adaptation_summary.get("smoke_ready_count", 0))
    adaptation_blocked_count = int(adaptation_summary.get("blocked_count", 0))
    internal_bridge_ready = bool(protocol_gates.get("internal_bridge_ready"))
    acceptance_skipped = bool(acceptance_queue.get("skipped"))
    accepted_workflow_count = int(acceptance_summary.get("accepted_workflow_count", 0))
    blocked_workflow_count = int(acceptance_summary.get("blocked_workflow_count", 0))
    return {
        "source_downloaded": source_downloaded,
        "source_trusted": environment.get("source_trusted"),
        "entrypoint_available": entrypoint_available,
        "plugin_install_gate_ok": bool(install_gate.get("ok")),
        "plugin_install_ready": plugin_install_ready,
        "install_queue_ok": bool(install_queue.get("ok")),
        "queued_harness_count": queued_count,
        "blocked_install_count": blocked_install_count,
        "adaptation_harness_count": int(adaptation_summary.get("harness_count", 0)),
        "native_ready_count": native_ready_count,
        "ready_for_repair_write_count": ready_for_repair_write_count,
        "smoke_ready_count": smoke_ready_count,
        "adaptation_blocked_count": adaptation_blocked_count,
        "protocol_internal_bridge_ready": internal_bridge_ready,
        "external_protocol_wire_compatible": bool(protocol_gates.get("external_protocol_wire_compatible")),
        "accepted_workflow_count": accepted_workflow_count,
        "blocked_workflow_count": blocked_workflow_count,
        "acceptance_queue_skipped": acceptance_skipped,
        "ready_for_next_market_download": bool(plugin_install_ready and queued_count > 0),
        "ready_for_harness_adaptation": bool(
            native_ready_count > 0 or ready_for_repair_write_count > 0 or smoke_ready_count > 0
        ),
        "ready_for_cli_to_cli_protocol_study": bool(
            internal_bridge_ready and not acceptance_skipped and blocked_workflow_count == 0
        ),
        "recommended_next_action": mvp_plan_next_action(
            source_downloaded=source_downloaded,
            plugin_install_ready=plugin_install_ready,
            queued_count=queued_count,
            ready_for_repair_write_count=ready_for_repair_write_count,
            smoke_ready_count=smoke_ready_count,
            adaptation_blocked_count=adaptation_blocked_count,
            internal_bridge_ready=internal_bridge_ready,
            blocked_workflow_count=blocked_workflow_count,
        ),
    }


def mvp_plan_next_action(
    source_downloaded: bool,
    plugin_install_ready: bool,
    queued_count: int,
    ready_for_repair_write_count: int,
    smoke_ready_count: int,
    adaptation_blocked_count: int,
    internal_bridge_ready: bool,
    blocked_workflow_count: int,
) -> str:
    if not source_downloaded:
        return "install_cli_anything_external_plugin"
    if not plugin_install_ready:
        return "fix_cli_anything_install_gate"
    if queued_count > 0:
        return "install_next_market_harness"
    if smoke_ready_count > 0:
        return "run_adapter_smoke"
    if ready_for_repair_write_count > 0:
        return "repair_entrypoint_with_smoke_evidence"
    if adaptation_blocked_count > 0:
        return "inspect_adaptation_blockers"
    if not internal_bridge_ready or blocked_workflow_count > 0:
        return "fix_cli_to_cli_acceptance"
    return "start_external_protocol_conformance_research"


def mvp_plan_stages(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "download_cli_anything",
            "title": "Download CLI-Anything",
            "status": "ready" if summary["source_downloaded"] else "next",
            "ready": bool(summary["plugin_install_ready"]),
            "recommended_next_action": (
                "verify_or_update_cli_anything"
                if summary["source_downloaded"]
                else "install_cli_anything_external_plugin"
            ),
        },
        {
            "id": "install_market_harnesses",
            "title": "Install Market Harnesses",
            "status": (
                "next"
                if summary["ready_for_next_market_download"]
                else "complete"
                if summary["queued_harness_count"] == 0
                and summary["blocked_install_count"] == 0
                and summary["adaptation_harness_count"] > 0
                else "blocked"
            ),
            "ready": bool(summary["ready_for_next_market_download"]),
            "queued_count": summary["queued_harness_count"],
            "blocked_count": summary["blocked_install_count"],
            "recommended_next_action": (
                "install_next_market_harness"
                if summary["ready_for_next_market_download"]
                else "inspect_market_install_queue"
            ),
        },
        {
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
        },
        {
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
        },
        {
            "id": "external_protocol_facades",
            "title": "External Protocol Facades",
            "status": "partial",
            "ready": bool(summary["protocol_internal_bridge_ready"]),
            "wire_compatible": bool(summary["external_protocol_wire_compatible"]),
            "recommended_next_action": "run_protocol_smoke_then_add_conformance_coverage",
        },
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
        {
            "id": "preflight",
            "title": "Preflight CLI-Anything Plugin",
            "status": "complete" if summary["install_gate_ok"] else "blocked",
            "ready": bool(summary["install_gate_ok"]),
            "command": "python -m cbn plugin preflight cli-anything",
        },
        {
            "id": "download_plugin",
            "title": "Download External Plugin Source",
            "status": "complete" if summary["source_downloaded"] else "next",
            "ready": bool(summary["install_gate_ok"]),
            "command": "python -m cbn plugin install cli-anything --yes",
        },
        {
            "id": "verify_provenance",
            "title": "Verify Source And Entrypoint Provenance",
            "status": (
                "complete"
                if summary["source_trusted"] is not False and summary["entrypoint_available"]
                else "blocked"
                if summary["source_trusted"] is False
                else "pending"
            ),
            "ready": bool(summary["source_downloaded"]),
            "command": "python -m cbn plugin provenance cli-anything",
        },
        {
            "id": "check_updates",
            "title": "Check External Plugin Updates",
            "status": "ready" if summary["source_downloaded"] else "pending",
            "ready": bool(summary["source_downloaded"]),
            "command": "python -m cbn plugin check-update cli-anything --remote",
        },
        {
            "id": "sync_market",
            "title": "Inspect CLI-Anything Market",
            "status": (
                "complete"
                if summary["market_scan_ok"]
                else "pending"
                if summary["market_scan_skipped"]
                else "blocked"
            ),
            "ready": bool(summary["entrypoint_available"]),
            "command": f"python -m cbn plugin candidates cli-anything --query {query_arg} --limit 10 --with-probes --compact",
        },
        {
            "id": "onboard_harness",
            "title": "Onboard First Market Harness",
            "status": "ready" if summary["onboarding_ok"] else "blocked",
            "ready": bool(summary["entrypoint_available"] and summary["market_scan_ok"]),
            "command": f"python -m cbn plugin onboard-harness cli-anything {harness_name} --from-market",
        },
        {
            "id": "protocol_lifecycle",
            "title": "Run Local Protocol Lifecycle Gate",
            "status": "complete" if summary["protocol_lifecycle_ok"] else "blocked",
            "ready": True,
            "command": f"python -m cbn protocol lifecycle-suite --capability-id git.version --workflow-path {workflow_path}",
        },
    ]
