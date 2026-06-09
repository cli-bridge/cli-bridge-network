"""Bridge message envelope for CLI-to-CLI interchange."""

from __future__ import annotations

import time
import uuid
import json
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
        elif not isinstance(metadata.get(key), str):
            errors.append(f"metadata.{key} must be a string")
    payload = message.get("payload")
    if not isinstance(payload, dict):
        errors.append("payload must be an object")
        payload = {}
    else:
        if not isinstance(payload.get("parser_ref"), str) or not payload.get("parser_ref"):
            errors.append("payload.parser_ref is required")
        if not isinstance(payload.get("ok"), bool):
            errors.append("payload.ok must be a boolean")
        if "data" in payload and not isinstance(payload["data"], dict):
            errors.append("payload.data must be an object when present")
        if payload.get("ok") is False and not payload.get("error") and "data" not in payload:
            errors.append("payload.error or payload.data is required when payload.ok=false")
    artifacts = message.get("artifacts", [])
    if not isinstance(artifacts, list):
        errors.append("artifacts must be a list")
        artifacts = []
    else:
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                errors.append(f"artifacts[{index}] must be an object")
                continue
            for key in ("artifact_id", "kind"):
                if not artifact.get(key):
                    errors.append(f"artifacts[{index}].{key} is required")
                elif not isinstance(artifact.get(key), str):
                    errors.append(f"artifacts[{index}].{key} must be a string")
            _validate_optional_artifact_field(errors, artifact, index, "path", str)
            _validate_optional_artifact_field(errors, artifact, index, "media_type", str)
            _validate_optional_artifact_field(errors, artifact, index, "size_bytes", int)
            _validate_optional_artifact_field(errors, artifact, index, "truncated", bool)
    return {
        "valid": not errors,
        "errors": errors,
        "apiVersion": message.get("apiVersion"),
        "kind": message.get("kind"),
        "message_id": metadata.get("id"),
        "producer": metadata.get("producer"),
        "channel": metadata.get("channel"),
        "correlation_id": metadata.get("correlationId"),
        "payload_parser_ref": payload.get("parser_ref") if isinstance(payload, dict) else None,
        "payload_ok": payload.get("ok") if isinstance(payload, dict) else None,
        "artifact_count": len(artifacts),
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


def bridge_value_to_arg(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def bridge_args_from_selectors(message: dict[str, Any], selectors: list[str]) -> dict[str, Any]:
    validation = validate_bridge_message(message)
    if not validation["valid"]:
        return {
            "valid": False,
            "errors": validation["errors"],
            "args": [],
            "mappings": [],
        }
    mappings = []
    args = []
    for selector in selectors:
        selected = select_bridge_value(message, selector)
        arg = bridge_value_to_arg(selected["value"])
        args.append(arg)
        mappings.append(
            {
                "selector": selector,
                "value": selected["value"],
                "arg": arg,
            }
        )
    return {
        "valid": True,
        "errors": [],
        "message_id": validation["message_id"],
        "producer": validation["producer"],
        "channel": validation["channel"],
        "correlation_id": validation["correlation_id"],
        "args": args,
        "mappings": mappings,
    }


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


def _validate_optional_artifact_field(
    errors: list[str],
    artifact: dict[str, Any],
    index: int,
    key: str,
    expected_type: type,
) -> None:
    if key not in artifact:
        return
    if expected_type is int and isinstance(artifact[key], bool):
        errors.append(f"artifacts[{index}].{key} must be an int")
        return
    if not isinstance(artifact[key], expected_type):
        errors.append(f"artifacts[{index}].{key} must be a {expected_type.__name__}")
