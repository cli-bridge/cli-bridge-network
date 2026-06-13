"""Multi-agent coordination plan for the built-in Adapter Agent harness."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbn_adapter_agent.agent_roles import DEFAULT_AGENT_SEQUENCE, get_agent_role
from cbn_adapter_agent.compiler import BUILT_IN_PROFILES
from cbn_adapter_agent.manifest_bootstrap import build_manifest_bootstrap_plan
from cbn_adapter_agent.tool_call_plan import build_agent_tool_call_plan, summarize_tool_call_plan
from cbn_adapter_agent.workflow_setup import build_workflow_setup_plan


def build_multi_agent_coordination_plan(
    *,
    message: str = "",
    workflow_path: str | Path | None = None,
    profiles: tuple[str, ...] | None = None,
    root: Path | None = None,
    workflow_setup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose manifest bootstrap, workflow setup, orchestration, and verification roles."""

    target = Path(workflow_path) if workflow_path is not None else Path("workflows/auth-gated-first-run.example.json")
    setup_plan = _setup_plan(target, root, workflow_setup)
    profile_scope = _profile_scope(profiles, setup_plan)
    manifest_plan = _manifest_plan(profile_scope, root)
    tool_call_plan = _tool_call_plan(
        message=message,
        target=target,
        root=root,
        workflow_setup=setup_plan,
    )
    agents = _agent_steps(manifest_plan=manifest_plan, workflow_setup=setup_plan)
    return {
        "kind": "AdapterAgentCoordinationPlan",
        "apiVersion": "bridge.dev/v1alpha1",
        "ok": bool(manifest_plan.get("ok")) and bool(setup_plan.get("ok")),
        "status": setup_plan.get("status"),
        "workflow_path": str(target),
        "message_present": bool(message.strip()),
        "profile_scope": list(profile_scope),
        "agents": agents,
        "handoffs": _handoffs(setup_plan),
        "tool_call_plan_summary": summarize_tool_call_plan(tool_call_plan),
        "long_running_loop": tool_call_plan["long_running_loop"],
        "parallelization": _parallelization(),
        "reference_learnings": _reference_learnings(),
        "next_actions": _next_actions(manifest_plan, setup_plan),
    }


def _setup_plan(
    target: Path,
    root: Path | None,
    workflow_setup: dict[str, Any] | None,
) -> dict[str, Any]:
    return workflow_setup or build_workflow_setup_plan(target, root=root)


def _profile_scope(profiles: tuple[str, ...] | None, setup_plan: dict[str, Any]) -> tuple[str, ...]:
    return profiles or _profiles_from_workflow_setup(setup_plan) or tuple(BUILT_IN_PROFILES)


def _manifest_plan(profile_scope: tuple[str, ...], root: Path | None) -> dict[str, Any]:
    return build_manifest_bootstrap_plan(
        profiles=profile_scope,
        root=root,
        include_drafts=False,
    )


def _tool_call_plan(
    *,
    message: str,
    target: Path,
    root: Path | None,
    workflow_setup: dict[str, Any],
) -> dict[str, Any]:
    return build_agent_tool_call_plan(
        message=message,
        workflow_path=target,
        root=root,
        workflow_setup=workflow_setup,
    )


def _parallelization() -> list[dict[str, Any]]:
    return [
        {
            "group_id": "read-only-bootstrap",
            "agents": ["manifest-bootstrap-agent"],
            "mode": "parallel-safe-by-profile",
            "reason": "profile evidence, schema validation, and fixture summaries are read-only",
        },
        {
            "group_id": "setup-and-routing",
            "agents": ["workflow-setup-agent", "orchestration-coordinator-agent"],
            "mode": "serial-after-manifest-acceptance",
            "reason": "workflow setup depends on accepted manifests and coordinator depends on setup status",
        },
        {
            "group_id": "verification",
            "agents": ["verification-agent"],
            "mode": "read-only-after-plan",
            "reason": "verification reports evidence and must not mark blocked setup as ready",
        },
    ]


def _reference_learnings() -> list[dict[str, str]]:
    return [
        {
            "source": "reference-learn/codex",
            "applied_as": "role catalog, explicit agent sequence, inherited policy boundary, structured lifecycle payloads",
        },
        {
            "source": "reference-learn/claude-code-v-2.1.88",
            "applied_as": "tool-bounded built-in agents, read-only setup/planning roles, verification evidence contract",
        },
    ]


