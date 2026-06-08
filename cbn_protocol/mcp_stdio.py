"""Minimal MCP stdio JSON-RPC server for CBN capabilities."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable
from typing import Any, TextIO

from cbn.version import __version__
from cbn_runtime.context import build_runtime
from protocols.mcp import export_capabilities


MCP_PROTOCOL_VERSION = "2025-11-25"


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
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            return _error_response(None, -32700, f"parse error: {exc.msg}")
        if not isinstance(message, dict):
            return _error_response(None, -32600, "JSON-RPC message must be an object")
        if message.get("jsonrpc") != "2.0":
            return _error_response(message.get("id"), -32600, "jsonrpc must be 2.0")
        method = message.get("method")
        request_id = message.get("id")
        if method == "notifications/initialized":
            return None
        if not isinstance(method, str):
            return _error_response(request_id, -32600, "method is required")
        try:
            result = self._dispatch(method, message.get("params", {}))
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

    def _dispatch(self, method: str, params: Any) -> dict[str, Any]:
        if method == "initialize":
            return _initialize_result(params)
        if method == "tools/list":
            descriptor = export_capabilities(self.runtime.registry.list())
            return {"tools": descriptor["tools"]}
        if method == "tools/call":
            return self._call_tool(params)
        raise NotImplementedError

    def _call_tool(self, params: Any) -> dict[str, Any]:
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
        extra_args = arguments.get("extra_args", [])
        if not isinstance(extra_args, list) or not all(isinstance(item, str) for item in extra_args):
            raise ValueError("arguments.extra_args must be a list of strings")
        result = self.runtime.executor.call(
            name,
            extra_args=tuple(extra_args),
            dry_run=bool(arguments.get("dry_run", False)),
            approval_id=_optional_str(arguments.get("approval_id")),
        )
        is_error = not result.get("allowed") or result.get("exit_code") not in (0, None)
        text = result.get("stdout") or result.get("stderr") or json.dumps(result.get("parsed", {}), ensure_ascii=False)
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": {
                "capability_id": result.get("capability_id"),
                "call_id": result.get("call_id"),
                "allowed": result.get("allowed"),
                "exit_code": result.get("exit_code"),
                "reason": result.get("reason"),
                "parsed": result.get("parsed"),
                "message": result.get("message"),
                "artifacts": result.get("artifacts", []),
            },
            "isError": bool(is_error),
        }


def serve_stdio() -> int:
    return McpStdioServer().serve()


def smoke_mcp_stdio(capability_id: str, extra_args: Iterable[str] = (), dry_run: bool = False) -> dict[str, Any]:
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
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "cbn-smoke", "version": __version__},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": capability_id,
                "arguments": {"extra_args": list(extra_args), "dry_run": dry_run},
            },
        },
    ]
    for request in requests:
        proc.stdin.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")
    proc.stdin.close()
    responses = []
    for _ in range(3):
        line = proc.stdout.readline()
        if not line:
            break
        responses.append(json.loads(line))
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    proc.stdout.close()
    if proc.stderr is not None:
        proc.stderr.close()
    return_code = proc.wait(timeout=30)
    ok = (
        return_code == 0
        and len(responses) == 3
        and responses[0].get("result", {}).get("serverInfo", {}).get("name") == "CLI Bridge Network"
        and any(tool.get("name") == capability_id for tool in responses[1].get("result", {}).get("tools", []))
        and responses[2].get("result", {}).get("isError") is False
    )
    return {
        "ok": ok,
        "command": command,
        "return_code": return_code,
        "capability_id": capability_id,
        "responses": responses,
        "stderr": stderr,
    }


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


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
