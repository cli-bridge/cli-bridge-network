"""Optional OpenAI-compatible LLM validation for Adapter Agent drafts."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
DEFAULT_MODEL = "GLM-5.1"
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
ZAI_ENV_FILE_VAR = "CBN_ZAI_ENV_FILE"
ZAI_LOAD_ENV_VAR = "CBN_ZAI_LOAD_ENV"


@dataclass(frozen=True)
class GlmConfig:
    key: str | None
    endpoint: str
    model: str


def validate_with_glm(
    payload: dict[str, Any],
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    config = _glm_config(base_url=base_url, model=model, api_key=api_key)
    if not config.key:
        return _missing_key_result("AdapterAgentLLMValidation")
    request_payload = _chat_payload(
        config.model,
        (
            "You validate CBN Adapter Agent drafts. Return compact JSON with keys "
            "ok, risks, missing_setup_guides, parser_contract_gaps, recommendation. "
            "Do not include secrets."
        ),
        json.dumps(_bounded_payload(payload), ensure_ascii=False),
    )
    parsed = _request_json("AdapterAgentLLMValidation", config, request_payload, timeout_seconds)
    if _is_llm_error_result(parsed, "AdapterAgentLLMValidation"):
        return parsed
    content = _message_content(parsed)
    return {
        "kind": "AdapterAgentLLMValidation",
        "ok": True,
        "skipped": False,
        "endpoint": config.endpoint,
        "model": config.model,
        "content": content,
        "raw_response": parsed,
    }


def complete_with_glm(
    payload: dict[str, Any],
    *,
    system_prompt: str,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    config = _glm_config(base_url=base_url, model=model, api_key=api_key)
    if not config.key:
        return _missing_key_result("AdapterAgentGLMTurn", config)
    request_payload = _chat_payload(
        config.model,
        system_prompt,
        json.dumps(_bounded_payload(payload), ensure_ascii=False),
    )
    parsed = _request_json("AdapterAgentGLMTurn", config, request_payload, timeout_seconds)
    if _is_llm_error_result(parsed, "AdapterAgentGLMTurn"):
        return parsed
    return {
        "kind": "AdapterAgentGLMTurn",
        "ok": True,
        "skipped": False,
        "endpoint": config.endpoint,
        "model": config.model,
        "content": _message_content(parsed),
        "raw_response": parsed,
    }


def stream_with_glm(
    payload: dict[str, Any],
    *,
    system_prompt: str,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int = 60,
) -> Iterator[dict[str, Any]]:
    config = _glm_config(base_url=base_url, model=model, api_key=api_key)
    if not config.key:
        yield {"type": "error", **_missing_key_result("AdapterAgentGLMStream", config)}
        return
    request_payload = {
        **_chat_payload(
            config.model,
            system_prompt,
            json.dumps(_bounded_payload(payload), ensure_ascii=False),
        ),
        "stream": True,
    }
    request = _chat_request(config.endpoint, config.key, request_payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            yield from _stream_response_events(response, config)
    except urllib.error.HTTPError as exc:
        yield {"type": "error", **_http_error_result("AdapterAgentGLMStream", config, exc)}
    except OSError as exc:
        yield {"type": "error", **_request_error_result("AdapterAgentGLMStream", config, exc)}


def _glm_config(*, base_url: str | None, model: str | None, api_key: str | None) -> GlmConfig:
    env = _zai_env()
    return GlmConfig(
        key=api_key or env.get("ZAI_API_KEY"),
        endpoint=_chat_endpoint(base_url or env.get("ZAI_BASE_URL") or DEFAULT_BASE_URL),
        model=model or env.get("ZAI_MODEL") or DEFAULT_MODEL,
    )


def _zai_env() -> dict[str, str]:
    values = _dotenv_values()
    values.update(os.environ)
    return values


def _dotenv_values() -> dict[str, str]:
    if _env_disabled(os.environ.get(ZAI_LOAD_ENV_VAR)):
        return {}
    env_path = Path(os.environ.get(ZAI_ENV_FILE_VAR) or DEFAULT_ENV_PATH)
    if not env_path.exists() or not env_path.is_file():
        return {}
    return _parse_dotenv(env_path.read_text(encoding="utf-8"))


def _env_disabled(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"0", "false", "no", "off"}


def _parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name:
            continue
        values[name] = _dotenv_value(value)
    return values


def _dotenv_value(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped


def _missing_key_result(kind: str, config: GlmConfig | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": kind,
        "ok": False,
        "skipped": True,
        "reason": "ZAI_API_KEY is not set",
    }
    if config is not None:
        result.update({"endpoint": config.endpoint, "model": config.model})
    return result


def _request_json(
    kind: str,
    config: GlmConfig,
    request_payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    request = _chat_request(config.endpoint, config.key or "", request_payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return _http_error_result(kind, config, exc)
    except OSError as exc:
        return _request_error_result(kind, config, exc)
    return json.loads(raw)


def _is_llm_error_result(result: dict[str, Any], kind: str) -> bool:
    return result.get("kind") == kind and result.get("ok") is False


def _http_error_result(kind: str, config: GlmConfig, exc: urllib.error.HTTPError) -> dict[str, Any]:
    body = exc.read().decode("utf-8", errors="replace")
    return {
        "kind": kind,
        "ok": False,
        "skipped": False,
        "endpoint": config.endpoint,
        "model": config.model,
        "error_type": "http_error",
        "status": exc.code,
        "body_summary": body[:1000],
    }


def _request_error_result(kind: str, config: GlmConfig, exc: OSError) -> dict[str, Any]:
    return {
        "kind": kind,
        "ok": False,
        "skipped": False,
        "endpoint": config.endpoint,
        "model": config.model,
        "error_type": "request_error",
        "error": str(exc),
    }


def _stream_response_events(response: Any, config: GlmConfig) -> Iterator[dict[str, Any]]:
    content_type = response.headers.get("Content-Type", "")
    if "text/event-stream" not in content_type and "stream" not in content_type:
        yield from _single_response_events(response, config)
        return
    for event in _sse_json_events(response):
        delta = _stream_delta_content(event)
        if delta:
            yield {"type": "delta", "text": delta}
    yield {"type": "done", "model": config.model, "endpoint": config.endpoint}


def _single_response_events(response: Any, config: GlmConfig) -> Iterator[dict[str, Any]]:
    raw = response.read().decode("utf-8", errors="replace")
    content = _message_content(json.loads(raw))
    if content:
        yield {"type": "delta", "text": content}
    yield {"type": "done", "model": config.model, "endpoint": config.endpoint}


def _sse_json_events(response: Any) -> Iterator[dict[str, Any]]:
    for raw_line in response:
        line = _sse_data_line(raw_line.decode("utf-8", errors="replace"))
        if line is None:
            continue
        if line == "[DONE]":
            return
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _sse_data_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return None
    if stripped.startswith("data:"):
        stripped = stripped.removeprefix("data:").strip()
    return stripped


def _chat_payload(model_name: str, system_prompt: str, user_content: str) -> dict[str, Any]:
    return {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
    }


def _chat_request(endpoint: str, key: str, request_payload: dict[str, Any]) -> urllib.request.Request:
    return urllib.request.Request(
        endpoint,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )


def _chat_endpoint(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def _message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _stream_delta_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= 12000:
        return payload
    kind = payload.get("kind")
    if kind == "AdapterAgentDraftBatch":
        return _bounded_adapter_draft_batch(payload)
    if kind == "AdapterAgentDraft":
        return _bounded_adapter_draft(payload)
    if kind == "AdapterAgentOrchestrationContext":
        return _bounded_orchestration_context(payload)
    if kind == "AdapterAgentOrchestrationTurn":
        return _bounded_orchestration_turn(payload)
    return _bounded_workflow_initialization(payload)


def _bounded_adapter_draft_batch(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": payload.get("kind"),
        "apiVersion": payload.get("apiVersion"),
        "summary": payload.get("summary"),
        "drafts": [_compact_adapter_draft(draft) for draft in payload.get("drafts", [])],
        "truncated": True,
        "truncation_strategy": "adapter-draft-summary",
    }


def _bounded_adapter_draft(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **_compact_adapter_draft(payload),
        "truncated": True,
        "truncation_strategy": "adapter-draft-summary",
    }


def _bounded_orchestration_context(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": payload.get("kind"),
        "apiVersion": payload.get("apiVersion"),
        "user_message": payload.get("user_message"),
        "workflow_initialization": _compact_workflow_initialization(
            payload.get("workflow_initialization") or {}
        ),
        "coordination_plan": _compact_coordination_plan(payload.get("coordination_plan") or {}),
        "cli_routes": payload.get("cli_routes", [])[:20],
        "auth_fallbacks": _compact_auth_fallbacks(payload.get("auth_fallbacks", [])),
        "recommended_next_action": payload.get("recommended_next_action"),
        "truncated": True,
        "truncation_strategy": "adapter-orchestration-context",
    }


def _bounded_orchestration_turn(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": payload.get("kind"),
        "apiVersion": payload.get("apiVersion"),
        "ok": payload.get("ok"),
        "status": payload.get("status"),
        "workflow_path": payload.get("workflow_path"),
        "recommended_next_action": payload.get("recommended_next_action"),
        "workflow_initialization": _compact_workflow_initialization(
            payload.get("workflow_initialization") or {}
        ),
        "coordination_plan": _compact_coordination_plan(payload.get("coordination_plan") or {}),
        "cli_routes": payload.get("cli_routes", [])[:20],
        "auth_fallbacks": _compact_auth_fallbacks(payload.get("auth_fallbacks", [])),
        "continuation": payload.get("continuation"),
        "truncated": True,
        "truncation_strategy": "adapter-orchestration-turn",
    }


def _bounded_workflow_initialization(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": payload.get("kind"),
        "apiVersion": payload.get("apiVersion"),
        "summary": payload.get("summary"),
        "status": payload.get("status"),
        "workflow": payload.get("workflow"),
        "tasks": payload.get("tasks", [])[:20],
        "setup_guides": payload.get("setup_guides", [])[:10],
        "truncated": True,
        "truncation_strategy": "workflow-init-summary",
    }


def _compact_adapter_draft(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": draft.get("kind"),
        "apiVersion": draft.get("apiVersion"),
        "ok": draft.get("ok"),
        "agent_role": _compact_agent_role(draft.get("agent_role")),
        "profile": draft.get("profile"),
        "agent_policy": draft.get("agent_policy"),
        "risk_summary": draft.get("risk_summary"),
        "setup_guides": draft.get("setup_guides"),
        "manifest_validation": draft.get("manifest_validation"),
        "stages": [
            {
                "id": stage.get("id"),
                "status": stage.get("status"),
                "evidence": stage.get("evidence"),
            }
            for stage in draft.get("stages", [])
        ],
        "capability_candidates": [
            {
                "capability_id": candidate.get("capability_id"),
                "adapter_action": candidate.get("adapter_action"),
                "policy": candidate.get("policy"),
                "output": candidate.get("output"),
                "auth_gate": candidate.get("auth_gate"),
                "workflow_hint": candidate.get("workflow_hint"),
            }
            for candidate in draft.get("capability_candidates", [])
        ],
        "adapter_lock_preview": {
            "profile_id": (draft.get("adapter_lock_preview") or {}).get("profile_id"),
            "capability_count": (draft.get("adapter_lock_preview") or {}).get("capability_count"),
            "digest": (draft.get("adapter_lock_preview") or {}).get("digest"),
        },
        "next_actions": draft.get("next_actions"),
    }


def _compact_workflow_initialization(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": plan.get("kind"),
        "apiVersion": plan.get("apiVersion"),
        "ok": plan.get("ok"),
        "status": plan.get("status"),
        "workflow": plan.get("workflow"),
        "summary": plan.get("summary"),
        "tasks": [
            {
                "task_id": task.get("task_id"),
                "uses": task.get("uses"),
                "title": task.get("title"),
                "risk": task.get("risk"),
                "network": task.get("network"),
                "requires_confirmation": task.get("requires_confirmation"),
                "auth_setup_required": task.get("auth_setup_required"),
                "auth_setup_id": task.get("auth_setup_id"),
                "auth_gate": task.get("auth_gate"),
                "missing_runtime_inputs": task.get("missing_runtime_inputs"),
                "status": task.get("status"),
            }
            for task in plan.get("tasks", [])[:20]
        ],
        "setup_guides": [
            {
                "setup_id": guide.get("setup_id"),
                "profile": guide.get("profile"),
                "title": guide.get("title"),
                "status": guide.get("status"),
                "reason": guide.get("reason"),
                "secret_inputs": guide.get("secret_inputs"),
                "user_steps": guide.get("user_steps"),
                "verification_commands": guide.get("verification_commands"),
                "resume_hint": guide.get("resume_hint"),
            }
            for guide in plan.get("setup_guides", [])[:10]
        ],
        "continuation": plan.get("continuation"),
    }


def _compact_coordination_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": plan.get("kind"),
        "apiVersion": plan.get("apiVersion"),
        "ok": plan.get("ok"),
        "status": plan.get("status"),
        "workflow_path": plan.get("workflow_path"),
        "profile_scope": plan.get("profile_scope"),
        "agents": [
            {
                "role_id": agent.get("role_id"),
                "title": agent.get("title"),
                "sequence": agent.get("sequence"),
                "status": agent.get("status"),
                "output_kind": agent.get("output_kind"),
                "summary": agent.get("summary"),
            }
            for agent in plan.get("agents", [])[:8]
        ],
        "handoffs": plan.get("handoffs", [])[:8],
        "tool_call_plan_summary": plan.get("tool_call_plan_summary"),
        "long_running_loop": _compact_loop_plan(plan.get("long_running_loop") or {}),
        "parallelization": plan.get("parallelization", [])[:8],
        "next_actions": plan.get("next_actions", [])[:12],
    }


def _compact_loop_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": plan.get("kind"),
        "loop_id": plan.get("loop_id"),
        "status": plan.get("status"),
        "checkpoints": [
            {
                "id": checkpoint.get("id"),
                "owner": checkpoint.get("owner"),
                "status": checkpoint.get("status"),
                "evidence": checkpoint.get("evidence"),
            }
            for checkpoint in plan.get("checkpoints", [])[:8]
        ],
        "continuation_policy": plan.get("continuation_policy"),
        "compaction_policy": plan.get("compaction_policy"),
    }


def _compact_agent_role(role: object) -> dict[str, Any] | None:
    if not isinstance(role, dict):
        return None
    return {
        "role_id": role.get("role_id"),
        "title": role.get("title"),
        "purpose": role.get("purpose"),
        "allowed_actions": role.get("allowed_actions"),
        "denied_actions": role.get("denied_actions"),
    }


def _compact_auth_fallbacks(fallbacks: list[Any]) -> list[dict[str, Any]]:
    compact = []
    for fallback in fallbacks[:20]:
        setup = fallback.get("setup") if isinstance(fallback, dict) else None
        compact.append(
            {
                "task_id": fallback.get("task_id") if isinstance(fallback, dict) else None,
                "uses": fallback.get("uses") if isinstance(fallback, dict) else None,
                "status": fallback.get("status") if isinstance(fallback, dict) else None,
                "setup": {
                    "setup_id": setup.get("setup_id"),
                    "profile": setup.get("profile"),
                    "title": setup.get("title"),
                    "status": setup.get("status"),
                    "reason": setup.get("reason"),
                    "secret_inputs": setup.get("secret_inputs"),
                    "user_steps": setup.get("user_steps"),
                    "verification_commands": setup.get("verification_commands"),
                    "resume_hint": setup.get("resume_hint"),
                }
                if isinstance(setup, dict)
                else None,
                "missing_runtime_inputs": fallback.get("missing_runtime_inputs")
                if isinstance(fallback, dict)
                else None,
                "resume_command": fallback.get("resume_command") if isinstance(fallback, dict) else None,
            }
        )
    return compact
