"""Project-level protocol readiness reporting.

This report keeps the CLI-to-CLI readiness boundary explicit: CBN's internal
BridgeMessage and workflow routing can be ready for MVP composition while
external MCP/A2A/ACP adapters remain descriptor-only or partial facades.
"""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_core.bridge_contract import workflow_bridge_contract_report
from cbn_protocol.compatibility import PROTOCOLS, check_all_protocols, protocol_matrix
from cbn_protocol.wire_conformance import protocol_wire_conformance_suite


def protocol_readiness_report(
    registry: ManifestRegistry,
    workflow_path: str | None = None,
    include_workflows: bool = True,
) -> dict[str, Any]:
    """Return a bounded readiness report for CLI-to-CLI protocol work."""

    context = _readiness_context(registry, workflow_path, include_workflows)
    gates = _readiness_gates(
        context["parser_summary"],
        context["source_summary"],
        context["route_summary"],
        context["protocol_summary"],
        context["contract"],
    )
    return _readiness_payload(workflow_path, include_workflows, context, gates)


def _readiness_context(
    registry: ManifestRegistry,
    workflow_path: str | None,
    include_workflows: bool,
) -> dict[str, Any]:
    manifests = registry.list()
    matrix = protocol_matrix(
        registry,
        include_workflows=include_workflows and workflow_path is None,
    )
    contract = (
        workflow_bridge_contract_report(registry, workflow_path=workflow_path)
        if include_workflows or workflow_path
        else None
    )
    selected_workflow_protocols = (
        check_all_protocols(registry, workflow_path=workflow_path)["checks"]
        if workflow_path
        else None
    )
    parser_summary = _parser_summary(manifests)
    source_summary = _manifest_source_summary(manifests)
    routes = _flatten_routes(contract) if contract else []
    route_summary = _route_summary(contract, routes)
    wire_conformance = protocol_wire_conformance_suite()
    protocol_summary = _readiness_protocol_summary(matrix, selected_workflow_protocols, wire_conformance)
    return {
        "manifests": manifests,
        "matrix": matrix,
        "contract": contract,
        "selected_workflow_protocols": selected_workflow_protocols,
        "parser_summary": parser_summary,
        "source_summary": source_summary,
        "routes": routes,
        "route_summary": route_summary,
        "protocol_summary": protocol_summary,
        "wire_conformance": wire_conformance,
    }


def _readiness_protocol_summary(
    matrix: dict[str, Any],
    selected_workflow_protocols: list[dict[str, Any]] | None,
    wire_conformance: dict[str, Any],
) -> dict[str, Any]:
    summary = _protocol_summary(matrix, selected_workflow_protocols)
    summary["wire_compatible_protocol_count"] = wire_conformance["summary"]["wire_compatible_protocol_count"]
    summary["wire_conformance_failed_count"] = wire_conformance["summary"]["failed_count"]
    return summary


def _readiness_payload(
    workflow_path: str | None,
    include_workflows: bool,
    context: dict[str, Any],
    gates: dict[str, Any],
) -> dict[str, Any]:
    matrix = context["matrix"]
    parser_summary = context["parser_summary"]
    source_summary = context["source_summary"]
    route_summary = context["route_summary"]
    protocol_summary = context["protocol_summary"]
    wire_conformance = context["wire_conformance"]
    return {
        "ok": bool(gates["internal_bridge_ready"]),
        "kind": "ProtocolReadinessReport",
        "scope": "workflow" if workflow_path else "project",
        "workflow_path": workflow_path,
        "include_workflows": include_workflows,
        "wire_compatible": bool(wire_conformance["wire_compatible"]),
        "summary": _readiness_summary(context),
        "readiness": gates,
        "parser_coverage": parser_summary,
        "manifest_sources": source_summary,
        "bridge_contract": _contract_summary(context["contract"]),
        "routes": context["routes"],
        "protocol_matrix": {
            "protocols": matrix["protocols"],
            "row_count": matrix["summary"]["row_count"],
            "capability_count": matrix["capability_count"],
            "workflow_count": matrix["workflow_count"],
            "summary": matrix["summary"],
        },
        "wire_conformance": wire_conformance,
        "selected_workflow_protocols": context["selected_workflow_protocols"],
        "protocol_gaps": protocol_summary["gaps"],
        "next_steps": _next_steps(parser_summary, source_summary, route_summary, protocol_summary),
    }


