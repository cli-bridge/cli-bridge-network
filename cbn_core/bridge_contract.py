"""CBN internal CLI-to-CLI contract reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_core.message import BRIDGE_MESSAGE_API_VERSION
from cbn_core.selector import validate_selector_syntax
from cbn_workflow.catalog import inspect_workflow, list_workflows


def bridge_message_contract() -> dict[str, Any]:
    return {
        "apiVersion": BRIDGE_MESSAGE_API_VERSION,
        "message_kind": "BridgeMessage",
        "protocol_name": "CBN BridgeMessage CLI-to-CLI Protocol",
        "protocol_scope": [
            "local workflow argsFrom routing",
            "artifact id routing",
            "MCP/A2A/ACP facade metadata handoff",
        ],
        "required_metadata": ["id", "createdAt", "producer", "channel", "correlationId"],
        "required_payload": ["parser_ref", "ok"],
        "payload_rules": [
            "payload.parser_ref is the parser id used for downstream routing.",
            "payload.ok is the parser success flag and must be boolean.",
            "payload.data is an object when structured parser data is available.",
            "payload.error or payload.data is required when payload.ok=false.",
        ],
        "artifact_rules": [
            "artifact entries must be objects.",
            "routable artifact references require artifact_id and kind.",
            "full local artifact records may include path, media_type, size_bytes, and truncated.",
        ],
        "selector_rules": [
            "selectors use dot paths with optional list indexes, such as payload.data.stdout",
            "selectors are deterministic routing addresses, not a query language",
            "workflow argsFrom selectors must point at a task listed in needs",
        ],
        "arg_mapping_rules": [
            "string values pass through unchanged",
            "null becomes an empty string",
            "objects and arrays become stable UTF-8 JSON with sorted keys",
            "booleans and numbers use their string form",
        ],
        "route_readiness_rules": [
            "the workflow must be valid",
            "the source task must exist and must be listed in needs",
            "the source and consumer capabilities must exist in the registry",
            "the selector must be syntactically valid and must target payload, artifacts, or metadata",
            "payload routes require a verified source parser/output contract",
            "artifact and metadata routes do not require parser verification but still require a valid BridgeMessage source",
        ],
    }


def workflow_bridge_contract_report(
    registry: ManifestRegistry,
    workflow_path: str | None = None,
) -> dict[str, Any]:
    if workflow_path:
        workflows = [inspect_workflow(Path(workflow_path), registry=registry)]
    else:
        workflows = list_workflows(registry=registry)
    workflow_reports = [_workflow_contract(workflow) for workflow in workflows]
    summary = _summary(workflow_reports)
    return {
        "ok": (
            summary["invalid_workflow_count"] == 0
            and summary["invalid_selector_count"] == 0
            and summary["blocked_route_count"] == 0
        ),
        "apiVersion": BRIDGE_MESSAGE_API_VERSION,
        "contract": bridge_message_contract(),
        "workflow_path": workflow_path,
        "workflows": workflow_reports,
        "summary": summary,
    }


def _workflow_contract(workflow: dict[str, Any]) -> dict[str, Any]:
    if not workflow.get("valid"):
        return {
            "valid": False,
            "workflow_id": workflow.get("workflow_id"),
            "path": workflow.get("path"),
            "title": workflow.get("title"),
            "task_count": workflow.get("task_count", 0),
            "routes": [],
            "errors": workflow.get("errors", []),
            "summary": {
                "route_count": 0,
                "route_ready_count": 0,
                "blocked_route_count": 0,
                "payload_route_count": 0,
                "artifact_route_count": 0,
                "metadata_route_count": 0,
                "unknown_route_count": 0,
                "invalid_selector_count": 0,
                "source_not_in_needs_count": 0,
                "missing_source_route_count": 0,
                "missing_capability_route_count": 0,
                "unverified_source_route_count": 0,
                "argv_mapping_ready_count": 0,
            },
        }
    tasks = workflow.get("tasks", [])
    by_task = {task["id"]: task for task in tasks if isinstance(task, dict) and "id" in task}
    routes = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for mapping in task.get("argsFrom", []):
            if not isinstance(mapping, dict):
                continue
            source_id = mapping.get("task")
            selector = mapping.get("selector", "")
            source = by_task.get(source_id)
            selector_report = validate_selector_syntax(selector)
            consumer_capability = task.get("capability", {}) if isinstance(task, dict) else {}
            source_capability = source.get("capability", {}) if isinstance(source, dict) else {}
            route_kind = _route_kind(selector)
            route = {
                "consumer_task": task.get("id"),
                "consumer_capability": task.get("uses"),
                "consumer_capability_exists": consumer_capability.get("exists"),
                "source_task": source_id,
                "source_capability": source.get("uses") if isinstance(source, dict) else None,
                "source_capability_exists": source_capability.get("exists"),
                "selector": selector,
                "selector_valid": selector_report["valid"],
                "selector_tokens": selector_report["tokens"],
                "selector_error": selector_report["error"],
                "route_kind": route_kind,
                "source_in_needs": source_id in task.get("needs", []),
                "source_exists": source is not None,
                "source_parser_ref": source_capability.get("parser_ref"),
                "source_output_verified": source_capability.get("verified"),
                "verified_source_required": route_kind == "payload",
                "verified_source_satisfied": route_kind != "payload" or source_capability.get("verified") is True,
                "argv_mapping": {
                    "ready": selector_report["valid"] and route_kind in {"payload", "artifact", "metadata"},
                    "encoding": "bridge_value_to_arg",
                },
            }
            route["blockers"] = _route_blockers(route)
            route["ready"] = len(route["blockers"]) == 0
            routes.append(route)
    return {
        "valid": True,
        "workflow_id": workflow.get("workflow_id"),
        "path": workflow.get("path"),
        "title": workflow.get("title"),
        "task_count": workflow.get("task_count", 0),
        "routes": routes,
        "errors": [],
        "summary": _workflow_summary(routes),
    }


def _route_kind(selector: str) -> str:
    if selector.startswith("payload."):
        return "payload"
    if selector.startswith("artifacts["):
        return "artifact"
    if selector.startswith("metadata."):
        return "metadata"
    return "unknown"


def _workflow_summary(routes: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "route_count": len(routes),
        "route_ready_count": sum(1 for route in routes if route["ready"]),
        "blocked_route_count": sum(1 for route in routes if not route["ready"]),
        "payload_route_count": sum(1 for route in routes if route["route_kind"] == "payload"),
        "artifact_route_count": sum(1 for route in routes if route["route_kind"] == "artifact"),
        "metadata_route_count": sum(1 for route in routes if route["route_kind"] == "metadata"),
        "unknown_route_count": sum(1 for route in routes if route["route_kind"] == "unknown"),
        "invalid_selector_count": sum(1 for route in routes if not route["selector_valid"]),
        "source_not_in_needs_count": sum(1 for route in routes if not route["source_in_needs"]),
        "missing_source_route_count": sum(1 for route in routes if not route["source_exists"]),
        "missing_capability_route_count": sum(
            1
            for route in routes
            if route["source_capability_exists"] is False or route["consumer_capability_exists"] is False
        ),
        "unverified_source_route_count": sum(
            1
            for route in routes
            if route["source_output_verified"] is False and route["route_kind"] == "payload"
        ),
        "argv_mapping_ready_count": sum(1 for route in routes if route["argv_mapping"]["ready"]),
    }


def _route_blockers(route: dict[str, Any]) -> list[str]:
    blockers = []
    if not route["source_exists"]:
        blockers.append("source task is missing")
    if not route["source_in_needs"]:
        blockers.append("source task is not listed in needs")
    if route["source_capability_exists"] is False:
        blockers.append("source capability is missing from registry")
    if route["consumer_capability_exists"] is False:
        blockers.append("consumer capability is missing from registry")
    if not route["selector_valid"]:
        blockers.append("selector syntax is invalid")
    if route["route_kind"] == "unknown":
        blockers.append("selector must target payload, artifacts, or metadata")
    if route["verified_source_required"] and not route["verified_source_satisfied"]:
        blockers.append("payload route source output is not verified")
    if not route["argv_mapping"]["ready"]:
        blockers.append("selector is not ready for deterministic argv mapping")
    return blockers


def _summary(workflows: list[dict[str, Any]]) -> dict[str, int]:
    result = {
        "workflow_count": len(workflows),
        "valid_workflow_count": sum(1 for workflow in workflows if workflow["valid"]),
        "invalid_workflow_count": sum(1 for workflow in workflows if not workflow["valid"]),
        "routed_workflow_count": sum(1 for workflow in workflows if workflow["summary"]["route_count"] > 0),
        "route_count": 0,
        "route_ready_count": 0,
        "blocked_route_count": 0,
        "payload_route_count": 0,
        "artifact_route_count": 0,
        "metadata_route_count": 0,
        "unknown_route_count": 0,
        "invalid_selector_count": 0,
        "source_not_in_needs_count": 0,
        "missing_source_route_count": 0,
        "missing_capability_route_count": 0,
        "unverified_source_route_count": 0,
        "argv_mapping_ready_count": 0,
    }
    for workflow in workflows:
        for key in (
            "route_count",
            "route_ready_count",
            "blocked_route_count",
            "payload_route_count",
            "artifact_route_count",
            "metadata_route_count",
            "unknown_route_count",
            "invalid_selector_count",
            "source_not_in_needs_count",
            "missing_source_route_count",
            "missing_capability_route_count",
            "unverified_source_route_count",
            "argv_mapping_ready_count",
        ):
            result[key] += int(workflow["summary"].get(key, 0))
    return result
