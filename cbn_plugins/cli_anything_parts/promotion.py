"""Promotion gate helpers for CLI-Anything runtime overlays."""

from __future__ import annotations

from typing import Any


def promotion_blockers(
    verification: dict[str, Any],
    source: Any,
    entrypoint_repair_active: bool,
    parser_contract: dict[str, Any],
    parser_fixture_gate: dict[str, Any],
    smoke_suite: dict[str, Any],
    run_smoke_suite: bool,
    readiness: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if source == "current_registry":
        blockers.append("capability is already loaded from portable manifests/")
    elif source != "runtime_local_overlay":
        blockers.append("capability is not loaded from runtime/manifests overlay")
    if not entrypoint_repair_active:
        blockers.append("runtime overlay does not declare a CBN entrypoint repair")
    for blocker in verification.get("verification_blockers", []):
        if blocker not in blockers:
            blockers.append(str(blocker))
    if not parser_contract.get("known"):
        blockers.append("parser is not known to the local parser registry")
    if not parser_contract.get("verified"):
        blockers.append("parser output contract is not verified in the manifest")
    if not parser_fixture_gate.get("ok"):
        blockers.append("parser fixtures are missing or failing")
    if not parser_fixture_gate.get("capability_verified"):
        blockers.append("parser fixtures do not list this capability as verified")
    if not run_smoke_suite:
        blockers.append("protocol smoke suite was not run for promotion")
    elif not smoke_suite.get("ok"):
        blockers.append("protocol smoke suite failed")
    readiness_gates = _readiness_gates(readiness)
    if not readiness_gates.get("internal_bridge_ready"):
        blockers.append("protocol readiness does not mark internal BridgeMessage routing ready")
    return sorted(set(blockers))


def promotion_requirements(
    source: Any,
    entrypoint_repair_active: bool,
    parser_contract: dict[str, Any],
    parser_fixture_gate: dict[str, Any],
    smoke_suite: dict[str, Any],
    run_smoke_suite: bool,
    readiness: dict[str, Any],
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    readiness_gates = _readiness_gates(readiness)
    return [
        {
            "id": "runtime_overlay_source",
            "status": "passed" if source == "runtime_local_overlay" else "blocked",
            "evidence": source,
        },
        {
            "id": "entrypoint_repair_provenance",
            "status": "passed" if entrypoint_repair_active else "blocked",
            "evidence": verification.get("registry", {}).get("manifest_path"),
        },
        {
            "id": "runtime_verification",
            "status": "passed" if verification.get("ready_for_runtime_verification") else "blocked",
            "evidence": verification.get("verification_blockers", []),
        },
        {
            "id": "parser_contract_verified",
            "status": "passed" if parser_contract.get("known") and parser_contract.get("verified") else "blocked",
            "evidence": parser_contract,
        },
        {
            "id": "parser_fixture_capability_coverage",
            "status": "passed" if parser_fixture_gate.get("ok") and parser_fixture_gate.get("capability_verified") else "blocked",
            "evidence": {
                "fixture_count": parser_fixture_gate.get("fixture_count"),
                "case_count": parser_fixture_gate.get("case_count"),
                "failed_case_count": parser_fixture_gate.get("failed_case_count"),
                "matching_fixture_ids": parser_fixture_gate.get("matching_fixture_ids"),
            },
        },
        {
            "id": "protocol_smoke_suite",
            "status": "passed" if run_smoke_suite and smoke_suite.get("ok") else "blocked",
            "evidence": {
                "run": bool(smoke_suite.get("run")),
                "ok": smoke_suite.get("ok"),
                "summary": smoke_suite.get("summary"),
            },
        },
        {
            "id": "internal_bridge_readiness",
            "status": "passed" if readiness_gates.get("internal_bridge_ready") else "blocked",
            "evidence": readiness.get("summary"),
        },
    ]


def _readiness_gates(readiness: dict[str, Any]) -> dict[str, Any]:
    gates = readiness.get("readiness")
    return gates if isinstance(gates, dict) else {}
