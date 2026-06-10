"""A2A HTTP JSON-RPC facade for CBN capabilities."""

from __future__ import annotations

import json
import uuid
import urllib.request
from http.server import ThreadingHTTPServer
from typing import Any

from cbn.version import __version__
from cbn_core.manifest import CapabilityManifest
from cbn_protocol.workflow_calls import run_workflow_from_metadata, workflow_messages, workflow_run_ok
from cbn_runtime.context import build_runtime
from cbn_workflow.catalog import list_workflows


A2A_PROTOCOL_VERSION = "1.0.0"
_TASKS: dict[str, dict[str, Any]] = {}


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
                "protocolBinding": "HTTP+JSON",
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
        "skills": [
            *[_skill_from_manifest(manifest) for manifest in runtime.registry.list()],
            *[_skill_from_workflow(workflow) for workflow in list_workflows(registry=runtime.registry)],
        ],
    }


def handle_a2a_jsonrpc_request(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return _jsonrpc_error(request_id, -32600, "jsonrpc must be 2.0")
    method = payload.get("method")
    params = payload.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32602, "params must be an object")
    try:
        if method in {"SendMessage", "message/send"}:
            task = _send_message(params)
            return {"jsonrpc": "2.0", "id": request_id, "result": task}
        if method in {"GetTask", "tasks/get"}:
            return {"jsonrpc": "2.0", "id": request_id, "result": _get_task(params)}
        if method in {"ListTasks", "tasks/list"}:
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tasks": list(_TASKS.values())}}
        if method in {"CancelTask", "tasks/cancel"}:
            return {"jsonrpc": "2.0", "id": request_id, "result": _cancel_task(params)}
        return _jsonrpc_error(request_id, -32601, f"method not found: {method}")
    except A2ATaskNotFound as exc:
        return _jsonrpc_error(request_id, -32001, str(exc))
    except A2ATaskNotCancelable as exc:
        return _jsonrpc_error(request_id, -32002, str(exc))
    except KeyError as exc:
        return _jsonrpc_error(request_id, -32602, str(exc))
    except ValueError as exc:
        return _jsonrpc_error(request_id, -32602, str(exc))


