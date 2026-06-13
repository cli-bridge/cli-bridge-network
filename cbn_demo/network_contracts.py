"""Consumer-facing network contract builders."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from cbn_demo.network_quickstart import quickstart_typed_responses
from cbn_demo.network_specs import CONNECT_API_VERSION, CONSUMER_SDK_REQUIRED_SEQUENCE, QUICKSTART_REQUEST_IDS


@dataclass(frozen=True)
class NetworkEntryProfileInput:
    workflow_path: str
    base_url: str | None
    quickstart: dict[str, Any]
    request_plan: dict[str, Any]
    registration_surface: dict[str, Any]
    demo_readiness: dict[str, Any]
    demo_playbook: dict[str, Any]
    protocol_summary: dict[str, Any]
    external_contract: dict[str, Any]
    setup_guidance: dict[str, Any]
    verify_network_command: str


@dataclass(frozen=True)
class NetworkConsumerManifestInput:
    workflow_path: str
    network_entry_profile: dict[str, Any]
    network_harness_agent: dict[str, Any]
    consumer_launch_contract: dict[str, Any]
    consumer_sdk_bootstrap: dict[str, Any]
    registration_surface: dict[str, Any]
    direct_cli_readiness: dict[str, Any]
    mvp_readiness: dict[str, Any]


def network_harness_agent_contract(
    *,
    workflow_path: str,
    base_url: str | None,
    quickstart: dict[str, Any],
    request_plan: dict[str, Any],
    compact_request: dict[str, Any],
    compact_bundle: dict[str, Any],
    setup_guidance: dict[str, Any],
) -> dict[str, Any]:
    """Stable, low-noise contract for reusing the natural-language CLI-CLI harness."""

    context = network_harness_agent_context(
        quickstart=quickstart,
        compact_request=compact_request,
        compact_bundle=compact_bundle,
    )
    harness = context["harness"]
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "NetworkHarnessAgent",
        "status": network_harness_status(request_plan, harness),
        "contract_id": "cbn.network.harness-agent.natural-language.v1",
        "audience": "external_program",
        "workflow_path": workflow_path,
        "base_url": base_url,
        "auth": network_harness_auth(context["headers"]),
        "natural_language": network_harness_natural_language(context),
        "harness": network_harness_section(context),
        "bridge": network_harness_bridge(context),
        "run": network_harness_run(context),
        "evidence": network_harness_evidence(context["entrypoints"]),
        "setup": network_harness_setup(setup_guidance),
        "safety": network_harness_safety(),
        "next_commands": network_harness_next_commands(workflow_path),
    }


def network_harness_status(request_plan: dict[str, Any], harness: dict[str, Any]) -> str:
    if request_plan.get("ok") and harness.get("kind") == "NaturalLanguageWorkflowHarness":
        return "ready"
    return "needs_attention"


def network_harness_next_commands(workflow_path: str) -> list[str]:
    return [
        f"python -m cbn network harness-agent --workflow-path {workflow_path}",
        f"python -m cbn_adapter_agent --workflow-request-plan --workflow-path {workflow_path}",
        f"python -m cbn workflow run {workflow_path} --dry-run",
    ]


def network_harness_agent_context(
    *,
    quickstart: dict[str, Any],
    compact_request: dict[str, Any],
    compact_bundle: dict[str, Any],
) -> dict[str, Any]:
    entrypoints = _dict_field(quickstart, "entrypoints")
    run = _dict_field(compact_request, "run")
    return {
        "bridge_message": _dict_field(compact_request, "bridge_message"),
        "bridge_routes": _list_field(compact_request, "bridge_routes"),
        "compact_bundle": compact_bundle,
        "entrypoints": entrypoints,
        "harness": _dict_field(compact_request, "reusable_harness"),
        "headers": _dict_field(quickstart, "required_headers"),
        "plan_entrypoint": _dict_field(entrypoints, "plan_agent_request"),
        "request": _dict_field(compact_request, "request"),
        "run": run,
        "run_entrypoint": _dict_field(entrypoints, "run_workflow"),
        "run_http": _dict_field(run, "http"),
    }


def _dict_field(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _list_field(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    return value if isinstance(value, list) else []


def network_harness_auth(headers: dict[str, Any]) -> dict[str, Any]:
    return {
        "required_headers": redact_entry_profile_secrets(headers),
        "session_token_required": "X-CBN-Session" in headers,
        "session_token_included": bool(headers.get("X-CBN-Session")),
        "secret_values_echoed": False,
    }


def network_harness_natural_language(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    return {
        "message": request.get("message"),
        "binding": request.get("binding"),
        "intent": request.get("intent", {}),
        "plan_endpoint": redact_entry_profile_secrets(context["plan_entrypoint"]),
    }


def network_harness_section(context: dict[str, Any]) -> dict[str, Any]:
    harness = context["harness"]
    compact_bundle = context["compact_bundle"]
    return {
        "kind": harness.get("kind"),
        "accepts": harness.get("accepts", []),
        "emits": harness.get("emits", []),
        "contract": harness.get("contract"),
        "agent_card_count": compact_bundle.get("card_count", 0),
        "agent_task_count": compact_bundle.get("task_count", 0),
        "roles": [card.get("id") for card in _list_of_dicts(compact_bundle.get("cards")) if card.get("id")],
        "harness_ids": [
            item.get("id")
            for item in _list_of_dicts(compact_bundle.get("harnesses"))
            if item.get("id")
        ],
    }


def network_harness_bridge(context: dict[str, Any]) -> dict[str, Any]:
    bridge_message = context["bridge_message"]
    bridge_routes = context["bridge_routes"]
    return {
        "message_kind": bridge_message.get("kind"),
        "message_channel": bridge_message.get("channel"),
        "parser_ref": bridge_message.get("parser_ref"),
        "route_count": len(bridge_routes),
        "routes": bridge_routes,
        "message": bridge_message,
    }


def network_harness_run(context: dict[str, Any]) -> dict[str, Any]:
    run_http = context["run_http"]
    run = context["run"]
    return {
        "dry_run_default": True,
        "confirmed_default": False,
        "method": run_http.get("method", "POST"),
        "endpoint": run_http.get("url") or context["run_entrypoint"].get("url"),
        "json": run_http.get("json") or run.get("payload", {}),
        "cli": run.get("cli"),
    }


def network_harness_evidence(entrypoints: dict[str, Any]) -> dict[str, Any]:
    return {
        "events": entrypoints.get("events"),
        "audit": entrypoints.get("audit"),
        "artifacts": entrypoints.get("artifacts"),
        "acceptance": entrypoints.get("acceptance"),
    }


def network_harness_setup(setup_guidance: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": setup_guidance.get("status"),
        "setup_required": setup_guidance.get("setup_required"),
        "requires_user_count": setup_guidance.get("requires_user_count", 0),
        "secret_count": setup_guidance.get("secret_count", 0),
        "secret_values_included": setup_guidance.get("safety", {}).get("secret_values_included"),
    }


def network_harness_safety() -> dict[str, Any]:
    return {
        "additive_contract": True,
        "confirmed_writes_disabled_by_default": True,
        "secret_values_echoed": False,
        "use_run_endpoint_after_plan": True,
    }


def network_entry_profile(
    profile: NetworkEntryProfileInput | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compact integration profile for programs entering CBN in one read."""

    profile = profile or NetworkEntryProfileInput(**kwargs)
    context = network_entry_profile_context(
        quickstart=profile.quickstart,
        request_plan=profile.request_plan,
        registration_surface=profile.registration_surface,
    )
    entry_status = (
        "ready"
        if profile.quickstart.get("status") in {"ready", "ready_without_daemon_url"} and profile.request_plan.get("ok")
        else "needs_attention"
    )
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "NetworkEntryProfile",
        "status": entry_status,
        "profile_id": "cbn.network.entry.cli-cli-harness.v1",
        "display_name": "CBN CLI-CLI Harness Network Entry",
        "workflow_path": profile.workflow_path,
        "base_url": profile.base_url,
        "integration_mode": "one_shot_package",
        "compatibility": network_entry_compatibility(profile.external_contract),
        "auth": network_harness_auth(context["headers"]),
        "primary_entrypoints": network_entry_primary_entrypoints(context, profile.verify_network_command),
        "harness_agent": network_entry_harness_agent(context),
        "evidence": network_entry_evidence(context, profile.demo_readiness, profile.demo_playbook),
        "registration": network_entry_registration(profile.registration_surface, context["importers"]),
        "setup": network_entry_setup(profile.setup_guidance),
        "protocol_facades": network_entry_protocol_facades(profile.protocol_summary),
    }


