"""Workflow catalog descriptors for CLI, daemon, and dashboard surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_core.manifest import ManifestRegistry
from cbn_execution.graph import WorkflowGraph


def list_workflows(
    workflows_dir: Path = Path("workflows"),
    registry: ManifestRegistry | None = None,
) -> list[dict[str, Any]]:
    return [
        inspect_workflow(path, registry=registry)
        for path in sorted(workflows_dir.glob("*.json"), key=lambda item: item.as_posix())
        if path.is_file()
    ]


def inspect_workflow(
    path: Path,
    registry: ManifestRegistry | None = None,
) -> dict[str, Any]:
    descriptor = _workflow_descriptor_base(path)
    try:
        graph = WorkflowGraph.from_file(path)
        graph.validate()
    except Exception as exc:
        descriptor["errors"].append(str(exc))
        return descriptor

    tasks = [_workflow_task_descriptor(task, registry) for task in graph.topological_order()]
    descriptor.update(_workflow_descriptor_success(graph, tasks))
    return descriptor


def _workflow_descriptor_base(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "valid": False,
        "workflow_id": None,
        "title": None,
        "task_count": 0,
        "tasks": [],
        "errors": [],
    }


def _workflow_task_descriptor(task: Any, registry: ManifestRegistry | None) -> dict[str, Any]:
    descriptor: dict[str, Any] = {
        "id": task.task_id,
        "uses": task.uses,
        "needs": list(task.needs),
        "args": list(task.args),
        "argsFrom": [arg_from.as_dict() for arg_from in task.args_from],
        "dryRun": task.dry_run,
        "approvalId": task.approval_id,
    }
    if registry is not None:
        descriptor["capability"] = _capability_summary(registry, task.uses)
    return descriptor


def _workflow_descriptor_success(
    graph: WorkflowGraph,
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "valid": True,
        "workflow_id": graph.workflow_id,
        "title": graph.title,
        "task_count": len(tasks),
        "tasks": tasks,
    }


def _capability_summary(registry: ManifestRegistry, capability_id: str) -> dict[str, Any]:
    try:
        manifest = registry.require(capability_id)
    except KeyError as exc:
        return {
            "exists": False,
            "error": str(exc),
        }
    return {
        "exists": True,
        "title": manifest.title,
        "transport": manifest.transport.kind,
        "risk": manifest.policy.risk,
        "network": manifest.policy.network,
        "parser_ref": manifest.output.parser_ref or "raw.text",
        "verified": manifest.output.verified,
    }
