"""Minimal A2A HTTP JSON-RPC facade for CBN capabilities."""

from __future__ import annotations

import json
import uuid
import urllib.request
from http.server import ThreadingHTTPServer
from typing import Any

from cbn.version import __version__
from cbn_core.manifest import CapabilityManifest
from cbn_runtime.context import build_runtime


A2A_PROTOCOL_VERSION = "0.3"


def agent_card(base_url: str = "http://127.0.0.1:8787") -> dict[str, Any]:
    runtime = build_runtime()
    endpoint = base_url.rstrip("/") + "/a2a"
    return {
        "name": "CLI Bridge Network",
        "description": "Local-first CBN capability network exposed as an A2A facade.",
        "version": __version__,
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "supportedInterfaces": [
            {
                "url": endpoint,
                "protocolBinding": "JSONRPC",
                "protocolVersion": A2A_PROTOCOL_VERSION,
            }
        ],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json", "text/plain"],
        "skills": [_skill_from_manifest(manifest) for manifest in runtime.registry.list()],
    }


def handle_a2a_jsonrpc_request(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return _jsonrpc_error(request_id, -32600, "jsonrpc must be 2.0")
    if payload.get("method") != "message/send":
        return _jsonrpc_error(request_id, -32601, f"method not found: {payload.get('method')}")
    params = payload.get("params")
    if not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32602, "params must be an object")
    try:
        task = _send_message(params)
    except KeyError as exc:
        return _jsonrpc_error(request_id, -32602, str(exc))
    except ValueError as exc:
        return _jsonrpc_error(request_id, -32602, str(exc))
    return {"jsonrpc": "2.0", "id": request_id, "result": task}


def smoke_a2a_http(capability_id: str = "git.version", extra_args: list[str] | None = None) -> dict[str, Any]:
    from api_server.server import CbnRequestHandler

    server = ThreadingHTTPServer(("127.0.0.1", 0), CbnRequestHandler)
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"{base_url}/.well-known/agent-card.json", timeout=5) as response:
            card = json.loads(response.read().decode("utf-8"))
        request = urllib.request.Request(
            f"{base_url}/a2a",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "smoke-1",
                    "method": "message/send",
                    "params": {
                        "message": {
                            "messageId": str(uuid.uuid4()),
                            "role": "user",
                            "parts": [{"text": "Run CBN capability"}],
                        },
                        "metadata": {
                            "cbn": {
                                "capability_id": capability_id,
                                "extra_args": extra_args or [],
                            }
                        },
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "A2A-Version": A2A_PROTOCOL_VERSION,
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            rpc = json.loads(response.read().decode("utf-8"))
        task = rpc.get("result", {})
        ok = (
            card.get("protocolVersion") == A2A_PROTOCOL_VERSION
            and any(skill.get("id") == capability_id for skill in card.get("skills", []))
            and task.get("status", {}).get("state") == "completed"
            and task.get("metadata", {}).get("cbn", {}).get("capability_id") == capability_id
        )
        return {
            "ok": ok,
            "base_url": base_url,
            "capability_id": capability_id,
            "agent_card": card,
            "response": rpc,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _send_message(params: dict[str, Any]) -> dict[str, Any]:
    message = params.get("message")
    if not isinstance(message, dict):
        raise ValueError("params.message must be an object")
    metadata = params.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("params.metadata must be an object when present")
    cbn_meta = metadata.get("cbn", {})
    if not isinstance(cbn_meta, dict):
        raise ValueError("params.metadata.cbn must be an object")
    capability_id = cbn_meta.get("capability_id")
    if not isinstance(capability_id, str) or not capability_id:
        raise ValueError("params.metadata.cbn.capability_id is required")
    extra_args = cbn_meta.get("extra_args", [])
    if not isinstance(extra_args, list) or not all(isinstance(item, str) for item in extra_args):
        raise ValueError("params.metadata.cbn.extra_args must be a list of strings")
    runtime = build_runtime()
    result = runtime.executor.call(capability_id, extra_args=tuple(extra_args))
    task_id = str(uuid.uuid4())
    context_id = message.get("contextId") if isinstance(message.get("contextId"), str) else str(uuid.uuid4())
    state = _task_state(result)
    agent_message = {
        "messageId": str(uuid.uuid4()),
        "contextId": context_id,
        "taskId": task_id,
        "role": "agent",
        "parts": [
            {
                "data": {
                    "capability_id": result.get("capability_id"),
                    "parsed": result.get("parsed"),
                    "message": result.get("message"),
                }
            }
        ],
    }
    return {
        "id": task_id,
        "contextId": context_id,
        "status": {
            "state": state,
            "message": agent_message,
        },
        "artifacts": [_artifact_from_cbn(item) for item in result.get("artifacts", [])],
        "history": [message, agent_message],
        "metadata": {
            "cbn": {
                "capability_id": result.get("capability_id"),
                "call_id": result.get("call_id"),
                "allowed": result.get("allowed"),
                "exit_code": result.get("exit_code"),
                "reason": result.get("reason"),
            }
        },
    }


def _skill_from_manifest(manifest: CapabilityManifest) -> dict[str, Any]:
    return {
        "id": manifest.capability_id,
        "name": manifest.title,
        "description": f"CBN capability exported from {manifest.transport.kind}.",
        "tags": [
            f"risk:{manifest.policy.risk}",
            f"transport:{manifest.transport.kind}",
            f"network:{manifest.policy.network}",
        ],
        "examples": [f"Run {manifest.capability_id} through CBN policy and audit."],
        "inputModes": ["application/json", "text/plain"],
        "outputModes": ["application/json", "text/plain"],
        "metadata": {
            "cbn": {
                "capability_id": manifest.capability_id,
                "parser_ref": manifest.output.parser_ref,
                "verified": manifest.output.verified,
            }
        },
    }


def _artifact_from_cbn(artifact: dict[str, Any]) -> dict[str, Any]:
    artifact_id = artifact.get("artifact_id") or str(uuid.uuid4())
    return {
        "artifactId": artifact_id,
        "name": artifact.get("kind", "artifact"),
        "description": f"CBN {artifact.get('kind', 'artifact')} artifact.",
        "parts": [{"data": artifact}],
        "metadata": {"cbn": artifact},
    }


def _task_state(result: dict[str, Any]) -> str:
    if not result.get("allowed"):
        return "rejected"
    if result.get("exit_code") not in (0, None):
        return "failed"
    return "completed"


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
