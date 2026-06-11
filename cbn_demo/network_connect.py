"""One-shot network connection package for external CBN consumers."""

from __future__ import annotations

import json
import re
import shlex
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from cbn_adapter_agent.nodes import build_adapter_agent_node_bundle
from cbn_adapter_agent.tool_call_plan import build_agent_tool_call_plan
from cbn_adapter_agent.workflow_request import build_agent_workflow_request_plan
from cbn_core.agent_cli_contract import (
    agent_cli_card_to_tool_manifests,
    agent_cli_contract_package_boundary,
    agent_cli_contract_package_health,
    run_receipt_to_cbn_records,
)
from cbn_core.import_catalog import cli_registration_surface
from cbn_core.manifest import ManifestRegistry
from cbn_demo.killer import DEFAULT_KILLER_WORKFLOW_PATH, KILLER_CAPABILITIES
from cbn_plugins.cli_anything import CliAnythingHub
from cbn_core.bridge_contract import workflow_bridge_contract_report
from cbn_protocol.exports import export_all_workflow_protocols
from cbn_workflow.catalog import inspect_workflow


CONTRACT_ROOT = Path("external_protocols/agent-cli-contract")
CONTRACT_CARD_FIXTURE = CONTRACT_ROOT / "fixtures/agent-cli-card.valid.json"
CONTRACT_RECEIPT_FIXTURE = CONTRACT_ROOT / "fixtures/run-receipt.valid.json"
CONNECT_API_VERSION = "bridge.dev/v1alpha1"
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:5173"
DEFAULT_AGENT_CONNECT_MESSAGE = "Run this workflow as a reusable CLI-CLI harness agent and connect an external program to CBN."


def network_connect_package(
    registry: ManifestRegistry,
    *,
    workflow_path: str = DEFAULT_KILLER_WORKFLOW_PATH,
    base_url: str | None = None,
    studio_url: str = "http://127.0.0.1:5177",
    dashboard_url: str = DEFAULT_DASHBOARD_URL,
    session_token: str | None = None,
    agent_message: str = DEFAULT_AGENT_CONNECT_MESSAGE,
) -> dict[str, Any]:
    """Return the minimum stable payload another program needs to enter CBN."""

    workflow = inspect_workflow(Path(workflow_path), registry=registry)
    bridge_contract = workflow_bridge_contract_report(registry, workflow_path=workflow_path)
    protocol_exports = export_all_workflow_protocols(registry, workflow_path=workflow_path)
    agent_bundle = build_adapter_agent_node_bundle(
        workflow_path=workflow_path,
        message=agent_message,
    )
    request_plan = build_agent_workflow_request_plan(
        workflow_path=workflow_path,
        message=agent_message,
        base_url=base_url,
        dry_run=True,
        confirmed=False,
    )
    setup_guidance = _compact_setup_guidance(
        build_agent_tool_call_plan(
            workflow_path=workflow_path,
            message=agent_message,
        )
    )
    external_contract = _external_agent_cli_contract()
    internal_contract = _internal_bridge_contract(bridge_contract)
    protocol_summary = _protocol_summary(protocol_exports)
    endpoint_catalog = _endpoint_catalog(base_url=base_url, workflow_path=workflow_path)
    studio_link = workflow_studio_demo_link(
        workflow_path=workflow_path,
        daemon_url=base_url,
        studio_url=studio_url,
        dashboard_url=dashboard_url,
        session_token=session_token,
        agent_message=agent_message,
        dry_run=True,
        confirmed=False,
    )
    ok = bool(
        workflow.get("valid")
        and bridge_contract.get("ok")
        and external_contract.get("ok")
        and protocol_summary["export_count"] >= 3
    )
    quickstart = _consumer_quickstart(
        base_url=base_url,
        workflow_path=workflow_path,
        session_token=session_token,
        studio_link=studio_link,
        request_plan=request_plan,
    )
    demo_readiness = _demo_readiness(
        workflow_path=workflow_path,
        workflow=workflow,
        bridge_contract=bridge_contract,
        protocol_summary=protocol_summary,
        endpoint_catalog=endpoint_catalog,
        studio_link=studio_link,
        base_url=base_url,
        session_token=session_token,
    )
    registration_surface = _registration_surface()
    plugin_health = _plugin_health()
    demo_playbook = _demo_playbook(
        workflow_path=workflow_path,
        studio_link=studio_link,
        demo_readiness=demo_readiness,
        quickstart=quickstart,
        registration_surface=registration_surface,
        base_url=base_url,
        session_token=session_token,
    )
    network_entry_profile = _network_entry_profile(
        workflow_path=workflow_path,
        base_url=base_url,
        quickstart=quickstart,
        request_plan=request_plan,
        registration_surface=registration_surface,
        demo_readiness=demo_readiness,
        demo_playbook=demo_playbook,
        protocol_summary=protocol_summary,
        external_contract=external_contract,
        setup_guidance=setup_guidance,
    )
    mvp_readiness = _mvp_readiness(
        workflow=workflow,
        bridge_contract=bridge_contract,
        external_contract=external_contract,
        protocol_summary=protocol_summary,
        request_plan=request_plan,
        setup_guidance=setup_guidance,
        registration_surface=registration_surface,
        demo_readiness=demo_readiness,
        demo_playbook=demo_playbook,
        quickstart=quickstart,
        plugin_health=plugin_health,
        studio_link=studio_link,
        network_entry_profile=network_entry_profile,
    )
    mvp_presenter_brief = _mvp_presenter_brief(
        workflow=workflow,
        protocol_summary=protocol_summary,
        quickstart=quickstart,
        request_plan=request_plan,
        registration_surface=registration_surface,
        demo_readiness=demo_readiness,
        demo_playbook=demo_playbook,
        setup_guidance=setup_guidance,
        network_entry_profile=network_entry_profile,
        mvp_readiness=mvp_readiness,
        studio_link=studio_link,
        base_url=base_url,
        workflow_path=workflow_path,
        session_token=session_token,
    )
    consumer_launch_contract = _consumer_launch_contract(
        workflow_path=workflow_path,
        quickstart=quickstart,
        request_plan=request_plan,
        network_entry_profile=network_entry_profile,
        setup_guidance=setup_guidance,
        mvp_readiness=mvp_readiness,
        mvp_presenter_brief=mvp_presenter_brief,
    )
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "NetworkConnectPackage",
        "ok": ok,
        "workflow_path": workflow_path,
        "base_url": base_url,
        "summary": {
            "workflow_id": workflow.get("workflow_id"),
            "task_count": workflow.get("task_count"),
            "bridge_route_count": (bridge_contract.get("summary") or {}).get("route_count", 0),
            "protocol_export_count": protocol_summary["export_count"],
            "agent_card_count": len(agent_bundle.get("cards", [])),
            "registration_importer_count": registration_surface["importer_count"],
            "consumer_snippet_count": len(quickstart.get("sdk_snippets", [])),
            "agent_workflow_request_ready": request_plan.get("ok"),
            "setup_status": setup_guidance.get("status"),
            "setup_required": setup_guidance.get("setup_required"),
            "setup_user_gate_count": setup_guidance.get("requires_user_count", 0),
            "setup_secret_count": setup_guidance.get("secret_count", 0),
            "demo_ready": demo_readiness.get("status") == "ready",
            "demo_stage_count": demo_readiness.get("stage_count", 0),
            "demo_playbook_step_count": demo_playbook["step_count"],
            "cli_anything_split_status": plugin_health.get("cli_anything", {})
            .get("module_split", {})
            .get("status"),
            "external_contract_ready": external_contract.get("ok"),
            "mvp_readiness_status": mvp_readiness["status"],
            "mvp_readiness_score": mvp_readiness["score"],
            "mvp_presenter_brief_status": mvp_presenter_brief["status"],
            "recommended_next_action": "call_daemon_endpoints" if ok else "fix_connect_package_inputs",
        },
        "contracts": {
            "internal": {
                "tool_manifest": "bridge.dev/v1alpha1 ToolManifest",
                "bridge_message": "bridge.dev/v1alpha1 BridgeMessage",
                "artifact": "CBN Artifact records",
                "workflow_selector": "argsFrom selector records",
                "protocol": internal_contract.get("protocol_name"),
                "api_version": internal_contract.get("apiVersion"),
                "contract_sections": sorted((internal_contract.get("contracts") or {}).keys()),
                "contracts": internal_contract.get("contracts", {}),
                "bridge_contract": {
                    "ok": bridge_contract.get("ok"),
                    "summary": bridge_contract.get("summary", {}),
                    "contract": internal_contract,
                },
            },
            "external": external_contract,
        },
        "daemon_endpoints": endpoint_catalog,
        "workflow": _compact_workflow(workflow),
        "protocols": protocol_summary,
        "plugins": plugin_health,
        "workflow_studio": studio_link,
        "demo_readiness": demo_readiness,
        "demo_playbook": demo_playbook,
        "network_entry_profile": network_entry_profile,
        "mvp_readiness": mvp_readiness,
        "mvp_presenter_brief": mvp_presenter_brief,
        "consumer_launch_contract": consumer_launch_contract,
        "agent_node_bundle": _compact_agent_bundle(agent_bundle),
        "agent_workflow_request": _compact_workflow_request_plan(request_plan),
        "setup_guidance": setup_guidance,
        "registration_surface": registration_surface,
        "acceptance": quickstart["acceptance"],
        "consumer_quickstart": quickstart,
        "next_commands": _next_commands(workflow_path, base_url=base_url, session_token=session_token),
    }


