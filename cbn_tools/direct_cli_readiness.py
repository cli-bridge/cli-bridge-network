"""Readiness report for deterministic direct external CLI profiles."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from cbn_parsers.fixtures import run_parser_fixtures
from cbn_parsers.registry import ParserRegistry
from cbn_core.manifest import ManifestRegistry
from cbn_runtime.context import RuntimeContext
from cbn_tools.external_cli import list_actions


DIRECT_CLI_PARSER_REF = "direct-cli.typed"


def direct_cli_readiness_report(
    runtime: RuntimeContext | None = None,
    *,
    registry: ManifestRegistry | None = None,
    parser_registry: ParserRegistry | None = None,
    fixture_path: Path = Path("parser_fixtures"),
) -> dict[str, Any]:
    """Summarize direct CLI manifests, parser fixtures, and setup recovery gates."""

    return _readiness_report_payload(
        direct_cli_readiness_context(runtime, registry, parser_registry, fixture_path)
    )


def direct_cli_readiness_context(
    runtime: RuntimeContext | None,
    registry: ManifestRegistry | None,
    parser_registry: ParserRegistry | None,
    fixture_path: Path,
) -> dict[str, Any]:
    registry, parser_registry = _resolve_registries(runtime, registry, parser_registry)
    parser_present = _parser_present(parser_registry)
    fixture_report = run_parser_fixtures(fixture_path, parser_ref=DIRECT_CLI_PARSER_REF, registry=parser_registry)
    direct_manifests = _direct_manifests(registry)
    manifest_lookup = _manifest_lookup(direct_manifests)
    actions = list_actions()
    profiles = _profile_reports(actions, manifest_lookup, fixture_report)
    missing_runtime_capabilities = _missing_runtime_capabilities(actions, manifest_lookup)
    summary = _readiness_summary(
        profiles=profiles,
        actions=actions,
        direct_manifests=direct_manifests,
        parser_present=parser_present,
        fixture_report=fixture_report,
        missing_runtime_capabilities=missing_runtime_capabilities,
    )
    recovery_matrix = _recovery_matrix(fixture_report)
    ok = _readiness_ok(parser_present, fixture_report, missing_runtime_capabilities, summary)
    return {
        "fixture_path": fixture_path,
        "fixture_report": fixture_report,
        "missing_runtime_capabilities": missing_runtime_capabilities,
        "ok": ok,
        "parser_present": parser_present,
        "profiles": profiles,
        "recovery_matrix": recovery_matrix,
        "summary": summary,
    }


def _readiness_report_payload(context: dict[str, Any]) -> dict[str, Any]:
    ok = context["ok"]
    fixture_report = context["fixture_report"]
    missing_runtime_capabilities = context["missing_runtime_capabilities"]
    return {
        "ok": ok,
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "DirectCliReadinessReport",
        "adapter": "direct-cli",
        "parser_ref": DIRECT_CLI_PARSER_REF,
        "summary": {**context["summary"], "recovery_type_count": len(context["recovery_matrix"])},
        "parser_contract": _parser_contract(context["parser_present"], fixture_report, context["fixture_path"]),
        "profiles": context["profiles"],
        "error_recovery": context["recovery_matrix"],
        "missing_runtime_capabilities": missing_runtime_capabilities,
        "next_steps": _next_steps(ok, missing_runtime_capabilities, fixture_report),
    }


def _resolve_registries(
    runtime: RuntimeContext | None,
    registry: ManifestRegistry | None,
    parser_registry: ParserRegistry | None,
) -> tuple[ManifestRegistry, ParserRegistry]:
    if runtime is not None:
        registry = runtime.registry
        parser_registry = runtime.parser_registry
    if registry is None:
        raise ValueError("registry is required when runtime is not supplied")
    return registry, parser_registry or ParserRegistry.builtins()


def _direct_manifests(registry: ManifestRegistry) -> list[Any]:
    return [
        manifest
        for manifest in registry.list()
        if manifest.labels.get("adapter") == "direct-cli" or manifest.annotations.get("cbn.adapter.profile")
    ]


def _manifest_lookup(direct_manifests: list[Any]) -> dict[tuple[str, str], Any]:
    return {
        (
            manifest.annotations.get("cbn.adapter.profile") or manifest.labels.get("profile") or "",
            manifest.annotations.get("cbn.adapter.action") or "",
        ): manifest
        for manifest in direct_manifests
    }


def _missing_runtime_capabilities(
    actions: list[dict[str, object]],
    manifest_lookup: dict[tuple[str, str], Any],
) -> list[str]:
    return [
        f"{item['profile']}.{item['action']}"
        for item in actions
        if not _is_setup_action(str(item["profile"]), str(item["action"]))
        and (str(item["profile"]), str(item["action"])) not in manifest_lookup
    ]


def _readiness_summary(
    *,
    profiles: list[dict[str, Any]],
    actions: list[dict[str, object]],
    direct_manifests: list[Any],
    parser_present: bool,
    fixture_report: dict[str, Any],
    missing_runtime_capabilities: list[str],
) -> dict[str, Any]:
    verified_output_count = sum(
        1 for manifest in direct_manifests if manifest.output.parser_ref == DIRECT_CLI_PARSER_REF and manifest.output.verified
    )
    return {
        "profile_count": len(profiles),
        "action_count": len(actions),
        "setup_action_count": sum(1 for item in actions if _is_setup_action(str(item["profile"]), str(item["action"]))),
        "capability_count": len(direct_manifests),
        "verified_output_count": verified_output_count,
        "gated_capability_count": sum(1 for manifest in direct_manifests if manifest.policy.requires_confirmation),
        "typed_parser_present": parser_present,
        "fixture_count": fixture_report["fixture_count"],
        "fixture_case_count": fixture_report["case_count"],
        "fixture_failed_case_count": fixture_report["failed_case_count"],
        "missing_runtime_capability_count": len(missing_runtime_capabilities),
    }


def _readiness_ok(
    parser_present: bool,
    fixture_report: dict[str, Any],
    missing_runtime_capabilities: list[str],
    summary: dict[str, Any],
) -> bool:
    return bool(
        parser_present
        and fixture_report["ok"]
        and not missing_runtime_capabilities
        and summary["verified_output_count"] == summary["capability_count"]
    )


def _parser_contract(
    parser_present: bool,
    fixture_report: dict[str, Any],
    fixture_path: Path,
) -> dict[str, Any]:
    return {
        "parser_ref": DIRECT_CLI_PARSER_REF,
        "present": parser_present,
        "fixture_ok": fixture_report["ok"],
        "fixture_path": str(fixture_path),
        "fixture_count": fixture_report["fixture_count"],
        "case_count": fixture_report["case_count"],
        "failed_case_count": fixture_report["failed_case_count"],
        "verified_capabilities": _fixture_verified_capabilities(fixture_report),
    }


def _parser_present(parser_registry: ParserRegistry) -> bool:
    try:
        parser_registry.inspect(DIRECT_CLI_PARSER_REF)
    except KeyError:
        return False
    return True


def _profile_reports(
    actions: list[dict[str, object]],
    manifest_lookup: dict[tuple[str, str], Any],
    fixture_report: dict[str, Any],
) -> list[dict[str, Any]]:
    fixture_caps = set(_fixture_verified_capabilities(fixture_report))
    return [
        _profile_report(
            profile,
            profile_actions,
            manifest_lookup=manifest_lookup,
            fixture_caps=fixture_caps,
        )
        for profile, profile_actions in _actions_by_profile(actions).items()
    ]


def _actions_by_profile(actions: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    actions_by_profile: dict[str, list[dict[str, object]]] = defaultdict(list)
    for action in actions:
        actions_by_profile[str(action["profile"])].append(action)
    return {
        profile: sorted(profile_actions, key=lambda item: str(item["action"]))
        for profile, profile_actions in sorted(actions_by_profile.items())
    }


def _profile_report(
    profile: str,
    profile_actions: list[dict[str, object]],
    *,
    manifest_lookup: dict[tuple[str, str], Any],
    fixture_caps: set[str],
) -> dict[str, Any]:
    setup_actions: list[dict[str, Any]] = []
    capabilities: list[dict[str, Any]] = []
    for action_record in profile_actions:
        action = str(action_record["action"])
        manifest = manifest_lookup.get((profile, action))
        if manifest is None and _is_setup_action(profile, action):
            setup_actions.append(_setup_action_report(action, action_record))
            continue
        capabilities.append(_capability_report(action, action_record, manifest, fixture_caps))
    counts = _profile_capability_counts(capabilities)
    return {
        "profile": profile,
        "action_count": len(profile_actions),
        "capability_count": len(capabilities),
        "setup_action_count": len(setup_actions),
        **counts,
        "status": "ready" if counts["verified_capability_count"] == len(capabilities) and capabilities else "needs_mapping",
        "setup_actions": setup_actions,
        "capabilities": capabilities,
    }


def _setup_action_report(action: str, action_record: dict[str, object]) -> dict[str, Any]:
    return {
        "action": action,
        "title": action_record.get("title"),
        "argv": action_record.get("argv"),
    }


def _capability_report(
    action: str,
    action_record: dict[str, object],
    manifest: Any,
    fixture_caps: set[str],
) -> dict[str, Any]:
    if manifest is None:
        return _missing_capability_report(action, action_record)
    return _manifest_capability_report(action, manifest, fixture_caps)


def _missing_capability_report(action: str, action_record: dict[str, object]) -> dict[str, Any]:
    return {
        "capability_id": None,
        "action": action,
        "title": action_record.get("title"),
        "manifest_present": False,
        "parser_ref": None,
        "verified": False,
        "fixture_verified": False,
        "requires_confirmation": False,
        "network": None,
        "risk": None,
        "auth_gate": None,
        "output_contract": None,
    }


def _manifest_capability_report(action: str, manifest: Any, fixture_caps: set[str]) -> dict[str, Any]:
    return {
        "capability_id": manifest.capability_id,
        "action": action,
        "title": manifest.title,
        "manifest_present": True,
        "parser_ref": manifest.output.parser_ref,
        "verified": bool(manifest.output.verified),
        "fixture_verified": bool(manifest.capability_id in fixture_caps),
        "requires_confirmation": bool(manifest.policy.requires_confirmation),
        "network": manifest.policy.network,
        "risk": manifest.policy.risk,
        "auth_gate": manifest.annotations.get("cbn.auth_gate"),
        "output_contract": manifest.annotations.get("cbn.output_contract"),
    }


def _profile_capability_counts(capabilities: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "verified_capability_count": sum(1 for item in capabilities if item["verified"]),
        "fixture_verified_capability_count": sum(1 for item in capabilities if item["fixture_verified"]),
        "gated_capability_count": sum(1 for item in capabilities if item["requires_confirmation"]),
    }


def _recovery_matrix(fixture_report: dict[str, Any]) -> list[dict[str, Any]]:
    cases = _fixture_cases(fixture_report)
    matrix = []
    for error_type, case_ids, next_action in _recovery_definitions():
        matched = [case for case in cases if case.get("case_id") in case_ids]
        matrix.append(
            {
                "error_type": error_type,
                "covered": bool(matched) and all(case.get("ok") for case in matched),
                "fixture_case_ids": [str(case.get("case_id")) for case in matched],
                "setup_required": error_type != "launcher_failure",
                "next_action": next_action,
            }
        )
    return matrix


def _recovery_definitions() -> list[tuple[str, tuple[str, ...], str]]:
    return [
        (
            "auth_required",
            ("jimeng-auth-required", "jimeng-list-task-auth-required", "jimeng-text2image-auth-required"),
            "run dreamina login and complete OAuth/device login before live API calls",
        ),
        (
            "config_missing",
            ("feishu-doctor-config-missing",),
            "run lark-cli config init --new and complete Feishu/Lark CLI configuration",
        ),
        (
            "local_rest_unavailable",
            ("obsidian-local-rest-unavailable", "obsidian-note-read-unavailable"),
            "start Obsidian and configure the Local REST API plugin/API key",
        ),
        (
            "service_unhealthy",
            ("caw-status-unhealthy",),
            "configure Cobo Agentic Wallet API URL/key or local service pairing",
        ),
        (
            "launcher_failure",
            ("launcher-failure",),
            "fix the configured executable path or required runtime before retrying",
        ),
    ]


def _fixture_cases(fixture_report: dict[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for report in fixture_report.get("reports", []):
        if isinstance(report, dict):
            cases.extend(case for case in report.get("cases", []) if isinstance(case, dict))
    return cases


def _fixture_verified_capabilities(fixture_report: dict[str, Any]) -> list[str]:
    capabilities: set[str] = set()
    for report in fixture_report.get("reports", []):
        if not isinstance(report, dict):
            continue
        for capability_id in report.get("verified_capabilities", []):
            if isinstance(capability_id, str):
                capabilities.add(capability_id)
    return sorted(capabilities)


def _is_setup_action(profile: str, action: str) -> bool:
    return profile == "jimeng" and action in {"login", "login-headless", "login-check"}


def _next_steps(ok: bool, missing_runtime_capabilities: list[str], fixture_report: dict[str, Any]) -> list[str]:
    if ok:
        return [
            "Expose this readiness report in Workflow Studio so users see first-run setup gates before live calls.",
            "Add live acceptance probes after users provide real credentials or local app sessions.",
        ]
    steps = []
    if missing_runtime_capabilities:
        steps.append("Add ToolManifest mappings for missing non-setup direct CLI actions.")
    if not fixture_report["ok"]:
        steps.append("Fix direct-cli.typed parser fixtures before promoting live CLI profiles.")
    return steps or ["Inspect direct CLI parser registration and manifest output verification."]
