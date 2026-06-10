"""Selector and argv mapping utilities for CBN bus messages."""

from __future__ import annotations

import json
from typing import Any


def select_bridge_value(message: dict[str, Any], selector: str) -> dict[str, Any]:
    if not selector:
        raise ValueError("selector cannot be empty")
    current: Any = message
    for token in selector_tokens(selector):
        if isinstance(token, int):
            if not isinstance(current, list):
                raise KeyError(f"selector expected list before [{token}]")
            current = current[token]
        else:
            if not isinstance(current, dict):
                raise KeyError(f"selector expected object before .{token}")
            current = current[token]
    return {"selector": selector, "value": current}


def bridge_value_to_arg(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def validate_selector_syntax(selector: str) -> dict[str, Any]:
    try:
        tokens = selector_tokens(selector)
    except (TypeError, ValueError) as exc:
        return {"valid": False, "selector": selector, "tokens": [], "error": str(exc)}
    return {"valid": True, "selector": selector, "tokens": tokens, "error": None}


def selector_tokens(selector: str) -> list[str | int]:
    tokens: list[str | int] = []
    for part in selector.split("."):
        if not part:
            raise ValueError(f"invalid selector: {selector}")
        while "[" in part:
            field, rest = part.split("[", 1)
            if field:
                tokens.append(field)
            index_text, remainder = rest.split("]", 1)
            tokens.append(int(index_text))
            part = remainder
        if part:
            tokens.append(part)
    return tokens
