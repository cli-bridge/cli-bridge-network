"""Adapter Agent tool-call and long-loop planning.

This module turns the reference lessons from Codex and Claude Code into a
deterministic CBN planning surface: every agent-facing tool call gets a stable
identifier, lifecycle stages, permission/hook boundaries, batching guidance, and
loop checkpoint expectations before anything is executed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_adapter_agent.workflow_setup import build_workflow_setup_plan


DEFAULT_TOOL_CALL_WORKFLOW_PATH = "workflows/auth-gated-first-run.example.json"

READ_ONLY_COMMAND_PREFIXES = (
    "verify-",
    "status",
    "doctor",
    "version",
    "help",
    "list",
    "query",
)


def build_agent_tool_call_plan(
    *,
    workflow_path: str | Path | None = None,
    message: str = "",
    root: Path | None = None,
    workflow_setup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = Path(workflow_path or DEFAULT_TOOL_CALL_WORKFLOW_PATH)
    setup_plan = workflow_setup or build_workflow_setup_plan(target, root=root)
    tool_calls = _setup_tool_calls(setup_plan) + _workflow_tool_calls(setup_plan)
    batches = partition_tool_calls(tool_calls)
    loop_plan = build_agent_loop_plan(
        workflow_setup=setup_plan,
        tool_calls=tool_calls,
        message_present=bool(message.strip()),
    )
    return {
        "kind": "AdapterAgentToolCallPlan",
        "apiVersion": "bridge.dev/v1alpha1",
        "ok": True,
        "workflow": setup_plan.get("workflow"),
        "workflow_path": str(target),
        "message_present": bool(message.strip()),
        "reference_basis": [
            {
                "source": "reference-learn/codex",
                "lesson": "centralize approval, sandbox, network approval, retry, telemetry, and lifecycle events around tool calls",
            },
            {
                "source": "reference-learn/claude-code-v-2.1.88",
                "lesson": "batch only concurrency-safe tool calls, race permission hooks with prompts, and dedupe resolved tool_use ids",
            },
            {
                "source": "reference-learn/codex",
                "lesson": "separate session-scoped state from turn-scoped state and checkpoint long loops before compaction or continuation",
            },
        ],
        "tool_call_policy": _tool_call_policy(),
        "lifecycle_events": _lifecycle_events(),
        "hook_points": _hook_points(),
        "duplicate_guard": {
            "tracks": "tool_use_id",
            "window": 1000,
            "behavior": "ignore duplicate completion/control responses after the first terminal result",
        },
        "tool_calls": tool_calls,
        "execution_batches": batches,
        "summary": summarize_tool_call_plan({"tool_calls": tool_calls, "execution_batches": batches}),
        "long_running_loop": loop_plan,
    }


def summarize_tool_call_plan(plan: dict[str, Any]) -> dict[str, Any]:
    tool_calls = plan.get("tool_calls", [])
    batches = plan.get("execution_batches", [])
    statuses: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for call in tool_calls:
        statuses[str(call.get("initial_status"))] = statuses.get(str(call.get("initial_status")), 0) + 1
        kinds[str(call.get("kind"))] = kinds.get(str(call.get("kind")), 0) + 1
    return {
        "tool_call_count": len(tool_calls),
        "batch_count": len(batches),
        "concurrency_safe_count": sum(1 for call in tool_calls if call.get("concurrency_safe")),
        "serial_count": sum(1 for call in tool_calls if not call.get("concurrency_safe")),
        "requires_user_count": sum(1 for call in tool_calls if call.get("requires_user")),
        "by_initial_status": statuses,
        "by_kind": kinds,
    }


def partition_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Partition calls like Claude Code: safe consecutive calls batch, unsafe calls serialize."""

    batches: list[dict[str, Any]] = []
    for call in tool_calls:
        is_safe = bool(call.get("concurrency_safe"))
        if is_safe and batches and batches[-1]["concurrency_safe"]:
            batches[-1]["tool_call_ids"].append(call["call_id"])
            batches[-1]["tool_use_ids"].append(call["tool_use_id"])
            continue
        batches.append(
            {
                "batch_id": f"batch-{len(batches) + 1}",
                "mode": "parallel" if is_safe else "serial",
                "concurrency_safe": is_safe,
                "tool_call_ids": [call["call_id"]],
                "tool_use_ids": [call["tool_use_id"]],
                "reason": "read-only or verification call" if is_safe else "mutating, user-gated, or workflow-ordered call",
            }
        )
    return batches