def smoke_a2a_http(
    capability_id: str = "git.version",
    extra_args: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
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
                    "method": "SendMessage",
                    "params": {
                        "message": {
                            "messageId": str(uuid.uuid4()),
                            "role": "ROLE_USER",
                            "parts": [{"text": "Run CBN capability"}],
                        },
                        "metadata": {
                            "cbn": {
                                "capability_id": capability_id,
                                "extra_args": extra_args or [],
                                "dry_run": dry_run,
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
            and _is_completed(task.get("status", {}).get("state"))
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


def smoke_a2a_workflow_http(workflow_path: str, dry_run: bool = False, confirmed: bool = False) -> dict[str, Any]:
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
        workflow_id = _workflow_id_from_path(workflow_path)
        request = urllib.request.Request(
            f"{base_url}/a2a",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "workflow-smoke-1",
                    "method": "SendMessage",
                    "params": {
                        "message": {
                            "messageId": str(uuid.uuid4()),
                            "role": "ROLE_USER",
                            "parts": [{"text": "Run CBN workflow"}],
                        },
                        "metadata": {
                            "cbn": {
                                "workflow_id": workflow_id,
                                "dry_run": dry_run,
                                "confirmed": confirmed,
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
        with urllib.request.urlopen(request, timeout=60) as response:
            rpc = json.loads(response.read().decode("utf-8"))
        task = rpc.get("result", {})
        ok = (
            card.get("protocolVersion") == A2A_PROTOCOL_VERSION
            and any(skill.get("id") == f"workflow:{workflow_id}" for skill in card.get("skills", []))
            and _is_completed(task.get("status", {}).get("state"))
            and _same_workflow_path(task.get("metadata", {}).get("cbn", {}).get("workflow_path"), workflow_path)
            and task.get("metadata", {}).get("cbn", {}).get("workflow_id") == workflow_id
            and task.get("metadata", {}).get("cbn", {}).get("status") == "completed"
        )
        return {
            "ok": ok,
            "base_url": base_url,
            "workflow_path": workflow_path,
            "workflow_id": workflow_id,
            "dry_run": dry_run,
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
    workflow_path = cbn_meta.get("workflow_path")
    workflow_id = cbn_meta.get("workflow_id")
    if (isinstance(workflow_path, str) and workflow_path) or (isinstance(workflow_id, str) and workflow_id):
        return _send_workflow_message(message, cbn_meta)
    if not isinstance(capability_id, str) or not capability_id:
        raise ValueError("params.metadata.cbn.capability_id is required")
    extra_args = cbn_meta.get("extra_args", [])
    if not isinstance(extra_args, list) or not all(isinstance(item, str) for item in extra_args):
        raise ValueError("params.metadata.cbn.extra_args must be a list of strings")
    runtime = build_runtime()
    result = runtime.executor.call(
        capability_id,
        extra_args=tuple(extra_args),
        dry_run=bool(cbn_meta.get("dry_run", False)),
    )
    task_id = str(uuid.uuid4())
    context_id = message.get("contextId") if isinstance(message.get("contextId"), str) else str(uuid.uuid4())
    state = _task_state(result)
    agent_message = {
        "messageId": str(uuid.uuid4()),
        "contextId": context_id,
        "taskId": task_id,
                    "role": "ROLE_AGENT",
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
    task = {
        "id": task_id,
        "taskId": task_id,
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
                "ok": result.get("ok"),
                "exit_code": result.get("exit_code"),
                "reason": result.get("reason"),
            }
        },
    }
    _TASKS[task_id] = task
    return task


def _send_workflow_message(message: dict[str, Any], cbn_meta: dict[str, Any]) -> dict[str, Any]:
    runtime = build_runtime()
    result = run_workflow_from_metadata(runtime, cbn_meta)
    workflow_path = result.get("workflow_path") or cbn_meta.get("workflow_path")
    task_id = str(uuid.uuid4())
    context_id = message.get("contextId") if isinstance(message.get("contextId"), str) else str(uuid.uuid4())
    state = "TASK_STATE_COMPLETED" if workflow_run_ok(result) else "TASK_STATE_FAILED"
    agent_message = {
        "messageId": str(uuid.uuid4()),
        "contextId": context_id,
        "taskId": task_id,
        "role": "ROLE_AGENT",
        "parts": [
            {
                "data": {
                    "workflow_path": workflow_path,
                    "workflow_id": result.get("workflow_id"),
                    "run": result,
                    "messages": workflow_messages(result),
                }
            }
        ],
    }
    artifacts = []
    for task in result.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_result = task.get("result", {})
        if not isinstance(task_result, dict):
            continue
        artifacts.extend(_artifact_from_cbn(artifact) for artifact in task_result.get("artifacts", []))
    task = {
        "id": task_id,
        "taskId": task_id,
        "contextId": context_id,
        "status": {
            "state": state,
            "message": agent_message,
        },
        "artifacts": artifacts,
        "history": [message, agent_message],
        "metadata": {
            "cbn": {
                "workflow_path": workflow_path,
                "workflow_id": result.get("workflow_id"),
                "run_id": result.get("run_id"),
                "status": result.get("status"),
            }
        },
    }
    _TASKS[task_id] = task
    return task


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


def _skill_from_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    workflow_id = workflow["workflow_id"] or workflow["path"]
    return {
        "id": f"workflow:{workflow_id}",
        "name": workflow["title"] or workflow["path"],
        "description": "CBN workflow exported as an A2A skill facade.",
        "tags": ["workflow", f"tasks:{workflow['task_count']}"],
        "examples": [f"Run workflow {workflow_id} through CBN policy and audit."],
        "inputModes": ["application/json", "text/plain"],
        "outputModes": ["application/json", "text/plain"],
        "metadata": {
            "cbn": {
                "workflow_id": workflow["workflow_id"],
                "workflow_path": workflow["path"],
                "valid": workflow["valid"],
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
        return "TASK_STATE_REJECTED"
    if not result.get("ok"):
        return "TASK_STATE_FAILED"
    return "TASK_STATE_COMPLETED"


def _get_task(params: dict[str, Any]) -> dict[str, Any]:
    task_id = params.get("id") or params.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("params.id or params.taskId is required")
    task = _TASKS.get(task_id)
    if task is None:
        raise A2ATaskNotFound(task_id)
    return task


def _cancel_task(params: dict[str, Any]) -> dict[str, Any]:
    task = _get_task(params)
    state = task.get("status", {}).get("state")
    if state in {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_REJECTED", "TASK_STATE_CANCELED"}:
        raise A2ATaskNotCancelable(task.get("id"))
    task["status"]["state"] = "TASK_STATE_CANCELED"
    return task


def _workflow_id_from_path(workflow_path: str) -> str:
    from pathlib import Path

    from cbn_execution.graph import WorkflowGraph

    return WorkflowGraph.from_file(Path(workflow_path)).workflow_id


def _same_workflow_path(left: Any, right: str) -> bool:
    if not isinstance(left, str):
        return False
    return left.replace("\\", "/") == right.replace("\\", "/")


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _is_completed(state: Any) -> bool:
    return state in {"TASK_STATE_COMPLETED", "completed"}


class A2ATaskNotFound(ValueError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"task not found: {task_id}")


class A2ATaskNotCancelable(ValueError):
    def __init__(self, task_id: Any) -> None:
        super().__init__(f"task is not cancelable: {task_id}")