def _readiness_summary(context: dict[str, Any]) -> dict[str, Any]:
    parser_summary = context["parser_summary"]
    source_summary = context["source_summary"]
    route_summary = context["route_summary"]
    protocol_summary = context["protocol_summary"]
    return {
        "capability_count": len(context["manifests"]),
        "workflow_count": route_summary["workflow_count"],
        "routed_workflow_count": route_summary["routed_workflow_count"],
        "route_count": route_summary["route_count"],
        "portable_manifest_count": source_summary["portable_manifest_count"],
        "runtime_local_overlay_count": source_summary["runtime_local_overlay_count"],
        "verified_output_count": parser_summary["verified_output_count"],
        "unverified_output_count": parser_summary["unverified_output_count"],
        "wire_compatible_protocol_count": protocol_summary["wire_compatible_protocol_count"],
    }


def _parser_summary(manifests: list[Any]) -> dict[str, Any]:
    unverified = []
    missing_parser = []
    by_parser: dict[str, int] = {}
    for manifest in manifests:
        parser_ref = manifest.output.parser_ref or "raw.text"
        by_parser[parser_ref] = by_parser.get(parser_ref, 0) + 1
        if manifest.output.parser_ref is None:
            missing_parser.append(manifest.capability_id)
        if not manifest.output.verified:
            unverified.append(
                {
                    "capability_id": manifest.capability_id,
                    "parser_ref": parser_ref,
                    "transport": manifest.transport.kind,
                    "risk": manifest.policy.risk,
                    "source_path": str(manifest.source_path) if manifest.source_path else None,
                    "source_kind": _manifest_source_kind(manifest.source_path),
                }
            )
    return {
        "capability_count": len(manifests),
        "parser_declared_count": len(manifests) - len(missing_parser),
        "missing_parser_count": len(missing_parser),
        "verified_output_count": sum(1 for manifest in manifests if manifest.output.verified),
        "unverified_output_count": len(unverified),
        "parser_ref_count": len(by_parser),
        "by_parser_ref": dict(sorted(by_parser.items())),
        "missing_parser_capabilities": missing_parser,
        "unverified_capabilities": unverified,
    }


def _manifest_source_summary(manifests: list[Any]) -> dict[str, Any]:
    by_source_kind: dict[str, int] = {}
    runtime_local_overlay_capabilities = []
    non_portable_capabilities = []
    for manifest in manifests:
        source_kind = _manifest_source_kind(manifest.source_path)
        by_source_kind[source_kind] = by_source_kind.get(source_kind, 0) + 1
        record = {
            "capability_id": manifest.capability_id,
            "source_path": str(manifest.source_path) if manifest.source_path else None,
            "parser_ref": manifest.output.parser_ref or "raw.text",
            "verified": manifest.output.verified,
            "transport": manifest.transport.kind,
            "risk": manifest.policy.risk,
        }
        if source_kind == "runtime_local_overlay":
            runtime_local_overlay_capabilities.append(record)
        if source_kind != "portable_manifest":
            non_portable_capabilities.append({**record, "source_kind": source_kind})
    return {
        "capability_count": len(manifests),
        "portable_manifest_count": by_source_kind.get("portable_manifest", 0),
        "runtime_local_overlay_count": by_source_kind.get("runtime_local_overlay", 0),
        "in_memory_count": by_source_kind.get("in_memory", 0),
        "other_source_count": by_source_kind.get("other", 0),
        "by_source_kind": dict(sorted(by_source_kind.items())),
        "runtime_local_overlay_capabilities": runtime_local_overlay_capabilities,
        "non_portable_capabilities": non_portable_capabilities,
    }


