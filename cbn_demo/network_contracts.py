"""Consumer-facing network contract builders."""

from __future__ import annotations

import re
from typing import Any

from cbn_demo.network_quickstart import quickstart_typed_responses
from cbn_demo.network_specs import CONNECT_API_VERSION, CONSUMER_SDK_REQUIRED_SEQUENCE, QUICKSTART_REQUEST_IDS


def consumer_sdk_bootstrap(
    *,
    workflow_path: str,
    quickstart: dict[str, Any],
    network_entry_profile: dict[str, Any],
    network_harness_agent: dict[str, Any],
    request_plan: dict[str, Any],
) -> dict[str, Any]:
    """Stable SDK initialization contract for external programs entering CBN."""

    headers = quickstart.get("required_headers") if isinstance(quickstart.get("required_headers"), dict) else {}
    entrypoints = quickstart.get("entrypoints") if isinstance(quickstart.get("entrypoints"), dict) else {}
    requests = [request for request in quickstart.get("requests", []) if isinstance(request, dict)]
    requests_by_id = {str(request.get("id")): request for request in requests if request.get("id")}
    required_sequence = list(CONSUMER_SDK_REQUIRED_SEQUENCE)
    typed_responses = quickstart_typed_responses(
        network_entry_profile=network_entry_profile,
        network_harness_agent=network_harness_agent,
    )
    bootstrap_requests = [
        {
            "id": request_id,
            "method": requests_by_id.get(request_id, {}).get("method", "GET"),
            "url": requests_by_id.get(request_id, {}).get("url", ""),
            "json": requests_by_id.get(request_id, {}).get("json"),
            "response_kind": typed_responses.get(request_id, "JSON"),
            "required": request_id in required_sequence,
        }
        for request_id in QUICKSTART_REQUEST_IDS
        if request_id in requests_by_id
    ]
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "ConsumerSdkBootstrap",
        "status": "ready"
        if quickstart.get("status") in {"ready", "ready_without_daemon_url"}
        and network_entry_profile.get("status") == "ready"
        and network_harness_agent.get("status") == "ready"
        and request_plan.get("ok")
        else "needs_attention",
        "bootstrap_id": "cbn.consumer.sdk-bootstrap.cli-cli-harness.v1",
        "audience": "external_sdk_or_program",
        "workflow_path": workflow_path,
        "base_url": network_entry_profile.get("base_url"),
        "auth": {
            "headers": redact_entry_profile_secrets(headers),
            "session_token_header": "X-CBN-Session" if "X-CBN-Session" in headers else None,
            "session_token_required": bool((network_entry_profile.get("auth") or {}).get("session_token_required")),
            "secret_values_echoed": False,
        },
        "compatibility": {
            "api_version": CONNECT_API_VERSION,
            "additive_fields_only": True,
            "external_protocol": (network_entry_profile.get("compatibility") or {}).get("external_protocol"),
            "internal_bus": (network_entry_profile.get("compatibility") or {}).get("internal_bus"),
            "minimum_required_fields": [
                "kind",
                "status",
                "bootstrap_id",
                "auth",
                "requests",
                "required_sequence",
                "typed_responses",
            ],
        },
        "entrypoints": {
            "connect_package": entrypoints.get("connect_package"),
            "quickstart": entrypoints.get("quickstart"),
            "consumer_manifest": entrypoints.get("consumer_manifest"),
            "launch_contract": entrypoints.get("launch_contract"),
            "entry_profile": entrypoints.get("entry_profile"),
            "harness_agent": entrypoints.get("harness_agent"),
            "run_workflow": entrypoints.get("run_workflow"),
            "evidence": {
                "events": entrypoints.get("events"),
                "audit": entrypoints.get("audit"),
                "artifacts": entrypoints.get("artifacts"),
            },
        },
        "request_count": len(bootstrap_requests),
        "requests": bootstrap_requests,
        "required_sequence": required_sequence,
        "typed_responses": typed_responses,
        "harness": {
            "contract_id": network_harness_agent.get("contract_id"),
            "kind": (network_harness_agent.get("harness") or {}).get("kind"),
            "bridge_message_channel": (network_harness_agent.get("bridge") or {}).get("message_channel"),
            "bridge_route_count": (network_harness_agent.get("bridge") or {}).get("route_count", 0),
            "run_endpoint": (network_harness_agent.get("run") or {}).get("endpoint"),
        },
        "safety": {
            "dry_run_default": True,
            "confirmed_default": False,
            "secret_values_included": False,
            "writes_require_explicit_confirmation": True,
        },
        "next_commands": [
            "python -m cbn network quickstart --output sdk-bootstrap",
            "python -m cbn network quickstart --output harness-agent",
            "python -m cbn network verify --base-url http://127.0.0.1:8787",
        ],
    }


