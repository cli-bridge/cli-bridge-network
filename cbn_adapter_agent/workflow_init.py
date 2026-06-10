"""Workflow initialization planning for Adapter Agent auth gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_core.manifest import ManifestRegistry
from cbn_execution.graph import WorkflowGraph

from cbn_adapter_agent.auth_setup import (
    auth_setup_required,
    build_auth_setup_guide,
    runtime_input_requirements,
)


def build_workflow_initialization_plan(
    workflow_path: Path,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    paths = resolve_project_paths(root)
    source_path = workflow_path if workflow_path.is_absolute() else paths.root / workflow_path
    graph = WorkflowGraph.from_file(source_path)
    graph.validate()
    registry = ManifestRegistry()
    registry.load_dir(paths.manifests)
    registry.load_dir(paths.local_manifests, replace=True)

    tasks = []
    setup_by_id: dict[str, dict[str, object]] = {}
    for task in graph.topological_order():
        manifest = registry.require(task.uses)
        guide = build_auth_setup_guide(manifest, workflow_path=workflow_path, root=paths.root)
        runtime_inputs = runtime_input_requirements(manifest)
        missing_runtime_inputs = _missing_runtime_inputs(task, runtime_inputs)
        setup_id = None
        if guide is not None:
            setup = guide.as_dict()
            setup_id = str(setup["setup_id"])
            setup_by_id.setdefault(setup_id, setup)
        tasks.append(
            {
                "task_id": task.task_id,
                "uses": task.uses,
                "title": manifest.title,
                "risk": manifest.policy.risk,
                "network": manifest.policy.network,
                "requires_confirmation": manifest.policy.requires_confirmation,
                "auth_setup_required": auth_setup_required(manifest),
                "auth_setup_id": setup_id,
                "auth_gate": manifest.annotations.get("cbn.auth_gate"),
                "runtime_inputs": runtime_inputs,
                "missing_runtime_inputs": missing_runtime_inputs,
                "status": _task_status(setup_id=setup_id, missing_runtime_inputs=missing_runtime_inputs),
            }
        )

    setup_guides = list(setup_by_id.values())
    blocking_tasks = [task for task in tasks if task["auth_setup_required"]]
    input_blocking_tasks = [task for task in tasks if task["missing_runtime_inputs"]]
    return {
        "kind": "WorkflowInitializationPlan",
        "apiVersion": "bridge.dev/v1alpha1",
        "workflow": {
            "workflow_id": graph.workflow_id,
            "title": graph.title,
            "path": str(workflow_path),
            "task_count": len(tasks),
        },
        "ok": not blocking_tasks and not input_blocking_tasks,
        "status": _plan_status(blocking_tasks, input_blocking_tasks),
        "tasks": tasks,
        "setup_guides": setup_guides,
        "summary": {
            "task_count": len(tasks),
            "setup_count": len(setup_guides),
            "blocking_task_count": len(blocking_tasks),
            "input_blocking_task_count": len(input_blocking_tasks),
            "requires_confirmation_count": sum(1 for task in tasks if task["requires_confirmation"]),
        },
        "continuation": {
            "mode": "manual_resume_after_setup" if blocking_tasks or input_blocking_tasks else "ready_to_run",
            "command": ["python", "-m", "cbn", "workflow", "run", str(workflow_path), "--yes"],
            "note": "Complete setup_guides and missing_runtime_inputs first; then resume with the command above.",
        },
    }


def _missing_runtime_inputs(task: object, requirements: list[dict[str, object]]) -> list[dict[str, object]]:
    missing = []
    explicit_inputs = len(task.args) + len(task.args_from)  # type: ignore[attr-defined]
    for requirement in requirements:
        if not requirement.get("required"):
            continue
        if requirement.get("kind") in {"secret", "authenticated-session"}:
            missing.append(requirement)
        elif explicit_inputs == 0:
            missing.append(requirement)
    return missing


def _task_status(setup_id: str | None, missing_runtime_inputs: list[dict[str, object]]) -> str:
    if setup_id and missing_runtime_inputs:
        return "requires_setup_and_inputs"
    if setup_id:
        return "requires_setup"
    if missing_runtime_inputs:
        return "requires_inputs"
    return "ready"


def _plan_status(
    blocking_tasks: list[dict[str, object]],
    input_blocking_tasks: list[dict[str, object]],
) -> str:
    if blocking_tasks and input_blocking_tasks:
        return "requires_user_setup_and_inputs"
    if blocking_tasks:
        return "requires_user_setup"
    if input_blocking_tasks:
        return "requires_runtime_inputs"
    return "ready"
