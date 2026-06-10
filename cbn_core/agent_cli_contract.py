"""Mapping from external Agent CLI Contract objects to CBN core contracts."""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import MANIFEST_API_VERSION
from cbn_core.message import BridgeMessage


AGENT_CLI_API_VERSION = "agent-cli.dev/v1alpha1"
AGENT_CLI_CARD_KIND = "AgentCliCard"
RUN_RECEIPT_KIND = "RunReceipt"


def agent_cli_card_to_tool_manifests(card: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one AgentCliCard into CBN ToolManifest dictionaries."""

    _require_agent_cli_card(card)
    metadata = card["metadata"]
    spec = card["spec"]
    runtime = spec.get("runtime") if isinstance(spec.get("runtime"), dict) else {}
    card_id = metadata["id"]
    manifests = []
    for command in spec["commands"]:
        command_id = command["id"]
        argv = list(command["argv"])
        policy = command.get("policy") if isinstance(command.get("policy"), dict) else {}
        output = command.get("output") if isinstance(command.get("output"), dict) else {}
        capability_id = f"{card_id}.{command_id}"
        manifests.append(
            {
                "apiVersion": MANIFEST_API_VERSION,
                "kind": "ToolManifest",
                "metadata": {
                    "id": capability_id,
                    "title": command.get("title", capability_id),
                    "labels": {
                        "adapter": "agent-cli-contract",
                        "agent_cli_card": card_id,
                        **_string_labels(metadata.get("labels", {})),
                    },
                    "annotations": {
                        "cbn.external_protocol": "agent-cli-contract",
                        "cbn.agent_cli.card_id": card_id,
                        "cbn.agent_cli.command_id": command_id,
                        "cbn.agent_cli.runtime_kind": str(runtime.get("kind", "stdio")),
                        "cbn.agent_cli.card_version": str(metadata.get("version", "")),
                    },
                },
                "spec": {
                    "transport": {
                        "kind": _cbn_transport_kind(runtime.get("kind")),
                        "command": argv[0],
                        "argsTemplate": argv[1:],
                        "cwdPolicy": str(runtime.get("cwdPolicy", "workspace")),
                        "timeoutSeconds": int(command.get("timeoutSeconds", 30)),
                    },
                    "policy": {
                        "risk": str(policy.get("risk", "read")),
                        "requiresConfirmation": bool(policy.get("requiresConfirmation", False)),
                        "network": str(policy.get("network", "deny")),
                    },
                    "output": {
                        "parserRef": str(output.get("parser", "raw.text")),
                        "verified": False,
                    },
                },
            }
        )
    return manifests


def run_receipt_to_cbn_records(receipt: dict[str, Any]) -> dict[str, Any]:
    """Convert a RunReceipt into BridgeMessage plus audit/event correlation records."""

    _require_run_receipt(receipt)
    run_id = receipt["runId"]
    producer = f"{receipt['cardId']}.{receipt['commandId']}"
    artifacts = tuple(_receipt_artifact_to_cbn(item) for item in receipt.get("artifacts", []))
    status = receipt["status"]
    payload = {
        "parser_ref": _receipt_parser_ref(receipt),
        "ok": status == "completed",
        "data": {
            "status": status,
            "exit_code": receipt.get("exitCode"),
            "stdout": receipt.get("stdout", ""),
            "stderr": receipt.get("stderr", ""),
            "parsed": receipt.get("parsed", {}),
        },
    }
    if status != "completed":
        error = receipt.get("error") if isinstance(receipt.get("error"), dict) else {}
        payload["error"] = str(error.get("message") or status)
    message = BridgeMessage(
        producer=producer,
        channel="agent-cli.run.receipt",
        correlation_id=run_id,
        payload=payload,
        artifacts=artifacts,
    ).as_dict()
    return {
        "kind": "AgentCliRunReceiptMapping",
        "apiVersion": MANIFEST_API_VERSION,
        "message": message,
        "artifacts": list(artifacts),
        "audit_event": {
            "type": "agent_cli.run_receipt",
            "call_id": run_id,
            "capability_id": producer,
            "status": status,
            "exit_code": receipt.get("exitCode"),
            "correlation": receipt.get("correlation", {}),
        },
        "event": {
            "type": "agent_cli.run.completed" if status == "completed" else "agent_cli.run.stopped",
            "subject": producer,
            "correlation_id": run_id,
            "payload": {
                "status": status,
                "artifact_count": len(artifacts),
            },
        },
    }


def _require_agent_cli_card(card: dict[str, Any]) -> None:
    if card.get("apiVersion") != AGENT_CLI_API_VERSION:
        raise ValueError(f"unsupported AgentCliCard apiVersion: {card.get('apiVersion')}")
    if card.get("kind") != AGENT_CLI_CARD_KIND:
        raise ValueError(f"unsupported AgentCliCard kind: {card.get('kind')}")
    metadata = card.get("metadata")
    spec = card.get("spec")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("id"), str):
        raise ValueError("AgentCliCard metadata.id is required")
    if not isinstance(spec, dict) or not isinstance(spec.get("commands"), list):
        raise ValueError("AgentCliCard spec.commands is required")
    for index, command in enumerate(spec["commands"]):
        if not isinstance(command, dict):
            raise ValueError(f"AgentCliCard spec.commands[{index}] must be an object")
        if not isinstance(command.get("id"), str) or not command["id"]:
            raise ValueError(f"AgentCliCard spec.commands[{index}].id is required")
        argv = command.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise ValueError(f"AgentCliCard spec.commands[{index}].argv must be a non-empty string array")


def _require_run_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("apiVersion") != AGENT_CLI_API_VERSION:
        raise ValueError(f"unsupported RunReceipt apiVersion: {receipt.get('apiVersion')}")
    if receipt.get("kind") != RUN_RECEIPT_KIND:
        raise ValueError(f"unsupported RunReceipt kind: {receipt.get('kind')}")
    for key in ("runId", "cardId", "commandId", "status"):
        if not isinstance(receipt.get(key), str) or not receipt[key]:
            raise ValueError(f"RunReceipt {key} is required")


def _string_labels(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _cbn_transport_kind(kind: Any) -> str:
    if kind in {"stdio", "pty"}:
        return str(kind)
    return "stdio"


def _receipt_parser_ref(receipt: dict[str, Any]) -> str:
    parsed = receipt.get("parsed")
    if isinstance(parsed, dict) and isinstance(parsed.get("parser_ref"), str):
        return parsed["parser_ref"]
    return "agent-cli.run-receipt"


def _receipt_artifact_to_cbn(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": str(artifact.get("id", "")),
        "kind": str(artifact.get("kind", "")),
        "path": str(artifact.get("uri", "")),
        "media_type": str(artifact.get("mediaType", "application/octet-stream")),
        "size_bytes": int(artifact.get("sizeBytes", 0)),
        "truncated": False,
    }
