"""Bridge message envelope for CLI-to-CLI interchange."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


BRIDGE_MESSAGE_API_VERSION = "bridge.dev/v1alpha1"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


@dataclass(frozen=True)
class BridgeMessage:
    producer: str
    channel: str
    correlation_id: str
    payload: dict[str, Any]
    artifacts: tuple[dict[str, Any], ...] = ()
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=now_iso)

    def as_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": BRIDGE_MESSAGE_API_VERSION,
            "kind": "BridgeMessage",
            "metadata": {
                "id": self.message_id,
                "createdAt": self.created_at,
                "producer": self.producer,
                "channel": self.channel,
                "correlationId": self.correlation_id,
            },
            "payload": self.payload,
            "artifacts": list(self.artifacts),
        }


def validate_bridge_message(message: dict[str, Any]) -> dict[str, Any]:
    errors = []
    if message.get("apiVersion") != BRIDGE_MESSAGE_API_VERSION:
        errors.append(f"unsupported apiVersion: {message.get('apiVersion')}")
    if message.get("kind") != "BridgeMessage":
        errors.append(f"unsupported kind: {message.get('kind')}")
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata must be an object")
        metadata = {}
    for key in ("id", "createdAt", "producer", "channel", "correlationId"):
        if not metadata.get(key):
            errors.append(f"metadata.{key} is required")
    if not isinstance(message.get("payload"), dict):
        errors.append("payload must be an object")
    if not isinstance(message.get("artifacts", []), list):
        errors.append("artifacts must be a list")
    return {
        "valid": not errors,
        "errors": errors,
        "apiVersion": message.get("apiVersion"),
        "kind": message.get("kind"),
        "message_id": metadata.get("id"),
        "producer": metadata.get("producer"),
        "channel": metadata.get("channel"),
        "correlation_id": metadata.get("correlationId"),
    }


def select_bridge_value(message: dict[str, Any], selector: str) -> dict[str, Any]:
    if not selector:
        raise ValueError("selector cannot be empty")
    current: Any = message
    for token in _selector_tokens(selector):
        if isinstance(token, int):
            if not isinstance(current, list):
                raise KeyError(f"selector expected list before [{token}]")
            current = current[token]
        else:
            if not isinstance(current, dict):
                raise KeyError(f"selector expected object before .{token}")
            current = current[token]
    return {"selector": selector, "value": current}


def _selector_tokens(selector: str) -> list[str | int]:
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
