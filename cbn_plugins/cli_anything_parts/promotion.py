"""Promotion gate helpers for CLI-Anything runtime overlays."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class PromotionGateRequest:
    harness_name: str
    title: str | None
    from_market: bool
    include_workflows: bool
    run_smoke_suite: bool
    smoke_extra_args: tuple[str, ...]


@dataclass(frozen=True)
class PromotionGateContext:
    capability_id: str
    registry_status: dict[str, Any]
    source: Any
    entrypoint_repair_active: bool
    parser_contract: dict[str, Any]
    parser_fixture_status: dict[str, Any]
    readiness: dict[str, Any]
    smoke_suite: dict[str, Any]


@dataclass(frozen=True)
class PromotionGateReportInput:
    hub: Any
    harness_name: str
    from_market: bool
    include_workflows: bool
    run_smoke_suite: bool
    verification: dict[str, Any]
    context: PromotionGateContext
    blockers: list[str]
    status: str


def promotion_gate(
    hub: Any,
    harness_name: str,
    title: str | None = None,
    from_market: bool = True,
    include_workflows: bool = True,
    run_smoke_suite: bool = False,
    smoke_extra_args: tuple[str, ...] = (),
) -> dict[str, Any]:
    request = PromotionGateRequest(
        harness_name,
        title,
        from_market,
        include_workflows,
        run_smoke_suite,
        smoke_extra_args,
    )
    verification = _promotion_verification_for_request(hub, request)
    if not verification.get("ok"):
        return failed_promotion_gate_report_for_request(request, verification)
    return successful_promotion_gate_report(promotion_gate_report_input(hub, request, verification))


def _promotion_verification_for_request(
    hub: Any,
    request: PromotionGateRequest,
) -> dict[str, Any]:
    return _promotion_verification(
        hub,
        request.harness_name,
        title=request.title,
        from_market=request.from_market,
        include_workflows=request.include_workflows,
        run_smoke_suite=request.run_smoke_suite,
        smoke_extra_args=request.smoke_extra_args,
    )


def promotion_gate_report_input(
    hub: Any,
    request: PromotionGateRequest,
    verification: dict[str, Any],
) -> PromotionGateReportInput:
    context = build_promotion_gate_context(
        hub,
        verification=verification,
        include_workflows=request.include_workflows,
    )
    blockers = promotion_blockers_from_context(verification, context, request.run_smoke_suite)
    status = promotion_status(context.source, blockers)
    return PromotionGateReportInput(
        hub=hub,
        harness_name=request.harness_name,
        from_market=request.from_market,
        include_workflows=request.include_workflows,
        run_smoke_suite=request.run_smoke_suite,
        verification=verification,
        context=context,
        blockers=blockers,
        status=status,
    )


def _promotion_verification(
    hub: Any,
    harness_name: str,
    *,
    title: str | None,
    from_market: bool,
    include_workflows: bool,
    run_smoke_suite: bool,
    smoke_extra_args: tuple[str, ...],
) -> dict[str, Any]:
    return hub.verify_harness(
        harness_name,
        title=title,
        from_market=from_market,
        include_workflows=include_workflows,
        run_smoke_suite=run_smoke_suite,
        smoke_extra_args=smoke_extra_args,
    )


def promotion_blockers_from_context(
    verification: dict[str, Any],
    context: PromotionGateContext,
    run_smoke_suite: bool,
) -> list[str]:
    return promotion_blockers(verification, context, run_smoke_suite)


def failed_promotion_gate_report(
    harness_name: str,
    from_market: bool,
    include_workflows: bool,
    run_smoke_suite: bool,
    verification: dict[str, Any],
) -> dict[str, Any]:
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


def failed_promotion_gate_report_for_request(
    request: PromotionGateRequest,
    verification: dict[str, Any],
) -> dict[str, Any]:
    return failed_promotion_gate_report(
        harness_name=request.harness_name,
        from_market=request.from_market,
        include_workflows=request.include_workflows,
        run_smoke_suite=request.run_smoke_suite,
        verification=verification,
    )


def build_promotion_gate_context(
    hub: Any,
    verification: dict[str, Any],
    include_workflows: bool,
) -> PromotionGateContext:
    capability_id = str(verification["capability_id"])
    registry = load_promotion_registry(hub)
    imported_manifest = registry.get(capability_id)
    effective_manifest = effective_manifest_dict(
        imported_manifest,
        verification.get("evaluation", {}).get("adaptation", {}).get("manifest", {}),
    )
    parser_contract = parser_contract_report_from_registry(effective_manifest)
    parser_fixture_status = promotion_parser_fixture_status(parser_contract, capability_id)
    registry_status = dict_from_report(verification, "registry")
    return PromotionGateContext(
        capability_id=capability_id,
        registry_status=registry_status,
        source=registry_status.get("protocol_check_source"),
        entrypoint_repair_active=bool(registry_status.get("entrypoint_repair_active")),
        parser_contract=parser_contract,
        parser_fixture_status=parser_fixture_status,
        readiness=protocol_readiness_report(registry, include_workflows=include_workflows),
        smoke_suite=dict_from_report(verification, "protocol_smoke_suite"),
    )


def load_promotion_registry(hub: Any) -> ManifestRegistry:
    registry = ManifestRegistry()
    registry.load_dir(hub.paths.manifests)
    registry.load_dir(hub.paths.local_manifests, replace=True)
    return registry


def promotion_parser_fixture_status(
    parser_contract: dict[str, Any],
    capability_id: str,
) -> dict[str, Any]:
    parser_fixture_report = run_parser_fixtures(
        parser_ref=parser_contract["parser_ref"],
        registry=ParserRegistry.builtins(),
    )
    return parser_fixture_gate(parser_fixture_report, capability_id)


def dict_from_report(report: dict[str, Any], key: str) -> dict[str, Any]:
    value = report.get(key)
    return value if isinstance(value, dict) else {}


def promotion_status(source: Any, blockers: list[str]) -> str:
    if source == "current_registry":
        return "already_portable"
    if blockers:
        return "blocked"
    return "ready_for_promotion"


def successful_promotion_gate_report(report: PromotionGateReportInput) -> dict[str, Any]:
    context = report.context
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "kind": "CliAnythingOverlayPromotionGate",
        "harness_name": report.harness_name,
        "from_market": report.from_market,
        "include_workflows": report.include_workflows,
        "run_smoke_suite": report.run_smoke_suite,
        "capability_id": context.capability_id,
        "status": report.status,
        "ready_for_promotion": report.status == "ready_for_promotion",
        "promotion_blockers": report.blockers,
        "source": promotion_source_report(report.hub, context),
        "requirements": promotion_requirements(report),
        "parser_contract": context.parser_contract,
        "parser_fixtures": context.parser_fixture_status,
        "protocol_smoke_suite": context.smoke_suite,
        "protocol_readiness": promotion_readiness_summary(context.readiness),
        "verification": report.verification,
        "next_commands": promotion_next_commands(report.harness_name, context),
    }


def promotion_source_report(hub: Any, context: PromotionGateContext) -> dict[str, Any]:
    return {
        "kind": context.source,
        "manifest_path": context.registry_status.get("manifest_path"),
        "entrypoint_repair_active": context.entrypoint_repair_active,
        "portable_manifest_path": str(hub.paths.manifests / f"{context.capability_id}.json"),
        "runtime_overlay_path": str(hub.paths.local_manifests / f"{context.capability_id}.json"),
    }


def promotion_readiness_summary(readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": readiness.get("ok"),
        "summary": readiness.get("summary"),
        "readiness": readiness.get("readiness"),
        "manifest_sources": readiness.get("manifest_sources"),
        "protocol_gaps": readiness.get("protocol_gaps"),
    }


def promotion_next_commands(harness_name: str, context: PromotionGateContext) -> list[str]:
    return [
        f"python -m cbn plugin verify-harness cli-anything {harness_name} --from-market",
        f"python -m cbn parser fixtures --parser-ref {context.parser_contract['parser_ref']}",
        (
            f"python -m cbn plugin promotion-gate cli-anything {harness_name} "
            f"--from-market --smoke-suite --smoke-extra-arg=--help"
        ),
        "python -m cbn registry validate runtime/manifests",
        "python -m cbn registry validate manifests",
        (
            "python -m cbn protocol smoke-suite "
            f"--capability-id {context.capability_id} --extra-arg=--help"
        ),
    ]


def promotion_blockers(
    verification: dict[str, Any],
    context: PromotionGateContext,
    run_smoke_suite: bool,
) -> list[str]:
    blockers = [
        *promotion_source_blockers(context.source, context.entrypoint_repair_active),
        *promotion_verification_blockers(verification),
        *promotion_parser_blockers(context.parser_contract, context.parser_fixture_status),
        *promotion_smoke_blockers(run_smoke_suite, context.smoke_suite),
        *promotion_readiness_blockers(context.readiness),
    ]
    return sorted(set(blockers))


def promotion_source_blockers(source: Any, entrypoint_repair_active: bool) -> list[str]:
    blockers = []
    if source == "current_registry":
        blockers.append("capability is already loaded from portable manifests/")
    elif source != "runtime_local_overlay":
        blockers.append("capability is not loaded from runtime/manifests overlay")
    if not entrypoint_repair_active:
        blockers.append("runtime overlay does not declare a CBN entrypoint repair")
    return blockers


def promotion_verification_blockers(verification: dict[str, Any]) -> list[str]:
    return [str(blocker) for blocker in verification.get("verification_blockers", [])]


def promotion_parser_blockers(
    parser_contract: dict[str, Any],
    parser_fixture_gate: dict[str, Any],
) -> list[str]:
    blockers = []
    if not parser_contract.get("known"):
        blockers.append("parser is not known to the local parser registry")
    if not parser_contract.get("verified"):
        blockers.append("parser output contract is not verified in the manifest")
    if not parser_fixture_gate.get("ok"):
        blockers.append("parser fixtures are missing or failing")
    if not parser_fixture_gate.get("capability_verified"):
        blockers.append("parser fixtures do not list this capability as verified")
    return blockers


def promotion_smoke_blockers(run_smoke_suite: bool, smoke_suite: dict[str, Any]) -> list[str]:
    if not run_smoke_suite:
        return ["protocol smoke suite was not run for promotion"]
    if not smoke_suite.get("ok"):
        return ["protocol smoke suite failed"]
    return []


def promotion_readiness_blockers(readiness: dict[str, Any]) -> list[str]:
    readiness_gates = _readiness_gates(readiness)
    if not readiness_gates.get("internal_bridge_ready"):
        return ["protocol readiness does not mark internal BridgeMessage routing ready"]
    return []


def promotion_requirements(report: PromotionGateReportInput) -> list[dict[str, Any]]:
    context = report.context
    readiness_gates = _readiness_gates(context.readiness)
    return [
        *_promotion_source_requirements(
            context.source,
            context.entrypoint_repair_active,
            report.verification,
        ),
        *_promotion_parser_requirements(context.parser_contract, context.parser_fixture_status),
        *_promotion_protocol_requirements(
            report.run_smoke_suite,
            context.smoke_suite,
            context.readiness,
            readiness_gates,
        ),
    ]


def _promotion_source_requirements(
    source: Any,
    entrypoint_repair_active: bool,
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        promotion_requirement("runtime_overlay_source", source == "runtime_local_overlay", source),
        promotion_requirement(
            "entrypoint_repair_provenance",
            entrypoint_repair_active,
            verification.get("registry", {}).get("manifest_path"),
        ),
        promotion_requirement(
            "runtime_verification",
            verification.get("ready_for_runtime_verification"),
            verification.get("verification_blockers", []),
        ),
    ]


def _promotion_parser_requirements(
    parser_contract: dict[str, Any],
    parser_fixture_gate: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        promotion_requirement(
            "parser_contract_verified",
            parser_contract.get("known") and parser_contract.get("verified"),
            parser_contract,
        ),
        promotion_requirement(
            "parser_fixture_capability_coverage",
            parser_fixture_gate.get("ok") and parser_fixture_gate.get("capability_verified"),
            _parser_fixture_evidence(parser_fixture_gate),
        ),
    ]


def _promotion_protocol_requirements(
    run_smoke_suite: bool,
    smoke_suite: dict[str, Any],
    readiness: dict[str, Any],
    readiness_gates: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        promotion_requirement(
            "protocol_smoke_suite",
            run_smoke_suite and smoke_suite.get("ok"),
            _smoke_suite_evidence(smoke_suite),
        ),
        promotion_requirement(
            "internal_bridge_readiness",
            readiness_gates.get("internal_bridge_ready"),
            readiness.get("summary"),
        ),
    ]


def _parser_fixture_evidence(parser_fixture_gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture_count": parser_fixture_gate.get("fixture_count"),
        "case_count": parser_fixture_gate.get("case_count"),
        "failed_case_count": parser_fixture_gate.get("failed_case_count"),
        "matching_fixture_ids": parser_fixture_gate.get("matching_fixture_ids"),
    }


def _smoke_suite_evidence(smoke_suite: dict[str, Any]) -> dict[str, Any]:
    return {
        "run": bool(smoke_suite.get("run")),
        "ok": smoke_suite.get("ok"),
        "summary": smoke_suite.get("summary"),
    }


def promotion_requirement(
    requirement_id: str,
    passed: Any,
    evidence: Any,
) -> dict[str, Any]:
    return {
        "id": requirement_id,
        "status": "passed" if passed else "blocked",
        "evidence": evidence,
    }


def _readiness_gates(readiness: dict[str, Any]) -> dict[str, Any]:
    gates = readiness.get("readiness")
    return gates if isinstance(gates, dict) else {}