def build_agent_loop_plan(
    *,
    workflow_setup: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    message_present: bool,
) -> dict[str, Any]:
    loop_id = _stable_id(
        "adapter-loop",
        workflow_setup.get("workflow", {}).get("workflow_id"),
        workflow_setup.get("status"),
        len(tool_calls),
    )
    return {
        "kind": "AdapterAgentLoopPlan",
        "loop_id": loop_id,
        "status": "waiting_on_setup" if not workflow_setup.get("ok") else "ready_to_run",
        "message_present": message_present,
        "session_scoped_state": {
            "workflow_id": workflow_setup.get("workflow", {}).get("workflow_id"),
            "agent_roles": [
                "manifest-bootstrap-agent",
                "workflow-setup-agent",
                "orchestration-coordinator-agent",
                "verification-agent",
            ],
            "resolved_tool_use_id_window": 1000,
            "transport_fallback_state": "session-scoped",
            "approval_state": "must persist across setup resume and workflow retry",
        },
        "turn_scoped_state": {
            "redacted_user_message": "turn-scoped",
            "tool_call_batches": "turn-scoped",
            "hook_results": "turn-scoped unless persisted by policy",
            "permission_prompt_state": "turn-scoped",
        },
        "checkpoints": _loop_checkpoints(workflow_setup, tool_calls),
        "continuation_policy": {
            "resume_modes": [
                "manual_resume_after_setup",
                "rerun_after_approval",
                "rerun_after_fix",
                "ready_to_run",
            ],
            "stall_detection": "record same blocking reason across turns before declaring blocked",
            "completion_gate": "run verification-agent checklist and inspect current evidence before marking complete",
        },
        "compaction_policy": {
            "trigger": [
                "large orchestration context",
                "long setup session",
                "multiple failed retries with repeated evidence",
            ],
            "must_preserve": [
                "workflow path and workflow id",
                "agent role sequence",
                "pending setup guides",
                "pending tool_use ids",
                "approval and permission state",
                "last checkpoint and next action",
            ],
        },
    }


