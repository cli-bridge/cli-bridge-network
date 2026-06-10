"""Deterministic natural-language to workflow invocation plans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_agent import AgentBridgeMessage, AgentSession, AgentTask
from cbn_adapter_agent.nodes import build_adapter_agent_node_bundle
from cbn_execution.graph import WorkflowGraph


REQUEST_PLAN_API_VERSION = "bridge.dev/v1alpha1"
DEFAULT_REQUEST_MESSAGE = "Run this workflow as a reusable CLI-CLI harness agent."


def build_agent_workflow_request_plan(
    *,
    message: str = DEFAULT_REQUEST_MESSAGE,
    workflow_path: str | Path,
    root: Path | None = None,
    base_url: str | None = None,
    dry_run: bool = True,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Return a reusable invocation package for a natural-language agent request.

    This intentionally does not run the workflow. It binds the operator's natural
    language request to the selected CLI-CLI workflow and emits the exact CLI/API
    payloads another program can reuse.
    """

    paths = resolve_project_paths(root)
    target = Path(workflow_path)
    source_path = target if target.is_absolute() else paths.root / target
    graph = WorkflowGraph.from_file(source_path)
    graph.validate()
    plan = graph.as_plan()
    ordered_tasks = graph.topological_order()
    route_summary = _route_summary(ordered_tasks)
    agent_bundle = build_adapter_agent_node_bundle(
        message=message,
        workflow_path=target,
        root=root,
    )
    session = AgentSession(
        agent_id="orchestration-coordinator-agent",
        workflow_id=graph.workflow_id,
        state="ready",
        context={
            "request_message": message,
            "workflow_path": str(target),
            "dry_run": dry_run,
            "confirmed": confirmed,
            "route_count": len(route_summary),
        },
    )
    request_task = AgentTask(
        task_id="agent-workflow-request",
        agent_id=session.agent_id,
        instruction="Map the natural-language request to the selected reusable CLI-CLI workflow.",
        uses="WorkflowInvocationPlan",
        inputs={
            "workflow_id": graph.workflow_id,
            "workflow_path": str(target),
            "request_message": message,
        },
    )
    run_payload = {
        "path": str(target),
        "dry_run": dry_run,
        "confirmed": confirmed,
    }
    bridge_message = AgentBridgeMessage(
        agent_id=session.agent_id,
        session_id=session.session_id,
        task_id=request_task.task_id,
        channel="agent.workflow.request.plan",
        data={
            "request_message": message,
            "workflow_id": graph.workflow_id,
            "workflow_path": str(target),
            "task_count": len(ordered_tasks),
            "route_count": len(route_summary),
            "run_payload": run_payload,
        },
    ).as_bridge_message()
    return {
        "apiVersion": REQUEST_PLAN_API_VERSION,
        "kind": "AdapterAgentWorkflowRequestPlan",
        "ok": True,
        "status": "ready",
        "workflow_path": str(target),
        "request": {
            "message": message,
            "intent": _intent_from_message(message),
            "binding": "selected_workflow_path",
        },
        "summary": {
            "workflow_id": graph.workflow_id,
            "workflow_title": graph.title,
            "task_count": len(ordered_tasks),
            "bridge_route_count": len(route_summary),
            "agent_card_count": len(agent_bundle.get("cards", [])),
            "recommended_next_action": "run_workflow_dry_run" if dry_run else "run_workflow_confirmed",
        },
        "agent_session": session.as_dict(),
        "agent_task": request_task.as_dict(),
        "agent_node_bundle": {
            "kind": agent_bundle.get("kind"),
            "status": agent_bundle.get("status"),
            "card_count": len(agent_bundle.get("cards", [])),
            "task_count": len(agent_bundle.get("tasks", [])),
        },
        "workflow": {
            "workflow_id": plan["workflow_id"],
            "title": plan["title"],
            "tasks": plan["tasks"],
        },
        "bridge_routes": route_summary,
        "run": {
            "payload": run_payload,
            "cli": f"python -m cbn workflow run {target} {'--dry-run' if dry_run else ''}".strip(),
            "http": {
                "method": "POST",
                "path": "/workflows/run",
                "url": f"{base_url.rstrip('/')}/workflows/run" if base_url else "/workflows/run",
                "json": run_payload,
            },
        },
        "reusable_harness": {
            "kind": "NaturalLanguageWorkflowHarness",
            "accepts": ["natural_language_request", "BridgeMessage"],
            "emits": ["BridgeMessage", "Artifact", "AuditEvent"],
            "contract": "agent request -> workflow run payload -> CLI-CLI BridgeMessage routes",
        },
        "bridge_message": bridge_message,
        "next_commands": [
            f"python -m cbn_adapter_agent --workflow-request-plan --workflow-path {target} --message \"{_shell_safe_message(message)}\"",
            f"python -m cbn workflow inspect {target}",
            f"python -m cbn workflow run {target} --dry-run",
            f"python -m cbn network connect-package --workflow-path {target}",
        ],
    }


def _route_summary(tasks: list[Any]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for task in tasks:
        selectors = [arg_from.as_dict() for arg_from in task.args_from]
        if not selectors:
            continue
        routes.append(
            {
                "task_id": task.task_id,
                "uses": task.uses,
                "needs": list(task.needs),
                "selectors": selectors,
                "communication": "BridgeMessage argsFrom",
            }
        )
    return routes


def _intent_from_message(message: str) -> dict[str, Any]:
    lowered = message.casefold()
    return {
        "mentions_run": any(term in lowered for term in ("run", "execute", "调用", "运行", "跑")),
        "mentions_reuse": any(term in lowered for term in ("reuse", "reusable", "复用", "接入")),
        "mentions_artifact": any(term in lowered for term in ("artifact", "output", "产物", "结果")),
    }


def _shell_safe_message(message: str) -> str:
    return message.replace('"', '\\"')