def network_entry_profile_context(
    *,
    quickstart: dict[str, Any],
    request_plan: dict[str, Any],
    registration_surface: dict[str, Any],
) -> dict[str, Any]:
    entrypoints = _dict_value(quickstart, "entrypoints")
    acceptance = _dict_value(quickstart, "acceptance")
    headers = _dict_value(quickstart, "required_headers")
    reusable_harness = _dict_value(request_plan, "reusable_harness")
    request = _dict_value(request_plan, "request")
    run_http = _dict_value(_dict_value(request_plan, "run"), "http")
    bridge_routes = request_plan.get("bridge_routes") if isinstance(request_plan.get("bridge_routes"), list) else []
    bridge_message = _dict_value(request_plan, "bridge_message")
    bridge_channel = _bridge_channel(request_plan, bridge_message)
    plan_entrypoint = _dict_value(entrypoints, "plan_agent_request")
    run_entrypoint = _dict_value(entrypoints, "run_workflow")
    importers = registration_surface.get("importers") if isinstance(registration_surface.get("importers"), list) else []
    return {
        "acceptance": acceptance,
        "bridge_channel": bridge_channel,
        "bridge_routes": bridge_routes,
        "entrypoints": entrypoints,
        "headers": headers,
        "importers": importers,
        "plan_entrypoint": plan_entrypoint,
        "request": request,
        "reusable_harness": reusable_harness,
        "run_entrypoint": run_entrypoint,
        "run_http": run_http,
    }


