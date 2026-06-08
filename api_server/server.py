"""Minimal stdlib HTTP API for the MVP daemon.

This API is intentionally small but real: it exposes the same runtime context
used by the CLI so the dashboard can later replace command staging with HTTP
calls without changing backend ownership.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from api_server.routes.health import health_payload
from cbn_core.manifest import validate_manifest_path
from cbn_execution.graph import WorkflowGraph
from cbn_parsers.registry import ParserRegistry
from cbn_protocol.a2a_http import agent_card, handle_a2a_jsonrpc_request
from cbn_protocol.envelope import bridge_args_from_selectors, select_bridge_value, validate_bridge_message
from cbn_protocol.compatibility import check_protocol
from cbn_protocol.exports import export_all_protocols, export_protocol, list_protocol_exports
from cbn_runtime.context import build_runtime
from cbn_workflow.catalog import inspect_workflow, list_workflows
from cbn_plugins.cli_anything import CliAnythingHub
from cbn_plugins.manager import PluginManager


ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}


ROUTE_SUMMARY = [
    {"method": "GET", "path": "/health"},
    {"method": "GET", "path": "/registry"},
    {"method": "GET", "path": "/registry?capability_id=<id>"},
    {"method": "GET", "path": "/registry?q=<query>"},
    {"method": "GET", "path": "/registry/validate"},
    {"method": "GET", "path": "/plugins"},
    {"method": "GET", "path": "/plugins/cli-anything/status"},
    {"method": "GET", "path": "/plugins/cli-anything/preflight"},
    {"method": "GET", "path": "/audit"},
    {"method": "GET", "path": "/events"},
    {"method": "GET", "path": "/artifacts"},
    {"method": "GET", "path": "/parsers"},
    {"method": "GET", "path": "/.well-known/agent-card.json"},
    {"method": "GET", "path": "/protocols"},
    {"method": "GET", "path": "/protocols/check"},
    {"method": "GET", "path": "/approvals"},
    {"method": "GET", "path": "/workflows"},
    {"method": "POST", "path": "/call"},
    {"method": "POST", "path": "/a2a"},
    {"method": "POST", "path": "/messages/validate"},
    {"method": "POST", "path": "/messages/select"},
    {"method": "POST", "path": "/messages/args"},
    {"method": "POST", "path": "/approvals/decide"},
    {"method": "POST", "path": "/workflows/validate"},
    {"method": "POST", "path": "/workflows/plan"},
    {"method": "POST", "path": "/workflows/run"},
    {"method": "POST", "path": "/plugins/plan"},
    {"method": "POST", "path": "/plugins/execute"},
    {"method": "POST", "path": "/plugins/cli-anything/market"},
    {"method": "POST", "path": "/plugins/cli-anything/import-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/adapt-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/prepare-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/evaluate-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/sync-market"},
    {"method": "POST", "path": "/plugins/cli-anything/harness"},
]


class CbnRequestHandler(BaseHTTPRequestHandler):
    server_version = "CBNHTTP/0.1"

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        cors_origin = self._cors_origin()
        if cors_origin:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, error_type: str, message: str) -> None:
        self._send(
            status,
            {
                "ok": False,
                "error": message,
                "error_type": error_type,
                "status": status,
            },
        )

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, fmt: str, *args: Any) -> None:
        runtime = build_runtime()
        runtime.audit_log.append({"type": "daemon.http_log", "message": fmt % args})

    def do_GET(self) -> None:
        if not self._require_allowed_origin():
            return
        try:
            self._handle_GET()
        except KeyError as exc:
            self._send_error(404, "not_found", str(exc))
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send_error(400, "bad_request", str(exc))
        except Exception as exc:
            self._send_error(500, "internal_error", str(exc))

    def do_POST(self) -> None:
        if not self._require_allowed_origin():
            return
        try:
            self._handle_POST()
        except KeyError as exc:
            self._send_error(404, "not_found", str(exc))
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send_error(400, "bad_request", str(exc))
        except Exception as exc:
            self._send_error(500, "internal_error", str(exc))

    def do_OPTIONS(self) -> None:
        if not self._require_allowed_origin():
            return
        self._send(200, {"ok": True})

    def _cors_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if not origin:
            return "http://127.0.0.1"
        return origin if _is_allowed_origin(origin) else None

    def _require_allowed_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if _is_allowed_origin(origin):
            return True
        self._send_error(403, "origin_denied", f"Origin is not allowed: {origin}")
        return False

    def _handle_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/health":
            self._send(200, health_payload())
            return
        if parsed.path == "/.well-known/agent-card.json":
            self._send(200, agent_card(_base_url(self)))
            return
        if parsed.path == "/plugins":
            self._send(200, PluginManager().list_plugins())
            return
        if parsed.path == "/plugins/cli-anything/status":
            self._send(200, CliAnythingHub().status())
            return
        if parsed.path == "/plugins/cli-anything/preflight":
            self._send(200, PluginManager().preflight("cli-anything"))
            return
        if parsed.path == "/registry/validate":
            path = Path(query.get("path", ["manifests"])[0])
            result = validate_manifest_path(path, known_parser_refs=_known_parser_refs())
            self._send(200 if result["valid"] else 422, result)
            return
        runtime = build_runtime()
        if parsed.path == "/registry":
            capability_id = query.get("capability_id", [None])[0]
            search_query = query.get("q", [None])[0]
            if capability_id:
                self._send(200, runtime.registry.require(capability_id).as_record())
            elif search_query is not None:
                limit = int(query.get("limit", ["20"])[0])
                self._send(200, runtime.registry.search(search_query, limit=limit))
            else:
                self._send(200, [manifest.as_record() for manifest in runtime.registry.list()])
            return
        if parsed.path == "/audit":
            self._send(200, runtime.audit_log.tail())
            return
        if parsed.path == "/events":
            limit = int(query.get("limit", ["50"])[0])
            self._send(200, runtime.event_bus.tail(limit=limit))
            return
        if parsed.path == "/artifacts":
            artifact_id = query.get("artifact_id", [None])[0]
            if artifact_id:
                self._send(200, runtime.artifact_store.inspect(artifact_id))
            else:
                limit = int(query.get("limit", ["50"])[0])
                self._send(200, runtime.artifact_store.list(limit=limit))
            return
        if parsed.path == "/parsers":
            parser_ref = query.get("parser_ref", [None])[0]
            if parser_ref:
                self._send(200, runtime.parser_registry.inspect(parser_ref))
            else:
                self._send(200, runtime.parser_registry.list())
            return
        if parsed.path == "/protocols":
            target = query.get("target", [None])[0]
            capability_id = query.get("capability_id", [None])[0]
            if target == "all":
                self._send(200, export_all_protocols(runtime.registry, capability_id=capability_id))
            elif target:
                self._send(
                    200,
                    export_protocol(runtime.registry, target, capability_id=capability_id),
                )
            else:
                self._send(200, list_protocol_exports())
            return
        if parsed.path == "/protocols/check":
            target = query.get("target", ["all"])[0]
            capability_id = query.get("capability_id", [None])[0]
            self._send(200, check_protocol(runtime.registry, target, capability_id=capability_id))
            return
        if parsed.path == "/approvals":
            approval_id = query.get("approval_id", [None])[0]
            if approval_id:
                self._send(200, runtime.approval_store.inspect(approval_id))
            else:
                limit = int(query.get("limit", ["50"])[0])
                status = query.get("status", [None])[0]
                self._send(200, runtime.approval_store.list(status=status, limit=limit))
            return
        if parsed.path == "/workflows":
            path = query.get("path", [None])[0]
            if path:
                result = inspect_workflow(Path(path), registry=runtime.registry)
                self._send(200 if result["valid"] else 422, result)
            else:
                self._send(200, list_workflows(registry=runtime.registry))
            return
        self._send(404, {"error": "not found", "routes": ROUTE_SUMMARY})

    def _handle_POST(self) -> None:
        runtime = build_runtime()
        payload = self._read_json()
        if self.path == "/call":
            result = runtime.executor.call(
                payload["capability_id"],
                extra_args=tuple(payload.get("extra_args", [])),
                dry_run=bool(payload.get("dry_run", False)),
                confirmed=bool(payload.get("confirmed", False)),
                approval_id=payload.get("approval_id"),
            )
            self._send(200 if result.get("allowed") else 403, result)
            return
        if self.path == "/a2a":
            self._send(200, handle_a2a_jsonrpc_request(payload))
            return
        if self.path == "/messages/validate":
            result = validate_bridge_message(payload["message"])
            self._send(200 if result["valid"] else 422, result)
            return
        if self.path == "/messages/select":
            try:
                self._send(200, select_bridge_value(payload["message"], payload["selector"]))
            except (KeyError, IndexError, ValueError) as exc:
                self._send(400, {"error": str(exc), "selector": payload.get("selector")})
            return
        if self.path == "/messages/args":
            try:
                selectors = payload["selectors"]
                if not isinstance(selectors, list) or not all(isinstance(item, str) for item in selectors):
                    self._send(400, {"error": "selectors must be a list of strings"})
                    return
                result = bridge_args_from_selectors(payload["message"], selectors)
                self._send(200 if result["valid"] else 422, result)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                self._send(400, {"error": str(exc), "selectors": payload.get("selectors")})
            return
        if self.path == "/approvals/decide":
            approval = runtime.approval_store.decide(
                payload["approval_id"],
                payload["decision"],
                actor=payload.get("actor", "api"),
                reason=payload.get("reason", ""),
            )
            runtime.event_bus.publish(
                "approval.decided",
                approval["capability_id"],
                {"approval": approval},
                correlation_id=approval["call_id"],
            )
            self._send(200, approval)
            return
        if self.path in {"/workflows/validate", "/workflows/plan", "/workflows/run"}:
            if "workflow" in payload:
                graph = WorkflowGraph.from_dict(payload["workflow"])
            else:
                graph = WorkflowGraph.from_file(Path(payload["path"]))
            if self.path == "/workflows/validate":
                graph.validate()
                self._send(200, {"valid": True, "workflow_id": graph.workflow_id})
                return
            if self.path == "/workflows/plan":
                self._send(200, runtime.workflow_runner.plan(graph))
                return
            result = runtime.workflow_runner.run(
                graph,
                dry_run=bool(payload.get("dry_run", False)),
                confirmed=bool(payload.get("confirmed", False)),
            )
            self._send(200 if result["status"] == "completed" else 409, result)
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
        if self.path == "/plugins/execute":
            if not bool(payload.get("confirmed", False)):
                self._send(403, {"error": "plugin execution requires confirmed=true"})
                return
            manager = PluginManager()
            plan = manager.plan(
                payload["plugin_id"],
                action=payload.get("action", "install"),
                include_codex_skill=bool(payload.get("include_codex_skill", False)),
            )
            self._send(200, runtime.plugin_runner.execute(plan))
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
            market_record = None
            if bool(payload.get("from_market", False)):
                market_record = hub.market_record_for_harness(payload["harness_name"])
                if market_record is None:
                    self._send(
                        502,
                        {
                            "error": "CLI-Anything market record not found",
                            "plugin_id": "cli-anything",
                            "harness_name": payload["harness_name"],
                        },
                    )
                    return
            manifest = hub.manifest_for_harness(
                payload["harness_name"],
                title=payload.get("title"),
                market_record=market_record,
            )
            if bool(payload.get("write", False)):
                if not bool(payload.get("confirmed", False)):
                    self._send(403, {"error": "manifest write requires confirmed=true"})
                    return
                path = hub.write_harness_manifest(
                    payload["harness_name"],
                    title=payload.get("title"),
                    market_record=market_record,
                )
                self._send(200, {"written": str(path), "manifest": manifest})
            else:
                self._send(200, manifest)
            return
        if self.path == "/plugins/cli-anything/adapt-harness":
            hub = CliAnythingHub()
            write = bool(payload.get("write", False))
            if write and not bool(payload.get("confirmed", False)):
                self._send(403, {"error": "manifest write requires confirmed=true"})
                return
            result = hub.adapt_harness(
                payload["harness_name"],
                title=payload.get("title"),
                from_market=bool(payload.get("from_market", False)),
                write=write,
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/prepare-harness":
            result = CliAnythingHub().prepare_harness(
                payload["harness_name"],
                title=payload.get("title"),
                from_market=bool(payload.get("from_market", False)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/evaluate-harness":
            result = CliAnythingHub().evaluate_harness(
                payload["harness_name"],
                title=payload.get("title"),
                from_market=bool(payload.get("from_market", True)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/sync-market":
            write = bool(payload.get("write", False))
            if write and not bool(payload.get("confirmed", False)):
                self._send(403, {"error": "manifest write requires confirmed=true"})
                return
            result = CliAnythingHub().sync_market(
                query=payload.get("query"),
                limit=int(payload.get("limit", 50)),
                write=write,
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/harness":
            hub = CliAnythingHub()
            if payload["action"] == "status":
                self._send(
                    200,
                    hub.harness_status(
                        payload["harness_name"],
                        from_market=bool(payload.get("from_market", False)),
                    ),
                )
                return
            plan = hub.harness_plan(
                payload["action"],
                payload["harness_name"],
                extra_args=tuple(payload.get("extra_args", [])),
            )
            if not bool(payload.get("confirmed", False)):
                self._send(200, plan.as_dict())
                return
            self._send(200, runtime.plugin_runner.execute(plan))
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


def _known_parser_refs() -> set[str]:
    return {item["parser_ref"] for item in ParserRegistry.builtins().list()}


def _is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and parsed.hostname in ALLOWED_ORIGIN_HOSTS


def _base_url(handler: BaseHTTPRequestHandler) -> str:
    host = handler.headers.get("Host")
    if host:
        return f"http://{host}"
    bound_host, bound_port = handler.server.server_address[:2]
    return f"http://{bound_host}:{bound_port}"
