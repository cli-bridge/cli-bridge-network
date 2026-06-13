"""Pure quickstart formatting helpers for external CBN consumers."""

from __future__ import annotations

import json
from typing import Any

from cbn_demo.network_specs import QUICKSTART_EVIDENCE_REQUEST_IDS, QUICKSTART_SDK_REQUEST_IDS


def quickstart_typed_responses(
    *,
    network_entry_profile: dict[str, Any] | None = None,
    network_harness_agent: dict[str, Any] | None = None,
) -> dict[str, str]:
    entry_profile = network_entry_profile or {}
    harness_agent = network_harness_agent or {}
    return {
        "health": "HealthReport",
        "launch_contract": "ConsumerLaunchContract",
        "entry_profile": entry_profile.get("kind", "NetworkEntryProfile"),
        "harness_agent": harness_agent.get("kind", "NetworkHarnessAgent"),
        "sdk_bootstrap": "ConsumerSdkBootstrap",
        "consumer_manifest": "NetworkConsumerManifest",
        "import_catalog": "CliRegistrationSurface",
        "direct_cli_readiness": "DirectCliReadinessReport",
        "inspect_workflow": "WorkflowInspect",
        "inspect_bridge_contract": "BridgeContractReport",
        "inspect_agent_nodes": "AdapterAgentNodeBundle",
        "export_protocols": "ProtocolExports",
        "plan_agent_request": "AdapterAgentWorkflowRequestPlan",
        "run_workflow": "WorkflowRunReceipt",
        "events": "EventList",
        "audit": "AuditList",
        "artifacts": "ArtifactList",
    }


