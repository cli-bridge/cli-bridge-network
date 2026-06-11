"""Promotion gate helpers for CLI-Anything runtime overlays."""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_parsers.fixtures import run_parser_fixtures
from cbn_parsers.registry import ParserRegistry
from cbn_protocol.readiness import protocol_readiness_report

from cbn_plugins.cli_anything_parts.verification import (
    effective_manifest_dict,
    parser_contract_report_from_registry,
    parser_fixture_gate,
)


PLUGIN_ID = "cli-anything"


def promotion_gate(
    hub: Any,
    harness_name: str,
    title: str | None = None,
    from_market: bool = True,
    include_workflows: bool = True,
    run_smoke_suite: bool = False,
    smoke_extra_args: tuple[str, ...] = (),
) -> dict[str, Any]:
    verification = hub.verify_harness(
        harness_name,
        title=title,
        from_market=from_market,
        include_workflows=include_workflows,
        run_smoke_suite=run_smoke_suite,
        smoke_extra_args=smoke_extra_args,
    )
    if not verification.get("ok"):
        return {
            "ok": False,
            "plugin_id": PLUGIN_ID,
            "kind": "CliAnythingOverlayPromotionGate",
            "harness_name": harness_name,
            "from_market": from_market,
            "include_workflows": include_workflows,
            "run_smoke_suite": run_smoke_suite,
            "error": verification.get("error", "harness verification failed"),
            "verification": verification,
        }

    capability_id = str(verification["capability_id"])
    registry = ManifestRegistry()
    registry.load_dir(hub.paths.manifests)
    registry.load_dir(hub.paths.local_manifests, replace=True)
    imported_manifest = registry.get(capability_id)
    effective_manifest = effective_manifest_dict(
        imported_manifest,
        verification.get("evaluation", {}).get("adaptation", {}).get("manifest", {}),
    )
    parser_contract = parser_contract_report_from_registry(effective_manifest)
    parser_fixture_report = run_parser_fixtures(
        parser_ref=parser_contract["parser_ref"],
        registry=ParserRegistry.builtins(),
    )
    parser_fixture_status = parser_fixture_gate(parser_fixture_report, capability_id)
    readiness = protocol_readiness_report(registry, include_workflows=include_workflows)
    registry_status = verification.get("registry") if isinstance(verification.get("registry"), dict) else {}
    smoke_suite = verification.get("protocol_smoke_suite") if isinstance(verification.get("protocol_smoke_suite"), dict) else {}
    source = registry_status.get("protocol_check_source")
    entrypoint_repair_active = bool(registry_status.get("entrypoint_repair_active"))
    blockers = promotion_blockers(
        verification=verification,
        source=source,
        entrypoint_repair_active=entrypoint_repair_active,
        parser_contract=parser_contract,
        parser_fixture_gate=parser_fixture_status,
        smoke_suite=smoke_suite,
        run_smoke_suite=run_smoke_suite,
        readiness=readiness,
    )
    if source == "current_registry":
        status = "already_portable"
    elif blockers:
        status = "blocked"
    else:
        status = "ready_for_promotion"
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingOverlayPromotionGate",
        "harness_name": harness_name,
        "from_market": from_market,
        "include_workflows": include_workflows,
        "run_smoke_suite": run_smoke_suite,
        "capability_id": capability_id,
        "status": status,
        "ready_for_promotion": status == "ready_for_promotion",
        "promotion_blockers": blockers,
        "source": {
            "kind": source,
            "manifest_path": registry_status.get("manifest_path"),
            "entrypoint_repair_active": entrypoint_repair_active,
            "portable_manifest_path": str(hub.paths.manifests / f"{capability_id}.json"),
            "runtime_overlay_path": str(hub.paths.local_manifests / f"{capability_id}.json"),
        },
        "requirements": promotion_requirements(
            source=source,
            entrypoint_repair_active=entrypoint_repair_active,
            parser_contract=parser_contract,
            parser_fixture_gate=parser_fixture_status,
            smoke_suite=smoke_suite,
            run_smoke_suite=run_smoke_suite,
            readiness=readiness,
            verification=verification,
        ),
        "parser_contract": parser_contract,
        "parser_fixtures": parser_fixture_status,
        "protocol_smoke_suite": smoke_suite,
        "protocol_readiness": {
            "ok": readiness.get("ok"),
            "summary": readiness.get("summary"),
            "readiness": readiness.get("readiness"),
            "manifest_sources": readiness.get("manifest_sources"),
            "protocol_gaps": readiness.get("protocol_gaps"),
        },
        "verification": verification,
        "next_commands": [
            f"python -m cbn plugin verify-harness cli-anything {harness_name} --from-market",
            f"python -m cbn parser fixtures --parser-ref {parser_contract['parser_ref']}",
            (
                f"python -m cbn plugin promotion-gate cli-anything {harness_name} "
                f"--from-market --smoke-suite --smoke-extra-arg=--help"
            ),
            "python -m cbn registry validate runtime/manifests",
            "python -m cbn registry validate manifests",
            f"python -m cbn protocol smoke-suite --capability-id {capability_id} --extra-arg=--help",
        ],
    }


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
