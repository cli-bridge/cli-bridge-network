"""Deterministic natural-language to workflow invocation plans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_agent import AgentBridgeMessage, AgentSession, AgentTask
from cbn_adapter_agent.nodes import build_adapter_agent_node_bundle
from cbn_execution.graph import WorkflowGraph


REQUEST_PLAN_API_VERSION = "bridge.dev/v1alpha1"
DEFAULT_REQUEST_MESSAGE = "Run this workflow as a reusable CLI-CLI harness agent."


@dataclass(frozen=True)
class _WorkflowRequestPlanContext:
    target: Path
    graph: WorkflowGraph
    plan: dict[str, Any]
    ordered_tasks: list[Any]
    route_summary: list[dict[str, Any]]
    agent_bundle: dict[str, Any]
    session: AgentSession
    request_task: AgentTask
    run_payload: dict[str, Any]
    bridge_message: dict[str, Any]


@dataclass(frozen=True)
class _WorkflowBridgeMessageInput:
    session: AgentSession
    request_task: AgentTask
    message: str
    workflow_id: str
    workflow_path: Path
    task_count: int
    route_count: int
    run_payload: dict[str, Any]


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

    target = Path(workflow_path)
    context = _workflow_request_plan_context(
        message=message,
        target=target,
        root=root,
        dry_run=dry_run,
        confirmed=confirmed,
    )
    return _workflow_request_plan_response(context, message=message, base_url=base_url, dry_run=dry_run)


def _workflow_request_plan_context(
    *,
    message: str,
    target: Path,
    root: Path | None,
    dry_run: bool,
    confirmed: bool,
) -> _WorkflowRequestPlanContext:
    graph = _load_workflow_graph(target, root)
    plan = graph.as_plan()
    ordered_tasks = graph.topological_order()
    route_summary = _route_summary(ordered_tasks)
    agent_bundle = build_adapter_agent_node_bundle(
        message=message,
        workflow_path=target,
        root=root,
    )
    session = _agent_session(message, target, graph.workflow_id, dry_run, confirmed, len(route_summary))
    request_task = _request_task(session.agent_id, graph.workflow_id, target, message)
    run_payload = _run_payload(target, dry_run, confirmed)
    counts = (len(ordered_tasks), len(route_summary))
    bridge_message = _workflow_bridge_message(session, request_task, message, graph, target, counts, run_payload)
    return _WorkflowRequestPlanContext(
        target=target,
        graph=graph,
        plan=plan,
        ordered_tasks=ordered_tasks,
        route_summary=route_summary,
        agent_bundle=agent_bundle,
        session=session,
        request_task=request_task,
        run_payload=run_payload,
        bridge_message=bridge_message,
    )


def _workflow_bridge_message(
    session: AgentSession,
    request_task: AgentTask,
    message: str,
    graph: WorkflowGraph,
    target: Path,
    counts: tuple[int, int],
    run_payload: dict[str, Any],
) -> dict[str, Any]:
    task_count, route_count = counts
    return _bridge_message(_WorkflowBridgeMessageInput(
        session=session,
        request_task=request_task,
        message=message,
        workflow_id=graph.workflow_id,
        workflow_path=target,
        task_count=task_count,
        route_count=route_count,
        run_payload=run_payload,
    ))


def _workflow_request_plan_response(
    context: _WorkflowRequestPlanContext,
    *,
    message: str,
    base_url: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "apiVersion": REQUEST_PLAN_API_VERSION,
        "kind": "AdapterAgentWorkflowRequestPlan",
        "ok": True,
        "status": "ready",
        "workflow_path": str(context.target),
        "request": _request_summary(message),
        "summary": _plan_summary(
            context.graph,
            context.ordered_tasks,
            context.route_summary,
            context.agent_bundle,
            dry_run,
        ),
        "agent_session": context.session.as_dict(),
        "agent_task": context.request_task.as_dict(),
        "agent_node_bundle": _agent_bundle_summary(context.agent_bundle),
        "workflow": _workflow_summary(context.plan),
        "bridge_routes": context.route_summary,
        "run": _run_instructions(context.target, context.run_payload, base_url, dry_run),
        "reusable_harness": _reusable_harness_contract(),
        "bridge_message": context.bridge_message,
        "next_commands": _next_commands(context.target, message),
    }


def _load_workflow_graph(target: Path, root: Path | None) -> WorkflowGraph:
    paths = resolve_project_paths(root)
    source_path = target if target.is_absolute() else paths.root / target
    graph = WorkflowGraph.from_file(source_path)
    graph.validate()
    return graph


def _agent_session(
    message: str,
    workflow_path: Path,
    workflow_id: str,
    dry_run: bool,
    confirmed: bool,
    route_count: int,
) -> AgentSession:
    return AgentSession(
        agent_id="orchestration-coordinator-agent",
        workflow_id=workflow_id,
        state="ready",
        context={
            "request_message": message,
            "workflow_path": str(workflow_path),
            "dry_run": dry_run,
            "confirmed": confirmed,
            "route_count": route_count,
        },
    )


def _request_task(agent_id: str, workflow_id: str, workflow_path: Path, message: str) -> AgentTask:
    return AgentTask(
        task_id="agent-workflow-request",
        agent_id=agent_id,
        instruction="Map the natural-language request to the selected reusable CLI-CLI workflow.",
        uses="WorkflowInvocationPlan",
        inputs={
            "workflow_id": workflow_id,
            "workflow_path": str(workflow_path),
            "request_message": message,
        },
    )


def _run_payload(workflow_path: Path, dry_run: bool, confirmed: bool) -> dict[str, Any]:
    return {
        "path": str(workflow_path),
        "dry_run": dry_run,
        "confirmed": confirmed,
    }


def _bridge_message(params: _WorkflowBridgeMessageInput) -> dict[str, Any]:
    return AgentBridgeMessage(
        agent_id=params.session.agent_id,
        session_id=params.session.session_id,
        task_id=params.request_task.task_id,
        channel="agent.workflow.request.plan",
        data={
            "request_message": params.message,
            "workflow_id": params.workflow_id,
            "workflow_path": str(params.workflow_path),
            "task_count": params.task_count,
            "route_count": params.route_count,
            "run_payload": params.run_payload,
        },
    ).as_bridge_message()


def _request_summary(message: str) -> dict[str, Any]:
    return {
        "message": message,
        "intent": _intent_from_message(message),
        "binding": "selected_workflow_path",
    }


def _plan_summary(
    graph: WorkflowGraph,
    ordered_tasks: list[Any],
    route_summary: list[dict[str, Any]],
    agent_bundle: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "workflow_id": graph.workflow_id,
        "workflow_title": graph.title,
        "task_count": len(ordered_tasks),
        "bridge_route_count": len(route_summary),
        "agent_card_count": len(agent_bundle.get("cards", [])),
        "recommended_next_action": "run_workflow_dry_run" if dry_run else "run_workflow_confirmed",
    }


def _agent_bundle_summary(agent_bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": agent_bundle.get("kind"),
        "status": agent_bundle.get("status"),
        "card_count": len(agent_bundle.get("cards", [])),
        "task_count": len(agent_bundle.get("tasks", [])),
    }


def _workflow_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow_id": plan["workflow_id"],
        "title": plan["title"],
        "tasks": plan["tasks"],
    }


def _run_instructions(
    workflow_path: Path,
    run_payload: dict[str, Any],
    base_url: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "payload": run_payload,
        "cli": f"python -m cbn workflow run {workflow_path} {'--dry-run' if dry_run else ''}".strip(),
        "http": {
            "method": "POST",
            "path": "/workflows/run",
            "url": f"{base_url.rstrip('/')}/workflows/run" if base_url else "/workflows/run",
            "json": run_payload,
        },
    }


def _reusable_harness_contract() -> dict[str, Any]:
    return {
        "kind": "NaturalLanguageWorkflowHarness",
        "accepts": ["natural_language_request", "BridgeMessage"],
        "emits": ["BridgeMessage", "Artifact", "AuditEvent"],
        "contract": "agent request -> workflow run payload -> CLI-CLI BridgeMessage routes",
    }


def _next_commands(workflow_path: Path, message: str) -> list[str]:
    return [
        f"python -m cbn_adapter_agent --workflow-request-plan --workflow-path {workflow_path} --message \"{_shell_safe_message(message)}\"",
        f"python -m cbn workflow inspect {workflow_path}",
        f"python -m cbn workflow run {workflow_path} --dry-run",
        f"python -m cbn network connect-package --workflow-path {workflow_path}",
    ]


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
