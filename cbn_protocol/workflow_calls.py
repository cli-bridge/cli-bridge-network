"""Shared helpers for protocol facade workflow calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_execution.graph import WorkflowGraph
from cbn_runtime.context import RuntimeContext
from cbn_workflow.catalog import list_workflows


def run_workflow_from_metadata(
    runtime: RuntimeContext,
    cbn_meta: dict[str, Any],
    workflow_tool: str | None = None,
) -> dict[str, Any]:
    workflow_path = resolve_workflow_path(runtime, cbn_meta, workflow_tool=workflow_tool)
    graph = WorkflowGraph.from_file(Path(workflow_path))
    result = runtime.workflow_runner.run(
        graph,
        dry_run=bool(cbn_meta.get("dry_run", False)),
        confirmed=bool(cbn_meta.get("confirmed", False)),
    )
    result.setdefault("workflow_path", workflow_path)
    return result


def resolve_workflow_path(
    runtime: RuntimeContext,
    cbn_meta: dict[str, Any],
    workflow_tool: str | None = None,
) -> str:
    direct_path = _metadata_workflow_path(cbn_meta)
    if direct_path:
        return direct_path
    workflow_id = _metadata_workflow_id(cbn_meta, workflow_tool)
    if not workflow_id:
        raise ValueError("cbn workflow metadata requires workflow_id or workflow_path")
    path = _catalog_workflow_path(runtime, workflow_id)
    if path:
        return path
    raise ValueError(f"unknown workflow_id: {workflow_id}")


def _metadata_workflow_path(cbn_meta: dict[str, Any]) -> str | None:
    workflow_path = cbn_meta.get("workflow_path")
    return workflow_path if isinstance(workflow_path, str) and workflow_path else None


def _metadata_workflow_id(cbn_meta: dict[str, Any], workflow_tool: str | None) -> str | None:
    workflow_id = cbn_meta.get("workflow_id")
    if isinstance(workflow_id, str) and workflow_id:
        return workflow_id
    return _workflow_id_from_tool(workflow_tool)


def _catalog_workflow_path(runtime: RuntimeContext, workflow_id: str) -> str | None:
    for workflow in list_workflows(registry=runtime.registry):
        if _workflow_matches_id(workflow, workflow_id):
            path = workflow.get("path")
            if isinstance(path, str) and path:
                return path
    return None


def _workflow_matches_id(workflow: dict[str, Any], workflow_id: str) -> bool:
    catalog_id = workflow.get("workflow_id")
    return catalog_id == workflow_id or f"workflow:{catalog_id}" == workflow_id


def workflow_run_ok(result: dict[str, Any]) -> bool:
    return result.get("status") == "completed"


def workflow_messages(result: dict[str, Any]) -> list[dict[str, Any]]:
    messages = []
    for task in result.get("tasks", []):
        if isinstance(task, dict):
            message = task.get("result", {}).get("message")
            if isinstance(message, dict):
                messages.append(message)
    return messages


def _workflow_id_from_tool(workflow_tool: str | None) -> str | None:
    if isinstance(workflow_tool, str) and workflow_tool.startswith("workflow:"):
        return workflow_tool.removeprefix("workflow:")
    return None