def _bridge_channel(request_plan: dict[str, Any], bridge_message: dict[str, Any]) -> Any:
    bridge_metadata = _dict_value(bridge_message, "metadata")
    return request_plan.get("bridge_message_channel") or bridge_metadata.get("channel") or bridge_message.get("channel")


def network_entry_compatibility(external_contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": CONNECT_API_VERSION,
        "additive_fields_only": True,
        "external_protocol": external_contract.get("protocol"),
        "external_kinds": external_contract.get("accepted_kinds", []),
        "internal_bus": "CBN BridgeMessage",
        "stable_fields": [
            "network_entry_profile",
            "network_harness_agent",
            "consumer_quickstart",
            "consumer_launch_contract",
            "consumer_sdk_bootstrap",
            "agent_workflow_request",
            "acceptance",
            "contracts.external",
        ],
    }


def network_entry_primary_entrypoints(
    context: dict[str, Any],
    verify_network_command: str,
) -> dict[str, Any]:
    entrypoints = context["entrypoints"]
    return {
        "open_studio": redact_entry_profile_secrets(entrypoints.get("open_studio")),
        "health": redact_entry_profile_secrets(entrypoints.get("health")),
        "import_catalog": redact_entry_profile_secrets(entrypoints.get("import_catalog")),
        "harness_agent": redact_entry_profile_secrets(entrypoints.get("harness_agent")),
        "plan_agent_request": redact_entry_profile_secrets(context["plan_entrypoint"]),
        "run_workflow": redact_entry_profile_secrets(context["run_entrypoint"]),
        "verify_network": redact_entry_profile_secrets(verify_network_command),
    }


