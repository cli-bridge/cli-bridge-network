"""Shared helpers for protocol facade workflow calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_execution.graph import WorkflowGraph
from cbn_runtime.context import RuntimeContext


def run_workflow_from_metadata(
    runtime: RuntimeContext,
    cbn_meta: dict[str, Any],
) -> dict[str, Any]:
    workflow_path = cbn_meta.get("workflow_path")
    if not isinstance(workflow_path, str) or not workflow_path:
        raise ValueError("cbn workflow metadata requires workflow_path")
    graph = WorkflowGraph.from_file(Path(workflow_path))
    return runtime.workflow_runner.run(
        graph,
        dry_run=bool(cbn_meta.get("dry_run", False)),
        confirmed=bool(cbn_meta.get("confirmed", False)),
    )


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
