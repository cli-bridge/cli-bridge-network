"""Map Adapter Agent planning roles into core CBN Agent node records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_agent import AgentBridgeMessage, AgentCard, AgentHarness, AgentSession, AgentTask
from cbn_adapter_agent.coordinator import build_multi_agent_coordination_plan


def build_adapter_agent_node_bundle(
    *,
    message: str = "",
    workflow_path: str | Path | None = None,
    profiles: tuple[str, ...] | None = None,
    root: Path | None = None,
    coordination_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = coordination_plan or build_multi_agent_coordination_plan(
        message=message,
        workflow_path=workflow_path,
        profiles=profiles,
        root=root,
    )
    session = AgentSession(
        agent_id="orchestration-coordinator-agent",
        workflow_id=str(plan.get("workflow_path") or ""),
        state="ready" if plan.get("ok") else "waiting_on_setup",
        context={
            "status": plan.get("status"),
            "profile_scope": plan.get("profile_scope", []),
            "message_present": bool(plan.get("message_present")),
            "next_actions": plan.get("next_actions", []),
        },
    )
    cards = [_agent_card(agent) for agent in plan.get("agents", []) if isinstance(agent, dict)]
    harnesses = [AgentHarness(harness_id=f"{card.agent_id}.harness", card=card) for card in cards]
    tasks = [
        _agent_task(agent=agent, session_id=session.session_id)
        for agent in plan.get("agents", [])
        if isinstance(agent, dict)
    ]
    bridge_message = AgentBridgeMessage(
        agent_id=session.agent_id,
        session_id=session.session_id,
        task_id="adapter-agent-node-bundle",
        channel="agent.adapter.node_bundle",
        ok=bool(plan.get("ok")),
        data={
            "workflow_path": plan.get("workflow_path"),
            "status": plan.get("status"),
            "agent_count": len(cards),
            "task_count": len(tasks),
            "next_actions": plan.get("next_actions", []),
        },
    ).as_bridge_message()
    return {
        "kind": "AdapterAgentNodeBundle",
        "apiVersion": "bridge.dev/v1alpha1",
        "ok": bool(plan.get("ok")),
        "status": plan.get("status"),
        "workflow_path": plan.get("workflow_path"),
        "session": session.as_dict(),
        "cards": [card.as_dict() for card in cards],
        "harnesses": [harness.as_dict() for harness in harnesses],
        "tasks": [task.as_dict() for task in tasks],
        "workflow_nodes": [task.as_workflow_node() for task in tasks],
        "bridge_message": bridge_message,
        "source_coordination_plan": {
            "kind": plan.get("kind"),
            "status": plan.get("status"),
            "profile_scope": plan.get("profile_scope", []),
            "handoffs": plan.get("handoffs", []),
            "tool_call_plan_summary": plan.get("tool_call_plan_summary", {}),
        },
    }


def _agent_card(agent: dict[str, Any]) -> AgentCard:
    role_id = str(agent["role_id"])
    return AgentCard(
        agent_id=role_id,
        role=role_id,
        title=str(agent.get("title") or role_id),
        capabilities=tuple(str(item) for item in agent.get("allowed_actions", [])),
        transport={"kind": "in-process", "runtime": "cbn_adapter_agent"},
        policy={
            "risk": _role_risk(agent),
            "allowedActions": list(agent.get("allowed_actions", [])),
            "deniedActions": list(agent.get("denied_actions", [])),
        },
        metadata={
            "status": agent.get("status"),
            "sequence": agent.get("sequence"),
            "outputKind": agent.get("output_kind"),
        },
    )


def _agent_task(agent: dict[str, Any], session_id: str) -> AgentTask:
    role_id = str(agent["role_id"])
    return AgentTask(
        task_id=f"{int(agent.get('sequence') or 0):02d}-{role_id}",
        agent_id=role_id,
        instruction=str(agent.get("purpose") or agent.get("title") or role_id),
        uses=str(agent.get("output_kind") or ""),
        inputs={
            "session_id": session_id,
            "status": agent.get("status"),
            "summary": agent.get("summary"),
        },
    )


def _role_risk(agent: dict[str, Any]) -> str:
    denied = " ".join(str(item) for item in agent.get("denied_actions", [])).casefold()
    allowed = " ".join(str(item) for item in agent.get("allowed_actions", [])).casefold()
    if "install" in allowed or "write" in allowed:
        return "write-workspace"
    if "install" in denied or "write" in denied:
        return "read"
    return "read"
