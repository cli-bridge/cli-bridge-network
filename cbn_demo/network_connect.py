"""One-shot network connection package for external CBN consumers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from cbn_adapter_agent.nodes import build_adapter_agent_node_bundle
from cbn_adapter_agent.workflow_request import build_agent_workflow_request_plan
from cbn_core.agent_cli_contract import agent_cli_card_to_tool_manifests, run_receipt_to_cbn_records
from cbn_core.manifest import ManifestRegistry
from cbn_demo.killer import DEFAULT_KILLER_WORKFLOW_PATH
from cbn_protocol.bridge_contract import workflow_bridge_contract_report
from cbn_protocol.exports import export_all_workflow_protocols
from cbn_workflow.catalog import inspect_workflow


CONTRACT_ROOT = Path("external_protocols/agent-cli-contract")
CONTRACT_CARD_FIXTURE = CONTRACT_ROOT / "fixtures/agent-cli-card.valid.json"
CONTRACT_RECEIPT_FIXTURE = CONTRACT_ROOT / "fixtures/run-receipt.valid.json"
CONNECT_API_VERSION = "bridge.dev/v1alpha1"


def network_connect_package(
    registry: ManifestRegistry,
    *,
    workflow_path: str = DEFAULT_KILLER_WORKFLOW_PATH,
    base_url: str | None = None,
    studio_url: str = "http://127.0.0.1:5177",
    session_token: str | None = None,
    agent_message: str = "Connect an external program to this CBN workflow.",
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
    external_contract = _external_agent_cli_contract()
    protocol_summary = _protocol_summary(protocol_exports)
    endpoint_catalog = _endpoint_catalog(base_url=base_url, workflow_path=workflow_path)
    studio_link = workflow_studio_demo_link(
        workflow_path=workflow_path,
        daemon_url=base_url,
        studio_url=studio_url,
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
            "agent_workflow_request_ready": request_plan.get("ok"),
            "external_contract_ready": external_contract.get("ok"),
            "recommended_next_action": "call_daemon_endpoints" if ok else "fix_connect_package_inputs",
        },
        "contracts": {
            "internal": {
                "tool_manifest": "bridge.dev/v1alpha1 ToolManifest",
                "bridge_message": "bridge.dev/v1alpha1 BridgeMessage",
                "artifact": "CBN Artifact records",
                "workflow_selector": "argsFrom selector records",
                "bridge_contract": {
                    "ok": bridge_contract.get("ok"),
                    "summary": bridge_contract.get("summary", {}),
                },
            },
            "external": external_contract,
        },
        "daemon_endpoints": endpoint_catalog,
        "workflow": _compact_workflow(workflow),
        "protocols": protocol_summary,
        "workflow_studio": studio_link,
        "agent_node_bundle": _compact_agent_bundle(agent_bundle),
        "agent_workflow_request": _compact_workflow_request_plan(request_plan),
        "consumer_quickstart": _consumer_quickstart(
            base_url=base_url,
            workflow_path=workflow_path,
            session_token=session_token,
            studio_link=studio_link,
            request_plan=request_plan,
        ),
        "next_commands": _next_commands(workflow_path),
    }


def workflow_studio_demo_link(
    *,
    workflow_path: str = DEFAULT_KILLER_WORKFLOW_PATH,
    daemon_url: str | None = None,
    studio_url: str = "http://127.0.0.1:5177",
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
    if session_token:
        query["sessionToken"] = session_token
    clean_studio_url = studio_url.rstrip("/")
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "WorkflowStudioDemoLink",
        "ok": True,
        "studio_url": clean_studio_url,
        "daemon_url": daemon_url.rstrip("/") if daemon_url else None,
        "workflow_path": workflow_path,
        "dry_run": dry_run,
        "confirmed": confirmed,
        "session_token_included": bool(session_token),
        "url": f"{clean_studio_url}/?{urlencode(query)}",
        "query": query,
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


def _endpoint_catalog(*, base_url: str | None, workflow_path: str) -> list[dict[str, Any]]:
    rows = [
        ("GET", "/network/connect-package", "read the full one-shot network connection package"),
        ("GET", "/network/quickstart", "read only the first-call quickstart payload"),
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
    return {
        "kind": bundle.get("kind"),
        "ok": bundle.get("ok"),
        "status": bundle.get("status"),
        "card_count": len(bundle.get("cards", [])),
        "task_count": len(bundle.get("tasks", [])),
        "bridge_message_channel": (bundle.get("bridge_message", {}).get("metadata") or {}).get("channel"),
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


def _compact_workflow_request_plan(plan: dict[str, Any]) -> dict[str, Any]:
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    run = plan.get("run") if isinstance(plan.get("run"), dict) else {}
    reusable = plan.get("reusable_harness") if isinstance(plan.get("reusable_harness"), dict) else {}
    message = plan.get("bridge_message") if isinstance(plan.get("bridge_message"), dict) else {}
    return {
        "kind": plan.get("kind"),
        "ok": plan.get("ok"),
        "status": plan.get("status"),
        "workflow_id": summary.get("workflow_id"),
        "bridge_route_count": summary.get("bridge_route_count", 0),
        "recommended_next_action": summary.get("recommended_next_action"),
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
        "bridge_message_channel": (message.get("metadata") or {}).get("channel"),
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
    headers = {"X-CBN-Session": session_token} if session_token else {}
    plan_payload = {
        "workflow_path": workflow_path,
        "message": (request_plan.get("request") or {}).get(
            "message",
            "Connect an external program to this CBN workflow.",
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
        "curl_script": _quickstart_curl_script(requests),
        "sequence": [
            "open_studio",
            "inspect_workflow",
            "inspect_bridge_contract",
            "plan_agent_request",
            "run_workflow",
            "read_events_audit_artifacts",
        ],
    }


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


def _absolute_url(base_url: str | None, path: str) -> str:
    return f"{base_url}{path}" if base_url else path


def _next_commands(workflow_path: str) -> list[str]:
    return [
        f"python -m cbn_adapter_agent --workflow-request-plan --workflow-path {workflow_path}",
        f"python -m cbn workflow inspect {workflow_path}",
        f"python -m cbn protocol export-workflows all --path {workflow_path}",
        f"python -m cbn demo killer --workflow-path {workflow_path} --run --dry-run",
    ]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
