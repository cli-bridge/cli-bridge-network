"""Evaluation and preparation orchestration for CLI-Anything harnesses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_core.manifest import validate_manifest_dict
from cbn_plugins.cli_anything_parts.lifecycle import (
    declared_requires,
    dependency_probes,
    lifecycle_report,
    platform_assessment,
    readiness_from_evaluation,
    readiness_summary,
    requirement_assessment,
    transport_assessment,
)
from cbn_plugins.cli_anything_parts.verification import (
    known_parser_refs,
    manifest_dict_from_path,
)


PLUGIN_ID = "cli-anything"


def harness_operation_gate(
    hub: Any,
    action: str,
    harness_name: str,
    from_market: bool = True,
) -> dict[str, Any]:
    if action not in {"install", "update"}:
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "action": action,
            "harness_name": harness_name,
            "gated": False,
            "blockers": [],
        }
    evaluation = evaluate_harness(hub, harness_name, from_market=from_market)
    if not evaluation["ok"]:
        return {
            "ok": False,
            "plugin_id": PLUGIN_ID,
            "action": action,
            "harness_name": harness_name,
            "gated": True,
            "blockers": [evaluation.get("error", "harness evaluation failed")],
            "evaluation": evaluation,
            "override_flag": "--allow-blocked",
        }
    gates = evaluation["gates"]
    blockers = list(evaluation["blockers"])
    readiness = readiness_from_evaluation(evaluation)
    for probe in readiness["probes"]:
        if (
            probe["status"] in {"missing", "unavailable", "manual_required"}
            and probe["severity"] == "blocker"
        ):
            blockers.append(f"dependency probe failed: {probe['id']}")
    if action == "install" and not (evaluation["install_candidate"] or gates["installed"]):
        blockers.append("harness is not an install candidate")
    if action == "update" and not gates["installed"]:
        blockers.append("harness is not installed")
    return {
        "ok": len(blockers) == 0,
        "plugin_id": PLUGIN_ID,
        "action": action,
        "harness_name": harness_name,
        "gated": True,
        "from_market": from_market,
        "blockers": blockers,
        "evaluation": evaluation,
        "readiness": readiness,
        "override_flag": "--allow-blocked",
    }


def adapt_harness(
    hub: Any,
    harness_name: str,
    title: str | None = None,
    from_market: bool = False,
    write: bool = False,
) -> dict[str, Any]:
    market_record = hub.market_record_for_harness(harness_name) if from_market else None
    if from_market and market_record is None:
        return {
            "ok": False,
            "error": "CLI-Anything market record not found",
            "plugin_id": PLUGIN_ID,
            "harness_name": harness_name,
            "from_market": True,
        }
    manifest = hub.manifest_for_harness(harness_name, title=title, market_record=market_record)
    capability_id = manifest["metadata"]["id"]
    manifest_path = hub.paths.manifests / f"{capability_id}.json"
    written = None
    if write:
        written = hub.write_harness_manifest(harness_name, title=title, market_record=market_record)
        manifest_path = written
        manifest = manifest_dict_from_path(manifest_path, manifest)
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "harness_name": harness_name,
        "from_market": from_market,
        "market_record_available": market_record is not None,
        "write": write,
        "written": str(written) if written else None,
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "validation": validate_manifest_dict(
            manifest,
            source_path=manifest_path,
            known_parser_refs=known_parser_refs(),
        ),
        "status": hub.harness_status(harness_name, from_market=from_market),
        "next_commands": [
            f"python -m cbn plugin harness cli-anything status {harness_name} --from-market",
            f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
            f"python -m cbn call {capability_id} --dry-run",
            f"python -m cbn protocol export all --capability-id {capability_id}",
        ],
    }


def prepare_harness(
    hub: Any,
    harness_name: str,
    title: str | None = None,
    from_market: bool = False,
) -> dict[str, Any]:
    adaptation = adapt_harness(hub, harness_name, title=title, from_market=from_market, write=False)
    if not adaptation["ok"]:
        return _adaptation_error_result(harness_name, from_market, adaptation)
    status = adaptation["status"]
    validation = adaptation["validation"]
    gates = _preparation_gates(status, adaptation, validation, from_market)
    capability_id = adaptation["manifest"]["metadata"]["id"]
    return {
        "ok": gates["market_required_satisfied"] and gates["manifest_valid"],
        "plugin_id": PLUGIN_ID,
        "harness_name": harness_name,
        "from_market": from_market,
        "capability_id": capability_id,
        "gates": gates,
        "status": status,
        "validation": validation,
        "adaptation": adaptation,
        "plans": {
            "install": hub.harness_plan("install", harness_name).as_dict(),
            "update": hub.harness_plan("update", harness_name).as_dict(),
            "launch": hub.harness_plan("launch", harness_name).as_dict(),
        },
        "next_commands": [
            f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
            f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
            "python -m cbn registry validate manifests",
            f"python -m cbn call {capability_id} --dry-run",
        ],
    }


def evaluate_harness(
    hub: Any,
    harness_name: str,
    title: str | None = None,
    from_market: bool = True,
) -> dict[str, Any]:
    adaptation = adapt_harness(hub, harness_name, title=title, from_market=from_market, write=False)
    if not adaptation["ok"]:
        return _adaptation_error_result(harness_name, from_market, adaptation)

    status = adaptation["status"]
    manifest, validation, adaptation = _imported_manifest_state(adaptation)
    market_record = status.get("market_record") if isinstance(status.get("market_record"), dict) else None
    requires = declared_requires(market_record, status)
    requirements = requirement_assessment(requires)
    platform = platform_assessment(market_record, requires)
    policy = manifest["spec"]["policy"]
    transport = transport_assessment(manifest)
    gates = _evaluation_gates(
        status=status,
        adaptation=adaptation,
        validation=validation,
        transport=transport,
        policy=policy,
        requirements=requirements,
        platform=platform,
        from_market=from_market,
    )
    blockers = _evaluation_blockers(gates)
    install_candidate = _install_candidate(gates)
    recommended_next_action = _recommended_next_action(gates, install_candidate)
    capability_id = manifest["metadata"]["id"]
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "harness_name": harness_name,
        "from_market": from_market,
        "capability_id": capability_id,
        "install_candidate": install_candidate,
        "recommended_next_action": recommended_next_action,
        "blockers": blockers,
        "gates": gates,
        "requirements": requirements,
        "platform": platform,
        "transport": transport,
        "policy": policy,
        "lifecycle": lifecycle_report(
            harness_name=harness_name,
            capability_id=capability_id,
            recommended_next_action=recommended_next_action,
            gates=gates,
            blockers=blockers,
            install_candidate=install_candidate,
        ),
        "status": status,
        "validation": validation,
        "adaptation": adaptation,
        "plans": {
            "install": hub.harness_plan("install", harness_name).as_dict(),
            "launch": hub.harness_plan("launch", harness_name).as_dict(),
        },
        "next_commands": [
            f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
            f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
            "python -m cbn registry validate manifests",
            f"python -m cbn call {capability_id} --dry-run",
        ],
    }


def probe_harness(
    hub: Any,
    harness_name: str,
    title: str | None = None,
    from_market: bool = True,
) -> dict[str, Any]:
    evaluation = evaluate_harness(hub, harness_name, title=title, from_market=from_market)
    if not evaluation["ok"]:
        return {
            "ok": False,
            "plugin_id": PLUGIN_ID,
            "harness_name": harness_name,
            "from_market": from_market,
            "error": evaluation["error"],
            "evaluation": evaluation,
            "probes": [],
        }
    status = evaluation["status"]
    market_record = status.get("market_record") if isinstance(status.get("market_record"), dict) else None
    readiness = readiness_summary(
        probes=dependency_probes(
            requires=declared_requires(market_record, status),
            entry_point=status.get("entry_point"),
        ),
        install_candidate=evaluation["install_candidate"],
    )
    return {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "harness_name": harness_name,
        "from_market": from_market,
        "capability_id": evaluation["capability_id"],
        "ready": readiness["ready"],
        "probe_blocker_count": readiness["probe_blocker_count"],
        "probes": readiness["probes"],
        "evaluation": evaluation,
        "next_commands": [
            f"python -m cbn plugin probe-harness cli-anything {harness_name}",
            f"python -m cbn plugin evaluate-harness cli-anything {harness_name}",
            f"python -m cbn plugin adapt-harness cli-anything {harness_name} --from-market --write",
            f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
        ],
    }


def _adaptation_error_result(
    harness_name: str,
    from_market: bool,
    adaptation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": False,
        "plugin_id": PLUGIN_ID,
        "harness_name": harness_name,
        "from_market": from_market,
        "error": adaptation["error"],
        "adaptation": adaptation,
    }


def _preparation_gates(
    status: dict[str, Any],
    adaptation: dict[str, Any],
    validation: dict[str, Any],
    from_market: bool,
) -> dict[str, bool]:
    return {
        "cli_hub_available": bool(status["cli_hub_available"]),
        "market_record_available": bool(adaptation["market_record_available"]),
        "market_required_satisfied": (not from_market) or bool(adaptation["market_record_available"]),
        "manifest_valid": bool(validation["valid"]),
        "manifest_imported": bool(status["manifest_imported"]),
        "installed": bool(status["installed"]),
        "entrypoint_available": bool(status["entrypoint_available"]),
        "launch_ready": bool(status["launch_ready"] and validation["valid"]),
    }


def _imported_manifest_state(
    adaptation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    status = adaptation["status"]
    manifest = adaptation["manifest"]
    validation = adaptation["validation"]
    if status.get("manifest_imported"):
        manifest_path = Path(adaptation["manifest_path"])
        manifest = manifest_dict_from_path(manifest_path, manifest)
        validation = validate_manifest_dict(
            manifest,
            source_path=manifest_path,
            known_parser_refs=known_parser_refs(),
        )
        adaptation = {
            **adaptation,
            "manifest": manifest,
            "validation": validation,
        }
    return manifest, validation, adaptation


def _evaluation_gates(
    status: dict[str, Any],
    adaptation: dict[str, Any],
    validation: dict[str, Any],
    transport: dict[str, Any],
    policy: dict[str, Any],
    requirements: dict[str, Any],
    platform: dict[str, Any],
    from_market: bool,
) -> dict[str, bool]:
    return {
        **_preparation_gates(status, adaptation, validation, from_market),
        "runtime_transport_ready": bool(transport["ready"]),
        "launch_ready": bool(status["launch_ready"] and validation["valid"] and transport["ready"]),
        "low_policy_risk": policy["risk"] in {"read", "write-workspace"} and not policy["requiresConfirmation"],
        "external_dependency_free": requirements["external_dependency_free"],
        "platform_compatible": platform["compatible"],
    }


def _evaluation_blockers(gates: dict[str, bool]) -> list[str]:
    blockers = []
    if not gates["cli_hub_available"]:
        blockers.append("cli-hub is not available")
    if not gates["market_required_satisfied"]:
        blockers.append("required market record is unavailable")
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


def _install_candidate(gates: dict[str, bool]) -> bool:
    return (
        gates["cli_hub_available"]
        and gates["market_required_satisfied"]
        and gates["manifest_valid"]
        and gates["low_policy_risk"]
        and gates["external_dependency_free"]
        and gates["platform_compatible"]
        and not (gates["installed"] and not gates["entrypoint_available"])
    )


def _recommended_next_action(gates: dict[str, bool], install_candidate: bool) -> str:
    if gates["launch_ready"]:
        return "call_capability"
    if gates["installed"] and not gates["entrypoint_available"]:
        return "resolve_blockers"
    if gates["installed"] and not gates["manifest_imported"]:
        return "write_manifest"
    if gates["installed"] and gates["manifest_imported"] and not gates["runtime_transport_ready"]:
        return "install_runtime_transport"
    if install_candidate and gates["manifest_imported"]:
        return "install_harness"
    if install_candidate:
        return "write_manifest"
    return "resolve_blockers"