def _consumer_launch_contract(
    *,
    workflow_path: str,
    quickstart: dict[str, Any],
    request_plan: dict[str, Any],
    network_entry_profile: dict[str, Any],
    setup_guidance: dict[str, Any],
    mvp_readiness: dict[str, Any],
    mvp_presenter_brief: dict[str, Any],
) -> dict[str, Any]:
    """Small stable contract for external programs that want to launch the MVP path."""

    entrypoints = quickstart.get("entrypoints") if isinstance(quickstart.get("entrypoints"), dict) else {}
    headers = quickstart.get("required_headers") if isinstance(quickstart.get("required_headers"), dict) else {}
    acceptance = quickstart.get("acceptance") if isinstance(quickstart.get("acceptance"), dict) else {}
    request_ids = [
        str(request.get("id"))
        for request in quickstart.get("requests", [])
        if isinstance(request, dict) and request.get("id")
    ]
    run = request_plan.get("run") if isinstance(request_plan.get("run"), dict) else {}
    run_http = run.get("http") if isinstance(run.get("http"), dict) else {}
    harness = request_plan.get("reusable_harness") if isinstance(request_plan.get("reusable_harness"), dict) else {}
    bridge_routes = request_plan.get("bridge_routes") if isinstance(request_plan.get("bridge_routes"), list) else []
    launch_sequence = [
        {
            "order": 1,
            "id": "discover",
            "request_id": "health",
            "intent": "Confirm daemon reachability and auth gate before any POST.",
            "success_signal": "health.status == ok and auth metadata is present.",
        },
        {
            "order": 2,
            "id": "inspect_contract",
            "request_id": "inspect_bridge_contract",
            "intent": "Read the internal BridgeMessage selector contract for this workflow.",
            "success_signal": "contract.summary.route_count >= 1.",
        },
        {
            "order": 3,
            "id": "plan_harness_agent",
            "request_id": "plan_agent_request",
            "intent": "Bind natural language to a reusable CLI-CLI workflow request.",
            "success_signal": "reusable_harness.kind == NaturalLanguageWorkflowHarness.",
        },
        {
            "order": 4,
            "id": "run_workflow",
            "request_id": "run_workflow",
            "intent": "Execute the selected workflow through the daemon bus.",
            "success_signal": "workflow_status == completed and BridgeMessage routes resolve.",
        },
        {
            "order": 5,
            "id": "collect_evidence",
            "request_id": "artifacts",
            "intent": "Read artifact, event, and audit evidence after execution.",
            "success_signal": "events/audit/artifacts each return at least one record.",
        },
    ]
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "ConsumerLaunchContract",
        "status": "ready"
        if quickstart.get("status") in {"ready", "ready_without_daemon_url"}
        and request_plan.get("ok")
        and mvp_readiness.get("status") == "ready"
        else "needs_attention",
        "contract_id": "cbn.consumer.launch.cli-cli-harness.v1",
        "audience": "external_program",
        "workflow_path": workflow_path,
        "profile_id": network_entry_profile.get("profile_id"),
        "stable_inputs": {
            "base_url": network_entry_profile.get("base_url"),
            "workflow_path": workflow_path,
            "agent_message": (request_plan.get("request") or {}).get("message"),
            "dry_run": True,
            "confirmed": False,
        },
        "auth": {
            "header": "X-CBN-Session" if "X-CBN-Session" in headers else None,
            "session_token_required": bool((network_entry_profile.get("auth") or {}).get("session_token_required")),
            "session_token_included": bool((network_entry_profile.get("auth") or {}).get("session_token_included")),
            "secret_values_echoed": False,
        },
        "launch_sequence": launch_sequence,
        "required_request_ids": [step["request_id"] for step in launch_sequence],
        "available_request_ids": request_ids,
        "entrypoints": {
            "open_studio": _redact_launch_secret(entrypoints.get("open_studio")),
            "plan_agent_request": entrypoints.get("plan_agent_request"),
            "run_workflow": entrypoints.get("run_workflow"),
            "verify_network": _redact_launch_secret(
                (network_entry_profile.get("primary_entrypoints") or {}).get("verify_network")
            ),
            "readiness": (mvp_presenter_brief.get("integration_handoff") or {}).get("readiness_url"),
        },
        "harness_agent": {
            "kind": harness.get("kind"),
            "accepts": harness.get("accepts", []),
            "emits": harness.get("emits", []),
            "bridge_route_count": len(bridge_routes),
            "run_endpoint": run_http.get("url") or (entrypoints.get("run_workflow") or {}).get("url"),
        },
        "success_gates": {
            "mvp_readiness_score": mvp_readiness.get("score"),
            "acceptance_check_count": acceptance.get("check_count", 0),
            "setup_status": setup_guidance.get("status"),
            "setup_required": setup_guidance.get("setup_required"),
            "no_secret_values_included": setup_guidance.get("safety", {}).get("secret_values_included") is False,
        },
        "do_not": [
            "Do not rely on CBN internal daemon state outside the listed entrypoints.",
            "Do not persist or echo session token values from this payload.",
            "Do not run confirmed writes until the user explicitly sets confirmed=true.",
        ],
    }


def _redact_launch_secret(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    redacted = re.sub(r"(sessionToken=)[^&\s]+", r"\1REDACTED", value)
    return re.sub(r"(--session-token)(?:=|\s+)\S+", r"\1 REDACTED", redacted)


def _redact_entry_profile_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {"x-cbn-session", "authorization"} and item:
                redacted[str(key)] = "REDACTED"
            else:
                redacted[str(key)] = _redact_entry_profile_secrets(item)
        return redacted
    if isinstance(value, list):
        return [_redact_entry_profile_secrets(item) for item in value]
    return _redact_launch_secret(value)


def _network_entry_profile(
    *,
    workflow_path: str,
    base_url: str | None,
    quickstart: dict[str, Any],
    request_plan: dict[str, Any],
    registration_surface: dict[str, Any],
    demo_readiness: dict[str, Any],
    demo_playbook: dict[str, Any],
    protocol_summary: dict[str, Any],
    external_contract: dict[str, Any],
    setup_guidance: dict[str, Any],
) -> dict[str, Any]:
    """Compact integration profile for programs entering CBN in one read."""

    entrypoints = quickstart.get("entrypoints") if isinstance(quickstart.get("entrypoints"), dict) else {}
    acceptance = quickstart.get("acceptance") if isinstance(quickstart.get("acceptance"), dict) else {}
    headers = quickstart.get("required_headers") if isinstance(quickstart.get("required_headers"), dict) else {}
    reusable_harness = (
        request_plan.get("reusable_harness")
        if isinstance(request_plan.get("reusable_harness"), dict)
        else {}
    )
    request = request_plan.get("request") if isinstance(request_plan.get("request"), dict) else {}
    run = request_plan.get("run") if isinstance(request_plan.get("run"), dict) else {}
    run_http = run.get("http") if isinstance(run.get("http"), dict) else {}
    bridge_routes = request_plan.get("bridge_routes") if isinstance(request_plan.get("bridge_routes"), list) else []
    bridge_message = (
        request_plan.get("bridge_message")
        if isinstance(request_plan.get("bridge_message"), dict)
        else {}
    )
    bridge_metadata = bridge_message.get("metadata") if isinstance(bridge_message.get("metadata"), dict) else {}
    bridge_channel = request_plan.get("bridge_message_channel") or bridge_metadata.get("channel") or bridge_message.get("channel")
    plan_entrypoint = entrypoints.get("plan_agent_request") if isinstance(entrypoints.get("plan_agent_request"), dict) else {}
    run_entrypoint = entrypoints.get("run_workflow") if isinstance(entrypoints.get("run_workflow"), dict) else {}
    importers = registration_surface.get("importers") if isinstance(registration_surface.get("importers"), list) else []
    entry_status = "ready" if quickstart.get("status") in {"ready", "ready_without_daemon_url"} and request_plan.get("ok") else "needs_attention"
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "NetworkEntryProfile",
        "status": entry_status,
        "profile_id": "cbn.network.entry.cli-cli-harness.v1",
        "display_name": "CBN CLI-CLI Harness Network Entry",
        "workflow_path": workflow_path,
        "base_url": base_url,
        "integration_mode": "one_shot_package",
        "compatibility": {
            "api_version": CONNECT_API_VERSION,
            "additive_fields_only": True,
            "external_protocol": external_contract.get("protocol"),
            "external_kinds": external_contract.get("accepted_kinds", []),
            "internal_bus": "CBN BridgeMessage",
            "stable_fields": [
                "network_entry_profile",
                "consumer_quickstart",
                "consumer_launch_contract",
                "agent_workflow_request",
                "acceptance",
                "contracts.external",
            ],
        },
        "auth": {
            "required_headers": _redact_entry_profile_secrets(headers),
            "session_token_required": "X-CBN-Session" in headers,
            "session_token_included": bool(headers.get("X-CBN-Session")),
            "secret_values_echoed": False,
        },
        "primary_entrypoints": {
            "open_studio": _redact_entry_profile_secrets(entrypoints.get("open_studio")),
            "health": _redact_entry_profile_secrets(entrypoints.get("health")),
            "import_catalog": _redact_entry_profile_secrets(entrypoints.get("import_catalog")),
            "plan_agent_request": _redact_entry_profile_secrets(plan_entrypoint),
            "run_workflow": _redact_entry_profile_secrets(run_entrypoint),
            "verify_network": _redact_entry_profile_secrets(
                _network_verify_command(
                    workflow_path,
                    base_url=base_url,
                    session_token=headers.get("X-CBN-Session"),
                )
            ),
        },
        "harness_agent": {
            "kind": reusable_harness.get("kind"),
            "request_binding": (request.get("binding") if isinstance(request, dict) else None),
            "message": request.get("message"),
            "accepts": reusable_harness.get("accepts", []),
            "emits": reusable_harness.get("emits", []),
            "bridge_message_channel": bridge_channel,
            "bridge_route_count": len(bridge_routes),
            "plan_endpoint": plan_entrypoint.get("url"),
            "run_endpoint": run_http.get("url") or run_entrypoint.get("url"),
        },
        "evidence": {
            "acceptance_status": acceptance.get("status"),
            "acceptance_check_count": acceptance.get("check_count", 0),
            "required_request_ids": acceptance.get("required_request_ids", []),
            "evidence_endpoints": {
                "events": entrypoints.get("events"),
                "audit": entrypoints.get("audit"),
                "artifacts": entrypoints.get("artifacts"),
            },
            "demo_status": demo_readiness.get("status"),
            "demo_stage_count": demo_readiness.get("stage_count", 0),
            "playbook_status": demo_playbook.get("status"),
            "playbook_step_count": demo_playbook.get("step_count", 0),
        },
        "registration": {
            "status": registration_surface.get("status"),
            "importer_count": registration_surface.get("importer_count", 0),
            "importer_ids": [str(importer.get("id")) for importer in importers if isinstance(importer, dict)],
            "next_commands": registration_surface.get("next_commands", []),
        },
        "setup": {
            "status": setup_guidance.get("status"),
            "setup_required": setup_guidance.get("setup_required"),
            "requires_user_count": setup_guidance.get("requires_user_count", 0),
            "secret_count": setup_guidance.get("secret_count", 0),
        },
        "protocol_facades": {
            "targets": protocol_summary.get("targets", []),
            "export_count": protocol_summary.get("export_count", 0),
        },
    }


