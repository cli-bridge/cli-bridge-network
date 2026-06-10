"""Optional OpenAI-compatible LLM validation for Adapter Agent drafts."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
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
    request_payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You validate CBN Adapter Agent drafts. Return compact JSON with keys "
                    "ok, risks, missing_setup_guides, parser_contract_gaps, recommendation. "
                    "Do not include secrets."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(_bounded_payload(payload), ensure_ascii=False),
            },
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
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


def _bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= 12000:
        return payload
    return {
        "kind": payload.get("kind"),
        "apiVersion": payload.get("apiVersion"),
        "summary": payload.get("summary"),
        "status": payload.get("status"),
        "workflow": payload.get("workflow"),
        "tasks": payload.get("tasks", [])[:20],
        "setup_guides": payload.get("setup_guides", [])[:10],
        "truncated": True,
    }