def _agent_steps(
    *,
    manifest_plan: dict[str, Any],
    workflow_setup: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _manifest_bootstrap_step(manifest_plan),
        _workflow_setup_step(workflow_setup),
        _orchestration_step(workflow_setup),
        _verification_step(),
    ]


def _manifest_bootstrap_step(manifest_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        **get_agent_role("manifest-bootstrap-agent"),
        "sequence": DEFAULT_AGENT_SEQUENCE.index("manifest-bootstrap-agent") + 1,
        "status": "ready" if manifest_plan.get("ok") else "needs_manifest_attention",
        "output_kind": "ManifestBootstrapPlan",
        "summary": manifest_plan.get("summary"),
    }


def _workflow_setup_step(workflow_setup: dict[str, Any]) -> dict[str, Any]:
    return {
        **get_agent_role("workflow-setup-agent"),
        "sequence": DEFAULT_AGENT_SEQUENCE.index("workflow-setup-agent") + 1,
        "status": workflow_setup.get("status"),
        "output_kind": workflow_setup.get("kind"),
        "summary": workflow_setup.get("summary"),
    }


def _orchestration_step(workflow_setup: dict[str, Any]) -> dict[str, Any]:
    summary = workflow_setup.get("summary") or {}
    return {
        **get_agent_role("orchestration-coordinator-agent"),
        "sequence": DEFAULT_AGENT_SEQUENCE.index("orchestration-coordinator-agent") + 1,
        "status": _coordinator_status(workflow_setup),
        "output_kind": "AdapterAgentOrchestrationTurn",
        "summary": {
            "recommended_next_action": _recommended_next_action(workflow_setup),
            "setup_blocking": bool(summary.get("blocking_task_count")),
            "input_blocking": bool(summary.get("input_blocking_task_count")),
        },
    }


def _verification_step() -> dict[str, Any]:
    return {
        **get_agent_role("verification-agent"),
        "sequence": DEFAULT_AGENT_SEQUENCE.index("verification-agent") + 1,
        "status": "pending",
        "output_kind": "VerificationChecklist",
        "summary": {
            "checks": [
                "manifest schema validation",
                "parser fixture coverage",
                "workflow setup gates",
                "orchestration redaction and fallback coverage",
            ]
        },
    }


def _handoffs(workflow_setup: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "from": "manifest-bootstrap-agent",
            "to": "workflow-setup-agent",
            "artifact": "accepted CapabilityManifest registry",
            "gate": "human acceptance before adapter.lock promotion",
        },
        {
            "from": "workflow-setup-agent",
            "to": "orchestration-coordinator-agent",
            "artifact": workflow_setup.get("kind"),
            "gate": "setup_guides and missing_runtime_inputs must be visible before workflow run",
        },
        {
            "from": "orchestration-coordinator-agent",
            "to": "verification-agent",
            "artifact": "AdapterAgentOrchestrationTurn",
            "gate": "verify redaction, route rendering, and continuation command",
        },
    ]


def _profiles_from_workflow_setup(plan: dict[str, Any]) -> tuple[str, ...]:
    profile_ids: list[str] = []
    for task in plan.get("tasks", []):
        uses = str(task.get("uses") or "")
        profile_id = uses.split(".", 1)[0]
        if profile_id in BUILT_IN_PROFILES and profile_id not in profile_ids:
            profile_ids.append(profile_id)
    return tuple(profile_ids)


def _coordinator_status(workflow_setup: dict[str, Any]) -> str:
    status = str(workflow_setup.get("status") or "")
    if status == "ready":
        return "ready_to_stage_run"
    return "guide_operator_before_run"


def _recommended_next_action(workflow_setup: dict[str, Any]) -> str:
    status = workflow_setup.get("status")
    if status == "ready":
        return "run_workflow"
    if status == "requires_runtime_inputs":
        return "collect_runtime_inputs"
    if status == "requires_user_setup":
        return "guide_user_setup"
    return "guide_user_setup_and_collect_inputs"


def _next_actions(manifest_plan: dict[str, Any], workflow_setup: dict[str, Any]) -> list[str]:
    actions = []
    if manifest_plan.get("next_actions"):
        actions.extend(str(action) for action in manifest_plan["next_actions"])
    setup_summary = workflow_setup.get("summary") or {}
    if setup_summary.get("blocking_task_count") or setup_summary.get("input_blocking_task_count"):
        actions.append("complete workflow setup guides and missing runtime inputs before workflow execution")
    else:
        actions.append("stage workflow run command through orchestration-coordinator-agent")
    actions.append("run verification-agent checks before promoting the split as stable")
    return actions
