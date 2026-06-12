"""Verification report helpers for CLI-Anything harnesses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cbn_core.manifest import CapabilityManifest, ManifestRegistry
from cbn_parsers.fixtures import run_parser_fixtures
from cbn_parsers.registry import ParserRegistry
from cbn_protocol.compatibility import check_all_protocols
from cbn_protocol.smoke_suite import protocol_smoke_suite
from cbn_workflow.catalog import list_workflows


PLUGIN_ID = "cli-anything"


def verify_harness(
    hub: Any,
    harness_name: str,
    title: str | None = None,
    from_market: bool = True,
    include_workflows: bool = True,
    run_smoke_suite: bool = False,
    smoke_extra_args: tuple[str, ...] = (),
) -> dict[str, Any]:
    probe = hub.probe_harness(
        harness_name,
        title=title,
        from_market=from_market,
    )
    if not probe["ok"]:
        return failed_verify_harness_report(
            harness_name=harness_name,
            from_market=from_market,
            include_workflows=include_workflows,
            run_smoke_suite=run_smoke_suite,
            probe=probe,
        )

    evaluation = probe["evaluation"]
    adaptation = evaluation["adaptation"]
    capability_id = evaluation["capability_id"]
    registry_context = verification_registry_context(
        hub,
        capability_id=capability_id,
        adaptation=adaptation,
    )
    readiness = readiness_from_probe(probe)
    registry_status = registry_context["registry_status"]
    parser_contract = parser_contract_report_from_registry(registry_context["effective_manifest"])
    verification_blocker_list = verification_blockers(evaluation, readiness, registry_status)
    workflow_matches = (
        workflow_matches_for_capability(registry_context["registry"], capability_id)
        if include_workflows
        else []
    )
    smoke_suite = harness_protocol_smoke_suite(
        registry=registry_context["registry"],
        capability_id=capability_id,
        include_workflows=include_workflows,
        extra_args=smoke_extra_args,
        run=run_smoke_suite,
    )
    verification_blocker_list = verification_blockers_with_smoke(
        verification_blocker_list,
        smoke_suite,
    )
    return successful_verify_harness_report(
        harness_name=harness_name,
        from_market=from_market,
        include_workflows=include_workflows,
        run_smoke_suite=run_smoke_suite,
        capability_id=capability_id,
        evaluation=evaluation,
        readiness=readiness,
        registry_status=registry_status,
        parser_contract=parser_contract,
        protocol_checks=registry_context["protocol_checks"],
        smoke_suite=smoke_suite,
        workflow_matches=workflow_matches,
        verification_blocker_list=verification_blocker_list,
        probe=probe,
    )


def failed_verify_harness_report(
    *,
    harness_name: str,
    from_market: bool,
    include_workflows: bool,
    run_smoke_suite: bool,
    probe: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": False,
        "plugin_id": PLUGIN_ID,
        "harness_name": harness_name,
        "from_market": from_market,
        "include_workflows": include_workflows,
        "run_smoke_suite": run_smoke_suite,
        "error": probe["error"],
        "probe": probe,
    }


def verification_registry_context(
    hub: Any,
    *,
    capability_id: str,
    adaptation: dict[str, Any],
) -> dict[str, Any]:
    manifest = adaptation["manifest"]
    registry = ManifestRegistry()
    registry.load_dir(hub.paths.manifests)
    registry.load_dir(hub.paths.local_manifests, replace=True)
    imported_manifest = registry.get(capability_id)
    effective_manifest = effective_manifest_dict(imported_manifest, manifest)
    protocol_registry = protocol_registry_for_manifest(
        registry=registry,
        imported_manifest=imported_manifest,
        manifest=manifest,
        source_path=Path(adaptation["manifest_path"]),
    )
    return {
        "registry": registry,
        "imported_manifest": imported_manifest,
        "effective_manifest": effective_manifest,
        "registry_status": registry_status_for_manifest(
            imported_manifest=imported_manifest,
            effective_manifest=effective_manifest,
            preview_manifest_path=adaptation["manifest_path"],
            local_manifest_dir=hub.paths.local_manifests,
        ),
        "protocol_checks": check_all_protocols(
            protocol_registry,
            capability_id=capability_id,
        )["checks"],
    }


def protocol_registry_for_manifest(
    *,
    registry: ManifestRegistry,
    imported_manifest: Any | None,
    manifest: dict[str, Any],
    source_path: Path,
) -> ManifestRegistry:
    if imported_manifest:
        return registry
    protocol_registry = ManifestRegistry()
    protocol_registry.register(CapabilityManifest.from_dict(manifest, source_path=source_path))
    return protocol_registry


def registry_status_for_manifest(
    *,
    imported_manifest: Any | None,
    effective_manifest: dict[str, Any],
    preview_manifest_path: str,
    local_manifest_dir: Path,
) -> dict[str, Any]:
    return {
        "manifest_imported": imported_manifest is not None,
        "manifest_path": str(imported_manifest.source_path) if imported_manifest else preview_manifest_path,
        "protocol_check_source": registry_source_for_manifest(
            imported_manifest,
            local_manifest_dir=local_manifest_dir,
        )
        if imported_manifest
        else "generated_preview",
        "entrypoint_repair_active": manifest_has_entrypoint_repair(effective_manifest),
    }


def readiness_from_probe(probe: dict[str, Any]) -> dict[str, Any]:
    return {
        "ready": probe["ready"],
        "probe_blocker_count": probe["probe_blocker_count"],
        "probes": probe["probes"],
    }


def verification_blockers_with_smoke(
    verification_blocker_list: list[str],
    smoke_suite: dict[str, Any],
) -> list[str]:
    if smoke_suite.get("run") and not smoke_suite.get("ok"):
        return sorted(set([*verification_blocker_list, "protocol smoke suite failed"]))
    return verification_blocker_list


def successful_verify_harness_report(
    *,
    harness_name: str,
    from_market: bool,
    include_workflows: bool,
    run_smoke_suite: bool,
    capability_id: str,
    evaluation: dict[str, Any],
    readiness: dict[str, Any],
    registry_status: dict[str, Any],
    parser_contract: dict[str, Any],
    protocol_checks: dict[str, dict[str, Any]],
    smoke_suite: dict[str, Any],
    workflow_matches: list[dict[str, Any]],
    verification_blocker_list: list[str],
    probe: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "harness_name": harness_name,
        "from_market": from_market,
        "include_workflows": include_workflows,
        "run_smoke_suite": run_smoke_suite,
        "capability_id": capability_id,
        "ready_for_manifest_write": bool(evaluation["gates"]["manifest_valid"] and not evaluation["blockers"]),
        "ready_for_runtime_verification": len(verification_blocker_list) == 0,
        "verification_blockers": verification_blocker_list,
        "readiness": readiness,
        "registry": registry_status,
        "parser_contract": parser_contract,
        "protocols": protocol_verification_summary(protocol_checks),
        "protocol_smoke_suite": smoke_suite,
        "workflow_matches": workflow_matches,
        "verification_stages": verification_stages(
            harness_name=harness_name,
            capability_id=capability_id,
            evaluation=evaluation,
            readiness=readiness,
            registry_status=registry_status,
            parser_contract=parser_contract,
            protocol_checks=protocol_checks,
            smoke_suite=smoke_suite,
        ),
        "probe": probe,
        "evaluation": evaluation,
        "next_commands": [
            f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
            f"python -m cbn plugin probe-harness cli-anything {harness_name}",
            f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
            "python -m cbn registry validate manifests",
            f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
            f"python -m cbn call {capability_id} --dry-run",
            f"python -m cbn protocol check all --capability-id {capability_id}",
            smoke_suite["command"],
            f"python -m cbn mcp smoke --capability-id {capability_id}",
            f"python -m cbn a2a smoke --capability-id {capability_id}",
            f"python -m cbn acp smoke --capability-id {capability_id}",
        ],
    }


def parser_contract_report(
    manifest: dict[str, Any],
    known_parser_refs: set[str],
) -> dict[str, Any]:
    output = manifest.get("spec", {}).get("output", {})
    if not isinstance(output, dict):
        output = {}
    parser_ref = output.get("parserRef") or "raw.text"
    known = parser_ref in known_parser_refs
    verified = bool(output.get("verified", False))
    if verified and known:
        status = "verified"
    elif known:
        status = "known_unverified"
    else:
        status = "unknown_parser"
    return {
        "parser_ref": parser_ref,
        "known": known,
        "verified": verified,
        "status": status,
        "next_step": (
            "Add harness-specific parser fixtures and set spec.output.verified=true."
            if not verified
            else "Keep parser fixtures in the release gate."
        ),
    }


def known_parser_refs() -> set[str]:
    return {item["parser_ref"] for item in ParserRegistry.builtins().list()}


def parser_contract_report_from_registry(manifest: dict[str, Any]) -> dict[str, Any]:
    return parser_contract_report(manifest, known_parser_refs())


def manifest_dict_from_path(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def effective_manifest_dict(
    imported_manifest: Any | None,
    preview_manifest: dict[str, Any],
) -> dict[str, Any]:
    if imported_manifest is None or getattr(imported_manifest, "source_path", None) is None:
        return preview_manifest
    return manifest_dict_from_path(imported_manifest.source_path, preview_manifest)


def load_manifest_registry(path: Path) -> ManifestRegistry:
    registry = ManifestRegistry()
    registry.load_dir(path)
    return registry


def protocol_verification_summary(protocol_checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        protocol: {
            "scope": report["scope"],
            "wire_compatible": report["wire_compatible"],
            "status_counts": report["status_counts"],
            "missing": [
                item["requirement"]
                for item in report["checks"]
                if item["status"] == "missing"
            ],
            "partial": [
                item["requirement"]
                for item in report["checks"]
                if item["status"] == "partial"
            ],
            "next_steps": report["next_steps"],
        }
        for protocol, report in protocol_checks.items()
    }


def verification_blockers(
    evaluation: dict[str, Any],
    readiness: dict[str, Any],
    registry_status: dict[str, Any],
) -> list[str]:
    blockers = list(evaluation.get("blockers", []))
    entrypoint_repair_active = bool(registry_status.get("entrypoint_repair_active"))
    if entrypoint_repair_active:
        blockers = [
            blocker
            for blocker in blockers
            if blocker != "installed harness entrypoint is missing from PATH"
        ]
    if readiness.get("probe_blocker_count", 0) > 0:
        blockers.append("dependency probes have blocker-level failures")
    if not registry_status.get("manifest_imported"):
        blockers.append("manifest is not imported into manifests/")
    gates = evaluation.get("gates", {})
    if not gates.get("installed"):
        blockers.append("harness is not installed")
    if not gates.get("runtime_transport_ready", True):
        blockers.append("runtime transport is not ready")
    if not gates.get("launch_ready") and not entrypoint_repair_active:
        blockers.append("harness launch is not ready")
    return sorted(set(blockers))


def manifest_has_entrypoint_repair(manifest: dict[str, Any]) -> bool:
    annotations = manifest.get("metadata", {}).get("annotations", {})
    if not isinstance(annotations, dict):
        return False
    return annotations.get("cbn.repair.kind") == "cli-anything-entrypoint-wrapper"


def registry_source_for_manifest(
    manifest: Any | None,
    *,
    local_manifest_dir: Path,
) -> str:
    if manifest is None or getattr(manifest, "source_path", None) is None:
        return "generated_preview"
    try:
        manifest.source_path.resolve().relative_to(local_manifest_dir.resolve())
        return "runtime_local_overlay"
    except ValueError:
        return "current_registry"


def workflow_matches_for_capability(
    registry: Any,
    capability_id: str,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for workflow in list_workflows(registry=registry):
        tasks = workflow.get("tasks") if isinstance(workflow.get("tasks"), list) else []
        matched_tasks = [
            {
                "id": task.get("id"),
                "uses": task.get("uses"),
                "capability": task.get("capability"),
            }
            for task in tasks
            if isinstance(task, dict) and task.get("uses") == capability_id
        ]
        if not matched_tasks:
            continue
        matches.append(
            {
                "workflow_id": workflow.get("workflow_id"),
                "title": workflow.get("title"),
                "path": workflow.get("path"),
                "valid": workflow.get("valid"),
                "matched_tasks": matched_tasks,
            }
        )
    return matches


def verification_stages(
    harness_name: str,
    capability_id: str,
    evaluation: dict[str, Any],
    readiness: dict[str, Any],
    registry_status: dict[str, Any],
    parser_contract: dict[str, Any],
    protocol_checks: dict[str, dict[str, Any]],
    smoke_suite: dict[str, Any],
) -> list[dict[str, Any]]:
    gates = evaluation.get("gates", {})
    dry_run_ready = bool(registry_status.get("manifest_imported"))
    return [
        verify_stage_evaluation(harness_name, evaluation),
        verify_stage_probe(harness_name, readiness),
        verify_stage_write_manifest(harness_name, registry_status),
        verify_stage_registry_validation(gates),
        verify_stage_install(harness_name, gates),
        verify_stage_dry_run(capability_id, dry_run_ready),
        verify_stage_parser_contract(parser_contract),
        verify_stage_protocol_exports(capability_id, registry_status, protocol_checks),
        verify_stage_protocol_smoke(capability_id, smoke_suite, gates),
    ]


def verify_stage_evaluation(harness_name: str, evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "evaluate_market_and_policy",
        "status": "completed" if evaluation.get("ok") else "blocked",
        "command": f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
    }


def verify_stage_probe(harness_name: str, readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "probe_dependencies",
        "status": "completed" if readiness.get("probe_blocker_count") == 0 else "blocked",
        "command": f"python -m cbn plugin probe-harness cli-anything {harness_name}",
    }


def verify_stage_write_manifest(harness_name: str, registry_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "write_manifest",
        "status": "completed" if registry_status.get("manifest_imported") else "ready",
        "command": f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
    }


def verify_stage_registry_validation(gates: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "validate_registry",
        "status": "completed" if gates.get("manifest_valid") else "blocked",
        "command": "python -m cbn registry validate manifests",
    }


def verify_stage_install(harness_name: str, gates: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "install_harness",
        "status": "completed" if gates.get("installed") else "pending",
        "command": f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
    }


def verify_stage_dry_run(capability_id: str, dry_run_ready: bool) -> dict[str, Any]:
    return {
        "id": "dry_run_call",
        "status": "ready" if dry_run_ready else "blocked",
        "command": f"python -m cbn call {capability_id} --dry-run",
    }


def verify_stage_parser_contract(parser_contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "verify_parser_contract",
        "status": "completed" if parser_contract.get("verified") else "pending",
        "command": f"python -m cbn parser fixtures --parser-ref {parser_contract.get('parser_ref')}",
    }


def verify_stage_protocol_exports(
    capability_id: str,
    registry_status: dict[str, Any],
    protocol_checks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": "check_protocol_exports",
        "status": "completed",
        "command": f"python -m cbn protocol check all --capability-id {capability_id}",
        "source": registry_status.get("protocol_check_source"),
        "protocol_status_counts": {
            protocol: report.get("status_counts", {})
            for protocol, report in protocol_checks.items()
        },
    }


def verify_stage_protocol_smoke(
    capability_id: str,
    smoke_suite: dict[str, Any],
    gates: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": "smoke_protocol_facades",
        "status": smoke_suite_stage_status(smoke_suite, gates),
        "command": smoke_suite.get("command"),
        "run": bool(smoke_suite.get("run")),
        "ok": smoke_suite.get("ok"),
        "summary": smoke_suite.get("summary"),
        "commands": [
            f"python -m cbn mcp smoke --capability-id {capability_id}",
            f"python -m cbn a2a smoke --capability-id {capability_id}",
            f"python -m cbn acp smoke --capability-id {capability_id}",
        ],
    }


def parser_fixture_gate(report: dict[str, Any], capability_id: str) -> dict[str, Any]:
    reports = report.get("reports") if isinstance(report.get("reports"), list) else []
    matching_reports = [
        item
        for item in reports
        if isinstance(item, dict)
        and capability_id in (item.get("verified_capabilities") or [])
    ]
    return {
        "ok": bool(report.get("ok")) and report.get("fixture_count", 0) > 0,
        "parser_ref": report.get("parser_ref"),
        "fixture_count": report.get("fixture_count", 0),
        "case_count": report.get("case_count", 0),
        "failed_case_count": report.get("failed_case_count", 0),
        "capability_verified": bool(matching_reports),
        "matching_fixture_ids": [
            item.get("fixture_id")
            for item in matching_reports
            if item.get("fixture_id") is not None
        ],
        "verified_capabilities": sorted(
            {
                str(capability)
                for item in reports
                if isinstance(item, dict)
                for capability in (item.get("verified_capabilities") or [])
            }
        ),
        "report": report,
    }


def mark_repaired_manifest_verified_from_fixtures(
    *,
    manifest: dict[str, Any],
    capability_id: str,
    fixture_dir: Path,
    root: Path,
    smoke_ok: bool,
) -> dict[str, Any]:
    output = manifest.setdefault("spec", {}).setdefault("output", {})
    if not isinstance(output, dict):
        return {
            "ok": False,
            "parser_ref": None,
            "capability_verified": False,
            "marked_verified": False,
            "error": "manifest spec.output is not an object",
        }
    parser_ref = str(output.get("parserRef") or "raw.text")
    try:
        fixture_report = run_parser_fixtures(
            path=fixture_dir,
            parser_ref=parser_ref,
            registry=ParserRegistry.builtins(),
        )
    except Exception as exc:
        return {
            "ok": False,
            "parser_ref": parser_ref,
            "capability_verified": False,
            "marked_verified": False,
            "error": str(exc),
        }
    gate = parser_fixture_gate(fixture_report, capability_id)
    gate["marked_verified"] = False
    if smoke_ok and gate.get("ok") and gate.get("capability_verified"):
        output["verified"] = True
        annotations = manifest.setdefault("metadata", {}).setdefault("annotations", {})
        matching_paths = matching_parser_fixture_paths(fixture_report, capability_id, root)
        if matching_paths:
            annotations["cbn.parser_fixture"] = matching_paths[0]
        annotations["cbn.parser_fixture_verified_capability"] = capability_id
        gate["marked_verified"] = True
    return gate


def harness_protocol_smoke_suite(
    registry: Any,
    capability_id: str,
    include_workflows: bool,
    extra_args: tuple[str, ...],
    run: bool,
) -> dict[str, Any]:
    workflow_paths: tuple[str, ...] = ("workflows/example.json",) if include_workflows else ()
    command = protocol_smoke_suite_command(capability_id, extra_args, workflow_paths)
    payload: dict[str, Any] = {
        "run": run,
        "ok": None,
        "command": command,
        "capability_id": capability_id,
        "workflow_paths": list(workflow_paths),
        "extra_args": list(extra_args),
        "wire_compatible": False,
        "summary": None,
        "report": None,
        "error": None,
    }
    if not run:
        payload["status"] = "not_run"
        return payload
    try:
        report = protocol_smoke_suite(
            registry,
            capability_ids=(capability_id,),
            workflow_paths=workflow_paths,
            extra_args=extra_args,
            workflow_dry_run=True,
        )
    except Exception as exc:
        payload.update({"status": "failed", "ok": False, "error": str(exc)})
        return payload
    payload.update(
        {
            "status": "completed" if report.get("ok") else "failed",
            "ok": bool(report.get("ok")),
            "wire_compatible": bool(report.get("wire_compatible")),
            "summary": report.get("summary"),
            "readiness": report.get("readiness"),
            "bridge_contract": report.get("bridge_contract"),
            "failures": report.get("failures", []),
            "report": report,
        }
    )
    return payload


def matching_parser_fixture_paths(
    fixture_report: dict[str, Any],
    capability_id: str,
    root: Path,
) -> list[str]:
    paths = []
    for item in fixture_report.get("reports") or []:
        if not isinstance(item, dict):
            continue
        if capability_id not in (item.get("verified_capabilities") or []):
            continue
        source_path = item.get("source_path")
        if not isinstance(source_path, str) or not source_path:
            continue
        path = Path(source_path)
        try:
            path = path.relative_to(root)
        except ValueError:
            pass
        paths.append(path.as_posix())
    return paths


def protocol_smoke_suite_command(
    capability_id: str,
    extra_args: tuple[str, ...],
    workflow_paths: tuple[str, ...],
) -> str:
    parts = [
        "python",
        "-m",
        "cbn",
        "protocol",
        "smoke-suite",
        "--capability-id",
        capability_id,
    ]
    for extra_arg in extra_args:
        parts.append(f"--extra-arg={extra_arg}")
    for workflow_path in workflow_paths:
        parts.extend(["--workflow-path", workflow_path, "--workflow-dry-run"])
    return " ".join(parts)


def smoke_suite_stage_status(smoke_suite: dict[str, Any], gates: dict[str, Any]) -> str:
    if smoke_suite.get("run"):
        return "completed" if smoke_suite.get("ok") else "failed"
    return "ready" if gates.get("launch_ready") else "blocked"


def policy_requires_confirmation(policy: dict[str, Any]) -> bool:
    return bool(policy.get("requiresConfirmation", policy.get("requires_confirmation", False)))