def _mvp_readiness(
    *,
    workflow: dict[str, Any],
    bridge_contract: dict[str, Any],
    external_contract: dict[str, Any],
    protocol_summary: dict[str, Any],
    request_plan: dict[str, Any],
    setup_guidance: dict[str, Any],
    registration_surface: dict[str, Any],
    demo_readiness: dict[str, Any],
    demo_playbook: dict[str, Any],
    quickstart: dict[str, Any],
    plugin_health: dict[str, Any],
    studio_link: dict[str, Any],
    network_entry_profile: dict[str, Any],
) -> dict[str, Any]:
    """Product-facing readiness matrix for the current killer MVP surface."""

    bridge_summary = bridge_contract.get("summary") if isinstance(bridge_contract.get("summary"), dict) else {}
    acceptance = quickstart.get("acceptance") if isinstance(quickstart.get("acceptance"), dict) else {}
    cli_anything = plugin_health.get("cli_anything") if isinstance(plugin_health.get("cli_anything"), dict) else {}
    module_split = cli_anything.get("module_split") if isinstance(cli_anything.get("module_split"), dict) else {}
    reusable_harness = request_plan.get("reusable_harness") if isinstance(request_plan.get("reusable_harness"), dict) else {}
    checks = [
        _mvp_check(
            "external_agent_cli_contract",
            "External Agent CLI contract",
            bool(external_contract.get("ok")),
            "AgentCliCard/RunReceipt package boundary is standalone and consumable.",
            {
                "protocol": external_contract.get("protocol"),
                "accepted_kinds": external_contract.get("accepted_kinds", []),
            },
            "repair_agent_cli_contract_package",
        ),
        _mvp_check(
            "internal_bridge_contract",
            "Internal BridgeMessage bus",
            bool(bridge_contract.get("ok") and int(bridge_summary.get("route_count", 0) or 0) >= 1),
            "ToolManifest, BridgeMessage, Artifact, and Workflow selector contracts are ready.",
            {
                "route_count": bridge_summary.get("route_count", 0),
                "route_ready_count": bridge_summary.get("route_ready_count", 0),
            },
            "repair_bridge_message_routes",
        ),
        _mvp_check(
            "workflow_studio_surface",
            "Workflow Studio surface",
            bool(studio_link.get("ok") and studio_link.get("url")),
            "User-facing Studio link is preconfigured for daemon, workflow, token, and demo mode.",
            {"url": studio_link.get("url"), "session_token_included": studio_link.get("session_token_included")},
            "start_workflow_studio",
        ),
        _mvp_check(
            "killer_workflow_dag",
            "Killer workflow DAG",
            bool(workflow.get("valid") and int(workflow.get("task_count", 0) or 0) >= 1),
            "The macrocli -> transform -> mermaid DAG can be inspected before running.",
            {"workflow_id": workflow.get("workflow_id"), "task_count": workflow.get("task_count", 0)},
            "fix_workflow_manifest_or_tasks",
        ),
        _mvp_check(
            "natural_language_harness_agent",
            "Natural-language harness agent",
            bool(request_plan.get("ok") and reusable_harness.get("kind") == "NaturalLanguageWorkflowHarness"),
            "A reusable harness agent can bind natural language to the CLI-CLI workflow run contract.",
            {
                "kind": reusable_harness.get("kind"),
                "bridge_route_count": request_plan.get("bridge_route_count", 0),
            },
            "repair_adapter_agent_workflow_request_plan",
        ),
        _mvp_check(
            "network_entry_profile",
            "One-shot network entry",
            network_entry_profile.get("status") == "ready",
            "External programs can read one profile to discover auth, endpoints, harness, evidence, and registration.",
            {
                "profile_id": network_entry_profile.get("profile_id"),
                "integration_mode": network_entry_profile.get("integration_mode"),
            },
            "repair_network_entry_profile",
        ),
        _mvp_check(
            "quickstart_acceptance",
            "First-call acceptance",
            bool(quickstart.get("status") in {"ready", "ready_without_daemon_url"} and int(acceptance.get("check_count", 0) or 0) >= 1),
            "The first-call sequence and acceptance checklist are available for replay.",
            {
                "quickstart_status": quickstart.get("status"),
                "check_count": acceptance.get("check_count", 0),
                "request_count": len(quickstart.get("requests", [])) if isinstance(quickstart.get("requests"), list) else 0,
            },
            "repair_network_quickstart",
        ),
        _mvp_check(
            "cli_registration_surface",
            "Low-cost CLI registration",
            bool(registration_surface.get("status") == "ready" and int(registration_surface.get("importer_count", 0) or 0) >= 5),
            "Next CLIs can enter through dry-run-first import command, CLI-Anything, MCP, skill, card, or parser fixture routes.",
            {
                "importer_count": registration_surface.get("importer_count", 0),
                "dry_run_by_default": (registration_surface.get("default_policy") or {}).get("dry_run_by_default"),
            },
            "repair_registration_surface",
        ),
        _mvp_check(
            "cli_anything_split",
            "CLI-Anything split facade",
            module_split.get("status") == "ready",
            "CLI-Anything remains compatible while market/probe/manifest/repair/verification/onboarding parts exist.",
            {
                "status": module_split.get("status"),
                "present_part_count": module_split.get("present_part_count", 0),
                "expected_part_count": module_split.get("expected_part_count", 0),
            },
            "continue_cli_anything_split",
        ),
        _mvp_check(
            "setup_guidance",
            "First-run setup guidance",
            bool(setup_guidance.get("status") and setup_guidance.get("safety", {}).get("secret_values_included") is False),
            "API key, login, and user-gated setup can be surfaced without leaking secret values.",
            {
                "status": setup_guidance.get("status"),
                "setup_required": setup_guidance.get("setup_required"),
                "requires_user_count": setup_guidance.get("requires_user_count", 0),
                "secret_count": setup_guidance.get("secret_count", 0),
            },
            "repair_setup_guidance",
        ),
        _mvp_check(
            "protocol_facades",
            "MCP/A2A/ACP facades",
            int(protocol_summary.get("export_count", 0) or 0) >= 3,
            "The same workflow can be exported to MCP, A2A, and ACP descriptors.",
            {"targets": protocol_summary.get("targets", []), "export_count": protocol_summary.get("export_count", 0)},
            "repair_protocol_exports",
        ),
        _mvp_check(
            "killer_demo_playbook",
            "Killer demo playbook",
            bool(demo_readiness.get("status") == "ready" and demo_playbook.get("status") == "ready"),
            "The product demo has ordered stages and success criteria for Studio presentation.",
            {
                "demo_status": demo_readiness.get("status"),
                "stage_count": demo_readiness.get("stage_count", 0),
                "playbook_step_count": demo_playbook.get("step_count", 0),
            },
            "repair_killer_demo_playbook",
        ),
    ]
    ready_count = sum(1 for check in checks if check["ready"])
    total = len(checks)
    status = "ready" if ready_count == total else "needs_attention"
    product_goals = {
        "show_cli_cli_protocol": _checks_ready(checks, "internal_bridge_contract", "killer_workflow_dag"),
        "run_reusable_harness_agent": _checks_ready(checks, "natural_language_harness_agent", "quickstart_acceptance"),
        "integrate_next_cli": _checks_ready(checks, "cli_registration_surface", "cli_anything_split"),
        "one_shot_external_network_entry": _checks_ready(checks, "network_entry_profile", "external_agent_cli_contract"),
        "demo_in_workflow_studio": _checks_ready(checks, "workflow_studio_surface", "killer_demo_playbook"),
        "safe_first_run_setup": _checks_ready(checks, "setup_guidance"),
    }
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "KillerMvpReadiness",
        "status": status,
        "score": f"{ready_count}/{total}",
        "ready_count": ready_count,
        "check_count": total,
        "checks": checks,
        "product_goals": product_goals,
        "recommended_next_action": "open_workflow_studio_demo" if status == "ready" else _first_unready_action(checks),
    }


def _mvp_check(
    check_id: str,
    title: str,
    ready: bool,
    proves: str,
    evidence: dict[str, Any],
    next_action: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "status": "ready" if ready else "needs_attention",
        "ready": ready,
        "proves": proves,
        "evidence": evidence,
        "next_action": None if ready else next_action,
    }


def _checks_ready(checks: list[dict[str, Any]], *check_ids: str) -> bool:
    by_id = {check["id"]: check for check in checks}
    return all(bool(by_id.get(check_id, {}).get("ready")) for check_id in check_ids)


def _first_unready_action(checks: list[dict[str, Any]]) -> str:
    for check in checks:
        if not check.get("ready"):
            return str(check.get("next_action") or "inspect_mvp_readiness")
    return "open_workflow_studio_demo"


def _plugin_health() -> dict[str, Any]:
    try:
        cli_anything = CliAnythingHub().status()
    except Exception as exc:  # pragma: no cover - defensive one-shot packaging guard
        cli_anything = {
            "plugin_id": "cli-anything",
            "ok": False,
            "error": str(exc),
            "module_split": {
                "kind": "CliAnythingModuleSplitReport",
                "status": "unknown",
            },
        }
    return {"cli_anything": cli_anything}


def _demo_readiness(
    *,
    workflow_path: str,
    workflow: dict[str, Any],
    bridge_contract: dict[str, Any],
    protocol_summary: dict[str, Any],
    endpoint_catalog: list[dict[str, Any]],
    studio_link: dict[str, Any],
    base_url: str | None,
    session_token: str | None,
) -> dict[str, Any]:
    endpoint_by_path = {
        str(endpoint.get("path", "")).split("?", 1)[0]: endpoint
        for endpoint in endpoint_catalog
        if isinstance(endpoint, dict)
    }
    route_count = int((bridge_contract.get("summary") or {}).get("route_count", 0) or 0)
    stages = [
        {
            "id": "import_cli_anything_harness",
            "title": "Import CLI-Anything harness",
            "proves": "CLI-Anything capabilities can enter CBN as ToolManifest records.",
            "capability_ids": [
                "cli-anything.macrocli.backends",
                "cli-anything.mermaid.set-diagram",
            ],
        },
        {
            "id": "run_macrocli",
            "title": "Run macrocli backend listing",
            "proves": "A CLI producer can emit a BridgeMessage payload for downstream tools.",
            "endpoint": endpoint_by_path.get("/workflows/run", {}),
        },
        {
            "id": "parse_payload",
            "title": "Parse BridgeMessage payload",
            "proves": "CBN parser contracts make CLI stdout deterministic enough for routing.",
            "bridge_route_count": route_count,
        },
        {
            "id": "transform_to_mermaid",
            "title": "Transform payload to Mermaid source",
            "proves": "Workflow selectors can map one CLI output into another CLI input.",
            "capability_ids": ["cbn.transform.macrocli-backends-to-mermaid"],
        },
        {
            "id": "run_mermaid",
            "title": "Run Mermaid consumer",
            "proves": "A downstream CLI consumer can produce inspectable artifacts.",
            "capability_ids": ["cli-anything.mermaid.set-diagram"],
        },
        {
            "id": "show_artifact_event_audit",
            "title": "Show artifact, event and audit evidence",
            "proves": "Runtime evidence can be inspected after the CLI-CLI chain runs.",
            "endpoints": [
                endpoint_by_path.get("/artifacts", {}),
                endpoint_by_path.get("/events", {}),
                endpoint_by_path.get("/audit", {}),
            ],
        },
        {
            "id": "export_mcp_a2a_acp_smoke",
            "title": "Export MCP/A2A/ACP smoke",
            "proves": "The same workflow can be exposed through external protocol facades.",
            "endpoint": endpoint_by_path.get("/protocols/workflows", {}),
        },
    ]
    ready = bool(workflow.get("valid") and route_count > 0 and protocol_summary.get("export_count", 0) >= 3)
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "KillerDemoReadiness",
        "status": "ready" if ready else "needs_attention",
        "workflow_path": workflow_path,
        "workflow_id": workflow.get("workflow_id"),
        "stage_count": len(stages),
        "stages": stages,
        "required_capability_ids": list(KILLER_CAPABILITIES),
        "evidence_contracts": [
            "ToolManifest",
            "BridgeMessage",
            "ArtifactRecord",
            "WorkflowSelector",
            "Event",
            "Audit",
        ],
        "protocol_targets": protocol_summary.get("targets", []),
        "studio_url": studio_link.get("url"),
        "demo_endpoint": endpoint_by_path.get("/demo/killer", {}),
        "acceptance_request_ids": [
            "inspect_agent_nodes",
            "export_protocols",
            "plan_agent_request",
            "run_workflow",
            "events",
            "audit",
            "artifacts",
        ],
        "next_commands": [
            f"python -m cbn demo killer --workflow-path {workflow_path} --run --dry-run",
            f"python -m cbn demo killer --workflow-path {workflow_path} --run --dry-run --smoke-suite",
            _network_verify_command(workflow_path, base_url=base_url, session_token=session_token),
        ],
    }


