"""Workflow setup planning for auth-gated Adapter Agent workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_core.manifest import ManifestRegistry
from cbn_execution.graph import WorkflowGraph

from cbn_adapter_agent.agent_roles import get_agent_role
from cbn_adapter_agent.auth_setup import (
    auth_setup_required,
    build_auth_setup_guide,
    runtime_input_requirements,
)


def build_workflow_setup_plan(
    workflow_path: Path,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Build the new Workflow Setup Agent payload."""

    return _build_workflow_setup_payload(
        workflow_path,
        root=root,
        kind="WorkflowSetupPlan",
        compatibility=None,
    )


def build_workflow_initialization_plan(
    workflow_path: Path,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for the previous Adapter Agent contract."""

    return _build_workflow_setup_payload(
        workflow_path,
        root=root,
        kind="WorkflowInitializationPlan",
        compatibility={
            "replacement": "WorkflowSetupPlan",
            "note": "Workflow initialization is now handled by workflow-setup-agent.",
        },
    )


def _build_workflow_setup_payload(
    workflow_path: Path,
    *,
    root: Path | None,
    kind: str,
    compatibility: dict[str, str] | None,
) -> dict[str, Any]:
    graph, registry, root_path = _load_workflow_setup_context(workflow_path, root)
    tasks, setup_guides = _workflow_setup_rows(graph, registry, workflow_path, root_path)
    blocking_tasks = [task for task in tasks if task["auth_setup_required"]]
    input_blocking_tasks = [task for task in tasks if task["missing_runtime_inputs"]]
    payload: dict[str, Any] = {
        "kind": kind,
        "apiVersion": "bridge.dev/v1alpha1",
        "agent_role": get_agent_role("workflow-setup-agent"),
        "agent_policy": _agent_policy(),
        "workflow": _workflow_summary(graph, workflow_path, len(tasks)),
        "ok": not blocking_tasks and not input_blocking_tasks,
        "status": _plan_status(blocking_tasks, input_blocking_tasks),
        "tasks": tasks,
        "setup_guides": setup_guides,
        "summary": _setup_summary(tasks, setup_guides, blocking_tasks, input_blocking_tasks),
        "handoff": _handoff(),
        "continuation": _continuation(workflow_path, blocking_tasks, input_blocking_tasks),
    }
    if compatibility is not None:
        payload["compatibility"] = compatibility
    return payload


def _load_workflow_setup_context(
    workflow_path: Path,
    root: Path | None,
) -> tuple[WorkflowGraph, ManifestRegistry, Path]:
    paths = resolve_project_paths(root)
    source_path = workflow_path if workflow_path.is_absolute() else paths.root / workflow_path
    graph = WorkflowGraph.from_file(source_path)
    graph.validate()
    registry = ManifestRegistry()
    registry.load_dir(paths.manifests)
    registry.load_dir(paths.local_manifests, replace=True)
    return graph, registry, paths.root


def _workflow_setup_rows(
    graph: WorkflowGraph,
    registry: ManifestRegistry,
    workflow_path: Path,
    root_path: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    tasks = []
    setup_by_id: dict[str, dict[str, object]] = {}
    for task in graph.topological_order():
        manifest = registry.require(task.uses)
        guide = build_auth_setup_guide(manifest, workflow_path=workflow_path, root=root_path)
        runtime_inputs = runtime_input_requirements(manifest)
        missing_runtime_inputs = _missing_runtime_inputs(task, runtime_inputs)
        setup_id = None
        if guide is not None:
            setup = guide.as_dict()
            setup_id = str(setup["setup_id"])
            setup_by_id.setdefault(setup_id, setup)
        tasks.append(_task_row(task, manifest, runtime_inputs, missing_runtime_inputs, setup_id))
    return tasks, list(setup_by_id.values())


def _task_row(
    task: object,
    manifest: object,
    runtime_inputs: list[dict[str, object]],
    missing_runtime_inputs: list[dict[str, object]],
    setup_id: str | None,
) -> dict[str, object]:
    return {
        "task_id": task.task_id,  # type: ignore[attr-defined]
        "uses": task.uses,  # type: ignore[attr-defined]
        "title": manifest.title,  # type: ignore[attr-defined]
        "risk": manifest.policy.risk,  # type: ignore[attr-defined]
        "network": manifest.policy.network,  # type: ignore[attr-defined]
        "requires_confirmation": manifest.policy.requires_confirmation,  # type: ignore[attr-defined]
        "auth_setup_required": auth_setup_required(manifest),  # type: ignore[arg-type]
        "auth_setup_id": setup_id,
        "auth_gate": manifest.annotations.get("cbn.auth_gate"),  # type: ignore[attr-defined]
        "runtime_inputs": runtime_inputs,
        "missing_runtime_inputs": missing_runtime_inputs,
        "status": _task_status(setup_id=setup_id, missing_runtime_inputs=missing_runtime_inputs),
    }


def _agent_policy() -> dict[str, object]:
    return {
        "role": "workflow-setup-agent",
        "drafts_manifests": False,
        "installs_tools": False,
        "runs_workflow_tasks": False,
        "collects_secrets_in_chat": False,
        "requires_accepted_manifests": True,
    }


def _workflow_summary(graph: WorkflowGraph, workflow_path: Path, task_count: int) -> dict[str, object]:
    return {
        "workflow_id": graph.workflow_id,
        "title": graph.title,
        "path": str(workflow_path),
        "task_count": task_count,
    }


def _setup_summary(
    tasks: list[dict[str, object]],
    setup_guides: list[dict[str, object]],
    blocking_tasks: list[dict[str, object]],
    input_blocking_tasks: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "task_count": len(tasks),
        "setup_count": len(setup_guides),
        "blocking_task_count": len(blocking_tasks),
        "input_blocking_task_count": len(input_blocking_tasks),
        "requires_confirmation_count": sum(1 for task in tasks if task["requires_confirmation"]),
    }


def _handoff() -> dict[str, str]:
    return {
        "from": "manifest-bootstrap-agent",
        "to": "workflow-setup-agent",
        "requires": "accepted CapabilityManifest registry",
        "produces": "setup gates and resume command for orchestration-coordinator-agent",
    }


def _continuation(
    workflow_path: Path,
    blocking_tasks: list[dict[str, object]],
    input_blocking_tasks: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "mode": "manual_resume_after_setup" if blocking_tasks or input_blocking_tasks else "ready_to_run",
        "command": ["python", "-m", "cbn", "workflow", "run", str(workflow_path), "--yes"],
        "note": "Complete setup_guides and missing_runtime_inputs first; then resume with the command above.",
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