def write_agent_loop_checkpoint(
    plan: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, str]:
    paths = resolve_project_paths(root)
    loop_plan = plan.get("long_running_loop") if plan.get("kind") == "AdapterAgentToolCallPlan" else plan
    loop_id = str(loop_plan["loop_id"])
    target_dir = paths.runtime / "adapter-agent" / "loops"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{loop_id}.json"
    path.write_text(json.dumps(loop_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"loop_id": loop_id, "path": str(path)}


def _setup_tool_calls(setup_plan: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for guide in setup_plan.get("setup_guides", []):
        setup_id = str(guide.get("setup_id"))
        profile = str(guide.get("profile") or "unknown")
        for secret in guide.get("secret_inputs", []):
            name = str(secret.get("name"))
            calls.append(
                _tool_call(
                    kind="setup-secret",
                    agent_role="workflow-setup-agent",
                    tool="AdapterAgentToolUse.store-secret",
                    source={"setup_id": setup_id, "profile": profile, "secret_name": name},
                    action="store-secret",
                    risk="write-workspace",
                    initial_status="waiting_user_secret",
                    requires_user=True,
                    concurrency_safe=False,
                    argv=[],
                    permission_reason="secret value must come through dashboard secret field or secret store, never chat",
                )
            )
        for command in guide.get("verification_commands", []):
            command_id = str(command.get("id"))
            is_start = command_id in {"login", "login-headless"}
            is_safe = _is_read_only_command(command_id)
            calls.append(
                _tool_call(
                    kind="setup-command",
                    agent_role="workflow-setup-agent",
                    tool="AdapterAgentToolUse.run-setup-tool",
                    source={"setup_id": setup_id, "profile": profile, "command_id": command_id},
                    action=command_id,
                    risk="external-network" if is_start else "read",
                    initial_status="waiting_user_action" if is_start else "queued",
                    requires_user=is_start,
                    concurrency_safe=is_safe and not is_start,
                    argv=[str(part) for part in command.get("argv", [])],
                    permission_reason=(
                        "interactive login starts a user-controlled external auth flow"
                        if is_start
                        else "verification command is read-only and can run after setup inputs exist"
                    ),
                )
            )
    return calls


def _workflow_tool_calls(setup_plan: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for task in setup_plan.get("tasks", []):
        task_id = str(task.get("task_id"))
        status = str(task.get("status"))
        risk = str(task.get("risk") or "read")
        calls.append(
            _tool_call(
                kind="workflow-capability",
                agent_role="orchestration-coordinator-agent",
                tool="cbn.workflow.task",
                source={"task_id": task_id, "capability_id": task.get("uses")},
                action=str(task.get("uses")),
                risk=risk,
                initial_status="blocked_by_setup" if status != "ready" else "queued",
                requires_user=bool(task.get("requires_confirmation")) or status != "ready",
                concurrency_safe=False,
                argv=[],
                permission_reason=(
                    "workflow task waits for setup/runtime inputs before execution"
                    if status != "ready"
                    else "workflow DAG order is authoritative; run through WorkflowRunner"
                ),
            )
        )
    return calls


def _tool_call(
    *,
    kind: str,
    agent_role: str,
    tool: str,
    source: dict[str, Any],
    action: str,
    risk: str,
    initial_status: str,
    requires_user: bool,
    concurrency_safe: bool,
    argv: list[str],
    permission_reason: str,
) -> dict[str, Any]:
    call_id = _stable_id(kind, agent_role, tool, action, json.dumps(source, ensure_ascii=False, sort_keys=True))
    tool_use_id = f"{agent_role}:{call_id}"
    return {
        "call_id": call_id,
        "tool_use_id": tool_use_id,
        "kind": kind,
        "agent_role": agent_role,
        "tool": tool,
        "source": source,
        "action": action,
        "argv": argv,
        "risk": risk,
        "initial_status": initial_status,
        "requires_user": requires_user,
        "concurrency_safe": concurrency_safe,
        "permission_flow": _permission_flow(risk=risk, requires_user=requires_user, reason=permission_reason),
        "lifecycle": _lifecycle_events(),
        "hook_points": _hook_points(),
    }


def _permission_flow(*, risk: str, requires_user: bool, reason: str) -> dict[str, Any]:
    behavior = "ask" if requires_user or risk in {"write-workspace", "privileged", "external-network"} else "allow"
    return {
        "default_behavior": behavior,
        "reason": reason,
        "order": [
            "pre_tool_use_hooks",
            "rule_based_policy",
            "permission_request_hooks",
            "operator_prompt_if_required",
            "audit_and_event_emit",
        ],
        "invariants": [
            "deny rules override hook allow",
            "hook allow may update input but must not bypass explicit ask/deny policy",
            "external-network and privileged calls require explicit confirmation",
        ],
    }


def _tool_call_policy() -> dict[str, Any]:
    return {
        "approval_order": [
            "pre_tool_use_hooks",
            "policy_engine",
            "permission_request_hooks",
            "human_or_dashboard_prompt",
            "execution",
            "post_tool_use_hooks",
            "audit_event",
        ],
        "batching": "only consecutive concurrency_safe calls may run in the same parallel batch",
        "retry": "retry requires new evidence or explicit approval; sandbox/network denial must keep original output summary",
        "secret_handling": "secrets are never accepted in chat and never echoed in results",
        "output_pairing": "every tool_call needs exactly one terminal output event keyed by tool_use_id",
    }


def _lifecycle_events() -> list[str]:
    return [
        "queued",
        "pre_tool_use",
        "permission_evaluated",
        "approval_requested",
        "started",
        "progress",
        "post_tool_use",
        "completed",
        "failed",
        "cancelled",
    ]


def _hook_points() -> list[dict[str, Any]]:
    return [
        {"event": "PreToolUse", "can_update_input": True, "can_block": True},
        {"event": "PermissionRequest", "can_allow": True, "can_deny": True},
        {"event": "PostToolUse", "can_add_context": True, "can_update_mcp_output": True},
        {"event": "PostToolUseFailure", "can_add_context": True, "can_request_retry": True},
        {"event": "PermissionDenied", "can_request_retry": True},
    ]


def _loop_checkpoints(workflow_setup: dict[str, Any], tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": "role-catalog-loaded",
            "owner": "orchestration-coordinator-agent",
            "status": "complete",
            "evidence": "agent role sequence is present in coordination plan",
        },
        {
            "id": "workflow-setup-built",
            "owner": "workflow-setup-agent",
            "status": "complete",
            "evidence": workflow_setup.get("status"),
        },
        {
            "id": "tool-call-plan-built",
            "owner": "orchestration-coordinator-agent",
            "status": "complete" if tool_calls else "empty",
            "evidence": {"tool_call_count": len(tool_calls)},
        },
        {
            "id": "setup-execution",
            "owner": "workflow-setup-agent",
            "status": "pending" if not workflow_setup.get("ok") else "skipped",
            "evidence": "setup_guides must be completed before workflow execution",
        },
        {
            "id": "verification",
            "owner": "verification-agent",
            "status": "pending",
            "evidence": "run schema/parser/setup/orchestration checks before completion",
        },
        {
            "id": "completion-audit",
            "owner": "verification-agent",
            "status": "pending",
            "evidence": "inspect current-state evidence requirement by requirement",
        },
    ]


def _is_read_only_command(command_id: str) -> bool:
    lowered = command_id.casefold()
    return lowered.startswith(READ_ONLY_COMMAND_PREFIXES) or lowered in {"verify-user-credit"}


def _stable_id(*parts: object) -> str:
    text = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
