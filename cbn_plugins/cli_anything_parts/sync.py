"""CLI-Anything market sync and candidate helpers."""

from __future__ import annotations

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
    harness_name = str(record.get("name") or record.get("display_name") or "").strip()
    if not harness_name:
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
    requires = declared_requires(record, {})
    requirements = requirement_assessment(requires)
    platform = platform_assessment(record, requires)
    policy = manifest["spec"]["policy"] if manifest else infer_market_policy(record)
    transport = transport_assessment(manifest) if manifest else {"ready": False}
    entry_point = str(record.get("entry_point") or "") or None
    entrypoint_path = shutil.which(entry_point) if entry_point else None
    manifest_imported = bool(manifest_path and manifest_path.exists())
    installed = entrypoint_path is not None
    launch_ready = bool(installed and manifest_imported and validation["valid"] and transport.get("ready"))
    low_policy_risk = policy["risk"] in {"read", "write-workspace"} and not policy_requires_confirmation(policy)
    gates = {
        "manifest_valid": bool(validation["valid"]),
        "manifest_imported": manifest_imported,
        "installed": installed,
        "entrypoint_available": installed,
        "runtime_transport_ready": bool(transport.get("ready")),
        "launch_ready": launch_ready,
        "low_policy_risk": low_policy_risk,
        "external_dependency_free": bool(requirements["external_dependency_free"]),
        "platform_compatible": bool(platform["compatible"]),
    }
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
    install_candidate = len(blockers) == 0
    if gates["launch_ready"]:
        recommended_next_action = "call_capability"
    elif install_candidate and gates["installed"] and not gates["manifest_imported"]:
        recommended_next_action = "write_manifest"
    elif install_candidate and gates["manifest_imported"]:
        recommended_next_action = "install_harness"
    elif install_candidate:
        recommended_next_action = "write_manifest"
    else:
        recommended_next_action = "resolve_blockers"
    lifecycle = lifecycle_report(
        harness_name=harness_name,
        capability_id=capability_id,
        recommended_next_action=recommended_next_action,
        gates=gates,
        blockers=blockers,
        install_candidate=install_candidate,
    )
    return {
        "ok": True,
        "market_index": market_index,
        "harness_name": harness_name,
        "display_name": str(record.get("display_name") or harness_name),
        "capability_id": capability_id,
        "manifest_path": str(manifest_path) if manifest_path else None,
        "install_candidate": install_candidate,
        "recommended_next_action": recommended_next_action,
        "blockers": blockers,
        "gates": gates,
        "local_status": {
            "manifest_imported": manifest_imported,
            "entry_point": entry_point,
            "entrypoint_path": entrypoint_path,
            "entrypoint_available": installed,
            "launch_ready": launch_ready,
        },
        "requirements": requirements,
        "platform": platform,
        "transport": transport,
        "policy": policy,
        "lifecycle": lifecycle,
        "validation": validation,
        "market_record": record,
        "next_commands": [
            f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
            f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
            f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
        ],
    }


def sync_market(
    hub: Any,
    query: str | None = None,
    limit: int = 50,
    write: bool = False,
) -> dict[str, Any]:
    result = hub.search_market(query) if query else hub.list_market()
    records = market_records_from_result(result.parsed_json)
    if result.exit_code != 0:
        return {
            "ok": False,
            "plugin_id": PLUGIN_ID,
            "query": query,
            "write": write,
            "error": "CLI-Anything market command failed",
            "market": result.as_dict(),
            "records": [],
            "manifests": [],
        }
    if records is None:
        return {
            "ok": False,
            "plugin_id": PLUGIN_ID,
            "query": query,
            "write": write,
            "error": "CLI-Anything market command did not return a supported JSON list shape",
            "market": result.as_dict(),
            "records": [],
            "manifests": [],
        }
    bounded_limit = max(0, min(limit, 500))
    selected = records[:bounded_limit]
    manifests = []
    for record in selected:
        harness_name = str(record.get("name") or record.get("display_name") or "").strip()
        if not harness_name:
            manifests.append(
                {
                    "ok": False,
                    "error": "market record is missing name/display_name",
                    "market_record": record,
                }
            )
            continue
        manifest = hub.manifest_for_harness(harness_name, market_record=record)
        capability_id = manifest["metadata"]["id"]
        path = hub.paths.manifests / f"{capability_id}.json"
        validation = validate_manifest_dict(
            manifest,
            source_path=path,
            known_parser_refs=known_parser_refs(),
        )
        manifests.append(
            {
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
        )
    mark_capability_collisions(manifests)
    writable = [item for item in manifests if item.get("ok")]
    if write:
        for item in writable:
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
    conflict_count = sum(
        1
        for item in manifests
        if item.get("error") == "duplicate capability_id generated from market records"
    )
    invalid_count = sum(1 for item in manifests if item.get("error") == "generated manifest is invalid")
    failed_count = sum(1 for item in manifests if not item.get("ok"))
    return {
        "ok": failed_count == 0,
        "plugin_id": PLUGIN_ID,
        "query": query,
        "write": write,
        "limit": bounded_limit,
        "market_count": len(records),
        "selected_count": len(selected),
        "importable_count": len(writable),
        "conflict_count": conflict_count,
        "invalid_count": invalid_count,
        "failed_count": failed_count,
        "market": result.as_dict(),
        "manifests": manifests,
        "next_commands": [
            "python -m cbn registry search cli-anything",
            "python -m cbn protocol export all --capability-id <capability_id>",
            "python -m cbn plugin harness cli-anything install <harness> --yes",
        ],
    }
