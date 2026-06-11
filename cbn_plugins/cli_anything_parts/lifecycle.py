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
    blocked = bool(blockers)
    manifest_imported = bool(gates.get("manifest_imported", False))
    installed = bool(gates.get("installed", False))
    launch_ready = bool(gates.get("launch_ready", False))
    runtime_transport_ready = bool(gates.get("runtime_transport_ready", True))
    ready_for_install = bool(install_candidate and not installed and not blocked)
    requires_override = blocked or not bool(gates.get("external_dependency_free", True))
    if launch_ready:
        state = "launch_ready"
    elif installed and manifest_imported and not runtime_transport_ready:
        state = "runtime_transport_missing"
    elif blocked:
        state = "blocked"
    elif installed and not manifest_imported:
        state = "installed_needs_manifest"
    elif installed:
        state = "installed"
    elif manifest_imported and ready_for_install:
        state = "manifest_ready"
    elif install_candidate:
        state = "market_candidate"
    else:
        state = "needs_review"

    stages = [
        {
            "id": "evaluate",
            "status": "completed",
            "command": f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
        },
        {
            "id": "write_manifest",
            "status": stage_status(
                done=manifest_imported,
                ready=recommended_next_action == "write_manifest" and not blocked,
                blocked=blocked,
            ),
            "command": f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
        },
        {
            "id": "install_harness",
            "status": stage_status(
                done=installed,
                ready=recommended_next_action == "install_harness" and not blocked,
                blocked=blocked,
            ),
            "command": f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
        },
        {
            "id": "dry_run_call",
            "status": stage_status(
                done=False,
                ready=manifest_imported,
                blocked=blocked or not capability_id,
            ),
            "command": f"python -m cbn call {capability_id} --dry-run" if capability_id else None,
        },
    ]
    return {
        "state": state,
        "recommended_next_action": recommended_next_action,
        "blocked": blocked,
        "requires_override": requires_override,
        "ready_for_install": ready_for_install,
        "ready_for_call": launch_ready,
        "blockers": blockers,
        "stages": stages,
    }


def stage_status(done: bool, ready: bool, blocked: bool) -> str:
    if done:
        return "completed"
    if blocked:
        return "blocked"
    if ready:
        return "ready"
    return "pending"
