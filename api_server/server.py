"""Minimal stdlib HTTP API for the MVP daemon.

This API is intentionally small but real: it exposes the same runtime context
used by the CLI so the dashboard can later replace command staging with HTTP
calls without changing backend ownership.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from api_server.routes.health import health_payload
from cbn_runtime.context import build_runtime
from cbn_plugins.cli_anything import CliAnythingHub
from cbn_plugins.manager import PluginManager


ROUTE_SUMMARY = [
    {"method": "GET", "path": "/health"},
    {"method": "GET", "path": "/registry"},
    {"method": "GET", "path": "/plugins"},
    {"method": "GET", "path": "/plugins/cli-anything/status"},
    {"method": "GET", "path": "/audit"},
    {"method": "POST", "path": "/call"},
    {"method": "POST", "path": "/plugins/plan"},
    {"method": "POST", "path": "/plugins/cli-anything/market"},
    {"method": "POST", "path": "/plugins/cli-anything/import-harness"},
]


class CbnRequestHandler(BaseHTTPRequestHandler):
    server_version = "CBNHTTP/0.1"

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, fmt: str, *args: Any) -> None:
        runtime = build_runtime()
        runtime.audit_log.append({"type": "daemon.http_log", "message": fmt % args})

    def do_GET(self) -> None:
        runtime = build_runtime()
        if self.path == "/health":
            self._send(200, health_payload())
            return
        if self.path == "/registry":
            self._send(200, [manifest.as_record() for manifest in runtime.registry.list()])
            return
        if self.path == "/plugins":
            self._send(200, PluginManager().list_plugins())
            return
        if self.path == "/plugins/cli-anything/status":
            self._send(200, CliAnythingHub().status())
            return
        if self.path == "/audit":
            self._send(200, runtime.audit_log.tail())
            return
        self._send(404, {"error": "not found", "routes": ROUTE_SUMMARY})

    def do_POST(self) -> None:
        runtime = build_runtime()
        payload = self._read_json()
        if self.path == "/call":
            result = runtime.executor.call(
                payload["capability_id"],
                extra_args=tuple(payload.get("extra_args", [])),
                dry_run=bool(payload.get("dry_run", False)),
                confirmed=bool(payload.get("confirmed", False)),
            )
            self._send(200 if result.get("allowed") else 403, result)
            return
        if self.path == "/plugins/plan":
            manager = PluginManager()
            plan = manager.plan(
                payload["plugin_id"],
                action=payload.get("action", "install"),
                include_codex_skill=bool(payload.get("include_codex_skill", False)),
            )
            self._send(200, plan.as_dict())
            return
        if self.path == "/plugins/cli-anything/market":
            hub = CliAnythingHub()
            command = payload.get("command", "list")
            if command == "list":
                result = hub.list_market()
            elif command == "search":
                result = hub.search_market(payload["query"])
            elif command == "info":
                result = hub.info(payload["harness_name"])
            else:
                self._send(400, {"error": f"unsupported market command: {command}"})
                return
            self._send(200 if result.exit_code == 0 else 502, result.as_dict())
            return
        if self.path == "/plugins/cli-anything/import-harness":
            hub = CliAnythingHub()
            manifest = hub.manifest_for_harness(
                payload["harness_name"],
                title=payload.get("title"),
            )
            self._send(200, manifest)
            return
        self._send(404, {"error": "not found", "routes": ROUTE_SUMMARY})


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    server = ThreadingHTTPServer((host, port), CbnRequestHandler)
    print(f"CBN daemon API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("CBN daemon API stopped")
    finally:
        server.server_close()