def _demo_playbook(
    *,
    workflow_path: str,
    studio_link: dict[str, Any],
    demo_readiness: dict[str, Any],
    quickstart: dict[str, Any],
    registration_surface: dict[str, Any],
    base_url: str | None,
    session_token: str | None,
) -> dict[str, Any]:
    entrypoints = quickstart.get("entrypoints") if isinstance(quickstart.get("entrypoints"), dict) else {}
    open_studio = str(studio_link.get("url") or entrypoints.get("open_studio") or "")
    verify_command = _network_verify_command(workflow_path, base_url=base_url, session_token=session_token)
    steps = [
        {
            "id": "open_workflow_studio",
            "title": "Open Workflow Studio",
            "intent": "Use the product UI as the primary demo surface.",
            "action": "open_url",
            "target": open_studio,
            "success_signal": "Workflow DAG, Connect Package, and evidence dock are visible.",
        },
        {
            "id": "inspect_one_shot_contract",
            "title": "Inspect one-shot connection package",
            "intent": "Show external protocol boundary, internal bus contracts, agent nodes, and quickstart calls.",
            "action": "click",
            "target": "Connect",
            "success_signal": "Connect panel shows AgentCliCard/RunReceipt, BridgeMessage routes, setup guidance, and registration surface.",
        },
        {
            "id": "run_killer_demo",
            "title": "Run CLI-CLI killer demo",
            "intent": "Prove macrocli output can route through BridgeMessage into Mermaid and produce artifacts.",
            "action": "click",
            "target": "Demo",
            "success_signal": "Killer Demo stages complete and artifact/event/audit counts are non-zero.",
        },
        {
            "id": "verify_network_acceptance",
            "title": "Verify external consumer acceptance",
            "intent": "Replay the first-call request sequence against the live daemon.",
            "action": "click_or_cli",
            "target": "Daemon Verify",
            "command": verify_command,
            "success_signal": "NetworkConnectionAcceptanceReport.status == passed.",
        },
        {
            "id": "show_protocol_facades",
            "title": "Show MCP/A2A/ACP workflow facades",
            "intent": "Show the same CLI-CLI workflow can be exported to external protocol descriptors.",
            "action": "inspect_endpoint",
            "target": entrypoints.get("export_protocols"),
            "success_signal": "Protocol targets include mcp, a2a, and acp.",
        },
        {
            "id": "register_next_cli",
            "title": "Register the next CLI",
            "intent": "Show the low-friction path for adding more CLIs to the network.",
            "action": "copy_command",
            "target": "registration_surface.next_commands",
            "command": (registration_surface.get("next_commands") or ["python -m cbn import command --help"])[0],
            "success_signal": "Importer help confirms dry-run-first registration entrypoints.",
        },
    ]
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "KillerMvpDemoPlaybook",
        "status": "ready" if demo_readiness.get("status") == "ready" else "needs_attention",
        "workflow_path": workflow_path,
        "step_count": len(steps),
        "steps": steps,
        "success_criteria": [
            "Workflow Studio opens with the target workflow path.",
            "Connect Package exposes external protocol boundary and internal BridgeMessage contract.",
            "Harness agent request can call the CLI-CLI workflow through /workflows/run.",
            "Runtime event, audit, and artifact evidence is visible after the run.",
            "MCP/A2A/ACP descriptors export for the same workflow.",
            "Registration surface lists dry-run-first importers for the next CLI.",
        ],
        "next_commands": [
            verify_command,
            f"python -m cbn demo killer --workflow-path {workflow_path} --run --dry-run --smoke-suite",
            "python -m cbn import command --help",
        ],
    }


def _mvp_presenter_brief(
    *,
    workflow: dict[str, Any],
    protocol_summary: dict[str, Any],
    quickstart: dict[str, Any],
    request_plan: dict[str, Any],
    registration_surface: dict[str, Any],
    demo_readiness: dict[str, Any],
    demo_playbook: dict[str, Any],
    setup_guidance: dict[str, Any],
    network_entry_profile: dict[str, Any],
    mvp_readiness: dict[str, Any],
    studio_link: dict[str, Any],
    base_url: str | None,
    workflow_path: str,
    session_token: str | None,
) -> dict[str, Any]:
    """Audience-facing brief for presenting the killer MVP without reading raw JSON first."""

    entrypoints = quickstart.get("entrypoints") if isinstance(quickstart.get("entrypoints"), dict) else {}
    request_plan_run = request_plan.get("run") if isinstance(request_plan.get("run"), dict) else {}
    request_plan_http = request_plan_run.get("http") if isinstance(request_plan_run.get("http"), dict) else {}
    harness = request_plan.get("reusable_harness") if isinstance(request_plan.get("reusable_harness"), dict) else {}
    product_goals = mvp_readiness.get("product_goals") if isinstance(mvp_readiness.get("product_goals"), dict) else {}
    goal_count = len(product_goals)
    ready_goal_count = sum(1 for ready in product_goals.values() if ready)
    base = base_url.rstrip("/") if base_url else None
    connect_package_url = _absolute_url(
        base,
        f"/network/connect-package?{urlencode({'workflow_path': workflow_path})}",
    )
    readiness_url = _absolute_url(base, f"/network/readiness?{urlencode({'workflow_path': workflow_path})}")
    readiness_command = _network_quickstart_command(
        workflow_path,
        base_url=base_url,
        session_token=session_token,
        output="readiness",
    )
    verify_command = _network_verify_command(workflow_path, base_url=base_url, session_token=session_token)
    brief_ready = bool(
        mvp_readiness.get("status") == "ready"
        and demo_playbook.get("status") == "ready"
        and demo_readiness.get("status") == "ready"
    )
    playbook_steps = demo_playbook.get("steps") if isinstance(demo_playbook.get("steps"), list) else []
    live_demo_flow = [
        {
            "id": step.get("id"),
            "title": step.get("title"),
            "target": step.get("target"),
            "success_signal": step.get("success_signal"),
        }
        for step in playbook_steps
        if isinstance(step, dict)
    ]
    proof_points = [
        {
            "id": "protocol_boundary",
            "title": "External protocol stays small",
            "evidence_source": "contracts.external",
            "metric": "accepted_kinds",
            "value": "AgentCliCard + RunReceipt",
        },
        {
            "id": "bridge_message_bus",
            "title": "CLI-CLI communication is inspectable",
            "evidence_source": "contracts.internal.bridge_contract",
            "metric": "bridge_routes",
            "value": f"{network_entry_profile.get('harness_agent', {}).get('bridge_route_count', 0)} BridgeMessage routes",
        },
        {
            "id": "reusable_harness_agent",
            "title": "Natural language can call the reusable harness",
            "evidence_source": "agent_workflow_request.reusable_harness",
            "metric": "harness_kind",
            "value": harness.get("kind", "NaturalLanguageWorkflowHarness"),
        },
        {
            "id": "one_shot_network_entry",
            "title": "Other programs can connect in one read",
            "evidence_source": "network_entry_profile",
            "metric": "profile_id",
            "value": network_entry_profile.get("profile_id"),
        },
        {
            "id": "first_call_acceptance",
            "title": "External first-call sequence is replayable",
            "evidence_source": "consumer_quickstart.acceptance",
            "metric": "checks",
            "value": f"{quickstart.get('acceptance', {}).get('check_count', 0)} checks",
        },
        {
            "id": "protocol_facades",
            "title": "MCP/A2A/ACP exports share the same workflow",
            "evidence_source": "protocols",
            "metric": "targets",
            "value": ", ".join(protocol_summary.get("targets", [])),
        },
    ]
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "KillerMvpPresenterBrief",
        "status": "ready" if brief_ready else "needs_attention",
        "headline": "CBN turns CLI tools into a reusable agent-callable network with visible BridgeMessage handoffs.",
        "subheadline": "The demo shows one external contract, one internal bus, one natural-language harness agent, and one Workflow Studio evidence surface.",
        "workflow_path": workflow_path,
        "workflow_id": workflow.get("workflow_id"),
        "audience": ["product_demo", "integration_partner", "developer_platform"],
        "narrative": [
            "Start from the small AgentCliCard/RunReceipt boundary instead of exposing CBN internals.",
            "Convert external tool contracts into ToolManifest records and BridgeMessage selector routes.",
            "Let a reusable harness agent bind natural language to the selected CLI-CLI workflow.",
            "Run macrocli -> transform -> mermaid and inspect artifact, event, audit, and protocol export evidence.",
            "Finish by showing how the next CLI enters through dry-run-first registration.",
        ],
        "proof_points": proof_points,
        "live_demo_flow": live_demo_flow,
        "integration_handoff": {
            "connect_package_url": connect_package_url,
            "readiness_url": readiness_url,
            "studio_url": studio_link.get("url"),
            "run_workflow_url": request_plan_http.get("url") or entrypoints.get("run_workflow", {}).get("url"),
            "verify_command": verify_command,
            "readiness_command": readiness_command,
            "next_cli_command": (registration_surface.get("next_commands") or ["python -m cbn import command --help"])[0],
        },
        "decision_gates": {
            "ready_goal_count": ready_goal_count,
            "goal_count": goal_count,
            "mvp_readiness_score": mvp_readiness.get("score"),
            "setup_status": setup_guidance.get("status"),
            "setup_required": setup_guidance.get("setup_required"),
            "demo_stage_count": demo_readiness.get("stage_count", 0),
            "playbook_step_count": demo_playbook.get("step_count", 0),
        },
        "recommended_next_action": mvp_readiness.get("recommended_next_action", "open_workflow_studio_demo"),
        "next_commands": [verify_command, readiness_command, (registration_surface.get("next_commands") or ["python -m cbn import command --help"])[0]],
    }


def _internal_bridge_contract(bridge_contract: dict[str, Any]) -> dict[str, Any]:
    contract = bridge_contract.get("contract")
    if not isinstance(contract, dict):
        return {}
    return contract


