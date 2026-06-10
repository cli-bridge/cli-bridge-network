"""Built-in Adapter Agent role catalog.

The catalog keeps role boundaries data-driven so the coordinator can compose
manifest bootstrapping, workflow setup, operator guidance, and verification
without turning the Adapter Agent into one monolithic prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdapterAgentRole:
    role_id: str
    title: str
    purpose: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    denied_actions: tuple[str, ...]
    reference_basis: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "title": self.title,
            "purpose": self.purpose,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "allowed_actions": list(self.allowed_actions),
            "denied_actions": list(self.denied_actions),
            "reference_basis": list(self.reference_basis),
        }


ADAPTER_AGENT_ROLES: dict[str, AdapterAgentRole] = {
    "manifest-bootstrap-agent": AdapterAgentRole(
        role_id="manifest-bootstrap-agent",
        title="Manifest Bootstrap Agent",
        purpose=(
            "Compile CLI profile evidence, probe plans, parser fixture coverage, "
            "risk summaries, and adapter.lock previews into reviewable manifest drafts."
        ),
        inputs=(
            "built-in adapter profile",
            "accepted manifests",
            "parser fixtures",
            "profile probe definitions",
        ),
        outputs=(
            "AdapterAgentDraft",
            "ManifestBootstrapPlan",
            "adapter.lock preview",
        ),
        allowed_actions=(
            "read manifests",
            "plan probes without executing them",
            "validate manifest schemas",
            "summarize parser fixture coverage",
        ),
        denied_actions=(
            "install external tools",
            "run high-risk profile actions",
            "run workflow tasks",
            "write adapter.lock without explicit acceptance",
        ),
        reference_basis=(
            "Codex role registry keeps role policy separate from task text",
            "Claude Code built-in agents make tool boundaries explicit",
        ),
    ),
    "workflow-setup-agent": AdapterAgentRole(
        role_id="workflow-setup-agent",
        title="Workflow Setup Agent",
        purpose=(
            "Inspect a workflow graph against accepted manifests, then emit auth, "
            "secret, local service, and runtime-input gates before first execution."
        ),
        inputs=(
            "workflow graph",
            "accepted manifest registry",
            "setup guide registry",
        ),
        outputs=(
            "WorkflowSetupPlan",
            "WorkflowInitializationPlan compatibility payload",
            "setup guides",
            "resume command",
        ),
        allowed_actions=(
            "read workflow graph",
            "read accepted manifests",
            "classify setup gates",
            "build manual continuation plan",
        ),
        denied_actions=(
            "draft new manifests",
            "install providers",
            "collect secrets in chat",
            "run the workflow before setup gates are ready",
        ),
        reference_basis=(
            "Claude Code plan and verification agents are read-only by default",
            "Codex spawned workers inherit execution policy instead of resetting it",
        ),
    ),
    "orchestration-coordinator-agent": AdapterAgentRole(
        role_id="orchestration-coordinator-agent",
        title="Orchestration Coordinator Agent",
        purpose=(
            "Join manifest-bootstrap and workflow-setup outputs into an operator turn, "
            "including BridgeMessage routes, fallbacks, and the next safe action."
        ),
        inputs=(
            "ManifestBootstrapPlan summary",
            "WorkflowSetupPlan",
            "CLI route graph",
            "redacted user message",
        ),
        outputs=(
            "AdapterAgentCoordinationPlan",
            "AdapterAgentOrchestrationTurn",
            "operator-facing next action",
        ),
        allowed_actions=(
            "compose role handoffs",
            "redact secrets",
            "call optional guidance LLM with bounded context",
            "stage deterministic continuation commands",
        ),
        denied_actions=(
            "override policy decisions",
            "accept LLM output as execution authority",
            "echo secrets",
            "claim setup is ready without setup-plan evidence",
        ),
        reference_basis=(
            "Codex uses structured thread and turn lifecycle events",
            "Claude Code coordinates permissions through hooks before interaction",
        ),
    ),
    "verification-agent": AdapterAgentRole(
        role_id="verification-agent",
        title="Verification Agent",
        purpose=(
            "Run or plan deterministic checks after bootstrap/setup changes and return "
            "PASS, PARTIAL, or FAIL evidence without mutating project state by default."
        ),
        inputs=(
            "manifest validation summary",
            "parser fixture report",
            "workflow setup status",
            "audit expectations",
        ),
        outputs=(
            "verification checklist",
            "test command evidence",
            "remaining risk summary",
        ),
        allowed_actions=(
            "run read-only schema checks",
            "run parser fixtures",
            "run non-destructive workflow/setup tests",
            "report exact evidence",
        ),
        denied_actions=(
            "edit files",
            "install dependencies",
            "approve privileged actions",
            "mark blocked setup as ready",
        ),
        reference_basis=(
            "Claude Code verification agent requires command evidence",
            "Codex orchestrator centralizes approval and retry policy",
        ),
    ),
}


DEFAULT_AGENT_SEQUENCE = (
    "manifest-bootstrap-agent",
    "workflow-setup-agent",
    "orchestration-coordinator-agent",
    "verification-agent",
)


def get_agent_role(role_id: str) -> dict[str, Any]:
    return ADAPTER_AGENT_ROLES[role_id].as_dict()


def build_role_catalog() -> dict[str, Any]:
    return {
        "kind": "AdapterAgentRoleCatalog",
        "apiVersion": "bridge.dev/v1alpha1",
        "roles": [ADAPTER_AGENT_ROLES[role_id].as_dict() for role_id in DEFAULT_AGENT_SEQUENCE],
        "default_sequence": list(DEFAULT_AGENT_SEQUENCE),
    }
