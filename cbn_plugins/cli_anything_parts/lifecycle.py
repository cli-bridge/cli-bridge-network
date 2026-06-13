"""Lifecycle and dependency readiness helpers for CLI-Anything harnesses."""

from __future__ import annotations

from typing import Any

from adapters.pty import pty_backend_status
from cbn_plugins.cli_anything_parts.manifest_factory import (
    has_external_network_signal,
    has_local_network_signal,
    has_write_workspace_signal,
    market_runtime_text,
    max_risk,
)
from cbn_plugins.cli_anything_parts.market import market_record_identity
from cbn_plugins.cli_anything_parts.probe import (
    declared_requires,
    dependency_probes,
    external_app_requirement_signals,
    localhost_port_available,
    managed_requirement_signals,
    platform_assessment,
    readiness_blocker_probes,
    readiness_summary,
    requirement_assessment,
    requirement_commands,
    requirement_env_vars,
    requirement_localhost_ports,
    requires_manual_account_or_key,
)


def transport_assessment(manifest: dict[str, Any]) -> dict[str, Any]:
    transport = manifest.get("spec", {}).get("transport", {})
    if not isinstance(transport, dict):
        return {
            "kind": None,
            "ready": False,
            "reason": "manifest transport is not an object",
            "backend": None,
            "install_hint": None,
        }
    kind = transport.get("kind")
    if kind == "stdio":
        return {
            "kind": "stdio",
            "ready": True,
            "reason": "stdio transport is available",
            "backend": "subprocess",
            "install_hint": None,
        }
    if kind == "pty":
        status = pty_backend_status()
        ready = bool(status["available"])
        return {
            "kind": "pty",
            "ready": ready,
            "reason": "pty transport is available" if ready else "pty transport backend is missing",
            "backend": status.get("backend"),
            "platform": status.get("platform"),
            "install_hint": status.get("install_hint"),
        }
    return {
        "kind": kind,
        "ready": False,
        "reason": f"unsupported transport kind: {kind}",
        "backend": None,
        "install_hint": None,
    }


def lifecycle_report(
    harness_name: str,
    capability_id: str | None,
    recommended_next_action: str,
    gates: dict[str, Any],
    blockers: list[str],
    install_candidate: bool,
) -> dict[str, Any]:
    flags = lifecycle_report_flags(gates, blockers, install_candidate)
    return {
        "state": lifecycle_state(
            manifest_imported=flags["manifest_imported"],
            installed=flags["installed"],
            launch_ready=flags["launch_ready"],
            runtime_transport_ready=flags["runtime_transport_ready"],
            blocked=flags["blocked"],
            ready_for_install=flags["ready_for_install"],
            install_candidate=install_candidate,
        ),
        "recommended_next_action": recommended_next_action,
        "blocked": flags["blocked"],
        "requires_override": flags["requires_override"],
        "ready_for_install": flags["ready_for_install"],
        "ready_for_call": flags["launch_ready"],
        "blockers": blockers,
        "stages": lifecycle_stages(
            harness_name=harness_name,
            capability_id=capability_id,
            recommended_next_action=recommended_next_action,
            manifest_imported=flags["manifest_imported"],
            installed=flags["installed"],
            blocked=flags["blocked"],
        ),
    }


def lifecycle_report_flags(
    gates: dict[str, Any],
    blockers: list[str],
    install_candidate: bool,
) -> dict[str, bool]:
    blocked = bool(blockers)
    installed = bool(gates.get("installed", False))
    return {
        "blocked": blocked,
        "manifest_imported": bool(gates.get("manifest_imported", False)),
        "installed": installed,
        "launch_ready": bool(gates.get("launch_ready", False)),
        "runtime_transport_ready": bool(gates.get("runtime_transport_ready", True)),
        "ready_for_install": bool(install_candidate and not installed and not blocked),
        "requires_override": blocked or not bool(gates.get("external_dependency_free", True)),
    }


def lifecycle_state(
    *,
    manifest_imported: bool,
    installed: bool,
    launch_ready: bool,
    runtime_transport_ready: bool,
    blocked: bool,
    ready_for_install: bool,
    install_candidate: bool,
) -> str:
    rules = lifecycle_state_rules(
        manifest_imported=manifest_imported,
        installed=installed,
        launch_ready=launch_ready,
        runtime_transport_ready=runtime_transport_ready,
        blocked=blocked,
        ready_for_install=ready_for_install,
        install_candidate=install_candidate,
    )
    return next((state for state, ready in rules if ready), "needs_review")