def workflow_studio_demo_link(
    *,
    workflow_path: str = DEFAULT_KILLER_WORKFLOW_PATH,
    daemon_url: str | None = None,
    studio_url: str = "http://127.0.0.1:5177",
    dashboard_url: str = DEFAULT_DASHBOARD_URL,
    session_token: str | None = None,
    agent_message: str = "Run this workflow as a reusable CLI-CLI harness agent and surface setup gates.",
    dry_run: bool = True,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Return a preconfigured Workflow Studio URL for the killer demo."""

    query: dict[str, str] = {
        "workflowPath": workflow_path,
        "agentMessage": agent_message,
        "dryRun": "true" if dry_run else "false",
        "confirmed": "true" if confirmed else "false",
    }
    if daemon_url:
        query["daemonUrl"] = daemon_url.rstrip("/")
    if dashboard_url:
        query["dashboardUrl"] = dashboard_url.rstrip("/")
    if session_token:
        query["sessionToken"] = session_token
    clean_studio_url = studio_url.rstrip("/")
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "WorkflowStudioDemoLink",
        "ok": True,
        "studio_url": clean_studio_url,
        "dashboard_url": dashboard_url.rstrip("/") if dashboard_url else None,
        "daemon_url": daemon_url.rstrip("/") if daemon_url else None,
        "workflow_path": workflow_path,
        "dry_run": dry_run,
        "confirmed": confirmed,
        "session_token_included": bool(session_token),
        "url": f"{clean_studio_url}/?{urlencode(query)}",
        "query": query,
    }


def network_acceptance_report(
    registry: ManifestRegistry,
    *,
    workflow_path: str = DEFAULT_KILLER_WORKFLOW_PATH,
    base_url: str = "http://127.0.0.1:8787",
    studio_url: str = "http://127.0.0.1:5177",
    dashboard_url: str = DEFAULT_DASHBOARD_URL,
    session_token: str | None = None,
    agent_message: str = DEFAULT_AGENT_CONNECT_MESSAGE,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """Run the one-shot network acceptance checklist against a live daemon."""

    package = network_connect_package(
        registry,
        workflow_path=workflow_path,
        base_url=base_url,
        studio_url=studio_url,
        dashboard_url=dashboard_url,
        session_token=session_token,
        agent_message=agent_message,
    )
    quickstart = package.get("consumer_quickstart") if isinstance(package.get("consumer_quickstart"), dict) else {}
    acceptance = quickstart.get("acceptance") if isinstance(quickstart.get("acceptance"), dict) else {}
    mvp_readiness = package.get("mvp_readiness") if isinstance(package.get("mvp_readiness"), dict) else {}
    requests = quickstart.get("requests") if isinstance(quickstart.get("requests"), list) else []
    requests_by_id = {
        str(request.get("id")): request
        for request in requests
        if isinstance(request, dict) and request.get("id")
    }
    results = [
        _run_acceptance_check(check, requests_by_id, timeout_seconds=timeout_seconds)
        for check in acceptance.get("checks", [])
        if isinstance(check, dict)
    ]
    passed = sum(1 for result in results if result["status"] == "passed")
    failed = sum(1 for result in results if result["status"] == "failed")
    skipped = sum(1 for result in results if result["status"] == "skipped")
    total = len(results)
    mvp_ready = bool(mvp_readiness.get("status") == "ready")
    ok = bool(package.get("ok") and mvp_ready and total > 0 and failed == 0 and skipped == 0)
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "NetworkConnectionAcceptanceReport",
        "ok": ok,
        "status": "passed" if ok else "failed" if failed else "skipped" if skipped else "not_run",
        "workflow_path": workflow_path,
        "base_url": base_url.rstrip("/"),
        "summary": {
            "connect_package_ok": bool(package.get("ok")),
            "request_count": len(requests),
            "check_count": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "mvp_readiness_status": mvp_readiness.get("status"),
            "mvp_readiness_score": mvp_readiness.get("score"),
        },
        "acceptance": acceptance,
        "mvp_readiness": mvp_readiness,
        "results": results,
        "next_commands": [
            _network_quickstart_command(workflow_path, base_url=base_url, session_token=session_token),
            _network_quickstart_command(
                workflow_path,
                base_url=base_url,
                session_token=session_token,
                output="readiness",
            ),
            _network_quickstart_command(
                workflow_path,
                base_url=base_url,
                session_token=session_token,
                output="acceptance",
            ),
        ],
    }


def _external_agent_cli_contract() -> dict[str, Any]:
    card = _read_json(CONTRACT_CARD_FIXTURE)
    receipt = _read_json(CONTRACT_RECEIPT_FIXTURE)
    manifests = agent_cli_card_to_tool_manifests(card)
    receipt_mapping = run_receipt_to_cbn_records(receipt)
    package_health = agent_cli_contract_package_health(CONTRACT_ROOT)
    return {
        "ok": bool(manifests)
        and receipt_mapping.get("message", {}).get("kind") == "BridgeMessage"
        and package_health.get("ok"),
        "protocol": "agent-cli-contract",
        "root": str(CONTRACT_ROOT),
        "card_fixture": str(CONTRACT_CARD_FIXTURE),
        "receipt_fixture": str(CONTRACT_RECEIPT_FIXTURE),
        "accepted_kinds": ["AgentCliCard", "RunReceipt"],
        "package_boundary": agent_cli_contract_package_boundary(CONTRACT_ROOT),
        "package_health": package_health,
        "generated_capability_ids": [manifest["metadata"]["id"] for manifest in manifests],
        "receipt_mapping": {
            "kind": receipt_mapping.get("kind"),
            "message_kind": receipt_mapping.get("message", {}).get("kind"),
            "message_channel": (receipt_mapping.get("message", {}).get("metadata") or {}).get("channel"),
            "artifact_count": len(receipt_mapping.get("artifacts", [])),
            "audit_event_type": (receipt_mapping.get("audit_event") or {}).get("type"),
            "event_type": (receipt_mapping.get("event") or {}).get("type"),
        },
    }


def _registration_surface() -> dict[str, Any]:
    return cli_registration_surface(api_version=CONNECT_API_VERSION)


def _endpoint_catalog(*, base_url: str | None, workflow_path: str) -> list[dict[str, Any]]:
    rows = [
        ("GET", "/network/connect-package", "read the full one-shot network connection package"),
        ("GET", "/network/quickstart", "read only the first-call quickstart payload"),
        ("GET", "/network/launch-contract", "read only the redacted launch contract for external programs"),
        ("GET", "/network/entry-profile", "read only the stable external integration profile"),
        ("GET", "/network/readiness", "read only the killer MVP readiness matrix"),
        ("POST", "/network/verify", "run the live network acceptance checklist"),
        ("GET", "/imports/catalog", "read the dry-run-first CLI importer catalog"),
        ("GET", "/health", "confirm daemon reachability"),
        ("GET", "/workflows", "discover registered workflow descriptors"),
        ("GET", f"/workflows?path={workflow_path}", "inspect one workflow DAG"),
        ("GET", f"/messages/contract?workflow_path={workflow_path}", "inspect BridgeMessage selector routes"),
        ("POST", "/workflows/run", "run the workflow with dry_run/confirmed flags"),
        ("GET", f"/protocols/workflows?target=all&path={workflow_path}", "export MCP/A2A/ACP workflow descriptors"),
        ("GET", f"/adapter-agent/node-bundle?workflow_path={workflow_path}", "read reusable harness agent nodes"),
        ("POST", "/adapter-agent/workflow-request-plan", "bind a natural-language agent request to this workflow"),
        ("POST", "/demo/killer", "run the product demo evidence bundle"),
        ("GET", "/events", "tail runtime events"),
        ("GET", "/audit", "tail runtime audit evidence"),
        ("GET", "/artifacts", "list produced artifacts"),
    ]
    return [
        {
            "method": method,
            "path": path,
            "url": f"{base_url.rstrip('/')}{path}" if base_url else path,
            "purpose": purpose,
        }
        for method, path, purpose in rows
    ]


def _protocol_summary(protocol_exports: dict[str, Any]) -> dict[str, Any]:
    exports = protocol_exports.get("exports") if isinstance(protocol_exports.get("exports"), dict) else {}
    mcp = exports.get("mcp") if isinstance(exports.get("mcp"), dict) else {}
    a2a = exports.get("a2a") if isinstance(exports.get("a2a"), dict) else {}
    acp = exports.get("acp") if isinstance(exports.get("acp"), dict) else {}
    return {
        "export_count": len(exports),
        "targets": sorted(str(key) for key in exports),
        "mcp": {
            "workflow_tool_count": len(mcp.get("workflowTools", [])) if isinstance(mcp.get("workflowTools"), list) else 0,
            "wire_facade": _wire_status(mcp),
        },
        "a2a": {
            "skill_count": len(((a2a.get("agentCard") or {}).get("skills") or []))
            if isinstance(a2a.get("agentCard"), dict)
            else 0,
            "wire_facade": _wire_status(a2a),
        },
        "acp": {
            "workflow_count": len(acp.get("workflows", [])) if isinstance(acp.get("workflows"), list) else 0,
            "wire_facade": _wire_status(acp),
        },
    }


def _wire_status(descriptor: dict[str, Any]) -> str:
    if descriptor.get("wire_compatible") is True:
        return "compatible"
    if descriptor.get("wire_compatible") is False:
        return "partial"
    return "unknown"


def _compact_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": workflow.get("valid"),
        "workflow_id": workflow.get("workflow_id"),
        "title": workflow.get("title"),
        "task_count": workflow.get("task_count"),
        "tasks": [
            {
                "id": task.get("id"),
                "uses": task.get("uses"),
                "needs": task.get("needs", []),
                "risk": (task.get("capability") or {}).get("risk"),
                "parser_ref": (task.get("capability") or {}).get("parser_ref"),
            }
            for task in workflow.get("tasks", [])
            if isinstance(task, dict)
        ],
    }


def _compact_agent_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    bridge_message = bundle.get("bridge_message") if isinstance(bundle.get("bridge_message"), dict) else {}
    bridge_metadata = bridge_message.get("metadata") if isinstance(bridge_message.get("metadata"), dict) else {}
    return {
        "kind": bundle.get("kind"),
        "ok": bundle.get("ok"),
        "status": bundle.get("status"),
        "card_count": len(bundle.get("cards", [])),
        "task_count": len(bundle.get("tasks", [])),
        "session": _compact_agent_session(bundle.get("session")),
        "cards": [_compact_agent_card(card) for card in _list_of_dicts(bundle.get("cards"))],
        "harnesses": [_compact_agent_harness(harness) for harness in _list_of_dicts(bundle.get("harnesses"))],
        "tasks": [_compact_agent_task(task) for task in _list_of_dicts(bundle.get("tasks"))],
        "bridge_message_channel": bridge_metadata.get("channel"),
        "bridge_message": {
            "kind": bridge_message.get("kind"),
            "producer": bridge_metadata.get("producer"),
            "channel": bridge_metadata.get("channel"),
            "correlation_id": bridge_metadata.get("correlationId"),
        },
        "workflow_nodes": [
            {
                "id": node.get("id"),
                "agent": node.get("agent"),
                "uses": node.get("uses"),
            }
            for node in bundle.get("workflow_nodes", [])
            if isinstance(node, dict)
        ],
    }


def _compact_agent_session(session: Any) -> dict[str, Any]:
    if not isinstance(session, dict):
        return {}
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    spec = session.get("spec") if isinstance(session.get("spec"), dict) else {}
    return {
        "kind": session.get("kind"),
        "id": metadata.get("id"),
        "agent_id": metadata.get("agentId"),
        "workflow_id": metadata.get("workflowId"),
        "state": spec.get("state"),
    }


def _compact_agent_card(card: dict[str, Any]) -> dict[str, Any]:
    metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
    spec = card.get("spec") if isinstance(card.get("spec"), dict) else {}
    policy = spec.get("policy") if isinstance(spec.get("policy"), dict) else {}
    return {
        "kind": card.get("kind"),
        "id": metadata.get("id"),
        "title": metadata.get("title"),
        "role": metadata.get("role"),
        "status": metadata.get("status"),
        "capabilities": spec.get("capabilities", []),
        "transport": (spec.get("transport") if isinstance(spec.get("transport"), dict) else {}).get("kind"),
        "risk": policy.get("risk"),
    }


def _compact_agent_harness(harness: dict[str, Any]) -> dict[str, Any]:
    metadata = harness.get("metadata") if isinstance(harness.get("metadata"), dict) else {}
    spec = harness.get("spec") if isinstance(harness.get("spec"), dict) else {}
    return {
        "kind": harness.get("kind"),
        "id": metadata.get("id"),
        "agent_id": metadata.get("agentId"),
        "accepts": spec.get("accepts", []),
        "emits": spec.get("emits", []),
    }


def _compact_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    spec = task.get("spec") if isinstance(task.get("spec"), dict) else {}
    return {
        "kind": task.get("kind"),
        "id": metadata.get("id"),
        "agent_id": metadata.get("agentId"),
        "instruction": spec.get("instruction"),
        "uses": spec.get("uses"),
        "selectors": spec.get("selectors", []),
    }


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _compact_workflow_request_plan(plan: dict[str, Any]) -> dict[str, Any]:
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    run = plan.get("run") if isinstance(plan.get("run"), dict) else {}
    reusable = plan.get("reusable_harness") if isinstance(plan.get("reusable_harness"), dict) else {}
    request = plan.get("request") if isinstance(plan.get("request"), dict) else {}
    message = plan.get("bridge_message") if isinstance(plan.get("bridge_message"), dict) else {}
    return {
        "kind": plan.get("kind"),
        "ok": plan.get("ok"),
        "status": plan.get("status"),
        "workflow_path": plan.get("workflow_path"),
        "workflow_id": summary.get("workflow_id"),
        "workflow_title": summary.get("workflow_title"),
        "task_count": summary.get("task_count", 0),
        "bridge_route_count": summary.get("bridge_route_count", 0),
        "agent_card_count": summary.get("agent_card_count", 0),
        "recommended_next_action": summary.get("recommended_next_action"),
        "request": {
            "message": request.get("message"),
            "binding": request.get("binding"),
            "intent": request.get("intent", {}),
        },
        "reusable_harness": {
            "kind": reusable.get("kind"),
            "accepts": reusable.get("accepts", []),
            "emits": reusable.get("emits", []),
            "contract": reusable.get("contract"),
        },
        "run": {
            "payload": run.get("payload", {}),
            "cli": run.get("cli"),
            "http": run.get("http", {}),
        },
        "bridge_routes": [
            {
                "task_id": route.get("task_id"),
                "uses": route.get("uses"),
                "needs": route.get("needs", []),
                "selectors": route.get("selectors", []),
                "communication": route.get("communication"),
            }
            for route in _list_of_dicts(plan.get("bridge_routes"))
        ],
        "bridge_message_channel": (message.get("metadata") or {}).get("channel"),
        "bridge_message": _compact_bridge_message(message),
        "next_commands": plan.get("next_commands", []),
    }


def _compact_bridge_message(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return {
        "kind": message.get("kind"),
        "producer": metadata.get("producer"),
        "channel": metadata.get("channel"),
        "correlation_id": metadata.get("correlationId"),
        "parser_ref": payload.get("parser_ref"),
        "ok": payload.get("ok"),
        "data": {
            "agent_id": data.get("agent_id"),
            "task_id": data.get("task_id"),
            "workflow_id": data.get("workflow_id"),
            "workflow_path": data.get("workflow_path"),
            "task_count": data.get("task_count"),
            "route_count": data.get("route_count"),
            "run_payload": data.get("run_payload", {}),
        },
    }


def _compact_setup_guidance(plan: dict[str, Any]) -> dict[str, Any]:
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    kinds = summary.get("by_kind") if isinstance(summary.get("by_kind"), dict) else {}
    loop = plan.get("long_running_loop") if isinstance(plan.get("long_running_loop"), dict) else {}
    status = loop.get("status") or plan.get("status") or "unknown"
    secret_count = int(kinds.get("setup-secret", 0) or 0)
    setup_command_count = int(kinds.get("setup-command", 0) or 0)
    workflow_capability_count = int(kinds.get("workflow-capability", 0) or 0)
    requires_user_count = int(summary.get("requires_user_count", 0) or 0)
    setup_required = bool(
        status != "ready_to_run"
        or requires_user_count > 0
        or secret_count > 0
        or setup_command_count > 0
    )
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "AdapterAgentSetupGuidance",
        "source_kind": plan.get("kind"),
        "ok": plan.get("ok"),
        "status": status,
        "setup_required": setup_required,
        "next_action": "complete_user_setup" if setup_required else "ready_to_run",
        "workflow_path": plan.get("workflow_path"),
        "summary": summary,
        "requires_user_count": requires_user_count,
        "secret_count": secret_count,
        "setup_command_count": setup_command_count,
        "workflow_capability_count": workflow_capability_count,
        "tool_calls": [_compact_setup_tool_call(call) for call in _list_of_dicts(plan.get("tool_calls"))[:10]],
        "execution_batches": [
            {
                "batch_id": batch.get("batch_id"),
                "mode": batch.get("mode"),
                "concurrency_safe": batch.get("concurrency_safe"),
                "tool_call_ids": batch.get("tool_call_ids", []),
                "tool_use_ids": batch.get("tool_use_ids", []),
                "reason": batch.get("reason"),
            }
            for batch in _list_of_dicts(plan.get("execution_batches"))[:8]
        ],
        "checkpoints": [
            {
                "id": checkpoint.get("id"),
                "owner": checkpoint.get("owner"),
                "status": checkpoint.get("status"),
                "evidence": checkpoint.get("evidence"),
            }
            for checkpoint in _list_of_dicts(loop.get("checkpoints"))[:8]
        ],
        "safety": {
            "read_only": True,
            "executes_tools": False,
            "secret_values_included": False,
            "secrets_must_not_be_pasted_in_chat": True,
        },
    }


def _compact_setup_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    source = call.get("source") if isinstance(call.get("source"), dict) else {}
    permission = call.get("permission_flow") if isinstance(call.get("permission_flow"), dict) else {}
    return {
        "call_id": call.get("call_id"),
        "tool_use_id": call.get("tool_use_id"),
        "kind": call.get("kind"),
        "agent_role": call.get("agent_role"),
        "action": call.get("action"),
        "risk": call.get("risk"),
        "initial_status": call.get("initial_status"),
        "requires_user": call.get("requires_user"),
        "concurrency_safe": call.get("concurrency_safe"),
        "setup_id": source.get("setup_id"),
        "profile": source.get("profile"),
        "command_id": source.get("command_id"),
        "secret_name": source.get("secret_name"),
        "task_id": source.get("task_id"),
        "capability_id": source.get("capability_id"),
        "permission": permission.get("default_behavior"),
        "permission_reason": permission.get("reason"),
    }


def _consumer_quickstart(
    *,
    base_url: str | None,
    workflow_path: str,
    session_token: str | None,
    studio_link: dict[str, Any],
    request_plan: dict[str, Any],
) -> dict[str, Any]:
    """Return machine-readable first calls for external consumers."""

    clean_base_url = base_url.rstrip("/") if base_url else None
    workflow_query = urlencode({"path": workflow_path})
    launch_query = urlencode({"workflow_path": workflow_path})
    contract_query = urlencode({"workflow_path": workflow_path})
    protocol_query = urlencode({"target": "all", "path": workflow_path})
    agent_query = urlencode(
        {
            "workflow_path": workflow_path,
            "message": (request_plan.get("request") or {}).get(
                "message",
                DEFAULT_AGENT_CONNECT_MESSAGE,
            ),
        }
    )
    headers = {"X-CBN-Session": session_token} if session_token else {}
    plan_payload = {
        "workflow_path": workflow_path,
        "message": (request_plan.get("request") or {}).get(
            "message",
            DEFAULT_AGENT_CONNECT_MESSAGE,
        ),
        "dry_run": True,
        "confirmed": False,
    }
    run = request_plan.get("run") if isinstance(request_plan.get("run"), dict) else {}
    run_http = run.get("http") if isinstance(run.get("http"), dict) else {}
    raw_run_payload = run.get("payload") if isinstance(run.get("payload"), dict) else {}
    run_payload = {
        "path": workflow_path,
        "dry_run": raw_run_payload.get("dry_run", True),
        "confirmed": raw_run_payload.get("confirmed", False),
    }
    plan_url = _absolute_url(clean_base_url, "/adapter-agent/workflow-request-plan")
    run_url = run_http.get("url") or _absolute_url(clean_base_url, "/workflows/run")
    entrypoints = {
        "open_studio": studio_link.get("url"),
        "health": _absolute_url(clean_base_url, "/health"),
        "launch_contract": _absolute_url(clean_base_url, f"/network/launch-contract?{launch_query}"),
        "entry_profile": _absolute_url(clean_base_url, f"/network/entry-profile?{launch_query}"),
        "import_catalog": _absolute_url(clean_base_url, "/imports/catalog"),
        "inspect_workflow": _absolute_url(clean_base_url, f"/workflows?{workflow_query}"),
        "inspect_bridge_contract": _absolute_url(clean_base_url, f"/messages/contract?{contract_query}"),
        "inspect_agent_nodes": _absolute_url(clean_base_url, f"/adapter-agent/node-bundle?{agent_query}"),
        "export_protocols": _absolute_url(clean_base_url, f"/protocols/workflows?{protocol_query}"),
        "plan_agent_request": {
            "method": "POST",
            "url": plan_url,
            "json": plan_payload,
        },
        "run_workflow": {
            "method": run_http.get("method", "POST"),
            "url": run_url,
            "json": run_payload,
        },
        "events": _absolute_url(clean_base_url, "/events"),
        "audit": _absolute_url(clean_base_url, "/audit"),
        "artifacts": _absolute_url(clean_base_url, "/artifacts"),
    }
    requests = [
        _quickstart_request("health", "GET", entrypoints["health"], headers=headers),
        _quickstart_request("launch_contract", "GET", entrypoints["launch_contract"], headers=headers),
        _quickstart_request("entry_profile", "GET", entrypoints["entry_profile"], headers=headers),
        _quickstart_request("import_catalog", "GET", entrypoints["import_catalog"], headers=headers),
        _quickstart_request("inspect_workflow", "GET", entrypoints["inspect_workflow"], headers=headers),
        _quickstart_request(
            "inspect_bridge_contract",
            "GET",
            entrypoints["inspect_bridge_contract"],
            headers=headers,
        ),
        _quickstart_request(
            "inspect_agent_nodes",
            "GET",
            entrypoints["inspect_agent_nodes"],
            headers=headers,
        ),
        _quickstart_request(
            "export_protocols",
            "GET",
            entrypoints["export_protocols"],
            headers=headers,
        ),
        _quickstart_request(
            "plan_agent_request",
            "POST",
            plan_url,
            headers=headers,
            json_payload=plan_payload,
        ),
        _quickstart_request(
            "run_workflow",
            run_http.get("method", "POST"),
            run_url,
            headers=headers,
            json_payload=run_payload,
        ),
        _quickstart_request("events", "GET", entrypoints["events"], headers=headers),
        _quickstart_request("audit", "GET", entrypoints["audit"], headers=headers),
        _quickstart_request("artifacts", "GET", entrypoints["artifacts"], headers=headers),
    ]
    return {
        "kind": "NetworkConnectQuickstart",
        "status": "ready" if clean_base_url else "ready_without_daemon_url",
        "required_headers": headers,
        "entrypoints": entrypoints,
        "requests": requests,
        "acceptance": _network_connection_acceptance(workflow_path=workflow_path, requests=requests),
        "sdk_snippets": _quickstart_sdk_snippets(
            workflow_path=workflow_path,
            requests=requests,
            headers=headers,
        ),
        "curl_script": _quickstart_curl_script(requests),
        "powershell_script": _quickstart_powershell_script(requests, headers=headers),
        "sequence": [
            "open_studio",
            "launch_contract",
            "entry_profile",
            "import_catalog",
            "inspect_workflow",
            "inspect_bridge_contract",
            "inspect_agent_nodes",
            "export_protocols",
            "plan_agent_request",
            "run_workflow",
            "read_events_audit_artifacts",
        ],
        "sequence_steps": _quickstart_sequence_steps(
            requests=requests,
            studio_url=studio_link.get("url"),
        ),
    }


def _quickstart_sequence_steps(*, requests: list[dict[str, Any]], studio_url: str | None) -> list[dict[str, Any]]:
    requests_by_id = {str(request.get("id")): request for request in requests if request.get("id")}

    def request_step(
        order: int,
        request_id: str,
        title: str,
        intent: str,
        success_signal: str,
    ) -> dict[str, Any]:
        request = requests_by_id.get(request_id, {})
        return {
            "order": order,
            "id": request_id,
            "kind": "http",
            "title": title,
            "intent": intent,
            "request_id": request_id,
            "method": request.get("method", "GET"),
            "url": request.get("url", ""),
            "success_signal": success_signal,
        }

    return [
        {
            "order": 1,
            "id": "open_studio",
            "kind": "ui",
            "title": "Open Workflow Studio",
            "intent": "Start the visual handoff for the target CLI-CLI workflow.",
            "target": studio_url or "",
            "success_signal": "Studio opens with daemon URL, workflow path, and session token prefilled.",
        },
        request_step(
            2,
            "launch_contract",
            "Read launch contract",
            "Read the redacted minimum contract before parsing the full one-shot package.",
            "ConsumerLaunchContract.status == ready and secret_values_echoed == false.",
        ),
        request_step(
            3,
            "entry_profile",
            "Read entry profile",
            "Read the stable external integration profile before discovering optional importers.",
            "NetworkEntryProfile.status == ready and secret_values_echoed == false.",
        ),
        request_step(
            4,
            "import_catalog",
            "Discover importers",
            "Read the dry-run-first CLI registration catalog before choosing a harness or adapter.",
            "CliRegistrationSurface.status == ready and importer_count >= 1.",
        ),
        request_step(
            5,
            "inspect_workflow",
            "Inspect workflow DAG",
            "Confirm the selected workflow is valid and has CLI tasks before execution.",
            "workflow.valid == true and task_count >= 1.",
        ),
        request_step(
            6,
            "inspect_bridge_contract",
            "Inspect Bridge Contract",
            "Understand ToolManifest, BridgeMessage, Artifact, and selector boundaries.",
            "bridge contract ok and route_count >= 1.",
        ),
        request_step(
            7,
            "inspect_agent_nodes",
            "Inspect harness agent nodes",
            "Read reusable AgentCard, AgentHarness, AgentTask, and BridgeMessage node bindings.",
            "AdapterAgentNodeBundle includes cards, harnesses, and BridgeMessage.",
        ),
        request_step(
            8,
            "export_protocols",
            "Export protocol facades",
            "Expose MCP, A2A, and ACP workflow descriptors from the same internal bus contract.",
            "protocol exports include mcp, a2a, and acp.",
        ),
        request_step(
            9,
            "plan_agent_request",
            "Plan natural-language run",
            "Bind a natural-language request to the reusable CLI-CLI harness run contract.",
            "AdapterAgentWorkflowRequestPlan.reusable_harness.kind == NaturalLanguageWorkflowHarness.",
        ),
        request_step(
            10,
            "run_workflow",
            "Run workflow",
            "Execute the CLI-CLI chain through the daemon with dry-run/confirmation gates.",
            "workflow run receipt status == completed.",
        ),
        {
            "order": 11,
            "id": "read_evidence",
            "kind": "evidence",
            "title": "Read evidence",
            "intent": "Collect runtime events, audit records, and artifacts after the workflow call.",
            "request_ids": ["events", "audit", "artifacts"],
            "success_signal": "events, audit, and artifacts endpoints return non-empty JSON arrays.",
        },
    ]


def _quickstart_sdk_snippets(
    *,
    workflow_path: str,
    requests: list[dict[str, Any]],
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    requests_by_id = {str(request.get("id")): request for request in requests if request.get("id")}
    required_ids = [
        "health",
        "launch_contract",
        "entry_profile",
        "import_catalog",
        "plan_agent_request",
        "run_workflow",
        "events",
        "audit",
        "artifacts",
    ]
    python_code = _python_consumer_snippet(requests_by_id, headers=headers)
    typescript_code = _typescript_consumer_snippet(requests_by_id, headers=headers)
    return [
        {
            "id": "python-stdlib-consumer",
            "title": "Python stdlib consumer",
            "language": "python",
            "runtime": "python>=3.10",
            "entrypoint": "run_workflow",
            "workflow_path": workflow_path,
            "uses_request_ids": required_ids,
            "code": python_code,
            "safety": {
                "dry_run": True,
                "confirmed": False,
                "writes_files": False,
                "requires_daemon": True,
            },
        },
        {
            "id": "typescript-fetch-consumer",
            "title": "TypeScript fetch consumer",
            "language": "typescript",
            "runtime": "node>=18 or browser fetch",
            "entrypoint": "run_workflow",
            "workflow_path": workflow_path,
            "uses_request_ids": required_ids,
            "code": typescript_code,
            "safety": {
                "dry_run": True,
                "confirmed": False,
                "writes_files": False,
                "requires_daemon": True,
            },
        },
    ]


def _python_consumer_snippet(requests_by_id: dict[str, dict[str, Any]], *, headers: dict[str, str]) -> str:
    def request_line(request_id: str) -> str:
        request = requests_by_id[request_id]
        payload = request.get("json") if isinstance(request.get("json"), dict) else None
        payload_literal = repr(payload) if payload is not None else "None"
        return (
            f"    {request_id!r}: "
            f"{{'method': {str(request.get('method') or 'GET')!r}, 'url': {str(request.get('url') or '')!r}, "
            f"'json': {payload_literal}}},"
        )

    request_lines = "\n".join(
        request_line(request_id)
        for request_id in [
            "health",
            "launch_contract",
            "entry_profile",
            "import_catalog",
            "plan_agent_request",
            "run_workflow",
            "events",
            "audit",
            "artifacts",
        ]
        if request_id in requests_by_id
    )
    return "\n".join(
        [
            "import json",
            "import urllib.request",
            "",
            f"HEADERS = {json.dumps(headers, ensure_ascii=False)}",
            "REQUESTS = {",
            request_lines,
            "}",
            "",
            "def call(request_id):",
            "    request = REQUESTS[request_id]",
            "    body = None",
            "    headers = dict(HEADERS)",
            "    if request['json'] is not None:",
            "        body = json.dumps(request['json']).encode('utf-8')",
            "        headers['Content-Type'] = 'application/json'",
            "    http_request = urllib.request.Request(request['url'], data=body, headers=headers, method=request['method'])",
            "    with urllib.request.urlopen(http_request, timeout=30) as response:",
            "        return json.loads(response.read().decode('utf-8'))",
            "",
            "call('health')",
            "launch_contract = call('launch_contract')",
            "entry_profile = call('entry_profile')",
            "catalog = call('import_catalog')",
            "plan = call('plan_agent_request')",
            "receipt = call('run_workflow')",
            "evidence = {key: call(key) for key in ('events', 'audit', 'artifacts')}",
            "print(json.dumps({'launch_contract': launch_contract.get('status'), 'entry_profile': entry_profile.get('status'), 'importers': catalog.get('importer_count'), 'plan': plan.get('kind'), 'workflow_status': receipt.get('status'), 'evidence': {k: len(v) for k, v in evidence.items()}}, indent=2))",
        ]
    )


def _typescript_consumer_snippet(requests_by_id: dict[str, dict[str, Any]], *, headers: dict[str, str]) -> str:
    serializable_requests = {
        request_id: {
            "method": request.get("method") or "GET",
            "url": request.get("url") or "",
            "json": request.get("json") if isinstance(request.get("json"), dict) else None,
        }
        for request_id, request in requests_by_id.items()
        if request_id in {"health", "launch_contract", "entry_profile", "import_catalog", "plan_agent_request", "run_workflow", "events", "audit", "artifacts"}
    }
    return "\n".join(
        [
            f"const headers = {json.dumps(headers, ensure_ascii=False)};",
            f"const requests = {json.dumps(serializable_requests, ensure_ascii=False, indent=2)};",
            "",
            "async function call(requestId: keyof typeof requests) {",
            "  const request = requests[requestId];",
            "  const response = await fetch(request.url, {",
            "    method: request.method,",
            "    headers: request.json ? { ...headers, 'Content-Type': 'application/json' } : headers,",
            "    body: request.json ? JSON.stringify(request.json) : undefined,",
            "  });",
            "  if (!response.ok) throw new Error(`${requestId} failed: ${response.status}`);",
            "  return response.json();",
            "}",
            "",
            "await call('health');",
            "const launchContract = await call('launch_contract');",
            "const entryProfile = await call('entry_profile');",
            "const catalog = await call('import_catalog');",
            "const plan = await call('plan_agent_request');",
            "const receipt = await call('run_workflow');",
            "const [events, audit, artifacts] = await Promise.all([call('events'), call('audit'), call('artifacts')]);",
            "console.log({ launchContract: launchContract.status, entryProfile: entryProfile.status, importers: catalog.importer_count, plan: plan.kind, workflowStatus: receipt.status, evidence: { events: events.length, audit: audit.length, artifacts: artifacts.length } });",
        ]
    )


def _network_connection_acceptance(*, workflow_path: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
    request_ids = [str(request.get("id", "")) for request in requests if request.get("id")]
    checks = [
        _acceptance_check(
            "daemon_reachable",
            "health",
            "CBN daemon answers authenticated first-call requests.",
            {"http_status": 200, "json.status": "ok"},
        ),
        _acceptance_check(
            "launch_contract_readable",
            "launch_contract",
            "External consumers can fetch the redacted minimum launch contract without reading the full package.",
            {
                "http_status": 200,
                "json.kind": "ConsumerLaunchContract",
                "json.status": "ready",
                "json.auth.secret_values_echoed": False,
                "json.harness_agent.kind": "NaturalLanguageWorkflowHarness",
            },
        ),
        _acceptance_check(
            "entry_profile_readable",
            "entry_profile",
            "External consumers can fetch the redacted stable entry profile before reading optional surfaces.",
            {
                "http_status": 200,
                "json.kind": "NetworkEntryProfile",
                "json.status": "ready",
                "json.auth.secret_values_echoed": False,
                "json.compatibility.internal_bus": "CBN BridgeMessage",
            },
        ),
        _acceptance_check(
            "import_catalog_readable",
            "import_catalog",
            "External consumers can discover CLI registration importers before choosing a harness.",
            {
                "http_status": 200,
                "json.kind": "CliRegistrationSurface",
                "json.status": "ready",
                "json.importer_count_min": 1,
            },
        ),
        _acceptance_check(
            "workflow_dag_loads",
            "inspect_workflow",
            "The selected CLI-CLI workflow DAG can be inspected before execution.",
            {"http_status": 200, "json.valid": True, "json.task_count_min": 1},
        ),
        _acceptance_check(
            "bridge_contract_routes",
            "inspect_bridge_contract",
            "BridgeMessage selector routes are available for CLI-CLI handoff inspection.",
            {"http_status": 200, "json.ok": True, "json.summary.route_count_min": 1},
        ),
        _acceptance_check(
            "agent_nodes_readable",
            "inspect_agent_nodes",
            "Reusable harness agent nodes can be inspected before execution.",
            {
                "http_status": 200,
                "json.kind": "AdapterAgentNodeBundle",
                "json.ok": True,
                "json.cards_count_min": 1,
                "json.harnesses_count_min": 1,
                "json.bridge_message.kind": "BridgeMessage",
            },
        ),
        _acceptance_check(
            "protocol_exports_readable",
            "export_protocols",
            "MCP/A2A/ACP workflow descriptors can be exported for external protocol facades.",
            {
                "http_status": 200,
                "json.exports.mcp.protocol": "mcp",
                "json.exports.a2a.protocol": "a2a",
                "json.exports.acp.protocol": "acp",
            },
        ),
        _acceptance_check(
            "natural_language_harness_plan",
            "plan_agent_request",
            "A reusable harness agent can bind natural language to the workflow run contract.",
            {
                "http_status": 200,
                "json.kind": "AdapterAgentWorkflowRequestPlan",
                "json.ok": True,
                "json.reusable_harness.kind": "NaturalLanguageWorkflowHarness",
            },
        ),
        _acceptance_check(
            "workflow_run_receipt",
            "run_workflow",
            "The daemon can produce a workflow run receipt for the CLI-CLI chain.",
            {"http_status": 200, "json.status": "completed", "json.workflow_id_type": "string"},
        ),
        _acceptance_check(
            "runtime_events_readable",
            "events",
            "Runtime events include evidence after the workflow call.",
            {"http_status": 200, "json.type": "array", "json.count_min": 1},
        ),
        _acceptance_check(
            "audit_evidence_readable",
            "audit",
            "Audit evidence includes records for demo and integration review.",
            {"http_status": 200, "json.type": "array", "json.count_min": 1},
        ),
        _acceptance_check(
            "artifacts_readable",
            "artifacts",
            "Produced artifacts can be listed by the consumer after workflow execution.",
            {"http_status": 200, "json.type": "array", "json.count_min": 1},
        ),
    ]
    return {
        "kind": "NetworkConnectionAcceptance",
        "status": "ready",
        "workflow_path": workflow_path,
        "required_request_ids": request_ids,
        "check_count": len(checks),
        "checks": checks,
        "success_signals": [
            "health.status == ok",
            "consumer_launch_contract.status == ready",
            "network_entry_profile.status == ready",
            "import_catalog.importer_count >= 1",
            "workflow.valid == true",
            "bridge_contract.summary.route_count >= 1",
            "agent_node_bundle.kind == AdapterAgentNodeBundle",
            "protocol_exports include mcp, a2a, acp",
            "agent_workflow_request.reusable_harness.kind == NaturalLanguageWorkflowHarness",
            "workflow_run.status == completed",
            "events/audit/artifacts endpoints return non-empty JSON arrays after run",
        ],
        "failure_recovery": [
            "If health fails, verify daemon URL and X-CBN-Session.",
            "If launch_contract fails, verify the daemon exposes /network/launch-contract from the current CBN build.",
            "If entry_profile fails, verify the daemon exposes /network/entry-profile and redacts session tokens.",
            "If import_catalog fails, verify the daemon exposes /imports/catalog from the current CBN build.",
            "If workflow inspection fails, verify workflow_path and required manifests.",
            "If run_workflow fails, rerun plan_agent_request and inspect bridge routes before retrying.",
        ],
    }


def _acceptance_check(
    check_id: str,
    request_id: str,
    proves: str,
    expect: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": check_id,
        "request_id": request_id,
        "proves": proves,
        "expect": expect,
    }


def _run_acceptance_check(
    check: dict[str, Any],
    requests_by_id: dict[str, dict[str, Any]],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    check_id = str(check.get("id") or check.get("request_id") or "acceptance_check")
    request_id = str(check.get("request_id") or "")
    request = requests_by_id.get(request_id)
    if request is None:
        return {
            "check_id": check_id,
            "request_id": request_id or "unknown",
            "status": "skipped",
            "proves": check.get("proves"),
            "expect": check.get("expect", {}),
            "error": "matching quickstart request not found",
        }
    response = _execute_quickstart_request(request, timeout_seconds=timeout_seconds)
    if response.get("error"):
        return {
            "check_id": check_id,
            "request_id": request_id,
            "status": "failed",
            "http_status": response.get("http_status", 0),
            "proves": check.get("proves"),
            "expect": check.get("expect", {}),
            "error": response.get("error"),
        }
    evaluation = _evaluate_acceptance_expectation(
        check.get("expect", {}) if isinstance(check.get("expect"), dict) else {},
        response.get("payload"),
        int(response.get("http_status", 0)),
    )
    return {
        "check_id": check_id,
        "request_id": request_id,
        "status": "passed" if evaluation["passed"] else "failed",
        "http_status": response.get("http_status", 0),
        "proves": check.get("proves"),
        "expect": check.get("expect", {}),
        "evidence": evaluation["evidence"],
        "error": evaluation.get("error"),
    }


def _execute_quickstart_request(request: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    method = str(request.get("method") or "GET")
    url = str(request.get("url") or "")
    headers = {
        str(key): str(value)
        for key, value in (request.get("headers") if isinstance(request.get("headers"), dict) else {}).items()
    }
    data = None
    if isinstance(request.get("json"), dict):
        headers["Content-Type"] = "application/json"
        data = json.dumps(request["json"], ensure_ascii=False).encode("utf-8")
    try:
        http_request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
            return {
                "http_status": response.status,
                "payload": _decode_json_body(response.read()),
            }
    except urllib.error.HTTPError as exc:
        return {
            "http_status": exc.code,
            "payload": _decode_json_body(exc.read()),
        }
    except urllib.error.URLError as exc:
        return {
            "http_status": 0,
            "payload": None,
            "error": str(exc.reason),
        }
    except TimeoutError as exc:
        return {
            "http_status": 0,
            "payload": None,
            "error": str(exc),
        }


def _decode_json_body(body: bytes) -> Any:
    if not body:
        return None
    text = body.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _evaluate_acceptance_expectation(
    expect: dict[str, Any],
    payload: Any,
    http_status: int,
) -> dict[str, Any]:
    evidence = {}
    failures = []
    for key, expected in expect.items():
        actual = _acceptance_actual_value(str(key), payload, http_status)
        ok = _acceptance_value_matches(str(key), actual, expected)
        evidence[str(key)] = {"expected": expected, "actual": actual, "ok": ok}
        if not ok:
            failures.append(f"{key} expected {expected!r} but got {actual!r}")
    return {
        "passed": not failures,
        "evidence": evidence,
        "error": "; ".join(failures) if failures else None,
    }


def _acceptance_actual_value(key: str, payload: Any, http_status: int) -> Any:
    if key == "http_status":
        return http_status
    if not key.startswith("json."):
        return None
    json_key = key.removeprefix("json.")
    if json_key == "type":
        return _json_type_name(payload)
    if json_key in {"count_min", "length_min"}:
        return len(payload) if isinstance(payload, (list, dict, str)) else None
    if json_key.endswith("_count_min"):
        value = _json_path(payload, json_key.removesuffix("_count_min"))
        if isinstance(value, (list, dict, str)):
            return len(value)
    if json_key.endswith("_min"):
        return _json_path(payload, json_key.removesuffix("_min"))
    if json_key.endswith("_type"):
        return _json_type_name(_json_path(payload, json_key.removesuffix("_type")))
    return _json_path(payload, json_key)


def _acceptance_value_matches(key: str, actual: Any, expected: Any) -> bool:
    if key.endswith("_min") and isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual >= expected
    return actual == expected


def _json_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _json_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__


def _quickstart_request(
    request_id: str,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "id": request_id,
        "method": method,
        "url": url,
        "headers": headers,
    }
    if json_payload is not None:
        request["json"] = json_payload
    request["curl"] = _quickstart_curl(method=method, url=url, headers=headers, json_payload=json_payload)
    return request


def _quickstart_curl_script(requests: list[dict[str, Any]]) -> str:
    lines = ["set -e"]
    lines.extend(str(request.get("curl", "")) for request in requests if request.get("curl"))
    return "\n".join(lines)


def _quickstart_powershell_script(requests: list[dict[str, Any]], *, headers: dict[str, str]) -> str:
    lines = ["$ErrorActionPreference = 'Stop'"]
    lines.append(f"$Headers = {_powershell_hashtable(headers)}")
    for request in requests:
        method = _powershell_quote(str(request.get("method", "GET")))
        url = _powershell_quote(str(request.get("url", "")))
        body = request.get("json")
        if isinstance(body, dict):
            variable = "$Body_" + str(request.get("id", "request")).replace("-", "_")
            lines.append(f"{variable} = @'")
            lines.append(json.dumps(body, ensure_ascii=False))
            lines.append("'@")
            lines.append(
                f"Invoke-RestMethod -Method {method} -Uri {url} -Headers $Headers "
                f"-ContentType 'application/json' -Body {variable}"
            )
        else:
            lines.append(f"Invoke-RestMethod -Method {method} -Uri {url} -Headers $Headers")
    return "\n".join(lines)


def _quickstart_curl(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any] | None,
) -> str:
    parts = ["curl", "-X", method, _shell_quote(url)]
    for key, value in headers.items():
        parts.extend(["-H", _shell_quote(f"{key}: {value}")])
    if json_payload is not None:
        parts.extend(["-H", _shell_quote("Content-Type: application/json")])
        parts.extend(["--data", _shell_quote(json.dumps(json_payload, ensure_ascii=False))])
    return " ".join(parts)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _powershell_hashtable(values: dict[str, str]) -> str:
    if not values:
        return "@{}"
    pairs = [f"{_powershell_quote(key)} = {_powershell_quote(value)}" for key, value in values.items()]
    return "@{ " + "; ".join(pairs) + " }"


def _absolute_url(base_url: str | None, path: str) -> str:
    return f"{base_url}{path}" if base_url else path


def _next_commands(workflow_path: str, *, base_url: str | None, session_token: str | None) -> list[str]:
    return [
        _network_verify_command(workflow_path, base_url=base_url, session_token=session_token),
        f"python -m cbn_adapter_agent --workflow-request-plan --workflow-path {workflow_path}",
        f"python -m cbn workflow inspect {workflow_path}",
        f"python -m cbn protocol export-workflows all --path {workflow_path}",
        f"python -m cbn demo killer --workflow-path {workflow_path} --run --dry-run",
    ]


def _network_verify_command(workflow_path: str, *, base_url: str | None, session_token: str | None) -> str:
    args = ["python", "-m", "cbn", "network", "verify", "--workflow-path", workflow_path]
    if base_url:
        args.extend(["--base-url", base_url.rstrip("/")])
    if session_token:
        args.extend(["--session-token", session_token])
    return _command(args)


def _network_quickstart_command(
    workflow_path: str,
    *,
    base_url: str | None,
    session_token: str | None,
    output: str | None = None,
) -> str:
    args = ["python", "-m", "cbn", "network", "quickstart", "--workflow-path", workflow_path]
    if base_url:
        args.extend(["--base-url", base_url.rstrip("/")])
    if session_token:
        args.extend(["--session-token", session_token])
    if output:
        args.extend(["--output", output])
    return _command(args)


def _command(args: list[str]) -> str:
    return " ".join(shlex.quote(str(arg)) for arg in args)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
