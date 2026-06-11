"""One-shot network connection package for external CBN consumers."""

from __future__ import annotations

import json
import shlex
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from cbn_adapter_agent.nodes import build_adapter_agent_node_bundle
from cbn_adapter_agent.tool_call_plan import build_agent_tool_call_plan
from cbn_adapter_agent.workflow_request import build_agent_workflow_request_plan
from cbn_core.agent_cli_contract import agent_cli_card_to_tool_manifests, run_receipt_to_cbn_records
from cbn_core.manifest import ManifestRegistry
from cbn_demo.killer import DEFAULT_KILLER_WORKFLOW_PATH, KILLER_CAPABILITIES
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
    demo_playbook = _demo_playbook(
        workflow_path=workflow_path,
        studio_link=studio_link,
        demo_readiness=demo_readiness,
        quickstart=quickstart,
        registration_surface=registration_surface,
        base_url=base_url,
        session_token=session_token,
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
            "external_contract_ready": external_contract.get("ok"),
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
        "workflow_studio": studio_link,
        "demo_readiness": demo_readiness,
        "demo_playbook": demo_playbook,
        "agent_node_bundle": _compact_agent_bundle(agent_bundle),
        "agent_workflow_request": _compact_workflow_request_plan(request_plan),
        "setup_guidance": setup_guidance,
        "registration_surface": registration_surface,
        "acceptance": quickstart["acceptance"],
        "consumer_quickstart": quickstart,
        "next_commands": _next_commands(workflow_path, base_url=base_url, session_token=session_token),
    }


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
    ok = bool(package.get("ok") and total > 0 and failed == 0 and skipped == 0)
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
        },
        "acceptance": acceptance,
        "results": results,
        "next_commands": [
            _network_quickstart_command(workflow_path, base_url=base_url, session_token=session_token),
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
    return {
        "ok": bool(manifests) and receipt_mapping.get("message", {}).get("kind") == "BridgeMessage",
        "protocol": "agent-cli-contract",
        "root": str(CONTRACT_ROOT),
        "card_fixture": str(CONTRACT_CARD_FIXTURE),
        "receipt_fixture": str(CONTRACT_RECEIPT_FIXTURE),
        "accepted_kinds": ["AgentCliCard", "RunReceipt"],
        "package_boundary": _agent_cli_contract_package_boundary(),
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


def _agent_cli_contract_package_boundary() -> dict[str, Any]:
    return {
        "kind": "ExternalProtocolPackageBoundary",
        "package_name": "agent-cli-contract",
        "npm_name": "@agent-cli/contract",
        "python_name": "agent-cli-contract",
        "version": "0.1.0",
        "root": str(CONTRACT_ROOT),
        "schemas": {
            "AgentCliCard": str(CONTRACT_ROOT / "schemas/agent-cli-card.schema.json"),
            "RunReceipt": str(CONTRACT_ROOT / "schemas/run-receipt.schema.json"),
        },
        "typescript_types": str(CONTRACT_ROOT / "ts/index.ts"),
        "python_validator": str(CONTRACT_ROOT / "python/agent_cli_contract/validator.py"),
        "fixtures": {
            "AgentCliCard": str(CONTRACT_CARD_FIXTURE),
            "RunReceipt": str(CONTRACT_RECEIPT_FIXTURE),
        },
        "conformance_smoke": {
            "command": "python external_protocols/agent-cli-contract/scripts/conformance_smoke.py",
            "script": str(CONTRACT_ROOT / "scripts/conformance_smoke.py"),
        },
        "dependency_boundary": {
            "standalone": True,
            "forbidden_cbn_modules": [
                "api_server",
                "cbn_workflow",
                "cbn_runtime",
                "cbn_protocol",
                "cbn_artifact",
                "cbn_audit",
            ],
            "allowed_scope": [
                "AgentCliCard schema",
                "RunReceipt schema",
                "TypeScript types",
                "Python validation CLI",
                "fixtures",
                "conformance smoke",
            ],
        },
        "cbn_mapping_responsibility": {
            "AgentCliCard": "CBN maps external command declarations to ToolManifest records.",
            "RunReceipt": "CBN maps run receipts to BridgeMessage, Artifact records, Audit evidence, and Events.",
        },
    }


def _registration_surface() -> dict[str, Any]:
    importers = [
        {
            "id": "command",
            "title": "Import ordinary CLI command",
            "entrypoint": "cbn import command",
            "accepts": ["executable", "args_template", "parser_ref"],
            "produces": ["ToolManifest"],
            "default_side_effects": "none",
            "write_gate": "--write",
            "confirm_gate": None,
            "example": "python -m cbn import command demo.echo echo --arg hello",
        },
        {
            "id": "cli-anything",
            "title": "Import CLI-Anything harness",
            "entrypoint": "cbn import cli-anything",
            "accepts": ["harness_name", "market metadata", "optional install request"],
            "produces": ["ToolManifest", "onboarding report", "verification plan"],
            "default_side_effects": "none",
            "write_gate": "--write",
            "confirm_gate": "--yes for --write or --install",
            "example": "python -m cbn import cli-anything mermaid --from-market",
        },
        {
            "id": "agent-cli-card",
            "title": "Import AgentCliCard",
            "entrypoint": "cbn import agent-cli-card",
            "accepts": ["agent-cli-contract AgentCliCard JSON"],
            "produces": ["ToolManifest"],
            "default_side_effects": "none",
            "write_gate": "--write",
            "confirm_gate": None,
            "example": "python -m cbn import agent-cli-card external_protocols/agent-cli-contract/fixtures/agent-cli-card.valid.json",
        },
        {
            "id": "mcp",
            "title": "Import MCP tool descriptor",
            "entrypoint": "cbn import mcp",
            "accepts": ["MCP tool descriptor JSON", "adapter command"],
            "produces": ["ToolManifest"],
            "default_side_effects": "none",
            "write_gate": "--write",
            "confirm_gate": None,
            "example": "python -m cbn import mcp tool.json --server-id local --adapter-command python",
        },
        {
            "id": "skill",
            "title": "Import skill descriptor",
            "entrypoint": "cbn import skill",
            "accepts": ["UTF-8 JSON or Markdown skill descriptor", "runner command"],
            "produces": ["ToolManifest"],
            "default_side_effects": "none",
            "write_gate": "--write",
            "confirm_gate": None,
            "example": "python -m cbn import skill SKILL.md --command python",
        },
        {
            "id": "parser-fixture",
            "title": "Record parser fixture",
            "entrypoint": "cbn record-parser-fixture",
            "accepts": ["parser_ref", "stdout", "stderr", "exit_code"],
            "produces": ["ParserFixture"],
            "default_side_effects": "none",
            "write_gate": "--write",
            "confirm_gate": None,
            "example": "python -m cbn record-parser-fixture raw.text demo --stdout output.txt",
        },
    ]
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "CliRegistrationSurface",
        "status": "ready",
        "importer_count": len(importers),
        "default_policy": {
            "dry_run_by_default": True,
            "writes_require_explicit_flag": True,
            "side_effects_require_confirmation": True,
            "utf8_required": True,
        },
        "importers": importers,
        "next_commands": [
            "python -m cbn import command --help",
            "python -m cbn import cli-anything --help",
            "python -m cbn import agent-cli-card --help",
            "python -m cbn import mcp --help",
            "python -m cbn import skill --help",
            "python -m cbn record-parser-fixture --help",
        ],
    }


def _endpoint_catalog(*, base_url: str | None, workflow_path: str) -> list[dict[str, Any]]:
    rows = [
        ("GET", "/network/connect-package", "read the full one-shot network connection package"),
        ("GET", "/network/quickstart", "read only the first-call quickstart payload"),
        ("POST", "/network/verify", "run the live network acceptance checklist"),
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
            "inspect_workflow",
            "inspect_bridge_contract",
            "inspect_agent_nodes",
            "export_protocols",
            "plan_agent_request",
            "run_workflow",
            "read_events_audit_artifacts",
        ],
    }


def _quickstart_sdk_snippets(
    *,
    workflow_path: str,
    requests: list[dict[str, Any]],
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    requests_by_id = {str(request.get("id")): request for request in requests if request.get("id")}
    required_ids = ["health", "plan_agent_request", "run_workflow", "events", "audit", "artifacts"]
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
        for request_id in ["health", "plan_agent_request", "run_workflow", "events", "audit", "artifacts"]
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
            "plan = call('plan_agent_request')",
            "receipt = call('run_workflow')",
            "evidence = {key: call(key) for key in ('events', 'audit', 'artifacts')}",
            "print(json.dumps({'plan': plan.get('kind'), 'workflow_status': receipt.get('status'), 'evidence': {k: len(v) for k, v in evidence.items()}}, indent=2))",
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
        if request_id in {"health", "plan_agent_request", "run_workflow", "events", "audit", "artifacts"}
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
            "const plan = await call('plan_agent_request');",
            "const receipt = await call('run_workflow');",
            "const [events, audit, artifacts] = await Promise.all([call('events'), call('audit'), call('artifacts')]);",
            "console.log({ plan: plan.kind, workflowStatus: receipt.status, evidence: { events: events.length, audit: audit.length, artifacts: artifacts.length } });",
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
