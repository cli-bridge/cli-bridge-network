"""Minimal ACP stdio JSON-RPC agent facade for CBN capabilities."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO

from cbn.version import __version__
from cbn_protocol.workflow_calls import run_workflow_from_metadata, workflow_messages, workflow_run_ok
from cbn_runtime.context import build_runtime


ACP_PROTOCOL_VERSION = 1


class AcpStdioAgent:
    def __init__(self) -> None:
        self.runtime = build_runtime()
        self._sessions: dict[str, dict[str, Any]] = {}

    def serve(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
        input_stream = stdin or sys.stdin
        output_stream = stdout or sys.stdout
        for line in input_stream:
            line = line.strip()
            if not line:
                continue
            response = self.handle_line(line)
            if response is None:
                continue
            output_stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            output_stream.flush()
        return 0

    def handle_line(self, line: str) -> dict[str, Any] | None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            return _error_response(None, -32700, f"parse error: {exc.msg}")
        if not isinstance(message, dict):
            return _error_response(None, -32600, "JSON-RPC message must be an object")
        if message.get("jsonrpc") != "2.0":
            return _error_response(message.get("id"), -32600, "jsonrpc must be 2.0")
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return _error_response(request_id, -32600, "method is required")
        try:
            result = self._dispatch(method, message.get("params", {}), request_id=request_id)
        except KeyError as exc:
            return _error_response(request_id, -32602, str(exc))
        except ValueError as exc:
            return _error_response(request_id, -32602, str(exc))
        except NotImplementedError:
            return _error_response(request_id, -32601, f"method not found: {method}")
        except Exception as exc:
            return _error_response(request_id, -32603, str(exc))
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: Any, request_id: Any) -> dict[str, Any]:
        if method == "initialize":
            return _initialize_result(params)
        if method == "session/new":
            return self._new_session(params)
        if method == "session/prompt":
            return self._prompt(params)
        if method == "session/cancel":
            return {}
        raise NotImplementedError

    def _new_session(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise ValueError("session/new params must be an object")
        cwd = params.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            raise ValueError("session/new params.cwd is required")
        if not Path(cwd).is_absolute():
            raise ValueError("session/new params.cwd must be absolute")
        mcp_servers = params.get("mcpServers", [])
        if not isinstance(mcp_servers, list):
            raise ValueError("session/new params.mcpServers must be a list")
        additional = params.get("additionalDirectories", [])
        if additional is None:
            additional = []
        if not isinstance(additional, list) or not all(isinstance(item, str) for item in additional):
            raise ValueError("session/new params.additionalDirectories must be a list of strings")
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = {
            "cwd": cwd,
            "mcpServers": mcp_servers,
            "additionalDirectories": additional,
        }
        return {
            "sessionId": session_id,
            "modes": None,
            "configOptions": None,
            "_meta": {"cbn": {"cwd": cwd}},
        }

    def _prompt(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise ValueError("session/prompt params must be an object")
        session_id = params.get("sessionId")
        if not isinstance(session_id, str) or session_id not in self._sessions:
            raise ValueError("session/prompt params.sessionId must reference an active session")
        prompt = params.get("prompt")
        if not isinstance(prompt, list):
            raise ValueError("session/prompt params.prompt must be a list")
        cbn_meta = _cbn_metadata(params)
        workflow_path = cbn_meta.get("workflow_path")
        if isinstance(workflow_path, str) and workflow_path:
            return self._prompt_workflow(workflow_path, cbn_meta)
        capability_id = cbn_meta.get("capability_id")
        if not isinstance(capability_id, str) or not capability_id:
            raise ValueError("params._meta.cbn.capability_id is required")
        extra_args = cbn_meta.get("extra_args", [])
        if not isinstance(extra_args, list) or not all(isinstance(item, str) for item in extra_args):
            raise ValueError("params._meta.cbn.extra_args must be a list of strings")
        result = self.runtime.executor.call(
            capability_id,
            extra_args=tuple(extra_args),
            dry_run=bool(cbn_meta.get("dry_run", False)),
            approval_id=_optional_str(cbn_meta.get("approval_id")),
        )
        success = bool(result.get("ok"))
        return {
            "stopReason": "end_turn" if success else "refusal",
            "_meta": {
                "cbn": {
                    "capability_id": result.get("capability_id"),
                    "call_id": result.get("call_id"),
                    "allowed": result.get("allowed"),
                    "ok": result.get("ok"),
                    "exit_code": result.get("exit_code"),
                    "reason": result.get("reason"),
                    "parsed": result.get("parsed"),
                    "message": result.get("message"),
                    "artifacts": result.get("artifacts", []),
                }
            },
        }

    def _prompt_workflow(self, workflow_path: str, cbn_meta: dict[str, Any]) -> dict[str, Any]:
        result = run_workflow_from_metadata(self.runtime, cbn_meta)
        success = workflow_run_ok(result)
        return {
            "stopReason": "end_turn" if success else "refusal",
            "_meta": {
                "cbn": {
                    "workflow_path": workflow_path,
                    "workflow_id": result.get("workflow_id"),
                    "run_id": result.get("run_id"),
                    "status": result.get("status"),
                    "run": result,
                    "messages": workflow_messages(result),
                }
            },
        }


def serve_stdio() -> int:
    return AcpStdioAgent().serve()


def smoke_acp_stdio(capability_id: str, extra_args: Iterable[str] = (), dry_run: bool = False) -> dict[str, Any]:
    command = [sys.executable, "-m", "cbn", "acp", "serve", "--stdio"]
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    cwd = str(Path.cwd())
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": False}, "terminal": False},
                "clientInfo": {"name": "cbn-smoke", "version": __version__},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {"cwd": cwd, "mcpServers": [], "additionalDirectories": []},
        },
    ]
    for request in requests:
        proc.stdin.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")
        proc.stdin.flush()
    responses = []
    for _ in range(2):
        line = proc.stdout.readline()
        if not line:
            break
        responses.append(json.loads(line))
    session_id = responses[1].get("result", {}).get("sessionId") if len(responses) > 1 else None
    prompt_request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "session/prompt",
        "params": {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": "Run CBN capability"}],
            "_meta": {
                "cbn": {
                    "capability_id": capability_id,
                    "extra_args": list(extra_args),
                    "dry_run": dry_run,
                }
            },
        },
    }
    proc.stdin.write(json.dumps(prompt_request, ensure_ascii=False, separators=(",", ":")) + "\n")
    proc.stdin.close()
    line = proc.stdout.readline()
    if line:
        responses.append(json.loads(line))
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    proc.stdout.close()
    if proc.stderr is not None:
        proc.stderr.close()
    return_code = proc.wait(timeout=30)
    prompt_result = responses[2].get("result", {}) if len(responses) > 2 else {}
    cbn = prompt_result.get("_meta", {}).get("cbn", {})
    ok = (
        return_code == 0
        and len(responses) == 3
        and responses[0].get("result", {}).get("agentInfo", {}).get("name") == "CLI Bridge Network"
        and isinstance(session_id, str)
        and prompt_result.get("stopReason") == "end_turn"
        and cbn.get("capability_id") == capability_id
        and cbn.get("allowed") is True
        and cbn.get("ok") is True
        and cbn.get("exit_code") == 0
    )
    return {
        "ok": ok,
        "command": command,
        "return_code": return_code,
        "capability_id": capability_id,
        "responses": responses,
        "stderr": stderr,
    }


def smoke_acp_workflow_stdio(workflow_path: str, dry_run: bool = False, confirmed: bool = False) -> dict[str, Any]:
    command = [sys.executable, "-m", "cbn", "acp", "serve", "--stdio"]
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    cwd = str(Path.cwd())
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": False}, "terminal": False},
                "clientInfo": {"name": "cbn-workflow-smoke", "version": __version__},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {"cwd": cwd, "mcpServers": [], "additionalDirectories": []},
        },
    ]
    for request in requests:
        proc.stdin.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")
        proc.stdin.flush()
    responses = []
    for _ in range(2):
        line = proc.stdout.readline()
        if not line:
            break
        responses.append(json.loads(line))
    session_id = responses[1].get("result", {}).get("sessionId") if len(responses) > 1 else None
    prompt_request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "session/prompt",
        "params": {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": "Run CBN workflow"}],
            "_meta": {
                "cbn": {
                    "workflow_path": workflow_path,
                    "dry_run": dry_run,
                    "confirmed": confirmed,
                }
            },
        },
    }
    proc.stdin.write(json.dumps(prompt_request, ensure_ascii=False, separators=(",", ":")) + "\n")
    proc.stdin.close()
    line = proc.stdout.readline()
    if line:
        responses.append(json.loads(line))
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    proc.stdout.close()
    if proc.stderr is not None:
        proc.stderr.close()
    return_code = proc.wait(timeout=60)
    prompt_result = responses[2].get("result", {}) if len(responses) > 2 else {}
    cbn = prompt_result.get("_meta", {}).get("cbn", {})
    ok = (
        return_code == 0
        and len(responses) == 3
        and responses[0].get("result", {}).get("agentInfo", {}).get("name") == "CLI Bridge Network"
        and isinstance(session_id, str)
        and prompt_result.get("stopReason") == "end_turn"
        and cbn.get("workflow_path") == workflow_path
        and cbn.get("status") == "completed"
    )
    return {
        "ok": ok,
        "command": command,
        "return_code": return_code,
        "workflow_path": workflow_path,
        "responses": responses,
        "stderr": stderr,
    }


def _initialize_result(params: Any) -> dict[str, Any]:
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    version = requested if isinstance(requested, int) and requested > 0 else ACP_PROTOCOL_VERSION
    return {
        "protocolVersion": version,
        "agentCapabilities": {
            "loadSession": False,
            "promptCapabilities": {
                "image": False,
                "audio": False,
                "embeddedContext": False,
            },
            "mcpCapabilities": {
                "http": False,
                "sse": False,
            },
            "sessionCapabilities": {},
        },
        "agentInfo": {
            "name": "CLI Bridge Network",
            "title": "CLI Bridge Network",
            "version": __version__,
        },
        "authMethods": [],
        "_meta": {
            "cbn": {
                "description": "Minimal ACP stdio facade for CBN capability calls.",
                "wire_compatible": False,
            }
        },
    }


def _cbn_metadata(params: dict[str, Any]) -> dict[str, Any]:
    metadata = params.get("_meta", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("params._meta must be an object when present")
    cbn_meta = metadata.get("cbn", {})
    if not isinstance(cbn_meta, dict):
        raise ValueError("params._meta.cbn must be an object")
    return cbn_meta


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
