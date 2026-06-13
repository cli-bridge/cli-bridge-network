"""Adapter Agent orchestration turns for the dashboard dialog."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_execution.graph import WorkflowGraph

from cbn_adapter_agent.coordinator import build_multi_agent_coordination_plan
from cbn_adapter_agent.llm_validation import complete_with_glm
from cbn_adapter_agent.workflow_init import build_workflow_initialization_plan


DEFAULT_WORKFLOW_PATH = "workflows/auth-gated-first-run.example.json"

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[-_ ]?key|token|secret|password)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"\b[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_.=-]{12,}\b"),
)


def build_orchestration_turn(
    *,
    message: str,
    workflow_path: str | Path | None = None,
    root: Path | None = None,
    use_glm: bool = True,
) -> dict[str, Any]:
    plan_context = build_orchestration_context(message=message, workflow_path=workflow_path, root=root)
    target = plan_context["workflow_path"]
    initialization = plan_context["workflow_initialization"]
    llm = orchestration_llm_turn(plan_context, use_glm)
    assistant = orchestration_assistant_message(plan_context, llm)
    return {
        "kind": "AdapterAgentOrchestrationTurn",
        "apiVersion": "bridge.dev/v1alpha1",
        "ok": initialization["ok"],
        "status": initialization["status"],
        "workflow_path": str(target),
        "message_redacted": plan_context["message_redacted"],
        "assistant_message": assistant["message"],
        "recommended_next_action": plan_context["recommended_next_action"],
        "coordination_plan": plan_context["coordination_plan"],
        "workflow_initialization": initialization,
        "cli_routes": plan_context["cli_routes"],
        "auth_fallbacks": plan_context["auth_fallbacks"],
        "continuation": initialization["continuation"],
        "glm_content_accepted": assistant["glm_content_accepted"],
        "glm": llm,
    }


def orchestration_llm_turn(plan_context: dict[str, Any], use_glm: bool) -> dict[str, Any]:
    if use_glm:
        return complete_with_glm(plan_context, system_prompt=ORCHESTRATION_SYSTEM_PROMPT)
    return {
        "kind": "AdapterAgentGLMTurn",
        "ok": False,
        "skipped": True,
        "reason": "GLM disabled by request",
    }


def orchestration_assistant_message(plan_context: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    llm_content = llm.get("content") if llm.get("ok") and llm.get("content") else ""
    accepted = llm_content_covers_fallbacks(str(llm_content), plan_context["auth_fallbacks"])
    return {
        "message": str(llm_content) if accepted else fallback_message(plan_context),
        "glm_content_accepted": accepted,
    }


def build_orchestration_context(
    *,
    message: str,
    workflow_path: str | Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    target = Path(workflow_path or DEFAULT_WORKFLOW_PATH)
    paths = resolve_project_paths(root)
    source_path = target if target.is_absolute() else paths.root / target
    initialization = build_workflow_initialization_plan(target, root=root)
    graph = WorkflowGraph.from_file(source_path)
    graph.validate()
    sanitized_message = _redact_secrets(message)
    coordination_plan = build_multi_agent_coordination_plan(
        message=sanitized_message,
        workflow_path=target,
        root=root,
        workflow_setup=initialization,
    )
    plan_context = {
        "kind": "AdapterAgentOrchestrationContext",
        "apiVersion": "bridge.dev/v1alpha1",
        "user_message": sanitized_message,
        "workflow_path": str(target),
        "message_redacted": sanitized_message != message,
        "workflow_initialization": initialization,
        "coordination_plan": coordination_plan,
        "cli_routes": _cli_routes(graph),
        "auth_fallbacks": _auth_fallbacks(initialization),
        "recommended_next_action": _recommended_next_action(initialization),
    }
    return plan_context


def _cli_routes(graph: WorkflowGraph) -> list[dict[str, Any]]:
    routes = []
    for task in graph.topological_order():
        routes.append(
            {
                "task_id": task.task_id,
                "uses": task.uses,
                "needs": list(task.needs),
                "args_from": [arg_from.as_dict() for arg_from in task.args_from],
                "communication": "BridgeMessage argsFrom" if task.args_from else "direct CLI invocation",
            }
        )
    return routes


def _auth_fallbacks(initialization: dict[str, Any]) -> list[dict[str, Any]]:
    fallbacks = []
    setup_by_id = {guide["setup_id"]: guide for guide in initialization.get("setup_guides", [])}
    for task in initialization.get("tasks", []):
        setup = setup_by_id.get(task.get("auth_setup_id"))
        missing = task.get("missing_runtime_inputs") or []
        if not setup and not missing:
            continue
        fallbacks.append(
            {
                "task_id": task["task_id"],
                "uses": task["uses"],
                "status": task["status"],
                "setup": setup,
                "missing_runtime_inputs": missing,
                "resume_command": initialization["continuation"]["command"],
            }
        )
    return fallbacks


def _recommended_next_action(initialization: dict[str, Any]) -> str:
    status = initialization["status"]
    if status == "ready":
        return "run_workflow"
    if status == "requires_runtime_inputs":
        return "collect_runtime_inputs"
    if status == "requires_user_setup":
        return "guide_user_setup"
    return "guide_user_setup_and_collect_inputs"


def fallback_message(context: dict[str, Any]) -> str:
    initialization = context["workflow_initialization"]
    lines = [
        f"Workflow {initialization['workflow']['workflow_id']} is {initialization['status']}.",
    ]
    if context["auth_fallbacks"]:
        lines.append("Complete the setup guides and missing runtime inputs before running the workflow.")
        for fallback in context["auth_fallbacks"]:
            setup = fallback.get("setup") or {}
            title = setup.get("title") or "runtime input"
            missing = ", ".join(item["name"] for item in fallback.get("missing_runtime_inputs", []))
            suffix = f"; missing {missing}" if missing else ""
            lines.append(f"- {fallback['task_id']} uses {fallback['uses']}: {title}{suffix}.")
    else:
        lines.append("No auth or API-key fallback is required; continue with the workflow run command.")
    lines.append("Resume command: " + " ".join(initialization["continuation"]["command"]))
    return "\n".join(lines)


def _redact_secrets(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(0).replace(match.group(2), "[REDACTED]") if match.lastindex else "[REDACTED]", redacted)
    return redacted


def llm_content_covers_fallbacks(content: str, fallbacks: list[dict[str, Any]]) -> bool:
    if not content:
        return False
    required_terms = fallback_required_terms(fallbacks)
    if not required_terms:
        return True
    lowered = content.casefold()
    return all(term in lowered for term in required_terms)


def fallback_required_terms(fallbacks: list[dict[str, Any]]) -> set[str]:
    required_terms: set[str] = set()
    for fallback in fallbacks:
        required_terms.update(fallback_setup_terms(fallback.get("setup") or {}))
    return required_terms


def fallback_setup_terms(setup: dict[str, Any]) -> set[str]:
    profile = str(setup.get("profile") or "").casefold()
    setup_id = str(setup.get("setup_id") or "").casefold()
    terms = {profile} if profile else set()
    if "obsidian" in setup_id:
        terms.add("obsidian")
    if "jimeng" in setup_id:
        terms.add("jimeng")
    return terms


ORCHESTRATION_SYSTEM_PROMPT = """
You are the built-in GLM orchestration brain for the CBN Adapter Agent coordinator.
Use the provided WorkflowInitializationPlan, AdapterAgentCoordinationPlan, and CLI routes as authoritative.
Respect the split between manifest-bootstrap-agent, workflow-setup-agent, orchestration-coordinator-agent, and verification-agent.
Guide the user through workflow orchestration, CLI-to-CLI BridgeMessage routing, and fallback.
If any task status requires setup, login, API key, authenticated session, or runtime input, do not tell the user to run the workflow yet.
Prefer tool-use affordances exposed by the CBN dashboard for starting login, storing session secrets, and running verification. When user action is unavoidable, ask only for the user to complete the OAuth UI or type the secret into the dashboard secret field.
Never ask the user to paste secrets into chat, never echo secrets, and never claim that a CLI is activated unless the plan says ready.
Return concise operator-facing text.
""".strip()
