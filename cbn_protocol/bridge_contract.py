"""CBN internal CLI-to-CLI contract reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_protocol.envelope import BRIDGE_MESSAGE_API_VERSION, validate_selector_syntax
from cbn_workflow.catalog import inspect_workflow, list_workflows


def bridge_message_contract() -> dict[str, Any]:
    return {
        "apiVersion": BRIDGE_MESSAGE_API_VERSION,
        "message_kind": "BridgeMessage",
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
        "ok": summary["invalid_workflow_count"] == 0 and summary["invalid_selector_count"] == 0,
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
                "payload_route_count": 0,
                "artifact_route_count": 0,
                "metadata_route_count": 0,
                "invalid_selector_count": 0,
                "unverified_source_route_count": 0,
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
            source_capability = source.get("capability", {}) if isinstance(source, dict) else {}
            route = {
                "consumer_task": task.get("id"),
                "consumer_capability": task.get("uses"),
                "source_task": source_id,
                "source_capability": source.get("uses") if isinstance(source, dict) else None,
                "selector": selector,
                "selector_valid": selector_report["valid"],
                "selector_tokens": selector_report["tokens"],
                "selector_error": selector_report["error"],
                "route_kind": _route_kind(selector),
                "source_in_needs": source_id in task.get("needs", []),
                "source_exists": source is not None,
                "source_parser_ref": source_capability.get("parser_ref"),
                "source_output_verified": source_capability.get("verified"),
            }
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
        "payload_route_count": sum(1 for route in routes if route["route_kind"] == "payload"),
        "artifact_route_count": sum(1 for route in routes if route["route_kind"] == "artifact"),
        "metadata_route_count": sum(1 for route in routes if route["route_kind"] == "metadata"),
        "invalid_selector_count": sum(1 for route in routes if not route["selector_valid"]),
        "unverified_source_route_count": sum(
            1
            for route in routes
            if route["source_output_verified"] is False and route["route_kind"] == "payload"
        ),
    }


def _summary(workflows: list[dict[str, Any]]) -> dict[str, int]:
    result = {
        "workflow_count": len(workflows),
        "valid_workflow_count": sum(1 for workflow in workflows if workflow["valid"]),
        "invalid_workflow_count": sum(1 for workflow in workflows if not workflow["valid"]),
        "routed_workflow_count": sum(1 for workflow in workflows if workflow["summary"]["route_count"] > 0),
        "route_count": 0,
        "payload_route_count": 0,
        "artifact_route_count": 0,
        "metadata_route_count": 0,
        "invalid_selector_count": 0,
        "unverified_source_route_count": 0,
    }
    for workflow in workflows:
        for key in (
            "route_count",
            "payload_route_count",
            "artifact_route_count",
            "metadata_route_count",
            "invalid_selector_count",
            "unverified_source_route_count",
        ):
            result[key] += int(workflow["summary"].get(key, 0))
    return result
