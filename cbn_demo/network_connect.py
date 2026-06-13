"""One-shot network connection package for external CBN consumers."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
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
from cbn_demo.network_specs import (
    CONNECT_API_VERSION,
    DEFAULT_AGENT_CONNECT_MESSAGE,
    QUICKSTART_EVIDENCE_REQUEST_IDS,
    QUICKSTART_GET_REQUEST_IDS,
    QUICKSTART_SEQUENCE,
)
from cbn_demo.network_acceptance import network_connection_acceptance, run_acceptance_check
from cbn_demo.network_contracts import (
    NetworkConsumerManifestInput,
    consumer_launch_contract as build_consumer_launch_contract,
    consumer_sdk_bootstrap as build_consumer_sdk_bootstrap,
    network_entry_profile as build_network_entry_profile,
    network_consumer_manifest as build_network_consumer_manifest,
    network_harness_agent_contract as build_network_harness_agent_contract,
)
from cbn_demo.network_quickstart import (
    quickstart_curl_script,
    quickstart_powershell_script,
    quickstart_request,
    quickstart_sdk_snippets,
    quickstart_sequence_steps,
)
from cbn_plugins.cli_anything import CliAnythingHub
from cbn_core.bridge_contract import workflow_bridge_contract_report
from cbn_tools.direct_cli_readiness import direct_cli_readiness_report
from cbn_protocol.exports import export_all_workflow_protocols
from cbn_workflow.catalog import inspect_workflow


CONTRACT_ROOT = Path("external_protocols/agent-cli-contract")
CONTRACT_CARD_FIXTURE = CONTRACT_ROOT / "fixtures/agent-cli-card.valid.json"
CONTRACT_RECEIPT_FIXTURE = CONTRACT_ROOT / "fixtures/run-receipt.valid.json"
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:5173"

_MVP_DEMO_PHASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "open_network_surface",
        "title": "Open the CBN network surface",
        "narrative": (
            "Establish that Workflow Studio is the user-facing surface and the connect package is the "
            "one-shot entrypoint."
        ),
        "playbook_step_ids": ["open_workflow_studio", "inspect_one_shot_contract"],
        "command_ids": ["connect_package"],
        "evidence_sources": ["workflow_studio", "network_entry_profile", "contracts.external"],
        "success_signal": (
            "Studio opens with the target workflow and Connect shows external protocol plus internal bus contracts."
        ),
    },
    {
        "id": "show_cli_cli_protocol",
        "title": "Show CLI-CLI protocol handoff",
        "narrative": (
            "Explain how AgentCliCard enters CBN, becomes ToolManifest, and routes values through "
            "BridgeMessage selectors."
        ),
        "playbook_step_ids": ["inspect_one_shot_contract"],
        "command_ids": ["connect_package"],
        "evidence_sources": ["contracts.internal.bridge_contract", "workflow", "agent_workflow_request.bridge_routes"],
        "success_signal": "BridgeMessage route count is visible and selector handoffs can be inspected before execution.",
    },
    {
        "id": "call_with_harness_agent",
        "title": "Call the workflow through a reusable harness agent",
        "narrative": (
            "Demonstrate that natural language can bind to the selected CLI-CLI workflow through a reusable "
            "agent contract."
        ),
        "playbook_step_ids": ["show_sdk_bootstrap", "verify_network_acceptance"],
        "command_ids": ["plan_harness", "sdk_bootstrap"],
        "evidence_sources": ["network_harness_agent", "consumer_sdk_bootstrap", "agent_workflow_request"],
        "success_signal": "NaturalLanguageWorkflowHarness is ready and the SDK bootstrap exposes typed run_workflow responses.",
    },
    {
        "id": "run_and_inspect_evidence",
        "title": "Run the killer workflow and inspect evidence",
        "narrative": "Run macrocli -> transform -> mermaid, then show artifact, event, and audit evidence from the same run.",
        "playbook_step_ids": ["run_killer_demo", "verify_network_acceptance"],
        "command_ids": ["run_demo"],
        "evidence_sources": ["demo_readiness", "demo_playbook", "events", "audit", "artifacts"],
        "success_signal": "Artifact, event, and audit endpoints all have replayable acceptance checks.",
    },
    {
        "id": "prove_extensibility",
        "title": "Prove protocol facades and next-CLI onboarding",
        "narrative": "Export MCP/A2A/ACP descriptors and show the dry-run-first path for registering another CLI.",
        "playbook_step_ids": ["show_protocol_facades", "register_next_cli"],
        "command_ids": ["export_protocols", "register_next_cli"],
        "evidence_sources": ["protocols", "registration_surface", "direct_cli_readiness"],
        "success_signal": (
            "Protocol targets include mcp, a2a, and acp, and importers cover CLI-Anything, MCP, skill, and "
            "parser fixtures."
        ),
    },
)

_MVP_PRESENTER_PROOF_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("protocol_boundary", "External protocol stays small", "contracts.external", "accepted_kinds"),
    ("bridge_message_bus", "CLI-CLI communication is inspectable", "contracts.internal.bridge_contract", "bridge_routes"),
    (
        "reusable_harness_agent",
        "Natural language can call the reusable harness",
        "agent_workflow_request.reusable_harness",
        "harness_kind",
    ),
    ("one_shot_network_entry", "Other programs can connect in one read", "network_entry_profile", "profile_id"),
    ("sdk_bootstrap_handoff", "SDKs get a small typed bootstrap", "consumer_sdk_bootstrap", "requests"),
    (
        "first_call_acceptance",
        "External first-call sequence is replayable",
        "consumer_quickstart.acceptance",
        "checks",
    ),
    ("protocol_facades", "MCP/A2A/ACP exports share the same workflow", "protocols", "targets"),
)


@dataclass(frozen=True)
class MvpDemoScriptInput:
    workflow: dict[str, Any]
    workflow_path: str
    protocol_summary: dict[str, Any]
    quickstart: dict[str, Any]
    demo_readiness: dict[str, Any]
    demo_playbook: dict[str, Any]
    setup_guidance: dict[str, Any]
    registration_surface: dict[str, Any]
    network_entry_profile: dict[str, Any]
    network_harness_agent: dict[str, Any]
    consumer_sdk_bootstrap: dict[str, Any]
    command_deck: list[dict[str, Any]]


@dataclass(frozen=True)
class MvpReadinessInput:
    workflow: dict[str, Any]
    bridge_contract: dict[str, Any]
    external_contract: dict[str, Any]
    protocol_summary: dict[str, Any]
    request_plan: dict[str, Any]
    setup_guidance: dict[str, Any]
    registration_surface: dict[str, Any]
    demo_readiness: dict[str, Any]
    demo_playbook: dict[str, Any]
    quickstart: dict[str, Any]
    plugin_health: dict[str, Any]
    direct_cli_readiness: dict[str, Any]
    studio_link: dict[str, Any]
    network_entry_profile: dict[str, Any]
    network_harness_agent: dict[str, Any]
    consumer_sdk_bootstrap: dict[str, Any]
    presenter_command_deck: list[dict[str, Any]]
    mvp_demo_script: dict[str, Any]


@dataclass(frozen=True)
class MvpPresenterInput:
    workflow: dict[str, Any]
    protocol_summary: dict[str, Any]
    quickstart: dict[str, Any]
    request_plan: dict[str, Any]
    registration_surface: dict[str, Any]
    demo_readiness: dict[str, Any]
    demo_playbook: dict[str, Any]
    setup_guidance: dict[str, Any]
    network_entry_profile: dict[str, Any]
    mvp_readiness: dict[str, Any]
    studio_link: dict[str, Any]
    base_url: str | None
    workflow_path: str
    session_token: str | None
    command_deck: list[dict[str, Any]]


@dataclass(frozen=True)
class WorkflowStudioDemoLinkRequest:
    workflow_path: str = DEFAULT_KILLER_WORKFLOW_PATH
    daemon_url: str | None = None
    studio_url: str = "http://127.0.0.1:5177"
    dashboard_url: str = DEFAULT_DASHBOARD_URL
    session_token: str | None = None
    agent_message: str = "Run this workflow as a reusable CLI-CLI harness agent and surface setup gates."
    dry_run: bool = True
    confirmed: bool = False


@dataclass(frozen=True)
class NetworkAcceptanceReportRequest:
    workflow_path: str = DEFAULT_KILLER_WORKFLOW_PATH
    base_url: str = "http://127.0.0.1:8787"
    studio_url: str = "http://127.0.0.1:5177"
    dashboard_url: str = DEFAULT_DASHBOARD_URL
    session_token: str | None = None
    agent_message: str = DEFAULT_AGENT_CONNECT_MESSAGE
    timeout_seconds: float = 8.0


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

    state = _network_connect_package_state(locals())
    return _network_connect_payload(
        workflow_path=workflow_path,
        base_url=base_url,
        session_token=session_token,
        state=state,
    )


def _network_connect_package_state(params: dict[str, Any]) -> dict[str, Any]:
    state = _network_connect_base_state(
        registry=params["registry"],
        workflow_path=params["workflow_path"],
        base_url=params["base_url"],
        studio_url=params["studio_url"],
        dashboard_url=params["dashboard_url"],
        session_token=params["session_token"],
        agent_message=params["agent_message"],
    )
    state.update(
        _network_connect_quickstart_state(
            registry=params["registry"],
            workflow_path=params["workflow_path"],
            base_url=params["base_url"],
            session_token=params["session_token"],
            state=state,
        )
    )
    state.update(
        _network_connect_profile_state(
            workflow_path=params["workflow_path"],
            base_url=params["base_url"],
            session_token=params["session_token"],
            agent_message=params["agent_message"],
            state=state,
        )
    )
    state.update(
        _network_connect_mvp_state(
            workflow_path=params["workflow_path"],
            base_url=params["base_url"],
            session_token=params["session_token"],
            state=state,
        )
    )
    state.update(_network_connect_consumer_state(workflow_path=params["workflow_path"], state=state))
    return state


def _network_connect_base_state(
    *,
    registry: ManifestRegistry,
    workflow_path: str,
    base_url: str | None,
    studio_url: str,
    dashboard_url: str,
    session_token: str | None,
    agent_message: str,
) -> dict[str, Any]:
    workflow = inspect_workflow(Path(workflow_path), registry=registry)
    bridge_contract = workflow_bridge_contract_report(registry, workflow_path=workflow_path)
    protocol_exports = export_all_workflow_protocols(registry, workflow_path=workflow_path)
    agent_bundle = build_adapter_agent_node_bundle(workflow_path=workflow_path, message=agent_message)
    request_plan = build_agent_workflow_request_plan(
        workflow_path=workflow_path,
        message=agent_message,
        base_url=base_url,
        dry_run=True,
        confirmed=False,
    )
    setup_guidance = _compact_setup_guidance(
        build_agent_tool_call_plan(workflow_path=workflow_path, message=agent_message)
    )
    external_contract = _external_agent_cli_contract()
    protocol_summary = _protocol_summary(protocol_exports)
    return _network_connect_base_payload(locals())


def _network_connect_base_payload(context: dict[str, Any]) -> dict[str, Any]:
    bridge_contract = context["bridge_contract"]
    external_contract = context["external_contract"]
    protocol_summary = context["protocol_summary"]
    return {
        "workflow": context["workflow"],
        "bridge_contract": bridge_contract,
        "protocol_exports": context["protocol_exports"],
        "agent_bundle": context["agent_bundle"],
        "request_plan": context["request_plan"],
        "compact_agent_bundle": _compact_agent_bundle(context["agent_bundle"]),
        "compact_request_plan": _compact_workflow_request_plan(context["request_plan"]),
        "setup_guidance": context["setup_guidance"],
        "external_contract": external_contract,
        "internal_contract": _internal_bridge_contract(bridge_contract),
        "protocol_summary": protocol_summary,
        "endpoint_catalog": _endpoint_catalog(
            base_url=context["base_url"],
            workflow_path=context["workflow_path"],
        ),
        "studio_link": workflow_studio_demo_link(
            workflow_path=context["workflow_path"],
            daemon_url=context["base_url"],
            studio_url=context["studio_url"],
            dashboard_url=context["dashboard_url"],
            session_token=context["session_token"],
            agent_message=context["agent_message"],
            dry_run=True,
            confirmed=False,
        ),
        "ok": bool(
            context["workflow"].get("valid")
            and bridge_contract.get("ok")
            and external_contract.get("ok")
            and protocol_summary["export_count"] >= 3
        ),
    }


def _network_connect_quickstart_state(
    *,
    registry: ManifestRegistry,
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    quickstart = _consumer_quickstart(
        base_url=base_url,
        workflow_path=workflow_path,
        session_token=session_token,
        studio_link=state["studio_link"],
        request_plan=state["request_plan"],
    )
    demo_readiness = _demo_readiness(workflow_path, base_url, session_token, state)
    direct_cli_readiness = direct_cli_readiness_report(registry=registry)
    network_harness_agent = build_network_harness_agent_contract(
        workflow_path=workflow_path,
        base_url=base_url,
        quickstart=quickstart,
        request_plan=state["request_plan"],
        compact_request=state["compact_request_plan"],
        compact_bundle=state["compact_agent_bundle"],
        setup_guidance=state["setup_guidance"],
    )
    return {
        "quickstart": quickstart,
        "demo_readiness": demo_readiness,
        "registration_surface": _registration_surface(),
        "plugin_health": _plugin_health(),
        "direct_cli_readiness": direct_cli_readiness,
        "network_harness_agent": network_harness_agent,
    }


def _network_connect_profile_state(
    *,
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
    agent_message: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    demo_playbook = _profile_demo_playbook(workflow_path, base_url, session_token, state)
    network_entry_profile = _profile_entry_profile(workflow_path, base_url, state, demo_playbook)
    consumer_sdk_bootstrap = _profile_sdk_bootstrap(workflow_path, state, network_entry_profile)
    presenter_command_deck = _profile_presenter_commands(
        workflow_path=workflow_path,
        base_url=base_url,
        session_token=session_token,
        state=state,
        agent_message=agent_message,
    )
    return {
        "demo_playbook": demo_playbook,
        "network_entry_profile": network_entry_profile,
        "consumer_sdk_bootstrap": consumer_sdk_bootstrap,
        "presenter_command_deck": presenter_command_deck,
        "mvp_demo_script": _profile_demo_script(
            workflow_path=workflow_path,
            state=state,
            demo_playbook=demo_playbook,
            network_entry_profile=network_entry_profile,
            consumer_sdk_bootstrap=consumer_sdk_bootstrap,
            presenter_command_deck=presenter_command_deck,
        ),
    }


def _profile_demo_playbook(
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    return _demo_playbook(
        workflow_path=workflow_path,
        studio_link=state["studio_link"],
        demo_readiness=state["demo_readiness"],
        quickstart=state["quickstart"],
        registration_surface=state["registration_surface"],
        base_url=base_url,
        session_token=session_token,
    )


def _profile_entry_profile(
    workflow_path: str,
    base_url: str | None,
    state: dict[str, Any],
    demo_playbook: dict[str, Any],
) -> dict[str, Any]:
    return build_network_entry_profile(
        workflow_path=workflow_path,
        base_url=base_url,
        quickstart=state["quickstart"],
        request_plan=state["request_plan"],
        registration_surface=state["registration_surface"],
        demo_readiness=state["demo_readiness"],
        demo_playbook=demo_playbook,
        protocol_summary=state["protocol_summary"],
        external_contract=state["external_contract"],
        setup_guidance=state["setup_guidance"],
        verify_network_command=_network_verify_command(
            workflow_path,
            base_url=base_url,
            session_token=_quickstart_session_token(state["quickstart"]),
        ),
    )


def _profile_sdk_bootstrap(
    workflow_path: str,
    state: dict[str, Any],
    network_entry_profile: dict[str, Any],
) -> dict[str, Any]:
    return build_consumer_sdk_bootstrap(
        workflow_path=workflow_path,
        quickstart=state["quickstart"],
        network_entry_profile=network_entry_profile,
        network_harness_agent=state["network_harness_agent"],
        request_plan=state["request_plan"],
    )


def _profile_presenter_commands(
    *,
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
    state: dict[str, Any],
    agent_message: str,
) -> list[dict[str, str]]:
    return _presenter_command_deck(
        workflow_path=workflow_path,
        base_url=base_url,
        session_token=session_token,
        registration_surface=state["registration_surface"],
        agent_message=agent_message,
    )


def _profile_demo_script(
    *,
    workflow_path: str,
    state: dict[str, Any],
    demo_playbook: dict[str, Any],
    network_entry_profile: dict[str, Any],
    consumer_sdk_bootstrap: dict[str, Any],
    presenter_command_deck: list[dict[str, Any]],
) -> dict[str, Any]:
    return _mvp_demo_script(MvpDemoScriptInput(
        workflow=state["workflow"],
        workflow_path=workflow_path,
        protocol_summary=state["protocol_summary"],
        quickstart=state["quickstart"],
        demo_readiness=state["demo_readiness"],
        demo_playbook=demo_playbook,
        setup_guidance=state["setup_guidance"],
        registration_surface=state["registration_surface"],
        network_entry_profile=network_entry_profile,
        network_harness_agent=state["network_harness_agent"],
        consumer_sdk_bootstrap=consumer_sdk_bootstrap,
        command_deck=presenter_command_deck,
    ))


def _quickstart_session_token(quickstart: dict[str, Any]) -> Any:
    headers = quickstart.get("required_headers") if isinstance(quickstart.get("required_headers"), dict) else {}
    return headers.get("X-CBN-Session")


def _network_connect_mvp_state(
    *,
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    mvp_readiness = _mvp_readiness(_mvp_readiness_input(state))
    presenter_input = _mvp_presenter_input(
        state,
        workflow_path=workflow_path,
        base_url=base_url,
        session_token=session_token,
        mvp_readiness=mvp_readiness,
    )
    return {
        "mvp_readiness": mvp_readiness,
        "mvp_presenter_brief": _mvp_presenter_brief(presenter_input),
    }


def _mvp_readiness_input(state: dict[str, Any]) -> MvpReadinessInput:
    return MvpReadinessInput(
        workflow=state["workflow"],
        bridge_contract=state["bridge_contract"],
        external_contract=state["external_contract"],
        protocol_summary=state["protocol_summary"],
        request_plan=state["request_plan"],
        setup_guidance=state["setup_guidance"],
        registration_surface=state["registration_surface"],
        demo_readiness=state["demo_readiness"],
        demo_playbook=state["demo_playbook"],
        quickstart=state["quickstart"],
        plugin_health=state["plugin_health"],
        direct_cli_readiness=state["direct_cli_readiness"],
        studio_link=state["studio_link"],
        network_entry_profile=state["network_entry_profile"],
        network_harness_agent=state["network_harness_agent"],
        consumer_sdk_bootstrap=state["consumer_sdk_bootstrap"],
        presenter_command_deck=state["presenter_command_deck"],
        mvp_demo_script=state["mvp_demo_script"],
    )


def _mvp_presenter_input(
    state: dict[str, Any],
    *,
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
    mvp_readiness: dict[str, Any],
) -> MvpPresenterInput:
    return MvpPresenterInput(
        workflow=state["workflow"],
        protocol_summary=state["protocol_summary"],
        quickstart=state["quickstart"],
        request_plan=state["request_plan"],
        registration_surface=state["registration_surface"],
        demo_readiness=state["demo_readiness"],
        demo_playbook=state["demo_playbook"],
        setup_guidance=state["setup_guidance"],
        network_entry_profile=state["network_entry_profile"],
        mvp_readiness=mvp_readiness,
        studio_link=state["studio_link"],
        base_url=base_url,
        workflow_path=workflow_path,
        session_token=session_token,
        command_deck=state["presenter_command_deck"],
    )


def _network_connect_consumer_state(
    *,
    workflow_path: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    consumer_launch_contract = build_consumer_launch_contract(
        workflow_path=workflow_path,
        quickstart=state["quickstart"],
        request_plan=state["request_plan"],
        network_entry_profile=state["network_entry_profile"],
        setup_guidance=state["setup_guidance"],
        mvp_readiness=state["mvp_readiness"],
        mvp_presenter_brief=state["mvp_presenter_brief"],
    )
    return {
        "consumer_launch_contract": consumer_launch_contract,
        "consumer_manifest": build_network_consumer_manifest(NetworkConsumerManifestInput(
            workflow_path=workflow_path,
            network_entry_profile=state["network_entry_profile"],
            network_harness_agent=state["network_harness_agent"],
            consumer_launch_contract=consumer_launch_contract,
            consumer_sdk_bootstrap=state["consumer_sdk_bootstrap"],
            registration_surface=state["registration_surface"],
            direct_cli_readiness=state["direct_cli_readiness"],
            mvp_readiness=state["mvp_readiness"],
        )),
    }


def _network_connect_payload(
    *,
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "NetworkConnectPackage",
        "ok": state["ok"],
        "workflow_path": workflow_path,
        "base_url": base_url,
        "summary": _network_connect_summary(state),
        "contracts": _network_connect_contracts(state),
        "daemon_endpoints": state["endpoint_catalog"],
        "workflow": _compact_workflow(state["workflow"]),
        "protocols": state["protocol_summary"],
        "plugins": state["plugin_health"],
        "direct_cli_readiness": state["direct_cli_readiness"],
        "workflow_studio": state["studio_link"],
        "demo_readiness": state["demo_readiness"],
        "demo_playbook": state["demo_playbook"],
        "mvp_demo_script": state["mvp_demo_script"],
        "network_entry_profile": state["network_entry_profile"],
        "network_harness_agent": state["network_harness_agent"],
        "mvp_readiness": state["mvp_readiness"],
        "mvp_presenter_brief": state["mvp_presenter_brief"],
        "consumer_launch_contract": state["consumer_launch_contract"],
        "consumer_sdk_bootstrap": state["consumer_sdk_bootstrap"],
        "consumer_manifest": state["consumer_manifest"],
        "agent_node_bundle": state["compact_agent_bundle"],
        "agent_workflow_request": state["compact_request_plan"],
        "setup_guidance": state["setup_guidance"],
        "registration_surface": state["registration_surface"],
        "acceptance": state["quickstart"]["acceptance"],
        "consumer_quickstart": state["quickstart"],
        "next_commands": _next_commands(workflow_path, base_url=base_url, session_token=session_token),
    }


def _network_connect_summary(state: dict[str, Any]) -> dict[str, Any]:
    plugin_health = state["plugin_health"]
    return {
        "workflow_id": state["workflow"].get("workflow_id"),
        "task_count": state["workflow"].get("task_count"),
        "bridge_route_count": (state["bridge_contract"].get("summary") or {}).get("route_count", 0),
        "protocol_export_count": state["protocol_summary"]["export_count"],
        "agent_card_count": len(state["agent_bundle"].get("cards", [])),
        "registration_importer_count": state["registration_surface"]["importer_count"],
        "direct_cli_profile_count": state["direct_cli_readiness"]["summary"]["profile_count"],
        "direct_cli_capability_count": state["direct_cli_readiness"]["summary"]["capability_count"],
        "direct_cli_recovery_type_count": state["direct_cli_readiness"]["summary"]["recovery_type_count"],
        "consumer_snippet_count": len(state["quickstart"].get("sdk_snippets", [])),
        "consumer_sdk_bootstrap_status": state["consumer_sdk_bootstrap"]["status"],
        "consumer_sdk_bootstrap_request_count": state["consumer_sdk_bootstrap"]["request_count"],
        "agent_workflow_request_ready": state["request_plan"].get("ok"),
        "setup_status": state["setup_guidance"].get("status"),
        "setup_required": state["setup_guidance"].get("setup_required"),
        "setup_user_gate_count": state["setup_guidance"].get("requires_user_count", 0),
        "setup_secret_count": state["setup_guidance"].get("secret_count", 0),
        "demo_ready": state["demo_readiness"].get("status") == "ready",
        "demo_stage_count": state["demo_readiness"].get("stage_count", 0),
        "demo_playbook_step_count": state["demo_playbook"]["step_count"],
        "mvp_demo_script_status": state["mvp_demo_script"]["status"],
        "mvp_demo_script_phase_count": state["mvp_demo_script"]["phase_count"],
        "cli_anything_split_status": plugin_health.get("cli_anything", {}).get("module_split", {}).get("status"),
        "external_contract_ready": state["external_contract"].get("ok"),
        "mvp_readiness_status": state["mvp_readiness"]["status"],
        "mvp_readiness_score": state["mvp_readiness"]["score"],
        "mvp_presenter_brief_status": state["mvp_presenter_brief"]["status"],
        "recommended_next_action": "call_daemon_endpoints" if state["ok"] else "fix_connect_package_inputs",
    }


def _network_connect_contracts(state: dict[str, Any]) -> dict[str, Any]:
    internal_contract = state["internal_contract"]
    return {
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
                "ok": state["bridge_contract"].get("ok"),
                "summary": state["bridge_contract"].get("summary", {}),
                "contract": internal_contract,
            },
        },
        "external": state["external_contract"],
    }


def _mvp_readiness(params: MvpReadinessInput) -> dict[str, Any]:
    """Product-facing readiness matrix for the current killer MVP surface."""

    return _mvp_readiness_from_params(params)


def _mvp_readiness_from_params(params: MvpReadinessInput) -> dict[str, Any]:
    raw_params = params.__dict__
    context = _mvp_readiness_context(params)
    checks = _mvp_readiness_checks(raw_params, context)
    return _mvp_readiness_report(checks)


def _mvp_readiness_context(params: MvpReadinessInput) -> dict[str, Any]:
    bridge_summary = _dict_field(params.bridge_contract, "summary")
    acceptance = _dict_field(params.quickstart, "acceptance")
    cli_anything = _dict_field(params.plugin_health, "cli_anything")
    presenter = _presenter_command_context(params.presenter_command_deck)
    demo_script = _mvp_demo_script_readiness_context(params.mvp_demo_script)
    consumer_manifest = _consumer_manifest_context(params.quickstart, params.consumer_sdk_bootstrap, acceptance)
    return {
        "acceptance": acceptance,
        "bridge_summary": bridge_summary,
        "consumer_manifest_acceptance_ready": consumer_manifest["acceptance_ready"],
        "consumer_manifest_url": consumer_manifest["url"],
        "demo_script_phase_ids": demo_script["phase_ids"],
        "direct_cli_parser": _dict_field(params.direct_cli_readiness, "parser_contract"),
        "direct_cli_summary": _dict_field(params.direct_cli_readiness, "summary"),
        "expected_demo_script_phase_ids": demo_script["expected_phase_ids"],
        "expected_presenter_command_ids": presenter["expected_ids"],
        "module_split": _dict_field(cli_anything, "module_split"),
        "mvp_demo_script_ready": demo_script["ready"],
        "presenter_command_deck_ready": presenter["ready"],
        "presenter_command_ids": presenter["ids"],
        "reusable_harness": _dict_field(params.request_plan, "reusable_harness"),
        "sdk_entrypoints": consumer_manifest["sdk_entrypoints"],
    }


def _dict_field(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _list_field(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    return value if isinstance(value, list) else []


def _presenter_command_context(command_deck: list[dict[str, Any]]) -> dict[str, Any]:
    expected_ids = [
        "connect_package",
        "plan_harness",
        "run_demo",
        "export_protocols",
        "sdk_bootstrap",
        "register_next_cli",
    ]
    ids = [
        str(command.get("id"))
        for command in command_deck
        if isinstance(command, dict) and command.get("id")
    ]
    ready = bool(
        len(ids) >= len(expected_ids)
        and ids[:3] == expected_ids[:3]
        and all(command_id in ids for command_id in expected_ids)
        and all(
            isinstance(command, dict) and bool(command.get("command")) and bool(command.get("copy_label"))
            for command in command_deck
        )
    )
    return {"expected_ids": expected_ids, "ids": ids, "ready": ready}


def _mvp_demo_script_readiness_context(mvp_demo_script: dict[str, Any]) -> dict[str, Any]:
    expected_phase_ids = [
        "open_network_surface",
        "show_cli_cli_protocol",
        "call_with_harness_agent",
        "run_and_inspect_evidence",
        "prove_extensibility",
    ]
    phase_ids = [
        str(phase.get("id"))
        for phase in _list_field(mvp_demo_script, "phases")
        if isinstance(phase, dict) and phase.get("id")
    ]
    ready = bool(
        mvp_demo_script.get("status") == "ready"
        and phase_ids == expected_phase_ids
        and int(mvp_demo_script.get("phase_count", 0) or 0) == len(expected_phase_ids)
        and _dict_field(mvp_demo_script, "runtime_story").get("harness_agent") == "NaturalLanguageWorkflowHarness"
    )
    return {"expected_phase_ids": expected_phase_ids, "phase_ids": phase_ids, "ready": ready}


def _consumer_manifest_context(
    quickstart: dict[str, Any],
    consumer_sdk_bootstrap: dict[str, Any],
    acceptance: dict[str, Any],
) -> dict[str, Any]:
    quickstart_entrypoints = _dict_field(quickstart, "entrypoints")
    sdk_entrypoints = _dict_field(consumer_sdk_bootstrap, "entrypoints")
    url = quickstart_entrypoints.get("consumer_manifest") or sdk_entrypoints.get("consumer_manifest")
    acceptance_ready = any(
        isinstance(check, dict)
        and check.get("id") == "consumer_manifest_readable"
        and check.get("request_id") == "consumer_manifest"
        for check in _list_field(acceptance, "checks")
    )
    return {"acceptance_ready": acceptance_ready, "url": url, "sdk_entrypoints": sdk_entrypoints}


def _mvp_readiness_checks(
    params: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        *_mvp_foundation_checks(
            external_contract=params["external_contract"],
            bridge_contract=params["bridge_contract"],
            bridge_summary=context["bridge_summary"],
            studio_link=params["studio_link"],
            workflow=params["workflow"],
            request_plan=params["request_plan"],
            reusable_harness=context["reusable_harness"],
        ),
        *_mvp_network_entry_checks(params, context),
        *_mvp_registration_checks(
            registration_surface=params["registration_surface"],
            direct_cli_readiness=params["direct_cli_readiness"],
            direct_cli_parser=context["direct_cli_parser"],
            direct_cli_summary=context["direct_cli_summary"],
            module_split=context["module_split"],
            setup_guidance=params["setup_guidance"],
            protocol_summary=params["protocol_summary"],
        ),
        *_mvp_demo_presentation_checks(params, context),
    ]


def _mvp_readiness_report(checks: list[dict[str, Any]]) -> dict[str, Any]:
    ready_count = sum(1 for check in checks if check["ready"])
    total = len(checks)
    status = "ready" if ready_count == total else "needs_attention"
    product_goals = {
        "show_cli_cli_protocol": _checks_ready(checks, "internal_bridge_contract", "killer_workflow_dag"),
        "run_reusable_harness_agent": _checks_ready(checks, "natural_language_harness_agent", "quickstart_acceptance"),
        "reuse_harness_agent_contract": _checks_ready(checks, "network_harness_agent_contract"),
        "integrate_next_cli": _checks_ready(checks, "cli_registration_surface", "cli_anything_split"),
        "integrate_direct_cli_profiles": _checks_ready(checks, "direct_cli_readiness"),
        "one_shot_external_network_entry": _checks_ready(
            checks,
            "network_entry_profile",
            "consumer_sdk_bootstrap",
            "network_consumer_manifest",
            "external_agent_cli_contract",
        ),
        "demo_in_workflow_studio": _checks_ready(checks, "workflow_studio_surface", "killer_demo_playbook"),
        "present_mvp_from_command_deck": _checks_ready(checks, "presenter_command_deck"),
        "present_product_demo_script": _checks_ready(checks, "mvp_demo_script"),
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


def _mvp_foundation_checks(
    *,
    external_contract: dict[str, Any],
    bridge_contract: dict[str, Any],
    bridge_summary: dict[str, Any],
    studio_link: dict[str, Any],
    workflow: dict[str, Any],
    request_plan: dict[str, Any],
    reusable_harness: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _external_contract_check(external_contract),
        _internal_bridge_contract_check(bridge_contract, bridge_summary),
        _workflow_studio_surface_check(studio_link),
        _killer_workflow_dag_check(workflow),
        _natural_language_harness_check(request_plan, reusable_harness),
    ]


def _external_contract_check(external_contract: dict[str, Any]) -> dict[str, Any]:
    return _mvp_check(
        "external_agent_cli_contract",
        "External Agent CLI contract",
        bool(external_contract.get("ok")),
        "AgentCliCard/RunReceipt package boundary is standalone and consumable.",
        {
            "protocol": external_contract.get("protocol"),
            "accepted_kinds": external_contract.get("accepted_kinds", []),
        },
        "repair_agent_cli_contract_package",
    )


def _internal_bridge_contract_check(
    bridge_contract: dict[str, Any],
    bridge_summary: dict[str, Any],
) -> dict[str, Any]:
    return _mvp_check(
        "internal_bridge_contract",
        "Internal BridgeMessage bus",
        bool(bridge_contract.get("ok") and int(bridge_summary.get("route_count", 0) or 0) >= 1),
        "ToolManifest, BridgeMessage, Artifact, and Workflow selector contracts are ready.",
        {
            "route_count": bridge_summary.get("route_count", 0),
            "route_ready_count": bridge_summary.get("route_ready_count", 0),
        },
        "repair_bridge_message_routes",
    )


def _workflow_studio_surface_check(studio_link: dict[str, Any]) -> dict[str, Any]:
    return _mvp_check(
        "workflow_studio_surface",
        "Workflow Studio surface",
        bool(studio_link.get("ok") and studio_link.get("url")),
        "User-facing Studio link is preconfigured for daemon, workflow, token, and demo mode.",
        {
            "url": studio_link.get("url"),
            "session_token_included": studio_link.get("session_token_included"),
        },
        "start_workflow_studio",
    )


def _killer_workflow_dag_check(workflow: dict[str, Any]) -> dict[str, Any]:
    return _mvp_check(
        "killer_workflow_dag",
        "Killer workflow DAG",
        bool(workflow.get("valid") and int(workflow.get("task_count", 0) or 0) >= 1),
        "The macrocli -> transform -> mermaid DAG can be inspected before running.",
        {"workflow_id": workflow.get("workflow_id"), "task_count": workflow.get("task_count", 0)},
        "fix_workflow_manifest_or_tasks",
    )


def _natural_language_harness_check(
    request_plan: dict[str, Any],
    reusable_harness: dict[str, Any],
) -> dict[str, Any]:
    return _mvp_check(
        "natural_language_harness_agent",
        "Natural-language harness agent",
        bool(request_plan.get("ok") and reusable_harness.get("kind") == "NaturalLanguageWorkflowHarness"),
        "A reusable harness agent can bind natural language to the CLI-CLI workflow run contract.",
        {
            "kind": reusable_harness.get("kind"),
            "bridge_route_count": request_plan.get("bridge_route_count", 0),
        },
        "repair_adapter_agent_workflow_request_plan",
    )


def _mvp_network_entry_checks(
    params: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        *_mvp_network_contract_checks(
            network_harness_agent=params["network_harness_agent"],
            network_entry_profile=params["network_entry_profile"],
            quickstart=params["quickstart"],
            acceptance=context["acceptance"],
        ),
        *_mvp_network_consumer_checks(
            consumer_sdk_bootstrap=params["consumer_sdk_bootstrap"],
            consumer_manifest_url=context["consumer_manifest_url"],
            consumer_manifest_acceptance_ready=context["consumer_manifest_acceptance_ready"],
            sdk_entrypoints=context["sdk_entrypoints"],
        ),
    ]


def _mvp_network_contract_checks(
    *,
    network_harness_agent: dict[str, Any],
    network_entry_profile: dict[str, Any],
    quickstart: dict[str, Any],
    acceptance: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _mvp_network_harness_agent_check(network_harness_agent),
        _mvp_network_entry_profile_check(network_entry_profile),
        _mvp_quickstart_acceptance_check(quickstart, acceptance),
    ]


def _mvp_network_harness_agent_check(network_harness_agent: dict[str, Any]) -> dict[str, Any]:
    return _mvp_check(
        "network_harness_agent_contract",
        "Network harness agent contract",
        network_harness_agent.get("status") == "ready",
        "External programs can read one focused natural-language harness contract before running the CLI-CLI workflow.",
        {
            "contract_id": network_harness_agent.get("contract_id"),
            "route_count": (network_harness_agent.get("bridge") or {}).get("route_count", 0),
            "secret_values_echoed": (network_harness_agent.get("auth") or {}).get("secret_values_echoed"),
        },
        "repair_network_harness_agent_contract",
    )


def _mvp_network_entry_profile_check(network_entry_profile: dict[str, Any]) -> dict[str, Any]:
    return _mvp_check(
        "network_entry_profile",
        "One-shot network entry",
        network_entry_profile.get("status") == "ready",
        "External programs can read one profile to discover auth, endpoints, harness, evidence, and registration.",
        {
            "profile_id": network_entry_profile.get("profile_id"),
            "integration_mode": network_entry_profile.get("integration_mode"),
        },
        "repair_network_entry_profile",
    )


def _mvp_quickstart_acceptance_check(
    quickstart: dict[str, Any],
    acceptance: dict[str, Any],
) -> dict[str, Any]:
    requests = quickstart.get("requests", [])
    return _mvp_check(
        "quickstart_acceptance",
        "First-call acceptance",
        bool(
            quickstart.get("status") in {"ready", "ready_without_daemon_url"}
            and int(acceptance.get("check_count", 0) or 0) >= 1
        ),
        "The first-call sequence and acceptance checklist are available for replay.",
        {
            "quickstart_status": quickstart.get("status"),
            "check_count": acceptance.get("check_count", 0),
            "request_count": len(requests) if isinstance(requests, list) else 0,
        },
        "repair_network_quickstart",
    )


def _mvp_network_consumer_checks(
    *,
    consumer_sdk_bootstrap: dict[str, Any],
    consumer_manifest_url: Any,
    consumer_manifest_acceptance_ready: bool,
    sdk_entrypoints: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _mvp_consumer_sdk_bootstrap_check(consumer_sdk_bootstrap),
        _mvp_consumer_manifest_check(
            consumer_sdk_bootstrap=consumer_sdk_bootstrap,
            consumer_manifest_url=consumer_manifest_url,
            consumer_manifest_acceptance_ready=consumer_manifest_acceptance_ready,
            sdk_entrypoints=sdk_entrypoints,
        ),
    ]


def _mvp_consumer_sdk_bootstrap_check(consumer_sdk_bootstrap: dict[str, Any]) -> dict[str, Any]:
    auth = consumer_sdk_bootstrap.get("auth") or {}
    return _mvp_check(
        "consumer_sdk_bootstrap",
        "Consumer SDK bootstrap",
        _consumer_sdk_bootstrap_ready(consumer_sdk_bootstrap, auth),
        "External SDKs can initialize from one small contract with typed responses, request sequence, and redacted auth.",
        {
            "bootstrap_id": consumer_sdk_bootstrap.get("bootstrap_id"),
            "request_count": consumer_sdk_bootstrap.get("request_count", 0),
            "run_endpoint": (consumer_sdk_bootstrap.get("harness") or {}).get("run_endpoint"),
            "secret_values_echoed": auth.get("secret_values_echoed"),
        },
        "repair_consumer_sdk_bootstrap",
    )


def _consumer_sdk_bootstrap_ready(consumer_sdk_bootstrap: dict[str, Any], auth: dict[str, Any]) -> bool:
    return bool(
        consumer_sdk_bootstrap.get("status") == "ready"
        and int(consumer_sdk_bootstrap.get("request_count", 0) or 0) >= 1
        and auth.get("secret_values_echoed") is False
    )


def _mvp_consumer_manifest_check(
    *,
    consumer_sdk_bootstrap: dict[str, Any],
    consumer_manifest_url: Any,
    consumer_manifest_acceptance_ready: bool,
    sdk_entrypoints: dict[str, Any],
) -> dict[str, Any]:
    auth = consumer_sdk_bootstrap.get("auth") or {}
    return _mvp_check(
        "network_consumer_manifest",
        "Persistable consumer manifest",
        _consumer_manifest_ready(consumer_manifest_url, consumer_manifest_acceptance_ready, auth),
        "External programs can fetch and save one redacted manifest to enter the CBN network.",
        {
            "url": consumer_manifest_url,
            "acceptance_check": "consumer_manifest_readable" if consumer_manifest_acceptance_ready else None,
            "sdk_bootstrap_has_entrypoint": bool(sdk_entrypoints.get("consumer_manifest")),
            "secret_values_echoed": auth.get("secret_values_echoed"),
        },
        "repair_network_consumer_manifest",
    )


def _consumer_manifest_ready(
    consumer_manifest_url: Any,
    consumer_manifest_acceptance_ready: bool,
    auth: dict[str, Any],
) -> bool:
    return bool(
        consumer_manifest_url
        and "consumer-manifest" in str(consumer_manifest_url)
        and consumer_manifest_acceptance_ready
        and auth.get("secret_values_echoed") is False
    )


def _mvp_registration_checks(
    *,
    registration_surface: dict[str, Any],
    direct_cli_readiness: dict[str, Any],
    direct_cli_parser: dict[str, Any],
    direct_cli_summary: dict[str, Any],
    module_split: dict[str, Any],
    setup_guidance: dict[str, Any],
    protocol_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _registration_surface_check(registration_surface),
        _direct_cli_readiness_check(direct_cli_readiness, direct_cli_parser, direct_cli_summary),
        _cli_anything_split_check(module_split),
        _setup_guidance_check(setup_guidance),
        _protocol_facades_check(protocol_summary),
    ]


def _registration_surface_check(registration_surface: dict[str, Any]) -> dict[str, Any]:
    return _mvp_check(
        "cli_registration_surface",
        "Low-cost CLI registration",
        bool(
            registration_surface.get("status") == "ready"
            and int(registration_surface.get("importer_count", 0) or 0) >= 5
        ),
        "Next CLIs can enter through dry-run-first import command, CLI-Anything, MCP, skill, card, or parser fixture routes.",
        {
            "importer_count": registration_surface.get("importer_count", 0),
            "dry_run_by_default": (registration_surface.get("default_policy") or {}).get("dry_run_by_default"),
        },
        "repair_registration_surface",
    )


def _direct_cli_readiness_check(
    direct_cli_readiness: dict[str, Any],
    direct_cli_parser: dict[str, Any],
    direct_cli_summary: dict[str, Any],
) -> dict[str, Any]:
    return _mvp_check(
        "direct_cli_readiness",
        "Direct CLI profile readiness",
        bool(
            direct_cli_readiness.get("ok")
            and direct_cli_parser.get("fixture_ok")
            and int(direct_cli_summary.get("capability_count", 0) or 0)
            == int(direct_cli_summary.get("verified_output_count", 0) or 0)
        ),
        "Feishu, Jimeng, Obsidian, and CAW direct CLI profiles have typed parser coverage and setup recovery gates.",
        {
            "profile_count": direct_cli_summary.get("profile_count", 0),
            "capability_count": direct_cli_summary.get("capability_count", 0),
            "verified_output_count": direct_cli_summary.get("verified_output_count", 0),
            "recovery_type_count": direct_cli_summary.get("recovery_type_count", 0),
            "fixture_failed_case_count": direct_cli_summary.get("fixture_failed_case_count", 0),
        },
        "repair_direct_cli_readiness",
    )


def _cli_anything_split_check(module_split: dict[str, Any]) -> dict[str, Any]:
    return _mvp_check(
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
    )


def _setup_guidance_check(setup_guidance: dict[str, Any]) -> dict[str, Any]:
    return _mvp_check(
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
    )


def _protocol_facades_check(protocol_summary: dict[str, Any]) -> dict[str, Any]:
    return _mvp_check(
        "protocol_facades",
        "MCP/A2A/ACP facades",
        int(protocol_summary.get("export_count", 0) or 0) >= 3,
        "The same workflow can be exported to MCP, A2A, and ACP descriptors.",
        {"targets": protocol_summary.get("targets", []), "export_count": protocol_summary.get("export_count", 0)},
        "repair_protocol_exports",
    )


def _mvp_demo_presentation_checks(params: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _killer_demo_playbook_check(params["demo_readiness"], params["demo_playbook"]),
        _presenter_command_deck_check(
            presenter_command_deck=params["presenter_command_deck"],
            ready=context["presenter_command_deck_ready"],
            command_ids=context["presenter_command_ids"],
            expected_command_ids=context["expected_presenter_command_ids"],
        ),
        _mvp_demo_script_check(
            mvp_demo_script=params["mvp_demo_script"],
            ready=context["mvp_demo_script_ready"],
            phase_ids=context["demo_script_phase_ids"],
            expected_phase_ids=context["expected_demo_script_phase_ids"],
        ),
    ]


def _killer_demo_playbook_check(
    demo_readiness: dict[str, Any],
    demo_playbook: dict[str, Any],
) -> dict[str, Any]:
    return _mvp_check(
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
    )


def _presenter_command_deck_check(
    *,
    presenter_command_deck: list[dict[str, Any]],
    ready: bool,
    command_ids: list[str],
    expected_command_ids: list[str],
) -> dict[str, Any]:
    copy_labels = [
        str(command.get("copy_label"))
        for command in presenter_command_deck
        if isinstance(command, dict) and command.get("copy_label")
    ]
    return _mvp_check(
        "presenter_command_deck",
        "Presenter command deck",
        ready,
        "The MVP presenter has ordered, copyable commands for connect, harness, demo, protocol export, SDK bootstrap, and next-CLI registration.",
        {
            "command_count": len(command_ids),
            "command_ids": command_ids,
            "expected_command_ids": expected_command_ids,
            "copy_labels": copy_labels,
        },
        "repair_presenter_command_deck",
    )


def _mvp_demo_script_check(
    *,
    mvp_demo_script: dict[str, Any],
    ready: bool,
    phase_ids: list[str],
    expected_phase_ids: list[str],
) -> dict[str, Any]:
    return _mvp_check(
        "mvp_demo_script",
        "MVP demo script",
        ready,
        "A product-ready demo script ties audience, phase order, CLI-CLI proof, harness agent, evidence, protocol export, and next-CLI registration together.",
        {
            "script_id": mvp_demo_script.get("script_id"),
            "phase_count": mvp_demo_script.get("phase_count", 0),
            "phase_ids": phase_ids,
            "expected_phase_ids": expected_phase_ids,
            "primary_surface": (mvp_demo_script.get("runtime_story") or {}).get("primary_surface"),
        },
        "repair_mvp_demo_script",
    )


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
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    workflow = state["workflow"]
    bridge_contract = state["bridge_contract"]
    protocol_summary = state["protocol_summary"]
    studio_link = state["studio_link"]
    endpoint_catalog = state["endpoint_catalog"]
    endpoint_by_path = _endpoint_by_path(endpoint_catalog)
    route_count = int((bridge_contract.get("summary") or {}).get("route_count", 0) or 0)
    stages = _demo_readiness_stages(endpoint_by_path, route_count)
    ready = _demo_readiness_ready(workflow, route_count, protocol_summary)
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "KillerDemoReadiness",
        "status": "ready" if ready else "needs_attention",
        "workflow_path": workflow_path,
        "workflow_id": workflow.get("workflow_id"),
        "stage_count": len(stages),
        "stages": stages,
        "required_capability_ids": list(KILLER_CAPABILITIES),
        "evidence_contracts": _demo_evidence_contracts(),
        "protocol_targets": protocol_summary.get("targets", []),
        "studio_url": studio_link.get("url"),
        "demo_endpoint": endpoint_by_path.get("/demo/killer", {}),
        "acceptance_request_ids": _demo_acceptance_request_ids(),
        "next_commands": _demo_readiness_next_commands(workflow_path, base_url, session_token),
    }


def _demo_readiness_ready(
    workflow: dict[str, Any],
    route_count: int,
    protocol_summary: dict[str, Any],
) -> bool:
    return bool(workflow.get("valid") and route_count > 0 and protocol_summary.get("export_count", 0) >= 3)


def _demo_evidence_contracts() -> list[str]:
    return [
        "ToolManifest",
        "BridgeMessage",
        "ArtifactRecord",
        "WorkflowSelector",
        "Event",
        "Audit",
    ]


def _demo_acceptance_request_ids() -> list[str]:
    return [
        "inspect_agent_nodes",
        "export_protocols",
        "plan_agent_request",
        "run_workflow",
        "events",
        "audit",
        "artifacts",
    ]


def _endpoint_by_path(endpoint_catalog: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(endpoint.get("path", "")).split("?", 1)[0]: endpoint
        for endpoint in endpoint_catalog
        if isinstance(endpoint, dict)
    }


def _demo_readiness_stages(
    endpoint_by_path: dict[str, dict[str, Any]],
    route_count: int,
) -> list[dict[str, Any]]:
    return [
        _demo_import_cli_anything_stage(),
        _demo_endpoint_stage(
            "run_macrocli",
            "Run macrocli backend listing",
            "A CLI producer can emit a BridgeMessage payload for downstream tools.",
            endpoint_by_path.get("/workflows/run", {}),
        ),
        _demo_parse_payload_stage(route_count),
        _demo_transform_stage(),
        _demo_run_mermaid_stage(),
        _demo_evidence_stage(endpoint_by_path),
        _demo_endpoint_stage(
            "export_mcp_a2a_acp_smoke",
            "Export MCP/A2A/ACP smoke",
            "The same workflow can be exposed through external protocol facades.",
            endpoint_by_path.get("/protocols/workflows", {}),
        ),
    ]


def _demo_import_cli_anything_stage() -> dict[str, Any]:
    return {
        "id": "import_cli_anything_harness",
        "title": "Import CLI-Anything harness",
        "proves": "CLI-Anything capabilities can enter CBN as ToolManifest records.",
        "capability_ids": [
            "cli-anything.macrocli.backends",
            "cli-anything.mermaid.set-diagram",
        ],
    }


def _demo_endpoint_stage(
    stage_id: str,
    title: str,
    proves: str,
    endpoint: dict[str, Any],
) -> dict[str, Any]:
    return {"id": stage_id, "title": title, "proves": proves, "endpoint": endpoint}


def _demo_parse_payload_stage(route_count: int) -> dict[str, Any]:
    return {
        "id": "parse_payload",
        "title": "Parse BridgeMessage payload",
        "proves": "CBN parser contracts make CLI stdout deterministic enough for routing.",
        "bridge_route_count": route_count,
    }


def _demo_transform_stage() -> dict[str, Any]:
    return {
        "id": "transform_to_mermaid",
        "title": "Transform payload to Mermaid source",
        "proves": "Workflow selectors can map one CLI output into another CLI input.",
        "capability_ids": ["cbn.transform.macrocli-backends-to-mermaid"],
    }


def _demo_run_mermaid_stage() -> dict[str, Any]:
    return {
        "id": "run_mermaid",
        "title": "Run Mermaid consumer",
        "proves": "A downstream CLI consumer can produce inspectable artifacts.",
        "capability_ids": ["cli-anything.mermaid.set-diagram"],
    }


def _demo_evidence_stage(endpoint_by_path: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "show_artifact_event_audit",
        "title": "Show artifact, event and audit evidence",
        "proves": "Runtime evidence can be inspected after the CLI-CLI chain runs.",
        "endpoints": [
            endpoint_by_path.get("/artifacts", {}),
            endpoint_by_path.get("/events", {}),
            endpoint_by_path.get("/audit", {}),
        ],
    }


def _demo_readiness_next_commands(
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
) -> list[str]:
    return [
        f"python -m cbn demo killer --workflow-path {workflow_path} --run --dry-run",
        f"python -m cbn demo killer --workflow-path {workflow_path} --run --dry-run --smoke-suite",
        _network_verify_command(workflow_path, base_url=base_url, session_token=session_token),
    ]


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
    entrypoints = _quickstart_entrypoints(quickstart)
    open_studio = str(studio_link.get("url") or entrypoints.get("open_studio") or "")
    verify_command = _network_verify_command(workflow_path, base_url=base_url, session_token=session_token)
    steps = _demo_playbook_steps(
        workflow_path=workflow_path,
        open_studio=open_studio,
        entrypoints=entrypoints,
        registration_surface=registration_surface,
        verify_command=verify_command,
        base_url=base_url,
        session_token=session_token,
    )
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "KillerMvpDemoPlaybook",
        "status": "ready" if demo_readiness.get("status") == "ready" else "needs_attention",
        "workflow_path": workflow_path,
        "step_count": len(steps),
        "steps": steps,
        "success_criteria": _demo_playbook_success_criteria(),
        "next_commands": _demo_playbook_next_commands(workflow_path, verify_command, base_url, session_token),
    }


def _quickstart_entrypoints(quickstart: dict[str, Any]) -> dict[str, Any]:
    entrypoints = quickstart.get("entrypoints")
    return entrypoints if isinstance(entrypoints, dict) else {}


def _demo_playbook_steps(
    *,
    workflow_path: str,
    open_studio: str,
    entrypoints: dict[str, Any],
    registration_surface: dict[str, Any],
    verify_command: str,
    base_url: str | None,
    session_token: str | None,
) -> list[dict[str, Any]]:
    return [
        _open_workflow_studio_step(open_studio),
        _inspect_one_shot_contract_step(),
        _show_sdk_bootstrap_step(workflow_path, entrypoints, base_url, session_token),
        _run_killer_demo_step(),
        _verify_network_acceptance_step(verify_command),
        _show_protocol_facades_step(entrypoints),
        _register_next_cli_step(registration_surface),
    ]


def _open_workflow_studio_step(open_studio: str) -> dict[str, Any]:
    return {
        "id": "open_workflow_studio",
        "title": "Open Workflow Studio",
        "intent": "Use the product UI as the primary demo surface.",
        "action": "open_url",
        "target": open_studio,
        "success_signal": "Workflow DAG, Connect Package, and evidence dock are visible.",
    }


def _inspect_one_shot_contract_step() -> dict[str, Any]:
    return {
        "id": "inspect_one_shot_contract",
        "title": "Inspect one-shot connection package",
        "intent": "Show external protocol boundary, internal bus contracts, agent nodes, and quickstart calls.",
        "action": "click",
        "target": "Connect",
        "success_signal": "Connect panel shows AgentCliCard/RunReceipt, BridgeMessage routes, setup guidance, and registration surface.",
    }


def _show_sdk_bootstrap_step(
    workflow_path: str,
    entrypoints: dict[str, Any],
    base_url: str | None,
    session_token: str | None,
) -> dict[str, Any]:
    return {
        "id": "show_sdk_bootstrap",
        "title": "Show SDK bootstrap handoff",
        "intent": "Show the smallest stable contract another program can read before calling the network.",
        "action": "inspect_endpoint",
        "target": entrypoints.get("sdk_bootstrap"),
        "command": _network_quickstart_command(
            workflow_path,
            base_url=base_url,
            session_token=session_token,
            output="sdk-bootstrap",
        ),
        "success_signal": "ConsumerSdkBootstrap.status == ready and typed_responses.run_workflow == WorkflowRunReceipt.",
    }


def _run_killer_demo_step() -> dict[str, Any]:
    return {
        "id": "run_killer_demo",
        "title": "Run CLI-CLI killer demo",
        "intent": "Prove macrocli output can route through BridgeMessage into Mermaid and produce artifacts.",
        "action": "click",
        "target": "Demo",
        "success_signal": "Killer Demo stages complete and artifact/event/audit counts are non-zero.",
    }


def _verify_network_acceptance_step(verify_command: str) -> dict[str, Any]:
    return {
        "id": "verify_network_acceptance",
        "title": "Verify external consumer acceptance",
        "intent": "Replay the first-call request sequence against the live daemon.",
        "action": "click_or_cli",
        "target": "Daemon Verify",
        "command": verify_command,
        "success_signal": "NetworkConnectionAcceptanceReport.status == passed.",
    }


def _show_protocol_facades_step(entrypoints: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "show_protocol_facades",
        "title": "Show MCP/A2A/ACP workflow facades",
        "intent": "Show the same CLI-CLI workflow can be exported to external protocol descriptors.",
        "action": "inspect_endpoint",
        "target": entrypoints.get("export_protocols"),
        "success_signal": "Protocol targets include mcp, a2a, and acp.",
    }


def _register_next_cli_step(registration_surface: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "register_next_cli",
        "title": "Register the next CLI",
        "intent": "Show the low-friction path for adding more CLIs to the network.",
        "action": "copy_command",
        "target": "registration_surface.next_commands",
        "command": (registration_surface.get("next_commands") or ["python -m cbn import command --help"])[0],
        "success_signal": "Importer help confirms dry-run-first registration entrypoints.",
    }


def _demo_playbook_success_criteria() -> list[str]:
    return [
        "Workflow Studio opens with the target workflow path.",
        "Connect Package exposes external protocol boundary and internal BridgeMessage contract.",
        "SDK bootstrap exposes the small external-program handoff without secret values.",
        "Harness agent request can call the CLI-CLI workflow through /workflows/run.",
        "Runtime event, audit, and artifact evidence is visible after the run.",
        "MCP/A2A/ACP descriptors export for the same workflow.",
        "Registration surface lists dry-run-first importers for the next CLI.",
    ]


def _demo_playbook_next_commands(
    workflow_path: str,
    verify_command: str,
    base_url: str | None,
    session_token: str | None,
) -> list[str]:
    return [
        verify_command,
        _network_quickstart_command(
            workflow_path,
            base_url=base_url,
            session_token=session_token,
            output="sdk-bootstrap",
        ),
        f"python -m cbn demo killer --workflow-path {workflow_path} --run --dry-run --smoke-suite",
        "python -m cbn import command --help",
    ]


def _mvp_demo_script(params: MvpDemoScriptInput) -> dict[str, Any]:
    """Structured PM-facing script for presenting the killer MVP end to end."""

    context = _mvp_demo_script_context(
        quickstart=params.quickstart,
        demo_playbook=params.demo_playbook,
        registration_surface=params.registration_surface,
        command_deck=params.command_deck,
    )
    phases = _mvp_demo_script_phases(context)
    ready = _mvp_demo_script_ready(
        workflow=params.workflow,
        demo_readiness=params.demo_readiness,
        demo_playbook=params.demo_playbook,
        network_entry_profile=params.network_entry_profile,
        network_harness_agent=params.network_harness_agent,
        consumer_sdk_bootstrap=params.consumer_sdk_bootstrap,
        phases=phases,
    )
    return _mvp_demo_script_payload(params, context, phases, ready)


def _mvp_demo_script_context(
    *,
    quickstart: dict[str, Any],
    demo_playbook: dict[str, Any],
    registration_surface: dict[str, Any],
    command_deck: list[dict[str, Any]],
) -> dict[str, Any]:
    command_by_id = {
        str(command.get("id")): command
        for command in command_deck
        if isinstance(command, dict) and command.get("id")
    }
    playbook_steps = demo_playbook.get("steps") if isinstance(demo_playbook.get("steps"), list) else []
    playbook_step_by_id = {
        str(step.get("id")): step
        for step in playbook_steps
        if isinstance(step, dict) and step.get("id")
    }
    entrypoints = quickstart.get("entrypoints") if isinstance(quickstart.get("entrypoints"), dict) else {}
    evidence_endpoints = {
        "events": entrypoints.get("events"),
        "audit": entrypoints.get("audit"),
        "artifacts": entrypoints.get("artifacts"),
    }
    registration_next_commands = [
        str(command)
        for command in registration_surface.get("next_commands", [])
        if isinstance(command, str) and command
    ]
    return {
        "command_by_id": command_by_id,
        "evidence_endpoints": evidence_endpoints,
        "playbook_step_by_id": playbook_step_by_id,
        "registration_next_commands": registration_next_commands,
    }


def _mvp_demo_script_phases(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [_mvp_demo_phase(spec, context) for spec in _MVP_DEMO_PHASE_SPECS]


def _mvp_demo_script_ready(
    *,
    workflow: dict[str, Any],
    demo_readiness: dict[str, Any],
    demo_playbook: dict[str, Any],
    network_entry_profile: dict[str, Any],
    network_harness_agent: dict[str, Any],
    consumer_sdk_bootstrap: dict[str, Any],
    phases: list[dict[str, Any]],
) -> bool:
    return bool(
        workflow.get("valid")
        and demo_readiness.get("status") == "ready"
        and demo_playbook.get("status") == "ready"
        and network_entry_profile.get("status") == "ready"
        and network_harness_agent.get("status") == "ready"
        and consumer_sdk_bootstrap.get("status") == "ready"
        and len(phases) == len(_MVP_DEMO_PHASE_SPECS)
    )


def _mvp_demo_script_payload(
    params: MvpDemoScriptInput,
    context: dict[str, Any],
    phases: list[dict[str, Any]],
    ready: bool,
) -> dict[str, Any]:
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "KillerMvpDemoScript",
        "status": "ready" if ready else "needs_attention",
        "script_id": "cbn.killer-mvp.demo-script.v1",
        "title": "CBN Killer MVP: CLI tools become a reusable agent-callable network",
        "workflow_path": params.workflow_path,
        "workflow_id": params.workflow.get("workflow_id"),
        "audience": ["product_reviewer", "integration_partner", "developer_platform"],
        "promise": "A third-party program can enter CBN once, inspect the CLI-CLI bus, call a natural-language harness agent, run the workflow, and reuse the network for the next CLI.",
        "phase_count": len(phases),
        "phases": phases,
        "runtime_story": _mvp_demo_runtime_story(
            setup_guidance=params.setup_guidance,
            network_entry_profile=params.network_entry_profile,
            network_harness_agent=params.network_harness_agent,
            consumer_sdk_bootstrap=params.consumer_sdk_bootstrap,
        ),
        "evidence_sources": _mvp_demo_evidence_sources(context["evidence_endpoints"]),
        "success_criteria": _mvp_demo_success_criteria(),
        "operator_cues": _mvp_demo_operator_cues(),
        "handoff_commands": _command_deck_commands(params.command_deck),
        "registration_next_commands": context["registration_next_commands"],
        "protocol_targets": params.protocol_summary.get("targets", []),
    }


def _mvp_demo_runtime_story(
    *,
    setup_guidance: dict[str, Any],
    network_entry_profile: dict[str, Any],
    network_harness_agent: dict[str, Any],
    consumer_sdk_bootstrap: dict[str, Any],
) -> dict[str, Any]:
    secret_policy = (
        "redacted"
        if (setup_guidance.get("safety") or {}).get("secret_values_included") is False
        else "inspect"
    )
    return {
        "primary_surface": "Workflow Studio",
        "external_protocol": "AgentCliCard + RunReceipt",
        "internal_bus": "CBN BridgeMessage",
        "harness_agent": (network_harness_agent.get("harness") or {}).get(
            "kind",
            "NaturalLanguageWorkflowHarness",
        ),
        "one_shot_entry": network_entry_profile.get("profile_id"),
        "sdk_bootstrap": consumer_sdk_bootstrap.get("bootstrap_id"),
        "secret_policy": secret_policy,
    }


def _mvp_demo_evidence_sources(evidence_endpoints: dict[str, Any]) -> dict[str, Any]:
    return {
        "connect_package": "NetworkConnectPackage",
        "readiness": "KillerMvpReadiness",
        "demo_playbook": "KillerMvpDemoPlaybook",
        "acceptance": "NetworkConnectionAcceptance",
        "events": evidence_endpoints.get("events"),
        "audit": evidence_endpoints.get("audit"),
        "artifacts": evidence_endpoints.get("artifacts"),
    }


def _mvp_demo_success_criteria() -> list[str]:
    return [
        "Reviewer can follow the phase order without reading raw JSON first.",
        "CLI-CLI BridgeMessage selector routing is visible before and after the run.",
        "NaturalLanguageWorkflowHarness is reusable for external programs.",
        "Runtime artifacts, events, and audit records prove execution.",
        "MCP/A2A/ACP export and dry-run-first CLI registration prove extension paths.",
    ]


def _mvp_demo_operator_cues() -> list[str]:
    return [
        "Open with the one-shot connect package, then zoom into Workflow Studio.",
        "Use the command deck only when the UI needs a CLI-backed proof point.",
        "Call out secret redaction before showing setup or SDK bootstrap payloads.",
        "End on next-CLI registration to show this is infrastructure, not a single demo.",
    ]


def _command_deck_commands(command_deck: list[dict[str, Any]]) -> list[str]:
    return [
        str(command.get("command"))
        for command in command_deck
        if isinstance(command, dict) and command.get("command")
    ]


def _mvp_demo_phase(spec: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    playbook_step_by_id = context["playbook_step_by_id"]
    command_by_id = context["command_by_id"]
    playbook_step_ids = spec["playbook_step_ids"]
    command_ids = spec["command_ids"]
    return {
        "id": spec["id"],
        "title": spec["title"],
        "narrative": spec["narrative"],
        "playbook_step_ids": playbook_step_ids,
        "playbook_titles": [
            str(playbook_step_by_id[step_id].get("title"))
            for step_id in playbook_step_ids
            if step_id in playbook_step_by_id
        ],
        "command_ids": command_ids,
        "commands": [
            {
                "id": command_id,
                "title": command_by_id[command_id].get("title"),
                "command": command_by_id[command_id].get("command"),
                "copy_label": command_by_id[command_id].get("copy_label"),
            }
            for command_id in command_ids
            if command_id in command_by_id
        ],
        "evidence_sources": spec["evidence_sources"],
        "success_signal": spec["success_signal"],
    }


def _mvp_presenter_brief(params: MvpPresenterInput) -> dict[str, Any]:
    """Audience-facing brief for presenting the killer MVP without reading raw JSON first."""

    return _mvp_presenter_brief_from_params(params)


def _mvp_presenter_brief_from_params(params: MvpPresenterInput) -> dict[str, Any]:
    context = _mvp_presenter_context(params)
    return _mvp_presenter_payload(params.__dict__, context)


def _mvp_presenter_context(params: MvpPresenterInput) -> dict[str, Any]:
    state = _mvp_presenter_state(
        quickstart=params.quickstart,
        request_plan=params.request_plan,
        registration_surface=params.registration_surface,
        demo_readiness=params.demo_readiness,
        demo_playbook=params.demo_playbook,
        mvp_readiness=params.mvp_readiness,
    )
    return {
        **state,
        **_mvp_presenter_commands(
            registration_surface=params.registration_surface,
            base_url=params.base_url,
            workflow_path=params.workflow_path,
            session_token=params.session_token,
            agent_message=state["agent_message"],
        ),
    }


def _mvp_presenter_state(
    *,
    quickstart: dict[str, Any],
    request_plan: dict[str, Any],
    registration_surface: dict[str, Any],
    demo_readiness: dict[str, Any],
    demo_playbook: dict[str, Any],
    mvp_readiness: dict[str, Any],
) -> dict[str, Any]:
    request_plan_run = _dict_field(request_plan, "run")
    request = _dict_field(request_plan, "request")
    agent_message = request.get("message") or DEFAULT_AGENT_CONNECT_MESSAGE
    product_goals = _dict_field(mvp_readiness, "product_goals")
    return {
        "agent_message": agent_message,
        "brief_ready": _mvp_presenter_brief_ready(mvp_readiness, demo_playbook, demo_readiness),
        "entrypoints": _dict_field(quickstart, "entrypoints"),
        "goal_count": len(product_goals),
        "harness": _dict_field(request_plan, "reusable_harness"),
        "live_demo_flow": _mvp_live_demo_flow(_list_field(demo_playbook, "steps")),
        "product_goals": product_goals,
        "ready_goal_count": sum(1 for ready in product_goals.values() if ready),
        "registration_next_commands": _string_list_field(registration_surface, "next_commands"),
        "request_plan_http": _dict_field(request_plan_run, "http"),
    }


def _mvp_presenter_brief_ready(
    mvp_readiness: dict[str, Any],
    demo_playbook: dict[str, Any],
    demo_readiness: dict[str, Any],
) -> bool:
    return bool(
        mvp_readiness.get("status") == "ready"
        and demo_playbook.get("status") == "ready"
        and demo_readiness.get("status") == "ready"
    )


def _string_list_field(data: dict[str, Any], key: str) -> list[str]:
    return [str(item) for item in _list_field(data, key) if isinstance(item, str)]


def _mvp_presenter_commands(
    *,
    registration_surface: dict[str, Any],
    base_url: str | None,
    workflow_path: str,
    session_token: str | None,
    agent_message: str,
) -> dict[str, Any]:
    base = base_url.rstrip("/") if base_url else None
    return {
        **_mvp_presenter_core_commands(
            registration_surface=registration_surface,
            base_url=base_url,
            base=base,
            workflow_path=workflow_path,
            session_token=session_token,
            agent_message=agent_message,
        ),
        **_mvp_presenter_registration_commands(registration_surface),
        **_mvp_presenter_protocol_commands(workflow_path),
        **_mvp_presenter_readiness_commands(workflow_path, base_url, base, session_token),
    }


def _mvp_presenter_core_commands(
    *,
    registration_surface: dict[str, Any],
    base_url: str | None,
    base: str | None,
    workflow_path: str,
    session_token: str | None,
    agent_message: str,
) -> dict[str, Any]:
    return {
        "agent_plan_command": _adapter_agent_workflow_request_command(workflow_path, message=agent_message),
        "connect_package_command": _network_connect_package_command(
            workflow_path,
            base_url=base_url,
            session_token=session_token,
        ),
        "connect_package_url": _absolute_url(
            base,
            f"/network/connect-package?{urlencode({'workflow_path': workflow_path})}",
        ),
        "demo_run_command": _demo_killer_command(workflow_path, smoke_suite=False),
        "demo_smoke_command": _demo_killer_command(workflow_path, smoke_suite=True),
    }


def _mvp_presenter_registration_commands(registration_surface: dict[str, Any]) -> dict[str, Any]:
    return {
        "cli_anything_import_command": _registration_command(
            registration_surface,
            "cli-anything",
            fallback="python -m cbn import cli-anything --help",
        ),
        "mcp_import_command": _registration_command(
            registration_surface,
            "mcp",
            fallback="python -m cbn import mcp --help",
        ),
        "next_cli_command": _registration_command(
            registration_surface,
            "command",
            fallback="python -m cbn import command --help",
        ),
        "parser_fixture_command": _registration_command(
            registration_surface,
            "parser-fixture",
            fallback="python -m cbn record-parser-fixture --help",
        ),
        "skill_import_command": _registration_command(
            registration_surface,
            "skill",
            fallback="python -m cbn import skill --help",
        ),
    }


def _mvp_presenter_protocol_commands(workflow_path: str) -> dict[str, str]:
    return {
        "protocol_export_command": _protocol_export_workflows_command(workflow_path),
        "protocol_smoke_command": _protocol_smoke_suite_command(workflow_path),
    }


def _mvp_presenter_readiness_commands(
    workflow_path: str,
    base_url: str | None,
    base: str | None,
    session_token: str | None,
) -> dict[str, Any]:
    return {
        "readiness_command": _network_quickstart_command(
            workflow_path,
            base_url=base_url,
            session_token=session_token,
            output="readiness",
        ),
        "readiness_url": _absolute_url(base, f"/network/readiness?{urlencode({'workflow_path': workflow_path})}"),
        "sdk_bootstrap_command": _network_quickstart_command(
            workflow_path,
            base_url=base_url,
            session_token=session_token,
            output="sdk-bootstrap",
        ),
        "verify_command": _network_verify_command(workflow_path, base_url=base_url, session_token=session_token),
    }


def _mvp_live_demo_flow(playbook_steps: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": step.get("id"),
            "title": step.get("title"),
            "target": step.get("target"),
            "success_signal": step.get("success_signal"),
        }
        for step in playbook_steps
        if isinstance(step, dict)
    ]


def _mvp_presenter_proof_points(
    *,
    protocol_summary: dict[str, Any],
    quickstart: dict[str, Any],
    network_entry_profile: dict[str, Any],
    harness: dict[str, Any],
) -> list[dict[str, Any]]:
    values = _mvp_presenter_proof_values(
        protocol_summary=protocol_summary,
        quickstart=quickstart,
        network_entry_profile=network_entry_profile,
        harness=harness,
    )
    return [
        _mvp_presenter_proof_point(proof_id, title, evidence_source, metric, values[proof_id])
        for proof_id, title, evidence_source, metric in _MVP_PRESENTER_PROOF_SPECS
    ]


def _mvp_presenter_proof_values(
    *,
    protocol_summary: dict[str, Any],
    quickstart: dict[str, Any],
    network_entry_profile: dict[str, Any],
    harness: dict[str, Any],
) -> dict[str, Any]:
    bridge_route_count = network_entry_profile.get("harness_agent", {}).get("bridge_route_count", 0)
    request_count = quickstart.get("consumer_sdk_bootstrap_request_count", 0) or len(quickstart.get("requests", []))
    acceptance = quickstart.get("acceptance", {})
    return {
        "protocol_boundary": "AgentCliCard + RunReceipt",
        "bridge_message_bus": f"{bridge_route_count} BridgeMessage routes",
        "reusable_harness_agent": harness.get("kind", "NaturalLanguageWorkflowHarness"),
        "one_shot_network_entry": network_entry_profile.get("profile_id"),
        "sdk_bootstrap_handoff": f"{request_count} typed requests",
        "first_call_acceptance": f"{acceptance.get('check_count', 0)} checks",
        "protocol_facades": ", ".join(protocol_summary.get("targets", [])),
    }


def _mvp_presenter_proof_point(
    proof_id: str,
    title: str,
    evidence_source: str,
    metric: str,
    value: Any,
) -> dict[str, Any]:
    return {
        "id": proof_id,
        "title": title,
        "evidence_source": evidence_source,
        "metric": metric,
        "value": value,
    }


def _mvp_presenter_handoff(
    *,
    request_plan: dict[str, Any],
    registration_surface: dict[str, Any],
    studio_link: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    entrypoints = context["entrypoints"]
    request_plan_http = context["request_plan_http"]
    return {
        "connect_package_url": context["connect_package_url"],
        "connect_package_command": context["connect_package_command"],
        "harness_agent_url": entrypoints.get("harness_agent"),
        "agent_plan_url": _mvp_presenter_entrypoint_url(entrypoints, "plan_agent_request"),
        "agent_plan_command": context["agent_plan_command"],
        "protocol_export_url": entrypoints.get("export_protocols"),
        "protocol_export_command": context["protocol_export_command"],
        "protocol_smoke_command": context["protocol_smoke_command"],
        "demo_run_command": context["demo_run_command"],
        "demo_smoke_command": context["demo_smoke_command"],
        "events_url": entrypoints.get("events"),
        "audit_url": entrypoints.get("audit"),
        "artifacts_url": entrypoints.get("artifacts"),
        "registration_catalog_url": entrypoints.get("import_catalog"),
        "registration_catalog_command": _mvp_presenter_registration_command(context),
        "next_cli_command": context["next_cli_command"],
        "cli_anything_import_command": context["cli_anything_import_command"],
        "mcp_import_command": context["mcp_import_command"],
        "skill_import_command": context["skill_import_command"],
        "parser_fixture_command": context["parser_fixture_command"],
        "sdk_bootstrap_url": entrypoints.get("sdk_bootstrap"),
        "readiness_url": context["readiness_url"],
        "studio_url": studio_link.get("url"),
        "run_workflow_url": request_plan_http.get("url") or _mvp_presenter_entrypoint_url(entrypoints, "run_workflow"),
        "verify_command": context["verify_command"],
        "readiness_command": context["readiness_command"],
        "sdk_bootstrap_command": context["sdk_bootstrap_command"],
    }


def _mvp_presenter_entrypoint_url(entrypoints: dict[str, Any], key: str) -> Any:
    entrypoint = entrypoints.get(key)
    return entrypoint.get("url") if isinstance(entrypoint, dict) else None


def _mvp_presenter_registration_command(context: dict[str, Any]) -> str:
    commands = context["registration_next_commands"]
    return commands[0] if commands else "python -m cbn import catalog"


def _mvp_presenter_payload(
    params: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    mvp_readiness = params["mvp_readiness"]
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "KillerMvpPresenterBrief",
        "status": "ready" if context["brief_ready"] else "needs_attention",
        "headline": "CBN turns CLI tools into a reusable agent-callable network with visible BridgeMessage handoffs.",
        "subheadline": "The demo shows one external contract, one internal bus, one natural-language harness agent, and one Workflow Studio evidence surface.",
        "workflow_path": params["workflow_path"],
        "workflow_id": params["workflow"].get("workflow_id"),
        "audience": ["product_demo", "integration_partner", "developer_platform"],
        "narrative": _mvp_presenter_narrative(),
        "proof_points": _mvp_presenter_proof_points(
            protocol_summary=params["protocol_summary"],
            quickstart=params["quickstart"],
            network_entry_profile=params["network_entry_profile"],
            harness=context["harness"],
        ),
        "live_demo_flow": context["live_demo_flow"],
        "integration_handoff": _mvp_presenter_handoff(
            request_plan=params["request_plan"],
            registration_surface=params["registration_surface"],
            studio_link=params["studio_link"],
            context=context,
        ),
        "command_deck": params["command_deck"],
        "decision_gates": _mvp_presenter_decision_gates(
            mvp_readiness=mvp_readiness,
            setup_guidance=params["setup_guidance"],
            demo_readiness=params["demo_readiness"],
            demo_playbook=params["demo_playbook"],
            context=context,
        ),
        "recommended_next_action": mvp_readiness.get("recommended_next_action", "open_workflow_studio_demo"),
        "next_commands": _mvp_presenter_next_commands(params["registration_surface"], context),
    }


def _mvp_presenter_narrative() -> list[str]:
    return [
        "Start from the small AgentCliCard/RunReceipt boundary instead of exposing CBN internals.",
        "Convert external tool contracts into ToolManifest records and BridgeMessage selector routes.",
        "Let a reusable harness agent bind natural language to the selected CLI-CLI workflow.",
        "Run macrocli -> transform -> mermaid and inspect artifact, event, audit, and protocol export evidence.",
        "Finish by showing how the next CLI enters through dry-run-first registration.",
    ]


def _mvp_presenter_decision_gates(
    *,
    mvp_readiness: dict[str, Any],
    setup_guidance: dict[str, Any],
    demo_readiness: dict[str, Any],
    demo_playbook: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ready_goal_count": context["ready_goal_count"],
        "goal_count": context["goal_count"],
        "mvp_readiness_score": mvp_readiness.get("score"),
        "setup_status": setup_guidance.get("status"),
        "setup_required": setup_guidance.get("setup_required"),
        "demo_stage_count": demo_readiness.get("stage_count", 0),
        "playbook_step_count": demo_playbook.get("step_count", 0),
    }


def _mvp_presenter_next_commands(
    registration_surface: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    return [
        context["connect_package_command"],
        context["agent_plan_command"],
        context["protocol_export_command"],
        context["protocol_smoke_command"],
        context["demo_run_command"],
        context["demo_smoke_command"],
        context["verify_command"],
        context["readiness_command"],
        context["sdk_bootstrap_command"],
        (registration_surface.get("next_commands") or ["python -m cbn import command --help"])[0],
    ]


def _internal_bridge_contract(bridge_contract: dict[str, Any]) -> dict[str, Any]:
    contract = bridge_contract.get("contract")
    if not isinstance(contract, dict):
        return {}
    return contract


_WORKFLOW_STUDIO_LINK_OPTION_NAMES = tuple(WorkflowStudioDemoLinkRequest.__dataclass_fields__)
_NETWORK_ACCEPTANCE_OPTION_NAMES = tuple(NetworkAcceptanceReportRequest.__dataclass_fields__)


def workflow_studio_demo_link(*args: Any, **options: Any) -> dict[str, Any]:
    """Return a preconfigured Workflow Studio URL for the killer demo."""

    request = _request_from_options(WorkflowStudioDemoLinkRequest, _WORKFLOW_STUDIO_LINK_OPTION_NAMES, args, options)
    query: dict[str, str] = {
        "workflowPath": request.workflow_path,
        "agentMessage": request.agent_message,
        "dryRun": "true" if request.dry_run else "false",
        "confirmed": "true" if request.confirmed else "false",
    }
    if request.daemon_url:
        query["daemonUrl"] = request.daemon_url.rstrip("/")
    if request.dashboard_url:
        query["dashboardUrl"] = request.dashboard_url.rstrip("/")
    if request.session_token:
        query["sessionToken"] = request.session_token
    clean_studio_url = request.studio_url.rstrip("/")
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "WorkflowStudioDemoLink",
        "ok": True,
        "studio_url": clean_studio_url,
        "dashboard_url": request.dashboard_url.rstrip("/") if request.dashboard_url else None,
        "daemon_url": request.daemon_url.rstrip("/") if request.daemon_url else None,
        "workflow_path": request.workflow_path,
        "dry_run": request.dry_run,
        "confirmed": request.confirmed,
        "session_token_included": bool(request.session_token),
        "url": f"{clean_studio_url}/?{urlencode(query)}",
        "query": query,
    }


def network_acceptance_report(
    registry: ManifestRegistry,
    *args: Any,
    **options: Any,
) -> dict[str, Any]:
    """Run the one-shot network acceptance checklist against a live daemon."""

    request = _request_from_options(NetworkAcceptanceReportRequest, _NETWORK_ACCEPTANCE_OPTION_NAMES, args, options)
    package = network_connect_package(
        registry,
        workflow_path=request.workflow_path,
        base_url=request.base_url,
        studio_url=request.studio_url,
        dashboard_url=request.dashboard_url,
        session_token=request.session_token,
        agent_message=request.agent_message,
    )
    context = _network_acceptance_context(package)
    results = _network_acceptance_results(context, request.timeout_seconds)
    summary = _network_acceptance_summary(package, context, results)
    ok = _network_acceptance_ok(package, context["mvp_readiness"], summary)
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "NetworkConnectionAcceptanceReport",
        "ok": ok,
        "status": _network_acceptance_status(ok, summary),
        "workflow_path": request.workflow_path,
        "base_url": request.base_url.rstrip("/"),
        "summary": summary,
        "acceptance": context["acceptance"],
        "mvp_readiness": context["mvp_readiness"],
        "results": results,
        "next_commands": _network_acceptance_next_commands(request.workflow_path, request.base_url, request.session_token),
    }


def _request_from_options(factory: Any, names: tuple[str, ...], args: tuple[Any, ...], options: dict[str, Any]) -> Any:
    if len(args) > len(names):
        raise TypeError(f"{factory.__name__} expected at most {len(names)} arguments")
    values = {}
    for name, value in zip(names, args):
        if name in options:
            raise TypeError(f"{factory.__name__} got multiple values for argument '{name}'")
        values[name] = value
    unknown = sorted(set(options) - set(names))
    if unknown:
        raise TypeError(f"unknown {factory.__name__} option(s): {', '.join(unknown)}")
    values.update(options)
    return factory(**values)


def _network_acceptance_context(package: dict[str, Any]) -> dict[str, Any]:
    quickstart = _dict_field(package, "consumer_quickstart")
    acceptance = _dict_field(quickstart, "acceptance")
    requests = _list_field(quickstart, "requests")
    return {
        "quickstart": quickstart,
        "acceptance": acceptance,
        "mvp_readiness": _dict_field(package, "mvp_readiness"),
        "requests": requests,
        "requests_by_id": {
            str(request.get("id")): request
            for request in requests
            if isinstance(request, dict) and request.get("id")
        },
    }


def _network_acceptance_results(
    context: dict[str, Any],
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    return [
        run_acceptance_check(check, context["requests_by_id"], timeout_seconds=timeout_seconds)
        for check in _list_field(context["acceptance"], "checks")
        if isinstance(check, dict)
    ]


def _network_acceptance_summary(
    package: dict[str, Any],
    context: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "connect_package_ok": bool(package.get("ok")),
        "request_count": len(context["requests"]),
        "check_count": len(results),
        "passed": sum(1 for result in results if result["status"] == "passed"),
        "failed": sum(1 for result in results if result["status"] == "failed"),
        "skipped": sum(1 for result in results if result["status"] == "skipped"),
        "mvp_readiness_status": context["mvp_readiness"].get("status"),
        "mvp_readiness_score": context["mvp_readiness"].get("score"),
    }


def _network_acceptance_ok(
    package: dict[str, Any],
    mvp_readiness: dict[str, Any],
    summary: dict[str, Any],
) -> bool:
    return bool(
        package.get("ok")
        and mvp_readiness.get("status") == "ready"
        and summary["check_count"] > 0
        and summary["failed"] == 0
        and summary["skipped"] == 0
    )


def _network_acceptance_status(ok: bool, summary: dict[str, Any]) -> str:
    if ok:
        return "passed"
    if summary["failed"]:
        return "failed"
    if summary["skipped"]:
        return "skipped"
    return "not_run"


def _network_acceptance_next_commands(
    workflow_path: str,
    base_url: str,
    session_token: str | None,
) -> list[str]:
    return [
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
    ]


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
        ("GET", "/network/acceptance", "read only the machine-readable network acceptance checklist"),
        ("GET", "/network/launch-contract", "read only the redacted launch contract for external programs"),
        ("GET", "/network/entry-profile", "read only the stable external integration profile"),
        ("GET", "/network/harness-agent", "read only the reusable natural-language harness agent contract"),
        ("GET", "/network/sdk-bootstrap", "read only the stable SDK bootstrap contract for external programs"),
        ("GET", "/network/consumer-manifest", "read the redacted persistable consumer network manifest"),
        ("GET", "/network/readiness", "read only the killer MVP readiness matrix"),
        ("POST", "/network/verify", "run the live network acceptance checklist"),
        ("GET", "/imports/catalog", "read the dry-run-first CLI importer catalog"),
        ("GET", "/direct-cli/readiness", "read direct CLI profile parser, setup, and recovery readiness"),
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
    exports = _dict_field(protocol_exports, "exports")
    mcp = _dict_field(exports, "mcp")
    a2a = _dict_field(exports, "a2a")
    acp = _dict_field(exports, "acp")
    return {
        "export_count": len(exports),
        "targets": sorted(str(key) for key in exports),
        "mcp": {
            "workflow_tool_count": _list_count(mcp, "workflowTools"),
            "wire_facade": _wire_status(mcp),
        },
        "a2a": {
            "skill_count": _list_count(_dict_field(a2a, "agentCard"), "skills"),
            "wire_facade": _wire_status(a2a),
        },
        "acp": {
            "workflow_count": _list_count(acp, "workflows"),
            "wire_facade": _wire_status(acp),
        },
    }


def _list_count(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    return len(value) if isinstance(value, list) else 0


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
        "request": _compact_workflow_request(request),
        "reusable_harness": _compact_reusable_harness(reusable),
        "run": _compact_workflow_run(run),
        "bridge_routes": _compact_bridge_routes(plan),
        "bridge_message_channel": (message.get("metadata") or {}).get("channel"),
        "bridge_message": _compact_bridge_message(message),
        "next_commands": plan.get("next_commands", []),
    }


def _compact_workflow_request(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": request.get("message"),
        "binding": request.get("binding"),
        "intent": request.get("intent", {}),
    }


def _compact_reusable_harness(reusable: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": reusable.get("kind"),
        "accepts": reusable.get("accepts", []),
        "emits": reusable.get("emits", []),
        "contract": reusable.get("contract"),
    }


def _compact_workflow_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "payload": run.get("payload", {}),
        "cli": run.get("cli"),
        "http": run.get("http", {}),
    }


def _compact_bridge_routes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "task_id": route.get("task_id"),
            "uses": route.get("uses"),
            "needs": route.get("needs", []),
            "selectors": route.get("selectors", []),
            "communication": route.get("communication"),
        }
        for route in _list_of_dicts(plan.get("bridge_routes"))
    ]


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
    context = _compact_setup_context(plan)
    summary = context["summary"]
    setup_required = context["setup_required"]
    loop = context["loop"]
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "AdapterAgentSetupGuidance",
        "source_kind": plan.get("kind"),
        "ok": plan.get("ok"),
        "status": context["status"],
        "setup_required": setup_required,
        "next_action": "complete_user_setup" if setup_required else "ready_to_run",
        "workflow_path": plan.get("workflow_path"),
        "summary": summary,
        "requires_user_count": context["requires_user_count"],
        "secret_count": context["secret_count"],
        "setup_command_count": context["setup_command_count"],
        "workflow_capability_count": context["workflow_capability_count"],
        "tool_calls": [_compact_setup_tool_call(call) for call in _list_of_dicts(plan.get("tool_calls"))[:10]],
        "execution_batches": _compact_setup_batches(plan),
        "checkpoints": _compact_setup_checkpoints(loop),
        "safety": _compact_setup_safety(),
    }


def _compact_setup_context(plan: dict[str, Any]) -> dict[str, Any]:
    summary = _dict_field(plan, "summary")
    loop = _dict_field(plan, "long_running_loop")
    status = loop.get("status") or plan.get("status") or "unknown"
    counts = _compact_setup_counts(summary)
    requires_user_count = int(summary.get("requires_user_count", 0) or 0)
    return {
        "status": status,
        "loop": loop,
        "setup_required": _compact_setup_required(status, requires_user_count, counts),
        "summary": summary,
        "requires_user_count": requires_user_count,
        **counts,
    }


def _compact_setup_counts(summary: dict[str, Any]) -> dict[str, int]:
    kinds = _dict_field(summary, "by_kind")
    return {
        "secret_count": int(kinds.get("setup-secret", 0) or 0),
        "setup_command_count": int(kinds.get("setup-command", 0) or 0),
        "workflow_capability_count": int(kinds.get("workflow-capability", 0) or 0),
    }


def _compact_setup_required(status: Any, requires_user_count: int, counts: dict[str, int]) -> bool:
    return bool(
        status != "ready_to_run"
        or requires_user_count > 0
        or counts["secret_count"] > 0
        or counts["setup_command_count"] > 0
    )


def _compact_setup_batches(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "batch_id": batch.get("batch_id"),
            "mode": batch.get("mode"),
            "concurrency_safe": batch.get("concurrency_safe"),
            "tool_call_ids": batch.get("tool_call_ids", []),
            "tool_use_ids": batch.get("tool_use_ids", []),
            "reason": batch.get("reason"),
        }
        for batch in _list_of_dicts(plan.get("execution_batches"))[:8]
    ]


def _compact_setup_checkpoints(loop: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": checkpoint.get("id"),
            "owner": checkpoint.get("owner"),
            "status": checkpoint.get("status"),
            "evidence": checkpoint.get("evidence"),
        }
        for checkpoint in _list_of_dicts(loop.get("checkpoints"))[:8]
    ]


def _compact_setup_safety() -> dict[str, bool]:
    return {
        "read_only": True,
        "executes_tools": False,
        "secret_values_included": False,
        "secrets_must_not_be_pasted_in_chat": True,
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

    context = _consumer_quickstart_context(
        base_url=base_url,
        workflow_path=workflow_path,
        session_token=session_token,
        request_plan=request_plan,
    )
    entrypoints = _consumer_quickstart_entrypoints(studio_link, context)
    requests = _consumer_quickstart_requests(entrypoints, context)
    return _consumer_quickstart_payload(
        workflow_path=workflow_path,
        studio_link=studio_link,
        context=context,
        entrypoints=entrypoints,
        requests=requests,
    )


def _consumer_quickstart_context(
    *,
    base_url: str | None,
    workflow_path: str,
    session_token: str | None,
    request_plan: dict[str, Any],
) -> dict[str, Any]:
    clean_base_url = base_url.rstrip("/") if base_url else None
    queries = _consumer_quickstart_queries(workflow_path, request_plan)
    headers = {"X-CBN-Session": session_token} if session_token else {}
    plan_payload = _consumer_quickstart_plan_payload(workflow_path, request_plan)
    run_context = _consumer_quickstart_run_context(workflow_path, request_plan, clean_base_url)
    return {
        **queries,
        "clean_base_url": clean_base_url,
        "headers": headers,
        "plan_payload": plan_payload,
        "plan_url": _absolute_url(clean_base_url, "/adapter-agent/workflow-request-plan"),
        **run_context,
    }


def _consumer_quickstart_queries(
    workflow_path: str,
    request_plan: dict[str, Any],
) -> dict[str, str]:
    message = (request_plan.get("request") or {}).get("message", DEFAULT_AGENT_CONNECT_MESSAGE)
    return {
        "agent_query": urlencode({"workflow_path": workflow_path, "message": message}),
        "contract_query": urlencode({"workflow_path": workflow_path}),
        "launch_query": urlencode({"workflow_path": workflow_path}),
        "protocol_query": urlencode({"target": "all", "path": workflow_path}),
        "workflow_query": urlencode({"path": workflow_path}),
    }


def _consumer_quickstart_plan_payload(
    workflow_path: str,
    request_plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "workflow_path": workflow_path,
        "message": (request_plan.get("request") or {}).get("message", DEFAULT_AGENT_CONNECT_MESSAGE),
        "dry_run": True,
        "confirmed": False,
    }


def _consumer_quickstart_run_context(
    workflow_path: str,
    request_plan: dict[str, Any],
    clean_base_url: str | None,
) -> dict[str, Any]:
    run = request_plan.get("run") if isinstance(request_plan.get("run"), dict) else {}
    run_http = run.get("http") if isinstance(run.get("http"), dict) else {}
    raw_run_payload = run.get("payload") if isinstance(run.get("payload"), dict) else {}
    run_payload = {
        "path": workflow_path,
        "dry_run": raw_run_payload.get("dry_run", True),
        "confirmed": raw_run_payload.get("confirmed", False),
    }
    return {
        "run_http": run_http,
        "run_payload": run_payload,
        "run_url": run_http.get("url") or _absolute_url(clean_base_url, "/workflows/run"),
    }


def _consumer_quickstart_entrypoints(
    studio_link: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    clean_base_url = context["clean_base_url"]
    launch_query = context["launch_query"]
    return {
        "open_studio": studio_link.get("url"),
        "connect_package": _absolute_url(clean_base_url, f"/network/connect-package?{launch_query}"),
        "quickstart": _absolute_url(clean_base_url, f"/network/quickstart?{launch_query}"),
        "consumer_manifest": _absolute_url(clean_base_url, f"/network/consumer-manifest?{launch_query}"),
        "sdk_bootstrap": _absolute_url(clean_base_url, f"/network/sdk-bootstrap?{launch_query}"),
        "health": _absolute_url(clean_base_url, "/health"),
        "acceptance": _absolute_url(clean_base_url, f"/network/acceptance?{launch_query}"),
        "launch_contract": _absolute_url(clean_base_url, f"/network/launch-contract?{launch_query}"),
        "entry_profile": _absolute_url(clean_base_url, f"/network/entry-profile?{launch_query}"),
        "harness_agent": _absolute_url(clean_base_url, f"/network/harness-agent?{launch_query}"),
        "import_catalog": _absolute_url(clean_base_url, "/imports/catalog"),
        "direct_cli_readiness": _absolute_url(clean_base_url, "/direct-cli/readiness"),
        "inspect_workflow": _absolute_url(clean_base_url, f"/workflows?{context['workflow_query']}"),
        "inspect_bridge_contract": _absolute_url(clean_base_url, f"/messages/contract?{context['contract_query']}"),
        "inspect_agent_nodes": _absolute_url(clean_base_url, f"/adapter-agent/node-bundle?{context['agent_query']}"),
        "export_protocols": _absolute_url(clean_base_url, f"/protocols/workflows?{context['protocol_query']}"),
        "plan_agent_request": {
            "method": "POST",
            "url": context["plan_url"],
            "json": context["plan_payload"],
        },
        "run_workflow": {
            "method": context["run_http"].get("method", "POST"),
            "url": context["run_url"],
            "json": context["run_payload"],
        },
        "events": _absolute_url(clean_base_url, "/events"),
        "audit": _absolute_url(clean_base_url, "/audit"),
        "artifacts": _absolute_url(clean_base_url, "/artifacts"),
    }


def _consumer_quickstart_requests(
    entrypoints: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    headers = context["headers"]
    requests = [
        quickstart_request(request_id, "GET", entrypoints[request_id], headers=headers)
        for request_id in QUICKSTART_GET_REQUEST_IDS
    ]
    requests.extend(
        [
            quickstart_request(
                "plan_agent_request",
                "POST",
                context["plan_url"],
                headers=headers,
                json_payload=context["plan_payload"],
            ),
            quickstart_request(
                "run_workflow",
                context["run_http"].get("method", "POST"),
                context["run_url"],
                headers=headers,
                json_payload=context["run_payload"],
            ),
        ]
    )
    requests.extend(
        quickstart_request(request_id, "GET", entrypoints[request_id], headers=headers)
        for request_id in QUICKSTART_EVIDENCE_REQUEST_IDS
    )
    return requests


def _consumer_quickstart_payload(
    *,
    workflow_path: str,
    studio_link: dict[str, Any],
    context: dict[str, Any],
    entrypoints: dict[str, Any],
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    headers = context["headers"]
    return {
        "kind": "NetworkConnectQuickstart",
        "status": "ready" if context["clean_base_url"] else "ready_without_daemon_url",
        "required_headers": headers,
        "entrypoints": entrypoints,
        "requests": requests,
        "acceptance": network_connection_acceptance(workflow_path=workflow_path, requests=requests),
        "sdk_snippets": quickstart_sdk_snippets(
            workflow_path=workflow_path,
            requests=requests,
            headers=headers,
        ),
        "curl_script": quickstart_curl_script(requests),
        "powershell_script": quickstart_powershell_script(requests, headers=headers),
        "sequence": list(QUICKSTART_SEQUENCE),
        "sequence_steps": quickstart_sequence_steps(
            requests=requests,
            studio_url=studio_link.get("url"),
        ),
    }


def _absolute_url(base_url: str | None, path: str) -> str:
    return f"{base_url}{path}" if base_url else path


def _next_commands(workflow_path: str, *, base_url: str | None, session_token: str | None) -> list[str]:
    return [
        _network_verify_command(workflow_path, base_url=base_url, session_token=session_token),
        _adapter_agent_workflow_request_command(workflow_path, message=DEFAULT_AGENT_CONNECT_MESSAGE),
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


def _network_connect_package_command(workflow_path: str, *, base_url: str | None, session_token: str | None) -> str:
    args = ["python", "-m", "cbn", "network", "connect-package", "--workflow-path", workflow_path]
    if base_url:
        args.extend(["--base-url", base_url.rstrip("/")])
    if session_token:
        args.extend(["--session-token", session_token])
    return _command(args)


def _adapter_agent_workflow_request_command(workflow_path: str, *, message: str) -> str:
    return _command(
        [
            "python",
            "-m",
            "cbn_adapter_agent",
            "--workflow-request-plan",
            "--workflow-path",
            workflow_path,
            "--message",
            message,
        ]
    )


def _protocol_export_workflows_command(workflow_path: str) -> str:
    return _command(["python", "-m", "cbn", "protocol", "export-workflows", "all", "--path", workflow_path])


def _protocol_smoke_suite_command(workflow_path: str) -> str:
    return _command(
        [
            "python",
            "-m",
            "cbn",
            "protocol",
            "smoke-suite",
            "--workflow-path",
            workflow_path,
            "--workflow-dry-run",
        ]
    )


def _demo_killer_command(workflow_path: str, *, smoke_suite: bool) -> str:
    args = ["python", "-m", "cbn", "demo", "killer", "--workflow-path", workflow_path, "--run", "--dry-run"]
    if smoke_suite:
        args.append("--smoke-suite")
    return _command(args)


def _registration_command(registration_surface: dict[str, Any], importer_id: str, *, fallback: str) -> str:
    importers = registration_surface.get("importers") if isinstance(registration_surface.get("importers"), list) else []
    for importer in importers:
        if isinstance(importer, dict) and importer.get("id") == importer_id:
            command = importer.get("help_command") or importer.get("example")
            if isinstance(command, str) and command:
                return command
    return fallback


def _presenter_command(command_id: str, title: str, command: str, proves: str, copy_label: str) -> dict[str, str]:
    return {
        "id": command_id,
        "title": title,
        "command": command,
        "proves": proves,
        "copy_label": copy_label,
    }


def _presenter_command_deck(
    *,
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
    registration_surface: dict[str, Any],
    agent_message: str,
) -> list[dict[str, str]]:
    commands = _presenter_commands(
        workflow_path=workflow_path,
        base_url=base_url,
        session_token=session_token,
        registration_surface=registration_surface,
        agent_message=agent_message,
    )
    return [
        _presenter_connect_package_command(commands["connect_package"]),
        _presenter_harness_command(commands["agent_plan"]),
        _presenter_demo_command(commands["demo_run"]),
        _presenter_protocol_command(commands["protocol_export"]),
        _presenter_sdk_command(commands["sdk_bootstrap"]),
        _presenter_register_cli_command(commands["next_cli"]),
    ]


def _presenter_commands(
    *,
    workflow_path: str,
    base_url: str | None,
    session_token: str | None,
    registration_surface: dict[str, Any],
    agent_message: str,
) -> dict[str, str]:
    return {
        "connect_package": _network_connect_package_command(
            workflow_path,
            base_url=base_url,
            session_token=session_token,
        ),
        "agent_plan": _adapter_agent_workflow_request_command(workflow_path, message=agent_message),
        "demo_run": _demo_killer_command(workflow_path, smoke_suite=False),
        "protocol_export": _protocol_export_workflows_command(workflow_path),
        "sdk_bootstrap": _network_quickstart_command(
            workflow_path,
            base_url=base_url,
            session_token=session_token,
            output="sdk-bootstrap",
        ),
        "next_cli": _registration_command(
            registration_surface,
            "command",
            fallback="python -m cbn import command --help",
        ),
    }


def _presenter_connect_package_command(command: str) -> dict[str, str]:
    return _presenter_command(
        "connect_package",
        "Read one-shot connect package",
        command,
        "External programs can discover every CBN network entrypoint in one read.",
        "Copy Package",
    )


def _presenter_harness_command(command: str) -> dict[str, str]:
    return _presenter_command(
        "plan_harness",
        "Plan natural-language harness request",
        command,
        "A reusable harness agent can bind a natural-language request to the CLI-CLI workflow.",
        "Copy Harness",
    )


def _presenter_demo_command(command: str) -> dict[str, str]:
    return _presenter_command(
        "run_demo",
        "Run killer demo with evidence",
        command,
        "The macrocli -> transform -> mermaid chain produces artifacts, events, and audit records.",
        "Copy Demo",
    )


def _presenter_protocol_command(command: str) -> dict[str, str]:
    return _presenter_command(
        "export_protocols",
        "Export MCP/A2A/ACP facades",
        command,
        "The same workflow exports to MCP, A2A, and ACP descriptors.",
        "Copy Protocols",
    )


def _presenter_sdk_command(command: str) -> dict[str, str]:
    return _presenter_command(
        "sdk_bootstrap",
        "Read SDK bootstrap contract",
        command,
        "External SDKs can initialize from the focused typed bootstrap contract.",
        "Copy SDK",
    )


def _presenter_register_cli_command(command: str) -> dict[str, str]:
    return _presenter_command(
        "register_next_cli",
        "Register the next CLI",
        command,
        "New CLIs enter through dry-run-first importers before writing manifests.",
        "Copy CLI",
    )


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
