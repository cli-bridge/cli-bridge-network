"""Agent-as-node contracts for CBN's internal bus.

These models deliberately sit below cbn_adapter_agent.  Adapter-specific code can
map into them, while workflow/runtime code can rely on stable Agent node records
and BridgeMessage emission without importing a specific agent implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid

from cbn_core.message import BridgeMessage


AGENT_API_VERSION = "bridge.dev/v1alpha1"
AGENT_BRIDGE_PARSER_REF = "cbn.agent.bridge_message"


@dataclass(frozen=True)
class AgentCard:
    agent_id: str
    role: str
    title: str
    capabilities: tuple[str, ...] = ()
    transport: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": AGENT_API_VERSION,
            "kind": "AgentCard",
            "metadata": {
                **self.metadata,
                "id": self.agent_id,
                "title": self.title,
                "role": self.role,
            },
            "spec": {
                "capabilities": list(self.capabilities),
                "transport": self.transport,
                "policy": self.policy,
            },
        }


@dataclass(frozen=True)
class AgentHarness:
    harness_id: str
    card: AgentCard
    accepts: tuple[str, ...] = ("BridgeMessage",)
    emits: tuple[str, ...] = ("BridgeMessage", "Artifact")

    def as_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": AGENT_API_VERSION,
            "kind": "AgentHarness",
            "metadata": {
                "id": self.harness_id,
                "agentId": self.card.agent_id,
            },
            "spec": {
                "card": self.card.as_dict(),
                "accepts": list(self.accepts),
                "emits": list(self.emits),
            },
        }


@dataclass(frozen=True)
class AgentSession:
    agent_id: str
    workflow_id: str | None = None
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: str = "active"
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": AGENT_API_VERSION,
            "kind": "AgentSession",
            "metadata": {
                "id": self.session_id,
                "agentId": self.agent_id,
                "workflowId": self.workflow_id,
            },
            "spec": {
                "state": self.state,
                "context": self.context,
            },
        }


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    agent_id: str
    instruction: str
    uses: str | None = None
    selectors: tuple[str, ...] = ()
    inputs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": AGENT_API_VERSION,
            "kind": "AgentTask",
            "metadata": {
                "id": self.task_id,
                "agentId": self.agent_id,
            },
            "spec": {
                "instruction": self.instruction,
                "uses": self.uses,
                "selectors": list(self.selectors),
                "inputs": self.inputs,
            },
        }

    def as_workflow_node(self) -> dict[str, Any]:
        node: dict[str, Any] = {
            "id": self.task_id,
            "agent": self.agent_id,
            "instruction": self.instruction,
        }
        if self.uses:
            node["uses"] = self.uses
        if self.selectors:
            node["argsFrom"] = [{"selector": selector} for selector in self.selectors]
        if self.inputs:
            node["with"] = self.inputs
        return node


@dataclass(frozen=True)
class AgentBridgeMessage:
    agent_id: str
    session_id: str
    task_id: str
    channel: str
    data: dict[str, Any]
    ok: bool = True
    error: str | None = None
    artifacts: tuple[dict[str, Any], ...] = ()

    def as_bridge_message(self) -> dict[str, Any]:
        return agent_bridge_message(
            agent_id=self.agent_id,
            session_id=self.session_id,
            task_id=self.task_id,
            channel=self.channel,
            data=self.data,
            ok=self.ok,
            error=self.error,
            artifacts=self.artifacts,
        )


def agent_bridge_message(
    *,
    agent_id: str,
    session_id: str,
    task_id: str,
    channel: str,
    data: dict[str, Any],
    ok: bool = True,
    error: str | None = None,
    artifacts: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "parser_ref": AGENT_BRIDGE_PARSER_REF,
        "ok": ok,
        "data": {
            "agent_id": agent_id,
            "session_id": session_id,
            "task_id": task_id,
            **data,
        },
    }
    if error:
        payload["error"] = error
    return BridgeMessage(
        producer=f"agent:{agent_id}",
        channel=channel,
        correlation_id=f"{session_id}:{task_id}",
        payload=payload,
        artifacts=artifacts,
    ).as_dict()