def lifecycle_state_rules(
    *,
    manifest_imported: bool,
    installed: bool,
    launch_ready: bool,
    runtime_transport_ready: bool,
    blocked: bool,
    ready_for_install: bool,
    install_candidate: bool,
) -> tuple[tuple[str, bool], ...]:
    return (
        ("launch_ready", launch_ready),
        ("runtime_transport_missing", installed and manifest_imported and not runtime_transport_ready),
        ("blocked", blocked),
        ("installed_needs_manifest", installed and not manifest_imported),
        ("installed", installed),
        ("manifest_ready", manifest_imported and ready_for_install),
        ("market_candidate", install_candidate),
    )


def lifecycle_stages(
    *,
    harness_name: str,
    capability_id: str | None,
    recommended_next_action: str,
    manifest_imported: bool,
    installed: bool,
    blocked: bool,
) -> list[dict[str, Any]]:
    return [
        lifecycle_evaluate_stage(harness_name),
        lifecycle_write_manifest_stage(harness_name, recommended_next_action, manifest_imported, blocked),
        lifecycle_install_stage(harness_name, recommended_next_action, installed, blocked),
        lifecycle_dry_run_stage(capability_id, manifest_imported, blocked),
    ]


def lifecycle_evaluate_stage(harness_name: str) -> dict[str, Any]:
    return {
        "id": "evaluate",
        "status": "completed",
        "command": f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
    }


def lifecycle_write_manifest_stage(
    harness_name: str,
    recommended_next_action: str,
    manifest_imported: bool,
    blocked: bool,
) -> dict[str, Any]:
    return {
        "id": "write_manifest",
        "status": stage_status(
            done=manifest_imported,
            ready=recommended_next_action == "write_manifest" and not blocked,
            blocked=blocked,
        ),
        "command": f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
    }


def lifecycle_install_stage(
    harness_name: str,
    recommended_next_action: str,
    installed: bool,
    blocked: bool,
) -> dict[str, Any]:
    return {
        "id": "install_harness",
        "status": stage_status(
            done=installed,
            ready=recommended_next_action == "install_harness" and not blocked,
            blocked=blocked,
        ),
        "command": f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
    }


def lifecycle_dry_run_stage(
    capability_id: str | None,
    manifest_imported: bool,
    blocked: bool,
) -> dict[str, Any]:
    return {
        "id": "dry_run_call",
        "status": stage_status(
            done=False,
            ready=manifest_imported,
            blocked=blocked or not capability_id,
        ),
        "command": f"python -m cbn call {capability_id} --dry-run" if capability_id else None,
    }


def refresh_candidate_lifecycle(item: dict[str, Any]) -> None:
    harness_name = item.get("harness_name")
    if not isinstance(harness_name, str) or not harness_name:
        return
    blockers = item.get("blockers")
    if not isinstance(blockers, list):
        blockers = []
    gates = item.get("gates")
    if not isinstance(gates, dict):
        gates = {}
    item["lifecycle"] = lifecycle_report(
        harness_name=harness_name,
        capability_id=item.get("capability_id") if isinstance(item.get("capability_id"), str) else None,
        recommended_next_action=str(item.get("recommended_next_action") or "resolve_blockers"),
        gates=gates,
        blockers=blockers,
        install_candidate=bool(item.get("install_candidate")),
    )


def attach_candidate_readiness(item: dict[str, Any]) -> None:
    record = item.get("market_record") if isinstance(item.get("market_record"), dict) else {}
    readiness = readiness_summary(
        probes=dependency_probes(
            requires=declared_requires(record, {}),
            entry_point=record.get("entry_point"),
        ),
        install_candidate=bool(item.get("install_candidate")),
    )
    item["readiness"] = readiness
    blocker_probes = readiness_blocker_probes(readiness)
    if blocker_probes:
        blockers = item.setdefault("blockers", [])
        if not isinstance(blockers, list):
            blockers = []
            item["blockers"] = blockers
        for probe in blocker_probes:
            probe_id = probe.get("id") or probe.get("kind") or "unknown"
            blocker = f"dependency probe failed: {probe_id}"
            if blocker not in blockers:
                blockers.append(blocker)
        gates = item.get("gates")
        if isinstance(gates, dict):
            gates["external_dependency_free"] = False
        item["install_candidate"] = False
        item["recommended_next_action"] = "resolve_blockers"
        refresh_candidate_lifecycle(item)


def readiness_from_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    status = evaluation.get("status") if isinstance(evaluation.get("status"), dict) else {}
    market_record = status.get("market_record") if isinstance(status.get("market_record"), dict) else None
    return readiness_summary(
        probes=dependency_probes(
            requires=declared_requires(market_record, status),
            entry_point=status.get("entry_point"),
        ),
        install_candidate=bool(evaluation.get("install_candidate")),
    )


def stage_status(done: bool, ready: bool, blocked: bool) -> str:
    if done:
        return "completed"
    if blocked:
        return "blocked"
    if ready:
        return "ready"
    return "pending"
