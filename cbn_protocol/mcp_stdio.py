"""Minimal MCP stdio JSON-RPC server for CBN capabilities."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from cbn.version import __version__
from cbn_execution.graph import WorkflowGraph
from cbn_protocol.exports import export_workflow_protocol
from cbn_protocol.workflow_calls import run_workflow_from_metadata, workflow_run_ok
from cbn_runtime.context import build_runtime
from protocols.mcp import export_capabilities


MCP_PROTOCOL_VERSION = "2025-11-25"


@dataclass(frozen=True)
class _McpRequest:
    request_id: Any
    method: str
    params: Any


class McpStdioServer:
    def __init__(self) -> None:
        self.runtime = build_runtime()

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
            request = _mcp_request_from_line(line)
        except _McpNotification:
            return None
        except _McpMessageError as exc:
            return _error_response(exc.request_id, exc.code, str(exc))
        try:
            result = self._dispatch(request.method, request.params)
        except KeyError as exc:
            return _error_response(request.request_id, -32602, str(exc))
        except ValueError as exc:
            return _error_response(request.request_id, -32602, str(exc))
        except NotImplementedError:
            return _error_response(request.request_id, -32601, f"method not found: {request.method}")
        except Exception as exc:
            return _error_response(request.request_id, -32603, str(exc))
        return _mcp_success_response(request, result)

    def _dispatch(self, method: str, params: Any) -> dict[str, Any]:
        if method == "initialize":
            return _initialize_result(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return self._list_tools(params)
        if method == "tools/call":
            return self._call_tool(params)
        raise NotImplementedError

    def _list_tools(self, params: Any) -> dict[str, Any]:
        # CBN extension: an optional `query` (or _meta.query) filters capabilities so an
        # external agent (e.g. Codex) can search "obsidian" without loading every tool.
        query = None
        if isinstance(params, dict):
            meta = params.get("_meta")
            raw_q = params.get("query") or (meta.get("query") if isinstance(meta, dict) else None)
            query = (str(raw_q).strip() if raw_q else "") or None
        capabilities = self.runtime.registry.list()
        if query:
            lowered = query.lower()
            capabilities = [
                c for c in capabilities
                if lowered in str(getattr(c, "capability_id", "")).lower()
                or lowered in str(getattr(c, "title", "")).lower()
            ]
        descriptor = export_capabilities(capabilities)
        workflow_tools = export_workflow_protocol(self.runtime.registry, "mcp")["workflowTools"]
        if query:
            lowered = query.lower()
            workflow_tools = [
                t for t in workflow_tools
                if lowered in str(t.get("name", "")).lower() or lowered in str(t.get("description", "")).lower()
            ]
        return {"tools": [*descriptor["tools"], *workflow_tools]}

    def _call_tool(self, params: Any) -> dict[str, Any]:
        name, arguments = _mcp_tool_call_args(params)
        if name.startswith("workflow:"):
            return self._call_workflow(name, arguments)
        result = self.runtime.executor.call(
            name,
            extra_args=tuple(_mcp_extra_args(arguments)),
            dry_run=bool(arguments.get("dry_run", False)),
            approval_id=_optional_str(arguments.get("approval_id")),
        )
        return _mcp_tool_result(result)

    def _call_workflow(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = run_workflow_from_metadata(
            self.runtime,
            {
                "workflow_id": arguments.get("workflow_id"),
                "workflow_path": arguments.get("workflow_path"),
                "dry_run": bool(arguments.get("dry_run", False)),
                "confirmed": bool(arguments.get("confirmed", False)),
            },
            workflow_tool=name,
        )
        is_error = not workflow_run_ok(result)
        workflow_path = result.get("workflow_path") or arguments.get("workflow_path")
        return {
            "content": [{"type": "text", "text": result.get("status", "unknown")}],
            "structuredContent": {
                "workflow_tool": name,
                "workflow_path": workflow_path,
                "workflow_id": result.get("workflow_id"),
                "run": result,
            },
            "isError": bool(is_error),
        }


def _mcp_tool_call_args(params: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(params, dict):
        raise ValueError("tools/call params must be an object")
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("tools/call params.name is required")
    arguments = params.get("arguments", {})
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("tools/call params.arguments must be an object")
    return name, arguments


def _mcp_extra_args(arguments: dict[str, Any]) -> list[str]:
    extra_args = arguments.get("extra_args", [])
    if not isinstance(extra_args, list) or not all(isinstance(item, str) for item in extra_args):
        raise ValueError("arguments.extra_args must be a list of strings")
    return extra_args


def _mcp_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    text = result.get("stdout") or result.get("stderr") or json.dumps(result.get("parsed", {}), ensure_ascii=False)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": {
            "capability_id": result.get("capability_id"),
            "call_id": result.get("call_id"),
            "allowed": result.get("allowed"),
            "ok": result.get("ok"),
            "exit_code": result.get("exit_code"),
            "reason": result.get("reason"),
            "parsed": result.get("parsed"),
            "message": result.get("message"),
            "artifacts": result.get("artifacts", []),
        },
        "isError": bool(not result.get("ok")),
    }


def _mcp_request_from_line(line: str) -> _McpRequest:
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        raise _McpMessageError(None, -32700, f"parse error: {exc.msg}") from exc
    if not isinstance(message, dict):
        raise _McpMessageError(None, -32600, "JSON-RPC message must be an object")
    request_id = message.get("id")
    if message.get("jsonrpc") != "2.0":
        raise _McpMessageError(request_id, -32600, "jsonrpc must be 2.0")
    method = message.get("method")
    if method == "notifications/initialized":
        raise _McpNotification()
    if not isinstance(method, str):
        raise _McpMessageError(request_id, -32600, "method is required")
    return _McpRequest(request_id=request_id, method=method, params=message.get("params", {}))


def _mcp_success_response(request: _McpRequest, result: dict[str, Any]) -> dict[str, Any] | None:
    if request.request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request.request_id, "result": result}


class _McpNotification(Exception):
    pass


class _McpMessageError(ValueError):
    def __init__(self, request_id: Any, code: int, message: str) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.code = code


def serve_stdio() -> int:
    return McpStdioServer().serve()


def smoke_mcp_stdio(capability_id: str, extra_args: Iterable[str] = (), dry_run: bool = False) -> dict[str, Any]:
    run = _run_mcp_smoke(
        client_name="cbn-smoke",
        call_request=_mcp_tool_call_request(
            capability_id,
            {"extra_args": list(extra_args), "dry_run": dry_run},
        ),
        timeout=30,
    )
    return {
        "ok": _mcp_capability_smoke_ok(run, capability_id),
        "command": run["command"],
        "return_code": run["return_code"],
        "capability_id": capability_id,
        "responses": run["responses"],
        "stderr": run["stderr"],
    }


def smoke_mcp_workflow_stdio(workflow_path: str, dry_run: bool = False, confirmed: bool = False) -> dict[str, Any]:
    tool_name = f"workflow:{_workflow_id_from_path(workflow_path)}"
    run = _run_mcp_smoke(
        client_name="cbn-workflow-smoke",
        call_request=_mcp_tool_call_request(
            tool_name,
            {"dry_run": dry_run, "confirmed": confirmed},
        ),
        timeout=60,
    )
    return {
        "ok": _mcp_workflow_smoke_ok(run, tool_name),
        "command": run["command"],
        "return_code": run["return_code"],
        "workflow_path": workflow_path,
        "tool_name": tool_name,
        "responses": run["responses"],
        "stderr": run["stderr"],
    }


def _run_mcp_smoke(
    client_name: str,
    call_request: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    command = [sys.executable, "-m", "cbn", "mcp", "serve", "--stdio"]
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
    requests = [_mcp_initialize_request(client_name), _mcp_initialized_notification(), _mcp_tools_list_request(), call_request]
    _write_json_requests(proc.stdin, requests)
    proc.stdin.close()
    responses = _read_json_responses(proc.stdout, count=3)
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    proc.stdout.close()
    if proc.stderr is not None:
        proc.stderr.close()
    return {
        "command": command,
        "return_code": proc.wait(timeout=timeout),
        "responses": responses,
        "stderr": stderr,
    }


def _mcp_initialize_request(client_name: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": client_name, "version": __version__},
        },
    }


def _mcp_initialized_notification() -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": "notifications/initialized"}


def _mcp_tools_list_request() -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def _mcp_tool_call_request(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def _write_json_requests(stream: TextIO, requests: list[dict[str, Any]]) -> None:
    for request in requests:
        stream.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")


def _read_json_responses(stream: TextIO, count: int) -> list[dict[str, Any]]:
    responses = []
    for _ in range(count):
        line = stream.readline()
        if not line:
            break
        responses.append(json.loads(line))
    return responses


def _mcp_base_smoke_ok(run: dict[str, Any]) -> bool:
    responses = run["responses"]
    return (
        run["return_code"] == 0
        and len(responses) == 3
        and responses[0].get("result", {}).get("serverInfo", {}).get("name") == "CLI Bridge Network"
    )


def _mcp_capability_smoke_ok(run: dict[str, Any], capability_id: str) -> bool:
    responses = run["responses"]
    return (
        _mcp_base_smoke_ok(run)
        and any(tool.get("name") == capability_id for tool in responses[1].get("result", {}).get("tools", []))
        and responses[2].get("result", {}).get("isError") is False
    )


def _mcp_workflow_smoke_ok(run: dict[str, Any], tool_name: str) -> bool:
    responses = run["responses"]
    workflow_tools = responses[1].get("result", {}).get("tools", []) if len(responses) > 1 else []
    structured = responses[2].get("result", {}).get("structuredContent", {}) if len(responses) > 2 else {}
    return (
        _mcp_base_smoke_ok(run)
        and any(tool.get("name") == tool_name for tool in workflow_tools)
        and responses[2].get("result", {}).get("isError") is False
        and structured.get("run", {}).get("status") == "completed"
    )


def _initialize_result(params: Any) -> dict[str, Any]:
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    return {
        "protocolVersion": requested if isinstance(requested, str) and requested else MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {
            "name": "CLI Bridge Network",
            "version": __version__,
            "description": "Local-first CBN capability network MCP stdio facade.",
        },
        "instructions": "Use tools/list to discover CBN capabilities and tools/call to invoke them through CBN policy, audit, and BridgeMessage output.",
    }


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _workflow_id_from_path(workflow_path: str) -> str:
    return WorkflowGraph.from_file(Path(workflow_path)).workflow_id


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
