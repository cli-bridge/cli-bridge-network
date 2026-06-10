"""Optional OpenAI-compatible LLM validation for Adapter Agent drafts."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any


DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
DEFAULT_MODEL = "GLM-5.1"


def validate_with_glm(
    payload: dict[str, Any],
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    key = api_key or os.environ.get("ZAI_API_KEY")
    if not key:
        return {
            "kind": "AdapterAgentLLMValidation",
            "ok": False,
            "skipped": True,
            "reason": "ZAI_API_KEY is not set",
        }
    endpoint = _chat_endpoint(base_url or os.environ.get("ZAI_BASE_URL") or DEFAULT_BASE_URL)
    model_name = model or os.environ.get("ZAI_MODEL") or DEFAULT_MODEL
    request_payload = _chat_payload(
        model_name,
        (
            "You validate CBN Adapter Agent drafts. Return compact JSON with keys "
            "ok, risks, missing_setup_guides, parser_contract_gaps, recommendation. "
            "Do not include secrets."
        ),
        json.dumps(_bounded_payload(payload), ensure_ascii=False),
    )
    request = _chat_request(endpoint, key, request_payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "kind": "AdapterAgentLLMValidation",
            "ok": False,
            "skipped": False,
            "endpoint": endpoint,
            "model": model_name,
            "error_type": "http_error",
            "status": exc.code,
            "body_summary": body[:1000],
        }
    except OSError as exc:
        return {
            "kind": "AdapterAgentLLMValidation",
            "ok": False,
            "skipped": False,
            "endpoint": endpoint,
            "model": model_name,
            "error_type": "request_error",
            "error": str(exc),
        }
    parsed = json.loads(raw)
    content = _message_content(parsed)
    return {
        "kind": "AdapterAgentLLMValidation",
        "ok": True,
        "skipped": False,
        "endpoint": endpoint,
        "model": model_name,
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
    key = api_key or os.environ.get("ZAI_API_KEY")
    endpoint = _chat_endpoint(base_url or os.environ.get("ZAI_BASE_URL") or DEFAULT_BASE_URL)
    model_name = model or os.environ.get("ZAI_MODEL") or DEFAULT_MODEL
    if not key:
        return {
            "kind": "AdapterAgentGLMTurn",
            "ok": False,
            "skipped": True,
            "endpoint": endpoint,
            "model": model_name,
            "reason": "ZAI_API_KEY is not set",
        }
    request_payload = _chat_payload(
        model_name,
        system_prompt,
        json.dumps(_bounded_payload(payload), ensure_ascii=False),
    )
    request = _chat_request(endpoint, key, request_payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "kind": "AdapterAgentGLMTurn",
            "ok": False,
            "skipped": False,
            "endpoint": endpoint,
            "model": model_name,
            "error_type": "http_error",
            "status": exc.code,
            "body_summary": body[:1000],
        }
    except OSError as exc:
        return {
            "kind": "AdapterAgentGLMTurn",
            "ok": False,
            "skipped": False,
            "endpoint": endpoint,
            "model": model_name,
            "error_type": "request_error",
            "error": str(exc),
        }
    parsed = json.loads(raw)
    return {
        "kind": "AdapterAgentGLMTurn",
        "ok": True,
        "skipped": False,
        "endpoint": endpoint,
        "model": model_name,
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
    key = api_key or os.environ.get("ZAI_API_KEY")
    endpoint = _chat_endpoint(base_url or os.environ.get("ZAI_BASE_URL") or DEFAULT_BASE_URL)
    model_name = model or os.environ.get("ZAI_MODEL") or DEFAULT_MODEL
    if not key:
        yield {
            "type": "error",
            "kind": "AdapterAgentGLMStream",
            "ok": False,
            "skipped": True,
            "endpoint": endpoint,
            "model": model_name,
            "reason": "ZAI_API_KEY is not set",
        }
        return
    request_payload = {
        **_chat_payload(
            model_name,
            system_prompt,
            json.dumps(_bounded_payload(payload), ensure_ascii=False),
        ),
        "stream": True,
    }
    request = _chat_request(endpoint, key, request_payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" not in content_type and "stream" not in content_type:
                raw = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw)
                content = _message_content(parsed)
                if content:
                    yield {"type": "delta", "text": content}
                yield {"type": "done", "model": model_name, "endpoint": endpoint}
                return
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line.removeprefix("data:").strip()
                if line == "[DONE]":
                    yield {"type": "done", "model": model_name, "endpoint": endpoint}
                    return
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = _stream_delta_content(event)
                if delta:
                    yield {"type": "delta", "text": delta}
            yield {"type": "done", "model": model_name, "endpoint": endpoint}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        yield {
            "type": "error",
            "kind": "AdapterAgentGLMStream",
            "ok": False,
            "skipped": False,
            "endpoint": endpoint,
            "model": model_name,
            "error_type": "http_error",
            "status": exc.code,
            "body_summary": body[:1000],
        }
    except OSError as exc:
        yield {
            "type": "error",
            "kind": "AdapterAgentGLMStream",
            "ok": False,
            "skipped": False,
            "endpoint": endpoint,
            "model": model_name,
            "error_type": "request_error",
            "error": str(exc),
        }


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
    if payload.get("kind") == "AdapterAgentDraftBatch":
        return {
            "kind": payload.get("kind"),
            "apiVersion": payload.get("apiVersion"),
            "summary": payload.get("summary"),
            "drafts": [_compact_adapter_draft(draft) for draft in payload.get("drafts", [])],
            "truncated": True,
            "truncation_strategy": "adapter-draft-summary",
        }
    if payload.get("kind") == "AdapterAgentDraft":
        return {
            **_compact_adapter_draft(payload),
            "truncated": True,
            "truncation_strategy": "adapter-draft-summary",
        }
    if payload.get("kind") == "AdapterAgentOrchestrationContext":
        return {
            "kind": payload.get("kind"),
            "apiVersion": payload.get("apiVersion"),
            "user_message": payload.get("user_message"),
            "workflow_initialization": _compact_workflow_initialization(
                payload.get("workflow_initialization") or {}
            ),
            "cli_routes": payload.get("cli_routes", [])[:20],
            "auth_fallbacks": _compact_auth_fallbacks(payload.get("auth_fallbacks", [])),
            "recommended_next_action": payload.get("recommended_next_action"),
            "truncated": True,
            "truncation_strategy": "adapter-orchestration-context",
        }
    if payload.get("kind") == "AdapterAgentOrchestrationTurn":
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
            "cli_routes": payload.get("cli_routes", [])[:20],
            "auth_fallbacks": _compact_auth_fallbacks(payload.get("auth_fallbacks", [])),
            "continuation": payload.get("continuation"),
            "truncated": True,
            "truncation_strategy": "adapter-orchestration-turn",
        }
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