def network_entry_harness_agent(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    reusable_harness = context["reusable_harness"]
    return {
        "kind": reusable_harness.get("kind"),
        "request_binding": (request.get("binding") if isinstance(request, dict) else None),
        "message": request.get("message"),
        "accepts": reusable_harness.get("accepts", []),
        "emits": reusable_harness.get("emits", []),
        "bridge_message_channel": context["bridge_channel"],
        "bridge_route_count": len(context["bridge_routes"]),
        "plan_endpoint": context["plan_entrypoint"].get("url"),
        "run_endpoint": context["run_http"].get("url") or context["run_entrypoint"].get("url"),
    }


def network_entry_evidence(
    context: dict[str, Any],
    demo_readiness: dict[str, Any],
    demo_playbook: dict[str, Any],
) -> dict[str, Any]:
    acceptance = context["acceptance"]
    entrypoints = context["entrypoints"]
    return {
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
    }


def network_entry_registration(
    registration_surface: dict[str, Any],
    importers: list[Any],
) -> dict[str, Any]:
    return {
        "status": registration_surface.get("status"),
        "importer_count": registration_surface.get("importer_count", 0),
        "importer_ids": [str(importer.get("id")) for importer in importers if isinstance(importer, dict)],
        "next_commands": registration_surface.get("next_commands", []),
    }


def network_entry_setup(setup_guidance: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": setup_guidance.get("status"),
        "setup_required": setup_guidance.get("setup_required"),
        "requires_user_count": setup_guidance.get("requires_user_count", 0),
        "secret_count": setup_guidance.get("secret_count", 0),
    }


def network_entry_protocol_facades(protocol_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "targets": protocol_summary.get("targets", []),
        "export_count": protocol_summary.get("export_count", 0),
    }


def consumer_sdk_bootstrap(
    *,
    workflow_path: str,
    quickstart: dict[str, Any],
    network_entry_profile: dict[str, Any],
    network_harness_agent: dict[str, Any],
    request_plan: dict[str, Any],
) -> dict[str, Any]:
    """Stable SDK initialization contract for external programs entering CBN."""

    context = consumer_sdk_context(
        quickstart=quickstart,
        network_entry_profile=network_entry_profile,
        network_harness_agent=network_harness_agent,
    )
    bootstrap_requests = consumer_sdk_requests(context)
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "ConsumerSdkBootstrap",
        "status": consumer_sdk_status(quickstart, network_entry_profile, network_harness_agent, request_plan),
        "bootstrap_id": "cbn.consumer.sdk-bootstrap.cli-cli-harness.v1",
        "audience": "external_sdk_or_program",
        "workflow_path": workflow_path,
        "base_url": network_entry_profile.get("base_url"),
        "auth": consumer_sdk_auth(context["headers"], network_entry_profile),
        "compatibility": consumer_sdk_compatibility(network_entry_profile),
        "entrypoints": consumer_sdk_entrypoints(context["entrypoints"]),
        "request_count": len(bootstrap_requests),
        "requests": bootstrap_requests,
        "required_sequence": context["required_sequence"],
        "typed_responses": context["typed_responses"],
        "harness": consumer_sdk_harness(network_harness_agent),
        "safety": consumer_sdk_safety(),
        "next_commands": consumer_sdk_next_commands(),
    }


def consumer_sdk_status(
    quickstart: dict[str, Any],
    network_entry_profile: dict[str, Any],
    network_harness_agent: dict[str, Any],
    request_plan: dict[str, Any],
) -> str:
    ready = (
        quickstart.get("status") in {"ready", "ready_without_daemon_url"}
        and network_entry_profile.get("status") == "ready"
        and network_harness_agent.get("status") == "ready"
        and request_plan.get("ok")
    )
    return "ready" if ready else "needs_attention"


def consumer_sdk_next_commands() -> list[str]:
    return [
        "python -m cbn network quickstart --output sdk-bootstrap",
        "python -m cbn network quickstart --output harness-agent",
        "python -m cbn network verify --base-url http://127.0.0.1:8787",
    ]


