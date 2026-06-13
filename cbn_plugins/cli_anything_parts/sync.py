"""CLI-Anything market sync and candidate helpers."""

from __future__ import annotations

from dataclasses import dataclass
import shutil
from typing import Any

from cbn_core.manifest import ManifestRegistry, validate_manifest_dict
from cbn_plugins.cli_anything_parts.lifecycle import (
    declared_requires,
    lifecycle_report,
    platform_assessment,
    requirement_assessment,
    transport_assessment,
)
from cbn_plugins.cli_anything_parts.manifest_factory import infer_market_policy
from cbn_plugins.cli_anything_parts.market import market_records_from_result, mark_capability_collisions
from cbn_plugins.cli_anything_parts.planning import safe_plugin_report
from cbn_plugins.cli_anything_parts.verification import (
    known_parser_refs,
    manifest_dict_from_path,
    policy_requires_confirmation,
)
from cbn_plugins.manager import PluginManager
from cbn_protocol.readiness import protocol_readiness_report


PLUGIN_ID = "cli-anything"


@dataclass(frozen=True)
class CandidateContext:
    harness_name: str
    capability_id: Any
    manifest_path: Any
    validation: dict[str, Any]
    requirements: dict[str, Any]
    platform: dict[str, Any]
    policy: dict[str, Any]
    transport: dict[str, Any]
    entry_point: str | None
    entrypoint_path: str | None
    manifest_imported: bool
    installed: bool
    launch_ready: bool
    gates: dict[str, bool]


@dataclass(frozen=True)
class SyncMarketReportInput:
    query: str | None
    write: bool
    limit: int
    market_count: int
    selected_count: int
    importable_count: int
    market: dict[str, Any]
    manifests: list[dict[str, Any]]
    counts: dict[str, int]


def environment_verification(root: Any) -> dict[str, Any]:
    manager = PluginManager(root=root)
    report: dict[str, Any] = {
        "preflight": safe_plugin_report(lambda: manager.preflight(PLUGIN_ID)),
        "provenance": safe_plugin_report(lambda: manager.provenance(PLUGIN_ID)),
        "update_check": safe_plugin_report(lambda: manager.update_check(PLUGIN_ID)),
    }
    preflight = report["preflight"]
    provenance = report["provenance"]
    update_check = report["update_check"]
    return {
        "ok": bool(
            preflight.get("ready")
            and provenance.get("source_trusted") is not False
            and not update_check.get("blockers")
        ),
        "preflight_ready": preflight.get("ready"),
        "source_downloaded": provenance.get("source_downloaded"),
        "source_trusted": provenance.get("source_trusted"),
        "ready_for_update": update_check.get("ready_for_update"),
        "repository": (provenance.get("repository") or {}),
        "entrypoints": provenance.get("entrypoints", []),
        "reports": report,
    }


def workflow_readiness(paths: Any, workflow_path: str) -> dict[str, Any] | None:
    path = paths.root / workflow_path
    if not path.exists():
        return None
    registry = ManifestRegistry()
    registry.load_dir(paths.manifests)
    return protocol_readiness_report(
        registry,
        workflow_path=workflow_path,
        include_workflows=True,
    )


def candidate_from_market_record(
    hub: Any,
    record: dict[str, Any],
    market_index: int,
) -> dict[str, Any]:
    harness_name = market_record_harness_name(record)
    if not harness_name:
        return missing_harness_name_candidate(record, market_index)

    context = build_candidate_context(hub, record, harness_name)
    blockers = candidate_blockers(context.gates)
    install_candidate = len(blockers) == 0
    recommended_next_action = candidate_recommended_next_action(context.gates, install_candidate)
    lifecycle = lifecycle_report(
        harness_name=harness_name,
        capability_id=context.capability_id,
        recommended_next_action=recommended_next_action,
        gates=context.gates,
        blockers=blockers,
        install_candidate=install_candidate,
    )
    return successful_candidate_report(
        market_index=market_index,
        record=record,
        context=context,
        blockers=blockers,
        install_candidate=install_candidate,
        recommended_next_action=recommended_next_action,
        lifecycle=lifecycle,
    )


def market_record_harness_name(record: dict[str, Any]) -> str:
    return str(record.get("name") or record.get("display_name") or "").strip()


def missing_harness_name_candidate(record: dict[str, Any], market_index: int) -> dict[str, Any]:
    return {
        "ok": False,
        "market_index": market_index,
        "harness_name": None,
        "capability_id": None,
        "install_candidate": False,
        "recommended_next_action": "resolve_blockers",
        "blockers": ["market record is missing name/display_name"],
        "market_record": record,
    }