def _manifest_source_kind(source_path: Any) -> str:
    if source_path is None:
        return "in_memory"
    parts = [part.casefold() for part in getattr(source_path, "parts", ())]
    if _is_runtime_manifest_path(parts):
        return "runtime_local_overlay"
    if _is_portable_manifest_path(parts):
        return "portable_manifest"
    return "other"


def _is_runtime_manifest_path(parts: list[str]) -> bool:
    return (len(parts) >= 2 and parts[-2:] == ["runtime", "manifests"]) or (
        "runtime" in parts and "manifests" in parts
    )


def _is_portable_manifest_path(parts: list[str]) -> bool:
    return (bool(parts) and parts[-1] == "manifests") or ("manifests" in parts and "runtime" not in parts)


def _flatten_routes(contract: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not contract:
        return []
    routes = []
    for workflow in contract.get("workflows", []):
        for route in workflow.get("routes", []):
            routes.append(
                {
                    "workflow_id": workflow.get("workflow_id"),
                    "workflow_path": workflow.get("path"),
                    "consumer_task": route.get("consumer_task"),
                    "consumer_capability": route.get("consumer_capability"),
                    "source_task": route.get("source_task"),
                    "source_capability": route.get("source_capability"),
                    "selector": route.get("selector"),
                    "route_kind": route.get("route_kind"),
                    "selector_valid": route.get("selector_valid"),
                    "source_in_needs": route.get("source_in_needs"),
                    "source_parser_ref": route.get("source_parser_ref"),
                    "source_output_verified": route.get("source_output_verified"),
                }
            )
    return routes


def _route_summary(contract: dict[str, Any] | None, routes: list[dict[str, Any]]) -> dict[str, int]:
    if not contract:
        return {
            "workflow_count": 0,
            "routed_workflow_count": 0,
            "route_count": 0,
            "payload_route_count": 0,
            "artifact_route_count": 0,
            "metadata_route_count": 0,
            "invalid_selector_count": 0,
            "unverified_source_route_count": 0,
        }
    summary = dict(contract.get("summary", {}))
    summary.setdefault("workflow_count", 0)
    summary.setdefault("routed_workflow_count", 0)
    summary.setdefault("route_count", len(routes))
    summary.setdefault("payload_route_count", 0)
    summary.setdefault("artifact_route_count", 0)
    summary.setdefault("metadata_route_count", 0)
    summary.setdefault("invalid_selector_count", 0)
    summary.setdefault("unverified_source_route_count", 0)
    return {key: int(value) for key, value in summary.items() if isinstance(value, int)}


def _protocol_summary(
    matrix: dict[str, Any],
    selected_workflow_protocols: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    if selected_workflow_protocols is not None:
        return _selected_workflow_protocol_summary(selected_workflow_protocols)
    return _project_protocol_summary(matrix)


def _selected_workflow_protocol_summary(
    selected_workflow_protocols: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    gaps = {}
    wire_compatible_count = 0
    for protocol in PROTOCOLS:
        report = selected_workflow_protocols[protocol]
        if report.get("wire_compatible"):
            wire_compatible_count += 1
        gaps[protocol] = _selected_protocol_gap(report)
    return {
        "wire_compatible_protocol_count": wire_compatible_count,
        "gaps": gaps,
    }


def _selected_protocol_gap(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": report["scope"],
        "status_counts": report["status_counts"],
        "missing": _requirements_by_status(report, "missing"),
        "partial": _requirements_by_status(report, "partial"),
        "next_steps": report["next_steps"],
    }


def _requirements_by_status(report: dict[str, Any], status: str) -> list[str]:
    return [item["requirement"] for item in report["checks"] if item["status"] == status]


def _project_protocol_summary(matrix: dict[str, Any]) -> dict[str, Any]:
    gaps = {}
    wire_compatible_count = 0
    by_protocol = matrix.get("summary", {}).get("by_protocol", {})
    for protocol in PROTOCOLS:
        report = by_protocol.get(protocol, {})
        gap = _project_protocol_gap(report)
        if _project_protocol_wire_ready(gap):
            wire_compatible_count += 1
        gaps[protocol] = gap
    return {
        "wire_compatible_protocol_count": wire_compatible_count,
        "gaps": gaps,
    }


def _project_protocol_gap(report: dict[str, Any]) -> dict[str, Any]:
    missing_count = int(report.get("missing", 0))
    partial_count = int(report.get("partial", 0))
    return {
        "scope": "project",
        "status_counts": {
            "present": int(report.get("present", 0)),
            "partial": partial_count,
            "missing": missing_count,
        },
        "missing_count": missing_count,
        "partial_count": partial_count,
        "wire_compatible_row_count": int(report.get("wire_compatible", 0)),
    }


def _project_protocol_wire_ready(gap: dict[str, Any]) -> bool:
    return (
        gap["wire_compatible_row_count"] > 0
        and gap["missing_count"] == 0
        and gap["partial_count"] == 0
    )


def _readiness_gates(
    parser_summary: dict[str, Any],
    source_summary: dict[str, Any],
    route_summary: dict[str, int],
    protocol_summary: dict[str, Any],
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    contract_ok = True if contract is None else bool(contract.get("ok"))
    routed = route_summary["route_count"] > 0
    return {
        "manifest_registry_loaded": parser_summary["capability_count"] > 0,
        "portable_manifests_present": source_summary["portable_manifest_count"] > 0,
        "runtime_local_overlay_present": source_summary["runtime_local_overlay_count"] > 0,
        "bridge_message_contract_ready": contract_ok,
        "workflow_routing_present": routed,
        "workflow_routes_valid": route_summary["invalid_selector_count"] == 0,
        "verified_parser_coverage": parser_summary["unverified_output_count"] == 0,
        "internal_bridge_ready": (
            parser_summary["capability_count"] > 0
            and contract_ok
            and route_summary["invalid_selector_count"] == 0
        ),
        "external_protocol_wire_compatible": protocol_summary["wire_compatible_protocol_count"] == len(PROTOCOLS),
        "external_protocol_boundary": "local official-shape wire conformance; third-party SDK certification remains a release gate",
    }


def _contract_summary(contract: dict[str, Any] | None) -> dict[str, Any]:
    if not contract:
        return {
            "included": False,
            "ok": None,
            "summary": {},
        }
    return {
        "included": True,
        "ok": contract.get("ok"),
        "apiVersion": contract.get("apiVersion"),
        "summary": contract.get("summary", {}),
    }


def _next_steps(
    parser_summary: dict[str, Any],
    source_summary: dict[str, Any],
    route_summary: dict[str, int],
    protocol_summary: dict[str, Any],
) -> list[str]:
    steps = []
    if source_summary["runtime_local_overlay_count"] > 0:
        steps.append("Treat runtime/manifests capabilities as local overlays; promote only portable, verified adapters into manifests/.")
    if parser_summary["unverified_output_count"] > 0:
        steps.append("Add verified parser fixtures for unverified capabilities before treating their payload routes as stable.")
    if route_summary["route_count"] == 0:
        steps.append("Add at least one workflow argsFrom route to prove CLI-to-CLI BridgeMessage handoff.")
    if route_summary["unverified_source_route_count"] > 0:
        steps.append("Verify parser output for every payload source task used by workflow argsFrom routes.")
    if protocol_summary["wire_compatible_protocol_count"] < len(PROTOCOLS):
        steps.append("Keep MCP/A2A/ACP marked wire_compatible=false until local wire conformance checks pass.")
    if not steps:
        steps.append("Run protocol smoke tests and keep this report as the adapter readiness baseline.")
    return steps
