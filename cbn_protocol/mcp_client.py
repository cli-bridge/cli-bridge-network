"""MCP stdio CLIENT — ingest external MCP servers as CBN nodes.

The inverse of ``McpStdioServer``: spawn an MCP server subprocess, do the JSON-RPC
handshake (initialize -> notifications/initialized -> tools/list), and proxy
``tools/call`` to it. Each ingested tool is registered as a ``kind=mcp`` capability so
the executor dispatches it back through this client (Slice 5). This is the
"accept already-working MCPs instead of re-wrapping" ingress — external agents' MCP
servers become first-class CBN nodes.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from cbn_core.manifest import CapabilityManifest


MCP_PROTOCOL_VERSION = "2025-11-25"
_RPC_VERSION = "2.0"


class McpClient:
    def __init__(self, ingress_dir: Path) -> None:
        self.dir = Path(ingress_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.servers_file = self.dir / "servers.json"
        self._procs: dict[str, subprocess.Popen[str]] = {}
        self._tools: dict[str, list[dict[str, Any]]] = {}
        self._next_id = 1

    # ------------------------------------------------------------------ connect
    def connect(self, server_id: str, command: str, args: list[str], env: dict[str, str] | None = None) -> dict[str, Any]:
        server_id = server_id or f"mcp-{int(time.time())}"
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        try:
            proc = subprocess.Popen(
                [command, *args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=full_env,
            )
        except OSError as exc:
            return {"ok": False, "server_id": server_id, "error": f"failed to start MCP server: {exc}"}
        try:
            self._request(proc, "initialize", {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "cbn-mcp-ingress", "version": "0.1.0"},
            })
            self._notify(proc, "notifications/initialized", {})
            list_result = self._request(proc, "tools/list", {})
        except (TimeoutError, ValueError, OSError) as exc:
            proc.terminate()
            return {"ok": False, "server_id": server_id, "error": f"handshake failed: {exc}"}
        tools = list_result.get("tools", []) if isinstance(list_result, dict) else []
        self._procs[server_id] = proc
        self._tools[server_id] = tools
        self._persist(server_id, command, args, env)
        return {"ok": True, "server_id": server_id, "tools": tools, "tool_count": len(tools)}

    def call_tool(self, server_id: str, tool_name: str, argv: list[str]) -> dict[str, Any]:
        proc = self._procs.get(server_id)
        if proc is None:
            return {"ok": False, "error": f"MCP server not connected: {server_id}"}
        try:
            result = self._request(proc, "tools/call", {"name": tool_name, "arguments": {"argv": list(argv)}})
        except (TimeoutError, ValueError, OSError) as exc:
            return {"ok": False, "error": f"tools/call failed: {exc}"}
        is_error = bool(result.get("isError")) if isinstance(result, dict) else False
        return {"ok": not is_error, "content": result.get("content"), "structuredContent": result.get("structuredContent")}

    def list_tools(self, server_id: str) -> list[dict[str, Any]]:
        return self._tools.get(server_id, [])

    def list_servers(self) -> list[dict[str, Any]]:
        if not self.servers_file.exists():
            return []
        try:
            data = json.loads(self.servers_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        servers = data.get("servers", []) if isinstance(data, dict) else []
        for entry in servers:
            sid = entry.get("server_id")
            entry["connected"] = sid in self._procs
            entry["tool_count"] = len(self._tools.get(sid, []))
        return servers

    def disconnect(self, server_id: str) -> bool:
        proc = self._procs.pop(server_id, None)
        self._tools.pop(server_id, None)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            return True
        return False

    # ---------------------------------------------------- capability registration
    def register_as_capabilities(self, server_id: str, registry: Any) -> list[str]:
        """Register each ingested tool as a kind=mcp CapabilityManifest."""
        registered: list[str] = []
        for tool in self._tools.get(server_id, []):
            tool_name = str(tool.get("name") or "")
            if not tool_name:
                continue
            capability_id = f"mcp.{server_id}.{tool_name}"
            raw = {
                "apiVersion": "bridge.dev/v1alpha1",
                "kind": "ToolManifest",
                "metadata": {
                    "id": capability_id,
                    "title": str(tool.get("description") or tool_name),
                    "labels": {"adapter": "mcp", "protocol": "mcp", "ingress_server": server_id},
                    "annotations": {"cbn.mcp.server_id": server_id, "cbn.mcp.tool_name": tool_name},
                },
                "spec": {
                    "transport": {"kind": "mcp", "command": "", "endpoint": {"server_id": server_id, "tool_name": tool_name}},
                    "policy": {"risk": "external-network", "requiresConfirmation": True, "network": "requires-confirmation"},
                    "output": {"parserRef": "raw.text", "verified": False},
                },
            }
            try:
                manifest = CapabilityManifest.from_dict(raw)
                registry.register(manifest, replace=True)
                registered.append(capability_id)
            except Exception:
                # skip a tool that fails to manifest — never block the rest
                continue
        return registered

    # ------------------------------------------------------------------ wire I/O
    def _request(self, proc: subprocess.Popen[str], method: str, params: Any, timeout: float = 20.0) -> dict[str, Any]:
        if proc.stdin is None or proc.stdout is None:
            raise OSError("MCP process has no stdio")
        request_id = self._next_id
        self._next_id += 1
        proc.stdin.write(json.dumps({"jsonrpc": _RPC_VERSION, "id": request_id, "method": method, "params": params}, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        line = _readline(proc, timeout)
        if not line:
            raise TimeoutError("MCP server closed the connection")
        message = json.loads(line)
        if isinstance(message, dict) and message.get("id") == request_id:
            if "error" in message:
                raise ValueError(f"MCP error: {message['error']}")
            return message.get("result", {}) if isinstance(message.get("result"), dict) else {"result": message.get("result")}
        raise ValueError(f"MCP response id mismatch: {message}")

    def _notify(self, proc: subprocess.Popen[str], method: str, params: Any) -> None:
        if proc.stdin is None:
            return
        proc.stdin.write(json.dumps({"jsonrpc": _RPC_VERSION, "method": method, "params": params}, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def _persist(self, server_id: str, command: str, args: list[str], env: dict[str, str] | None) -> None:
        data = {"servers": []}
        if self.servers_file.exists():
            try:
                data = json.loads(self.servers_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {"servers": []}
        servers = data.get("servers", []) if isinstance(data, dict) else []
        servers = [s for s in servers if s.get("server_id") != server_id]
        servers.append({"server_id": server_id, "command": command, "args": args, "env": env or {}, "connected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        data["servers"] = servers
        self.servers_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _readline(proc: subprocess.Popen[str], timeout: float) -> str:
    # Line-buffered stdout; poll for a line with a deadline.
    deadline = time.time() + timeout
    chunks: list[str] = []
    while time.time() < deadline:
        if proc.stdout is None:
            break
        chunk = proc.stdout.read(1)
        if not chunk:
            # process may have exited
            if proc.poll() is not None:
                break
            time.sleep(0.02)
            continue
        if chunk == "\n":
            return "".join(chunks)
        chunks.append(chunk)
    return "".join(chunks)