def build_candidate_context(
    hub: Any,
    record: dict[str, Any],
    harness_name: str,
) -> CandidateContext:
    manifest, capability_id, manifest_path, validation = candidate_manifest_data(
        hub,
        record,
        harness_name,
    )
    requirements, platform = candidate_requirements(record)
    policy, transport = candidate_policy_transport(record, manifest)
    install_state = candidate_install_state(record, manifest_path, validation, transport)
    gates = candidate_gates(
        validation=validation,
        install_state=install_state,
        transport=transport,
        policy=policy,
        requirements=requirements,
        platform=platform,
    )
    return CandidateContext(
        harness_name=harness_name,
        capability_id=capability_id,
        manifest_path=manifest_path,
        validation=validation,
        requirements=requirements,
        platform=platform,
        policy=policy,
        transport=transport,
        entry_point=install_state["entry_point"],
        entrypoint_path=install_state["entrypoint_path"],
        manifest_imported=install_state["manifest_imported"],
        installed=install_state["installed"],
        launch_ready=install_state["launch_ready"],
        gates=gates,
    )


def candidate_requirements(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    requires = declared_requires(record, {})
    return requirement_assessment(requires), platform_assessment(record, requires)


def candidate_policy_transport(
    record: dict[str, Any],
    manifest: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = manifest["spec"]["policy"] if manifest else infer_market_policy(record)
    transport = transport_assessment(manifest) if manifest else {"ready": False}
    return policy, transport


def candidate_install_state(
    record: dict[str, Any],
    manifest_path: Any,
    validation: dict[str, Any],
    transport: dict[str, Any],
) -> dict[str, Any]:
    entry_point = str(record.get("entry_point") or "") or None
    entrypoint_path = shutil.which(entry_point) if entry_point else None
    manifest_imported = bool(manifest_path and manifest_path.exists())
    installed = entrypoint_path is not None
    launch_ready = bool(installed and manifest_imported and validation["valid"] and transport.get("ready"))
    return {
        "entry_point": entry_point,
        "entrypoint_path": entrypoint_path,
        "manifest_imported": manifest_imported,
        "installed": installed,
        "launch_ready": launch_ready,
    }


def candidate_manifest_data(
    hub: Any,
    record: dict[str, Any],
    harness_name: str,
) -> tuple[dict[str, Any] | None, str | None, Any, dict[str, Any]]:
    try:
        manifest = hub.manifest_for_harness(harness_name, market_record=record)
        capability_id = manifest["metadata"]["id"]
        manifest_path = hub.paths.manifests / f"{capability_id}.json"
        if manifest_path.exists():
            manifest = manifest_dict_from_path(manifest_path, manifest)
        validation = validate_manifest_dict(
            manifest,
            source_path=manifest_path,
            known_parser_refs=known_parser_refs(),
        )
    except (TypeError, ValueError) as exc:
        manifest = None
        capability_id = None
        manifest_path = None
        validation = {"valid": False, "errors": [str(exc)], "warnings": []}
    return manifest, capability_id, manifest_path, validation


def candidate_gates(
    *,
    validation: dict[str, Any],
    install_state: dict[str, Any],
    transport: dict[str, Any],
    policy: dict[str, Any],
    requirements: dict[str, Any],
    platform: dict[str, Any],
) -> dict[str, bool]:
    low_policy_risk = policy["risk"] in {"read", "write-workspace"} and not policy_requires_confirmation(policy)
    return {
        "manifest_valid": bool(validation["valid"]),
        "manifest_imported": bool(install_state["manifest_imported"]),
        "installed": bool(install_state["installed"]),
        "entrypoint_available": bool(install_state["installed"]),
        "runtime_transport_ready": bool(transport.get("ready")),
        "launch_ready": bool(install_state["launch_ready"]),
        "low_policy_risk": low_policy_risk,
        "external_dependency_free": bool(requirements["external_dependency_free"]),
        "platform_compatible": bool(platform["compatible"]),
    }


def candidate_blockers(gates: dict[str, bool]) -> list[str]:
    blockers = []
    if not gates["manifest_valid"]:
        blockers.append("generated manifest is invalid")
    if not gates["low_policy_risk"]:
        blockers.append("policy requires elevated confirmation")
    if not gates["external_dependency_free"]:
        blockers.append("declared requirements need external app, account, token, or service")
    if not gates["platform_compatible"]:
        blockers.append("declared platform does not match this host")
    if gates["installed"] and not gates["entrypoint_available"]:
        blockers.append("installed harness entrypoint is missing from PATH")
    return blockers


def candidate_recommended_next_action(
    gates: dict[str, bool],
    install_candidate: bool,
) -> str:
    if gates["launch_ready"]:
        return "call_capability"
    if install_candidate and gates["installed"] and not gates["manifest_imported"]:
        return "write_manifest"
    if install_candidate and gates["manifest_imported"]:
        return "install_harness"
    if install_candidate:
        return "write_manifest"
    return "resolve_blockers"


def successful_candidate_report(
    *,
    market_index: int,
    record: dict[str, Any],
    context: CandidateContext,
    blockers: list[str],
    install_candidate: bool,
    recommended_next_action: str,
    lifecycle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "market_index": market_index,
        "harness_name": context.harness_name,
        "display_name": str(record.get("display_name") or context.harness_name),
        "capability_id": context.capability_id,
        "manifest_path": str(context.manifest_path) if context.manifest_path else None,
        "install_candidate": install_candidate,
        "recommended_next_action": recommended_next_action,
        "blockers": blockers,
        "gates": context.gates,
        "local_status": candidate_local_status(context),
        "requirements": context.requirements,
        "platform": context.platform,
        "transport": context.transport,
        "policy": context.policy,
        "lifecycle": lifecycle,
        "validation": context.validation,
        "market_record": record,
        "next_commands": candidate_next_commands(context.harness_name),
    }


def candidate_local_status(context: CandidateContext) -> dict[str, Any]:
    return {
        "manifest_imported": context.manifest_imported,
        "entry_point": context.entry_point,
        "entrypoint_path": context.entrypoint_path,
        "entrypoint_available": context.installed,
        "launch_ready": context.launch_ready,
    }


def candidate_next_commands(harness_name: str) -> list[str]:
    return [
        f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
        f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
        f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
    ]


def sync_market(
    hub: Any,
    query: str | None = None,
    limit: int = 50,
    write: bool = False,
) -> dict[str, Any]:
    result = hub.search_market(query) if query else hub.list_market()
    records = market_records_from_result(result.parsed_json)
    if result.exit_code != 0:
        return failed_sync_market_report(
            query=query,
            write=write,
            result=result,
            error="CLI-Anything market command failed",
        )
    if records is None:
        return failed_sync_market_report(
            query=query,
            write=write,
            result=result,
            error="CLI-Anything market command did not return a supported JSON list shape",
        )
    bounded_limit = max(0, min(limit, 500))
    selected = records[:bounded_limit]
    manifests = sync_manifest_previews(hub, selected)
    mark_capability_collisions(manifests)
    writable = [item for item in manifests if item.get("ok")]
    if write:
        write_sync_manifests(hub, writable)
    counts = sync_manifest_counts(manifests)
    return successful_sync_market_report(SyncMarketReportInput(
        query=query,
        write=write,
        limit=bounded_limit,
        market_count=len(records),
        selected_count=len(selected),
        importable_count=len(writable),
        market=result.as_dict(),
        manifests=manifests,
        counts=counts,
    ))


def failed_sync_market_report(
    *,
    query: str | None,
    write: bool,
    result: Any,
    error: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "plugin_id": PLUGIN_ID,
        "query": query,
        "write": write,
        "error": error,
        "market": result.as_dict(),
        "records": [],
        "manifests": [],
    }


def sync_manifest_previews(hub: Any, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [sync_manifest_preview(hub, record) for record in records]


def sync_manifest_preview(hub: Any, record: dict[str, Any]) -> dict[str, Any]:
    harness_name = market_record_harness_name(record)
    if not harness_name:
        return {
            "ok": False,
            "error": "market record is missing name/display_name",
            "market_record": record,
        }
    manifest = hub.manifest_for_harness(harness_name, market_record=record)
    capability_id = manifest["metadata"]["id"]
    path = hub.paths.manifests / f"{capability_id}.json"
    validation = validate_manifest_dict(
        manifest,
        source_path=path,
        known_parser_refs=known_parser_refs(),
    )
    return {
        "ok": bool(validation["valid"]),
        "error": None if validation["valid"] else "generated manifest is invalid",
        "harness_name": harness_name,
        "capability_id": capability_id,
        "manifest_path": str(path),
        "written": None,
        "manifest": manifest,
        "validation": validation,
        "market_record": record,
    }


def write_sync_manifests(hub: Any, manifests: list[dict[str, Any]]) -> None:
    for item in manifests:
        record = item["market_record"]
        harness_name = item["harness_name"]
        written = hub.write_harness_manifest(harness_name, market_record=record)
        item["written"] = str(written)
        item["manifest_path"] = str(written)
        item["validation"] = validate_manifest_dict(
            item["manifest"],
            source_path=written,
            known_parser_refs=known_parser_refs(),
        )


def sync_manifest_counts(manifests: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "conflict_count": sum(
            1
            for item in manifests
            if item.get("error") == "duplicate capability_id generated from market records"
        ),
        "invalid_count": sum(
            1 for item in manifests if item.get("error") == "generated manifest is invalid"
        ),
        "failed_count": sum(1 for item in manifests if not item.get("ok")),
    }


def successful_sync_market_report(report: SyncMarketReportInput) -> dict[str, Any]:
    return {
        "ok": report.counts["failed_count"] == 0,
        "plugin_id": PLUGIN_ID,
        "query": report.query,
        "write": report.write,
        "limit": report.limit,
        "market_count": report.market_count,
        "selected_count": report.selected_count,
        "importable_count": report.importable_count,
        "conflict_count": report.counts["conflict_count"],
        "invalid_count": report.counts["invalid_count"],
        "failed_count": report.counts["failed_count"],
        "market": report.market,
        "manifests": report.manifests,
        "next_commands": [
            "python -m cbn registry search cli-anything",
            "python -m cbn protocol export all --capability-id <capability_id>",
            "python -m cbn plugin harness cli-anything install <harness> --yes",
        ],
    }
