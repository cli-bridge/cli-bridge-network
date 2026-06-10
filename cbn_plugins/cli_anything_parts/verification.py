"""Verification report helpers for CLI-Anything harnesses."""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
        {
            "id": "evaluate_market_and_policy",
            "status": "completed" if evaluation.get("ok") else "blocked",
            "command": f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
        },
        {
            "id": "probe_dependencies",
            "status": "completed" if readiness.get("probe_blocker_count") == 0 else "blocked",
            "command": f"python -m cbn plugin probe-harness cli-anything {harness_name}",
        },
        {
            "id": "write_manifest",
            "status": "completed" if registry_status.get("manifest_imported") else "ready",
            "command": f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
        },
        {
            "id": "validate_registry",
            "status": "completed" if gates.get("manifest_valid") else "blocked",
            "command": "python -m cbn registry validate manifests",
        },
        {
            "id": "install_harness",
            "status": "completed" if gates.get("installed") else "pending",
            "command": f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
        },
        {
            "id": "dry_run_call",
            "status": "ready" if dry_run_ready else "blocked",
            "command": f"python -m cbn call {capability_id} --dry-run",
        },
        {
            "id": "verify_parser_contract",
            "status": "completed" if parser_contract.get("verified") else "pending",
            "command": f"python -m cbn parser fixtures --parser-ref {parser_contract.get('parser_ref')}",
        },
        {
            "id": "check_protocol_exports",
            "status": "completed",
            "command": f"python -m cbn protocol check all --capability-id {capability_id}",
            "source": registry_status.get("protocol_check_source"),
            "protocol_status_counts": {
                protocol: report.get("status_counts", {})
                for protocol, report in protocol_checks.items()
            },
        },
        {
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
        },
    ]


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