def consumer_sdk_context(
    *,
    quickstart: dict[str, Any],
    network_entry_profile: dict[str, Any],
    network_harness_agent: dict[str, Any],
) -> dict[str, Any]:
    headers = quickstart.get("required_headers") if isinstance(quickstart.get("required_headers"), dict) else {}
    entrypoints = quickstart.get("entrypoints") if isinstance(quickstart.get("entrypoints"), dict) else {}
    requests = [request for request in quickstart.get("requests", []) if isinstance(request, dict)]
    requests_by_id = {str(request.get("id")): request for request in requests if request.get("id")}
    required_sequence = list(CONSUMER_SDK_REQUIRED_SEQUENCE)
    typed_responses = quickstart_typed_responses(
        network_entry_profile=network_entry_profile,
        network_harness_agent=network_harness_agent,
    )
    return {
        "entrypoints": entrypoints,
        "headers": headers,
        "requests_by_id": requests_by_id,
        "required_sequence": required_sequence,
        "typed_responses": typed_responses,
    }


def consumer_sdk_requests(context: dict[str, Any]) -> list[dict[str, Any]]:
    requests_by_id = context["requests_by_id"]
    required_sequence = context["required_sequence"]
    typed_responses = context["typed_responses"]
    return [
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


def consumer_sdk_auth(
    headers: dict[str, Any],
    network_entry_profile: dict[str, Any],
) -> dict[str, Any]:
    return {
        "headers": redact_entry_profile_secrets(headers),
        "session_token_header": "X-CBN-Session" if "X-CBN-Session" in headers else None,
        "session_token_required": bool((network_entry_profile.get("auth") or {}).get("session_token_required")),
        "secret_values_echoed": False,
    }


def consumer_sdk_compatibility(network_entry_profile: dict[str, Any]) -> dict[str, Any]:
    return {
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
    }


def consumer_sdk_entrypoints(entrypoints: dict[str, Any]) -> dict[str, Any]:
    return {
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
    }


def consumer_sdk_harness(network_harness_agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_id": network_harness_agent.get("contract_id"),
        "kind": (network_harness_agent.get("harness") or {}).get("kind"),
        "bridge_message_channel": (network_harness_agent.get("bridge") or {}).get("message_channel"),
        "bridge_route_count": (network_harness_agent.get("bridge") or {}).get("route_count", 0),
        "run_endpoint": (network_harness_agent.get("run") or {}).get("endpoint"),
    }


def consumer_sdk_safety() -> dict[str, Any]:
    return {
        "dry_run_default": True,
        "confirmed_default": False,
        "secret_values_included": False,
        "writes_require_explicit_confirmation": True,
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

    context = consumer_launch_context(
        quickstart=quickstart,
        request_plan=request_plan,
    )
    launch_sequence = consumer_launch_sequence()
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "ConsumerLaunchContract",
        "status": consumer_launch_status(quickstart, request_plan, mvp_readiness),
        "contract_id": "cbn.consumer.launch.cli-cli-harness.v1",
        "audience": "external_program",
        "workflow_path": workflow_path,
        "profile_id": network_entry_profile.get("profile_id"),
        "stable_inputs": consumer_launch_stable_inputs(workflow_path, request_plan, network_entry_profile),
        "auth": consumer_launch_auth(context["headers"], network_entry_profile),
        "launch_sequence": launch_sequence,
        "required_request_ids": [step["request_id"] for step in launch_sequence],
        "available_request_ids": context["request_ids"],
        "entrypoints": consumer_launch_entrypoints(context, network_entry_profile, mvp_presenter_brief),
        "harness_agent": consumer_launch_harness_agent(context),
        "success_gates": consumer_launch_success_gates(mvp_readiness, context["acceptance"], setup_guidance),
        "do_not": consumer_launch_do_not(),
    }


def consumer_launch_status(
    quickstart: dict[str, Any],
    request_plan: dict[str, Any],
    mvp_readiness: dict[str, Any],
) -> str:
    ready = (
        quickstart.get("status") in {"ready", "ready_without_daemon_url"}
        and request_plan.get("ok")
        and mvp_readiness.get("status") == "ready"
    )
    return "ready" if ready else "needs_attention"


def consumer_launch_do_not() -> list[str]:
    return [
        "Do not rely on CBN internal daemon state outside the listed entrypoints.",
        "Do not persist or echo session token values from this payload.",
        "Do not run confirmed writes until the user explicitly sets confirmed=true.",
    ]


def consumer_launch_context(
    *,
    quickstart: dict[str, Any],
    request_plan: dict[str, Any],
) -> dict[str, Any]:
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
    return {
        "acceptance": acceptance,
        "bridge_routes": bridge_routes,
        "entrypoints": entrypoints,
        "harness": harness,
        "headers": headers,
        "request_ids": request_ids,
        "run_http": run_http,
    }


def consumer_launch_sequence() -> list[dict[str, Any]]:
    return [
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


def consumer_launch_stable_inputs(
    workflow_path: str,
    request_plan: dict[str, Any],
    network_entry_profile: dict[str, Any],
) -> dict[str, Any]:
    return {
        "base_url": network_entry_profile.get("base_url"),
        "workflow_path": workflow_path,
        "agent_message": (request_plan.get("request") or {}).get("message"),
        "dry_run": True,
        "confirmed": False,
    }


def consumer_launch_auth(
    headers: dict[str, Any],
    network_entry_profile: dict[str, Any],
) -> dict[str, Any]:
    return {
        "header": "X-CBN-Session" if "X-CBN-Session" in headers else None,
        "session_token_required": bool((network_entry_profile.get("auth") or {}).get("session_token_required")),
        "session_token_included": bool((network_entry_profile.get("auth") or {}).get("session_token_included")),
        "secret_values_echoed": False,
    }


def consumer_launch_entrypoints(
    context: dict[str, Any],
    network_entry_profile: dict[str, Any],
    mvp_presenter_brief: dict[str, Any],
) -> dict[str, Any]:
    entrypoints = context["entrypoints"]
    return {
        "open_studio": _redact_launch_secret(entrypoints.get("open_studio")),
        "plan_agent_request": entrypoints.get("plan_agent_request"),
        "harness_agent": entrypoints.get("harness_agent"),
        "run_workflow": entrypoints.get("run_workflow"),
        "verify_network": _redact_launch_secret(
            (network_entry_profile.get("primary_entrypoints") or {}).get("verify_network")
        ),
        "readiness": (mvp_presenter_brief.get("integration_handoff") or {}).get("readiness_url"),
    }


def consumer_launch_harness_agent(context: dict[str, Any]) -> dict[str, Any]:
    harness = context["harness"]
    entrypoints = context["entrypoints"]
    return {
        "kind": harness.get("kind"),
        "accepts": harness.get("accepts", []),
        "emits": harness.get("emits", []),
        "bridge_route_count": len(context["bridge_routes"]),
        "run_endpoint": context["run_http"].get("url") or (entrypoints.get("run_workflow") or {}).get("url"),
    }


def consumer_launch_success_gates(
    mvp_readiness: dict[str, Any],
    acceptance: dict[str, Any],
    setup_guidance: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mvp_readiness_score": mvp_readiness.get("score"),
        "acceptance_check_count": acceptance.get("check_count", 0),
        "setup_status": setup_guidance.get("status"),
        "setup_required": setup_guidance.get("setup_required"),
        "no_secret_values_included": setup_guidance.get("safety", {}).get("secret_values_included") is False,
    }


def network_consumer_manifest(params: NetworkConsumerManifestInput) -> dict[str, Any]:
    """Small redacted manifest that an external program can persist as its CBN entry file."""

    return _network_consumer_manifest_payload(params)


def _network_consumer_manifest_payload(params: NetworkConsumerManifestInput) -> dict[str, Any]:
    sdk_requests = consumer_manifest_sdk_requests(params.consumer_sdk_bootstrap)
    importers = consumer_manifest_importers(params.registration_surface)
    return {
        "apiVersion": CONNECT_API_VERSION,
        "kind": "NetworkConsumerManifest",
        "status": network_consumer_manifest_status_for_input(params),
        "manifest_id": "cbn.consumer.manifest.cli-cli-network.v1",
        "audience": "external_program_or_sdk",
        "workflow_path": params.workflow_path,
        "base_url": params.network_entry_profile.get("base_url"),
        "contracts": consumer_manifest_contracts_for_input(params),
        "auth": consumer_manifest_auth(params.network_entry_profile, params.consumer_sdk_bootstrap),
        "entrypoints": consumer_manifest_entrypoints(params.consumer_launch_contract, params.consumer_sdk_bootstrap),
        "harness_agent": consumer_manifest_harness_agent(params.consumer_launch_contract, params.network_harness_agent),
        "request_sequence": params.consumer_sdk_bootstrap.get("required_sequence", []),
        "request_count": len(sdk_requests),
        "requests": sdk_requests,
        "typed_responses": params.consumer_sdk_bootstrap.get("typed_responses", {}),
        "registration": consumer_manifest_registration(params.registration_surface, importers),
        "readiness": consumer_manifest_readiness(params.mvp_readiness, params.direct_cli_readiness),
        "safety": consumer_manifest_safety(),
        "next_commands": consumer_manifest_next_commands(),
    }


def network_consumer_manifest_status_for_input(params: NetworkConsumerManifestInput) -> str:
    return network_consumer_manifest_status(
        params.network_entry_profile,
        params.network_harness_agent,
        params.consumer_launch_contract,
        params.consumer_sdk_bootstrap,
    )


def consumer_manifest_contracts_for_input(params: NetworkConsumerManifestInput) -> dict[str, Any]:
    return consumer_manifest_contracts(
        params.network_entry_profile,
        params.consumer_launch_contract,
        params.consumer_sdk_bootstrap,
        params.network_harness_agent,
    )


def consumer_manifest_next_commands() -> list[str]:
    return [
        "python -m cbn network consumer-manifest --base-url http://127.0.0.1:8787",
        "python -m cbn network verify --base-url http://127.0.0.1:8787",
        "python -m cbn import catalog",
    ]


def network_consumer_manifest_status(
    network_entry_profile: dict[str, Any],
    network_harness_agent: dict[str, Any],
    consumer_launch_contract: dict[str, Any],
    consumer_sdk_bootstrap: dict[str, Any],
) -> str:
    ready = all(
        item.get("status") == "ready"
        for item in (
            network_entry_profile,
            network_harness_agent,
            consumer_launch_contract,
            consumer_sdk_bootstrap,
        )
    )
    return "ready" if ready else "needs_attention"


def consumer_manifest_sdk_requests(consumer_sdk_bootstrap: dict[str, Any]) -> list[dict[str, Any]]:
    return [
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


def consumer_manifest_importers(registration_surface: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": importer.get("id"),
            "entrypoint": importer.get("entrypoint"),
            "write_gate": importer.get("write_gate"),
            "default_side_effects": importer.get("default_side_effects"),
        }
        for importer in registration_surface.get("importers", [])
        if isinstance(importer, dict) and importer.get("id")
    ]


def consumer_manifest_contracts(
    network_entry_profile: dict[str, Any],
    consumer_launch_contract: dict[str, Any],
    consumer_sdk_bootstrap: dict[str, Any],
    network_harness_agent: dict[str, Any],
) -> dict[str, Any]:
    return {
        "external_protocol": (network_entry_profile.get("compatibility") or {}).get("external_protocol"),
        "internal_bus": (network_entry_profile.get("compatibility") or {}).get("internal_bus"),
        "launch_contract": consumer_launch_contract.get("contract_id"),
        "sdk_bootstrap": consumer_sdk_bootstrap.get("bootstrap_id"),
        "harness_agent": network_harness_agent.get("contract_id"),
    }


def consumer_manifest_auth(
    network_entry_profile: dict[str, Any],
    consumer_sdk_bootstrap: dict[str, Any],
) -> dict[str, Any]:
    return {
        "required_headers": (network_entry_profile.get("auth") or {}).get("required_headers", {}),
        "session_token_header": (consumer_sdk_bootstrap.get("auth") or {}).get("session_token_header"),
        "session_token_required": bool((network_entry_profile.get("auth") or {}).get("session_token_required")),
        "secret_values_echoed": False,
    }


def consumer_manifest_entrypoints(
    consumer_launch_contract: dict[str, Any],
    consumer_sdk_bootstrap: dict[str, Any],
) -> dict[str, Any]:
    sdk_entrypoints = consumer_sdk_bootstrap.get("entrypoints") or {}
    return {
        "open_studio": (consumer_launch_contract.get("entrypoints") or {}).get("open_studio"),
        "connect_package": sdk_entrypoints.get("connect_package"),
        "quickstart": sdk_entrypoints.get("quickstart"),
        "consumer_manifest": sdk_entrypoints.get("consumer_manifest"),
        "launch_contract": sdk_entrypoints.get("launch_contract"),
        "entry_profile": sdk_entrypoints.get("entry_profile"),
        "harness_agent": sdk_entrypoints.get("harness_agent"),
        "run_workflow": sdk_entrypoints.get("run_workflow"),
        "evidence": sdk_entrypoints.get("evidence", {}),
    }


def consumer_manifest_harness_agent(
    consumer_launch_contract: dict[str, Any],
    network_harness_agent: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": (consumer_launch_contract.get("harness_agent") or {}).get("kind"),
        "bridge_message_channel": (network_harness_agent.get("bridge") or {}).get("message_channel"),
        "bridge_route_count": (network_harness_agent.get("bridge") or {}).get("route_count", 0),
        "run_endpoint": (consumer_launch_contract.get("harness_agent") or {}).get("run_endpoint"),
    }


def consumer_manifest_registration(
    registration_surface: dict[str, Any],
    importers: list[dict[str, Any]],
) -> dict[str, Any]:
    default_policy = registration_surface.get("default_policy") or {}
    return {
        "importer_count": registration_surface.get("importer_count", 0),
        "dry_run_by_default": default_policy.get("dry_run_by_default"),
        "writes_require_explicit_flag": default_policy.get("writes_require_explicit_flag"),
        "importers": importers,
    }


def consumer_manifest_readiness(
    mvp_readiness: dict[str, Any],
    direct_cli_readiness: dict[str, Any],
) -> dict[str, Any]:
    direct_cli_summary = direct_cli_readiness.get("summary") or {}
    return {
        "mvp_score": mvp_readiness.get("score"),
        "mvp_status": mvp_readiness.get("status"),
        "direct_cli_profile_count": direct_cli_summary.get("profile_count", 0),
        "direct_cli_capability_count": direct_cli_summary.get("capability_count", 0),
        "direct_cli_recovery_type_count": direct_cli_summary.get("recovery_type_count", 0),
    }


def consumer_manifest_safety() -> dict[str, Any]:
    return {
        "dry_run_default": True,
        "confirmed_default": False,
        "secret_values_included": False,
        "writes_require_explicit_confirmation": True,
        "side_effects_require_confirmation": True,
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


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _dict_value(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key) if isinstance(value, dict) else {}
    return item if isinstance(item, dict) else {}


def _redact_launch_secret(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    redacted = re.sub(r"(sessionToken=)[^&\s]+", r"\1REDACTED", value)
    return re.sub(r"(--session-token)(?:=|\s+)\S+", r"\1 REDACTED", redacted)