def quickstart_request(
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


def quickstart_curl_script(requests: list[dict[str, Any]]) -> str:
    lines = ["set -e"]
    lines.extend(str(request.get("curl", "")) for request in requests if request.get("curl"))
    return "\n".join(lines)


def quickstart_powershell_script(requests: list[dict[str, Any]], *, headers: dict[str, str]) -> str:
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


def quickstart_sequence_steps(*, requests: list[dict[str, Any]], studio_url: str | None) -> list[dict[str, Any]]:
    requests_by_id = {str(request.get("id")): request for request in requests if request.get("id")}
    step_definitions = quickstart_request_step_definitions()
    evidence_order = len(step_definitions) + 2
    return [
        quickstart_open_studio_step(studio_url),
        *(
            quickstart_request_step(index, requests_by_id, request_id, title, intent, success_signal)
            for index, (request_id, title, intent, success_signal) in enumerate(step_definitions, start=2)
        ),
        quickstart_evidence_step(evidence_order),
    ]


def quickstart_request_step_definitions() -> list[tuple[str, str, str, str]]:
    return [
        *quickstart_entry_step_definitions(),
        *quickstart_inspection_step_definitions(),
        *quickstart_execution_step_definitions(),
    ]


def quickstart_entry_step_definitions() -> list[tuple[str, str, str, str]]:
    return [
        (
            "launch_contract",
            "Read launch contract",
            "Read the redacted minimum contract before parsing the full one-shot package.",
            "ConsumerLaunchContract.status == ready and secret_values_echoed == false.",
        ),
        (
            "entry_profile",
            "Read entry profile",
            "Read the stable external integration profile before discovering optional importers.",
            "NetworkEntryProfile.status == ready and secret_values_echoed == false.",
        ),
        (
            "harness_agent",
            "Read harness agent",
            "Read the focused natural-language harness contract before planning a workflow request.",
            "NetworkHarnessAgent.status == ready and route_count >= 1.",
        ),
        (
            "sdk_bootstrap",
            "Read SDK bootstrap",
            "Read the small SDK initialization contract before choosing the full quickstart or package.",
            "ConsumerSdkBootstrap.status == ready and request_count >= 1.",
        ),
        (
            "consumer_manifest",
            "Read consumer manifest",
            "Read the redacted persistable network entry file before discovering optional importers.",
            "NetworkConsumerManifest.status == ready and secret_values_included == false.",
        ),
    ]


def quickstart_inspection_step_definitions() -> list[tuple[str, str, str, str]]:
    return [
        *quickstart_registration_inspection_steps(),
        *quickstart_workflow_inspection_steps(),
        *quickstart_protocol_inspection_steps(),
    ]


def quickstart_registration_inspection_steps() -> list[tuple[str, str, str, str]]:
    return [
        (
            "import_catalog",
            "Discover importers",
            "Read the dry-run-first CLI registration catalog before choosing a harness or adapter.",
            "CliRegistrationSurface.status == ready and importer_count >= 1.",
        ),
        (
            "direct_cli_readiness",
            "Inspect direct CLI readiness",
            "Confirm typed parser coverage and setup recovery for direct external CLI profiles.",
            "DirectCliReadinessReport.ok == true and recovery_type_count >= 1.",
        ),
    ]


def quickstart_workflow_inspection_steps() -> list[tuple[str, str, str, str]]:
    return [
        (
            "inspect_workflow",
            "Inspect workflow DAG",
            "Confirm the selected workflow is valid and has CLI tasks before execution.",
            "workflow.valid == true and task_count >= 1.",
        ),
        (
            "inspect_bridge_contract",
            "Inspect Bridge Contract",
            "Understand ToolManifest, BridgeMessage, Artifact, and selector boundaries.",
            "bridge contract ok and route_count >= 1.",
        ),
    ]


def quickstart_protocol_inspection_steps() -> list[tuple[str, str, str, str]]:
    return [
        (
            "inspect_agent_nodes",
            "Inspect harness agent nodes",
            "Read reusable AgentCard, AgentHarness, AgentTask, and BridgeMessage node bindings.",
            "AdapterAgentNodeBundle includes cards, harnesses, and BridgeMessage.",
        ),
        (
            "export_protocols",
            "Export protocol facades",
            "Expose MCP, A2A, and ACP workflow descriptors from the same internal bus contract.",
            "protocol exports include mcp, a2a, and acp.",
        ),
    ]


def quickstart_execution_step_definitions() -> list[tuple[str, str, str, str]]:
    return [
        (
            "plan_agent_request",
            "Plan natural-language run",
            "Bind a natural-language request to the reusable CLI-CLI harness run contract.",
            "AdapterAgentWorkflowRequestPlan.reusable_harness.kind == NaturalLanguageWorkflowHarness.",
        ),
        (
            "run_workflow",
            "Run workflow",
            "Execute the CLI-CLI chain through the daemon with dry-run/confirmation gates.",
            "workflow run receipt status == completed.",
        ),
    ]


def quickstart_open_studio_step(studio_url: str | None) -> dict[str, Any]:
    return {
        "order": 1,
        "id": "open_studio",
        "kind": "ui",
        "title": "Open Workflow Studio",
        "intent": "Start the visual handoff for the target CLI-CLI workflow.",
        "target": studio_url or "",
        "success_signal": "Studio opens with daemon URL, workflow path, and session token prefilled.",
    }


def quickstart_request_step(
    order: int,
    requests_by_id: dict[str, dict[str, Any]],
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


def quickstart_evidence_step(order: int) -> dict[str, Any]:
    return {
        "order": order,
        "id": "read_evidence",
        "kind": "evidence",
        "title": "Read evidence",
        "intent": "Collect runtime events, audit records, and artifacts after the workflow call.",
        "request_ids": list(QUICKSTART_EVIDENCE_REQUEST_IDS),
        "success_signal": "events, audit, and artifacts endpoints return non-empty JSON arrays.",
    }


def quickstart_sdk_snippets(
    *,
    workflow_path: str,
    requests: list[dict[str, Any]],
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    requests_by_id = {str(request.get("id")): request for request in requests if request.get("id")}
    return [
        quickstart_sdk_snippet("python-stdlib-consumer", "Python stdlib consumer", "python", "python>=3.10", workflow_path, _python_consumer_snippet(requests_by_id, headers=headers)),
        quickstart_sdk_snippet("typescript-fetch-consumer", "TypeScript fetch consumer", "typescript", "node>=18 or browser fetch", workflow_path, _typescript_consumer_snippet(requests_by_id, headers=headers)),
    ]


def quickstart_sdk_snippet(
    snippet_id: str,
    title: str,
    language: str,
    runtime: str,
    workflow_path: str,
    code: str,
) -> dict[str, Any]:
    return {
        "id": snippet_id,
        "title": title,
        "language": language,
        "runtime": runtime,
        "entrypoint": "run_workflow",
        "workflow_path": workflow_path,
        "uses_request_ids": list(QUICKSTART_SDK_REQUEST_IDS),
        "code": code,
        "safety": quickstart_sdk_safety(),
    }


def quickstart_sdk_safety() -> dict[str, bool]:
    return {
        "dry_run": True,
        "confirmed": False,
        "writes_files": False,
        "requires_daemon": True,
    }


def _python_consumer_snippet(requests_by_id: dict[str, dict[str, Any]], *, headers: dict[str, str]) -> str:
    request_lines = "\n".join(
        _python_request_line(requests_by_id, request_id)
        for request_id in QUICKSTART_SDK_REQUEST_IDS
        if request_id in requests_by_id
    )
    return "\n".join(
        [
            *_python_prelude_lines(headers),
            "REQUESTS = {",
            request_lines,
            "}",
            "",
            *_python_call_function_lines(),
            *_python_consumer_flow_lines(),
        ]
    )


def _python_prelude_lines(headers: dict[str, str]) -> list[str]:
    return [
            "import json",
            "import urllib.request",
            "",
            f"HEADERS = {json.dumps(headers, ensure_ascii=False)}",
    ]


def _python_call_function_lines() -> list[str]:
    return [
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
    ]


def _python_consumer_flow_lines() -> list[str]:
    return [
            "call('health')",
            "launch_contract = call('launch_contract')",
            "entry_profile = call('entry_profile')",
            "harness_agent = call('harness_agent')",
            "sdk_bootstrap = call('sdk_bootstrap')",
            "consumer_manifest = call('consumer_manifest')",
            "catalog = call('import_catalog')",
            "direct_cli = call('direct_cli_readiness')",
            "plan = call('plan_agent_request')",
            "receipt = call('run_workflow')",
            "evidence = {key: call(key) for key in ('events', 'audit', 'artifacts')}",
            "print(json.dumps({'launch_contract': launch_contract.get('status'), 'entry_profile': entry_profile.get('status'), 'harness_agent': harness_agent.get('status'), 'sdk_bootstrap': sdk_bootstrap.get('status'), 'consumer_manifest': consumer_manifest.get('status'), 'importers': catalog.get('importer_count'), 'direct_cli': direct_cli.get('summary', {}).get('capability_count'), 'plan': plan.get('kind'), 'workflow_status': receipt.get('status'), 'evidence': {k: len(v) for k, v in evidence.items()}}, indent=2))",
    ]


def _python_request_line(requests_by_id: dict[str, dict[str, Any]], request_id: str) -> str:
    request = requests_by_id[request_id]
    payload = request.get("json") if isinstance(request.get("json"), dict) else None
    payload_literal = repr(payload) if payload is not None else "None"
    return (
        f"    {request_id!r}: "
        f"{{'method': {str(request.get('method') or 'GET')!r}, 'url': {str(request.get('url') or '')!r}, "
        f"'json': {payload_literal}}},"
    )


def _typescript_consumer_snippet(requests_by_id: dict[str, dict[str, Any]], *, headers: dict[str, str]) -> str:
    serializable_requests = _typescript_serializable_requests(requests_by_id)
    return "\n".join(
        [
            f"const headers = {json.dumps(headers, ensure_ascii=False)};",
            f"const requests = {json.dumps(serializable_requests, ensure_ascii=False, indent=2)};",
            "",
            *_typescript_call_function_lines(),
            *_typescript_consumer_flow_lines(),
        ]
    )


def _typescript_serializable_requests(requests_by_id: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        request_id: {
            "method": request.get("method") or "GET",
            "url": request.get("url") or "",
            "json": request.get("json") if isinstance(request.get("json"), dict) else None,
        }
        for request_id, request in requests_by_id.items()
        if request_id in QUICKSTART_SDK_REQUEST_IDS
    }


def _typescript_call_function_lines() -> list[str]:
    return [
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
    ]


def _typescript_consumer_flow_lines() -> list[str]:
    return [
        "await call('health');",
        "const launchContract = await call('launch_contract');",
        "const entryProfile = await call('entry_profile');",
        "const harnessAgent = await call('harness_agent');",
        "const sdkBootstrap = await call('sdk_bootstrap');",
        "const consumerManifest = await call('consumer_manifest');",
        "const catalog = await call('import_catalog');",
        "const directCli = await call('direct_cli_readiness');",
        "const plan = await call('plan_agent_request');",
        "const receipt = await call('run_workflow');",
        "const [events, audit, artifacts] = await Promise.all([call('events'), call('audit'), call('artifacts')]);",
        "console.log({ launchContract: launchContract.status, entryProfile: entryProfile.status, harnessAgent: harnessAgent.status, sdkBootstrap: sdkBootstrap.status, consumerManifest: consumerManifest.status, importers: catalog.importer_count, directCli: directCli.summary?.capability_count, plan: plan.kind, workflowStatus: receipt.status, evidence: { events: events.length, audit: audit.length, artifacts: artifacts.length } });",
    ]


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