def consumer_launch_contract(
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
            "harness_agent": entrypoints.get("harness_agent"),
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


def network_consumer_manifest(
    *,
    workflow_path: str,
    network_entry_profile: dict[str, Any],
    network_harness_agent: dict[str, Any],
    consumer_launch_contract: dict[str, Any],
    consumer_sdk_bootstrap: dict[str, Any],
    registration_surface: dict[str, Any],
    direct_cli_readiness: dict[str, Any],
    mvp_readiness: dict[str, Any],
) -> dict[str, Any]:
    """Small redacted manifest that an external program can persist as its CBN entry file."""

    sdk_requests = [
        {
            "id": request.get("id"),
            "method": request.get("method"),
            "url": request.get("url"),
            "json": request.get("json"),
            "response_kind": request.get("response_kind"),
            "required": request.get("required", False),
        }
        for request in consumer_sdk_bootstrap.get("requests", [])
        if isinstance(request, dict) and request.get("id")
    ]
    importers = [
        {
            "id": importer.get("id"),
            "entrypoint": importer.get("entrypoint"),
            "write_gate": importer.get("write_gate"),
            "default_side_effects": importer.get("default_side_effects"),
        }
        for importer in registration_surface.get("importers", [])
        if isinstance(importer, dict) and importer.get("id")
    ]
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "NetworkConsumerManifest",
        "status": "ready"
        if network_entry_profile.get("status") == "ready"
        and network_harness_agent.get("status") == "ready"
        and consumer_launch_contract.get("status") == "ready"
        and consumer_sdk_bootstrap.get("status") == "ready"
        else "needs_attention",
        "manifest_id": "cbn.consumer.manifest.cli-cli-network.v1",
        "audience": "external_program_or_sdk",
        "workflow_path": workflow_path,
        "base_url": network_entry_profile.get("base_url"),
        "contracts": {
            "external_protocol": (network_entry_profile.get("compatibility") or {}).get("external_protocol"),
            "internal_bus": (network_entry_profile.get("compatibility") or {}).get("internal_bus"),
            "launch_contract": consumer_launch_contract.get("contract_id"),
            "sdk_bootstrap": consumer_sdk_bootstrap.get("bootstrap_id"),
            "harness_agent": network_harness_agent.get("contract_id"),
        },
        "auth": {
            "required_headers": (network_entry_profile.get("auth") or {}).get("required_headers", {}),
            "session_token_header": (consumer_sdk_bootstrap.get("auth") or {}).get("session_token_header"),
            "session_token_required": bool(
                (network_entry_profile.get("auth") or {}).get("session_token_required")
            ),
            "secret_values_echoed": False,
        },
        "entrypoints": {
            "open_studio": (consumer_launch_contract.get("entrypoints") or {}).get("open_studio"),
            "connect_package": (consumer_sdk_bootstrap.get("entrypoints") or {}).get("connect_package"),
            "quickstart": (consumer_sdk_bootstrap.get("entrypoints") or {}).get("quickstart"),
            "consumer_manifest": (consumer_sdk_bootstrap.get("entrypoints") or {}).get("consumer_manifest"),
            "launch_contract": (consumer_sdk_bootstrap.get("entrypoints") or {}).get("launch_contract"),
            "entry_profile": (consumer_sdk_bootstrap.get("entrypoints") or {}).get("entry_profile"),
            "harness_agent": (consumer_sdk_bootstrap.get("entrypoints") or {}).get("harness_agent"),
            "run_workflow": (consumer_sdk_bootstrap.get("entrypoints") or {}).get("run_workflow"),
            "evidence": (consumer_sdk_bootstrap.get("entrypoints") or {}).get("evidence", {}),
        },
        "harness_agent": {
            "kind": (consumer_launch_contract.get("harness_agent") or {}).get("kind"),
            "bridge_message_channel": (network_harness_agent.get("bridge") or {}).get("message_channel"),
            "bridge_route_count": (network_harness_agent.get("bridge") or {}).get("route_count", 0),
            "run_endpoint": (consumer_launch_contract.get("harness_agent") or {}).get("run_endpoint"),
        },
        "request_sequence": consumer_sdk_bootstrap.get("required_sequence", []),
        "request_count": len(sdk_requests),
        "requests": sdk_requests,
        "typed_responses": consumer_sdk_bootstrap.get("typed_responses", {}),
        "registration": {
            "importer_count": registration_surface.get("importer_count", 0),
            "dry_run_by_default": (registration_surface.get("default_policy") or {}).get("dry_run_by_default"),
            "writes_require_explicit_flag": (registration_surface.get("default_policy") or {}).get(
                "writes_require_explicit_flag"
            ),
            "importers": importers,
        },
        "readiness": {
            "mvp_score": mvp_readiness.get("score"),
            "mvp_status": mvp_readiness.get("status"),
            "direct_cli_profile_count": (direct_cli_readiness.get("summary") or {}).get("profile_count", 0),
            "direct_cli_capability_count": (direct_cli_readiness.get("summary") or {}).get("capability_count", 0),
            "direct_cli_recovery_type_count": (direct_cli_readiness.get("summary") or {}).get(
                "recovery_type_count",
                0,
            ),
        },
        "safety": {
            "dry_run_default": True,
            "confirmed_default": False,
            "secret_values_included": False,
            "writes_require_explicit_confirmation": True,
            "side_effects_require_confirmation": True,
        },
        "next_commands": [
            "python -m cbn network consumer-manifest --base-url http://127.0.0.1:8787",
            "python -m cbn network verify --base-url http://127.0.0.1:8787",
            "python -m cbn import catalog",
        ],
    }


def redact_entry_profile_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {"x-cbn-session", "authorization"} and item:
                redacted[str(key)] = "REDACTED"
            else:
                redacted[str(key)] = redact_entry_profile_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_entry_profile_secrets(item) for item in value]
    return _redact_launch_secret(value)


def _redact_launch_secret(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    redacted = re.sub(r"(sessionToken=)[^&\s]+", r"\1REDACTED", value)
    return re.sub(r"(--session-token)(?:=|\s+)\S+", r"\1 REDACTED", redacted)
