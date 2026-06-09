"""Minimal stdlib HTTP API for the MVP daemon.

This API is intentionally small but real: it exposes the same runtime context
used by the CLI so the dashboard can later replace command staging with HTTP
calls without changing backend ownership.
"""

from __future__ import annotations

import os
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from api_server.routes.health import health_payload
from cbn_core.manifest import validate_manifest_path
from cbn_execution.graph import WorkflowGraph
from cbn_parsers.fixtures import run_parser_fixtures
from cbn_parsers.registry import ParserRegistry
from cbn_protocol.acceptance import cli_to_cli_acceptance_report
from cbn_protocol.acceptance_queue import cli_to_cli_acceptance_queue
from cbn_protocol.a2a_http import agent_card, handle_a2a_jsonrpc_request
from cbn_protocol.bridge_contract import workflow_bridge_contract_report
from cbn_protocol.bridge_lab import bridge_lab_report
from cbn_protocol.envelope import bridge_args_from_selectors, select_bridge_value, validate_bridge_message
from cbn_protocol.compatibility import check_protocol, protocol_matrix
from cbn_protocol.conformance import protocol_conformance_plan
from cbn_protocol.exports import (
    export_all_protocols,
    export_all_workflow_protocols,
    export_protocol,
    export_workflow_protocol,
    list_protocol_exports,
)
from cbn_protocol.lifecycle_suite import protocol_lifecycle_suite
from cbn_protocol.readiness import protocol_readiness_report
from cbn_protocol.smoke_suite import protocol_smoke_suite
from cbn_runtime.context import build_runtime
from cbn_workflow.catalog import inspect_workflow, list_workflows
from cbn_plugins.cli_anything import CliAnythingHub
from cbn_plugins.manager import PluginManager


ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}
SESSION_TOKEN_ENV = "CBN_DAEMON_SESSION_TOKEN"


ROUTE_SUMMARY = [
    {"method": "GET", "path": "/health"},
    {"method": "GET", "path": "/registry"},
    {"method": "GET", "path": "/registry?capability_id=<id>"},
    {"method": "GET", "path": "/registry?q=<query>"},
    {"method": "GET", "path": "/registry/validate"},
    {"method": "GET", "path": "/plugins"},
    {"method": "GET", "path": "/plugins/operations"},
    {"method": "GET", "path": "/plugins/operations/validate"},
    {"method": "GET", "path": "/plugins/cli-anything/status"},
    {"method": "GET", "path": "/plugins/cli-anything/preflight"},
    {"method": "GET", "path": "/plugins/cli-anything/provenance"},
    {"method": "GET", "path": "/plugins/cli-anything/update-check"},
    {"method": "GET", "path": "/audit"},
    {"method": "GET", "path": "/events"},
    {"method": "GET", "path": "/artifacts"},
    {"method": "GET", "path": "/parsers"},
    {"method": "GET", "path": "/parsers/fixtures"},
    {"method": "GET", "path": "/.well-known/agent-card.json"},
    {"method": "GET", "path": "/protocols"},
    {"method": "GET", "path": "/protocols/workflows"},
    {"method": "GET", "path": "/protocols/check"},
    {"method": "GET", "path": "/protocols/matrix"},
    {"method": "GET", "path": "/protocols/readiness"},
    {"method": "GET", "path": "/protocols/conformance-plan"},
    {"method": "GET", "path": "/protocols/lifecycle-suite"},
    {"method": "GET", "path": "/protocols/smoke-suite"},
    {"method": "GET", "path": "/protocols/acceptance-queue"},
    {"method": "GET", "path": "/protocols/bridge-lab"},
    {"method": "POST", "path": "/protocols/accept-workflow"},
    {"method": "POST", "path": "/protocols/acceptance-queue"},
    {"method": "POST", "path": "/protocols/bridge-lab"},
    {"method": "GET", "path": "/approvals"},
    {"method": "GET", "path": "/workflows"},
    {"method": "GET", "path": "/runtime/transports"},
    {"method": "GET", "path": "/messages/contract"},
    {"method": "POST", "path": "/call"},
    {"method": "POST", "path": "/a2a"},
    {"method": "POST", "path": "/messages/validate"},
    {"method": "POST", "path": "/messages/select"},
    {"method": "POST", "path": "/messages/args"},
    {"method": "POST", "path": "/approvals/decide"},
    {"method": "POST", "path": "/workflows/validate"},
    {"method": "POST", "path": "/workflows/plan"},
    {"method": "POST", "path": "/workflows/run"},
    {"method": "POST", "path": "/runtime/transports/gate"},
    {"method": "POST", "path": "/runtime/transports/plan"},
    {"method": "POST", "path": "/runtime/transports/install"},
    {"method": "POST", "path": "/plugins/gate"},
    {"method": "POST", "path": "/plugins/check-update"},
    {"method": "POST", "path": "/plugins/operation-plan"},
    {"method": "POST", "path": "/plugins/plan"},
    {"method": "POST", "path": "/plugins/execute"},
    {"method": "POST", "path": "/plugins/cli-anything/market"},
    {"method": "POST", "path": "/plugins/cli-anything/import-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/adapt-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/prepare-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/evaluate-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/probe-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/verify-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/onboard-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/live-verification"},
    {"method": "POST", "path": "/plugins/cli-anything/mvp-plan"},
    {"method": "POST", "path": "/plugins/cli-anything/bootstrap-plan"},
    {"method": "POST", "path": "/plugins/cli-anything/candidates"},
    {"method": "POST", "path": "/plugins/cli-anything/install-queue"},
    {"method": "POST", "path": "/plugins/cli-anything/blocked-plan"},
    {"method": "POST", "path": "/plugins/cli-anything/repair-plan"},
    {"method": "POST", "path": "/plugins/cli-anything/repair-entrypoint"},
    {"method": "POST", "path": "/plugins/cli-anything/promotion-gate"},
    {"method": "POST", "path": "/plugins/cli-anything/adapter-targets"},
    {"method": "POST", "path": "/plugins/cli-anything/adapter-smoke"},
    {"method": "POST", "path": "/plugins/cli-anything/adaptation-gate"},
    {"method": "POST", "path": "/plugins/cli-anything/adaptation-queue"},
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
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-CBN-Session")
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
        if not self._require_session_token():
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

    def _require_session_token(self) -> bool:
        expected = getattr(self.server, "session_token", None)
        if expected is None:
            return True
        token = self.headers.get("X-CBN-Session", "")
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
        if secrets.compare_digest(token, expected):
            return True
        self._send_error(403, "session_denied", "valid daemon session token required")
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
        if parsed.path == "/plugins/operations":
            plugin_id = query.get("plugin_id", [None])[0]
            self._send(200, PluginManager().operation_catalog(plugin_id))
            return
        if parsed.path == "/plugins/operations/validate":
            plugin_id = query.get("plugin_id", [None])[0]
            result = PluginManager().validate_operation_catalog(plugin_id)
            self._send(200 if result["ok"] else 422, result)
            return
        if parsed.path == "/plugins/cli-anything/status":
            self._send(200, CliAnythingHub().status())
            return
        if parsed.path == "/plugins/cli-anything/preflight":
            self._send(200, PluginManager().preflight("cli-anything"))
            return
        if parsed.path == "/plugins/cli-anything/provenance":
            self._send(200, PluginManager().provenance("cli-anything"))
            return
        if parsed.path == "/plugins/cli-anything/update-check":
            remote = query.get("remote", ["false"])[0].lower() in {"1", "true", "yes"}
            result = PluginManager().update_check("cli-anything", remote=remote)
            self._send(200 if result["ready_for_update"] else 409, result)
            return
        if parsed.path == "/runtime/transports":
            kind = query.get("kind", ["pty"])[0]
            status = PluginManager().runtime_transport_status(kind)
            self._send(200, status)
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
        if parsed.path == "/parsers/fixtures":
            path = Path(query.get("path", ["parser_fixtures"])[0])
            parser_ref = query.get("parser_ref", [None])[0]
            result = run_parser_fixtures(path, parser_ref=parser_ref, registry=runtime.parser_registry)
            self._send(200 if result["ok"] else 422, result)
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
        if parsed.path == "/protocols/workflows":
            target = query.get("target", ["all"])[0]
            workflow_path = query.get("path", [None])[0]
            if target == "all":
                self._send(200, export_all_workflow_protocols(runtime.registry, workflow_path=workflow_path))
            else:
                self._send(200, export_workflow_protocol(runtime.registry, target, workflow_path=workflow_path))
            return
        if parsed.path == "/protocols/check":
            target = query.get("target", ["all"])[0]
            capability_id = query.get("capability_id", [None])[0]
            workflow_path = query.get("path", query.get("workflow_path", [None]))[0]
            self._send(
                200,
                check_protocol(
                    runtime.registry,
                    target,
                    capability_id=capability_id,
                    workflow_path=workflow_path,
                ),
            )
            return
        if parsed.path == "/protocols/matrix":
            include_workflows = query.get("include_workflows", ["false"])[0].lower() in {"1", "true", "yes"}
            self._send(200, protocol_matrix(runtime.registry, include_workflows=include_workflows))
            return
        if parsed.path == "/protocols/readiness":
            include_workflows = query.get("include_workflows", ["true"])[0].lower() in {"1", "true", "yes"}
            workflow_path = query.get("workflow_path", query.get("path", [None]))[0]
            result = protocol_readiness_report(
                runtime.registry,
                workflow_path=workflow_path,
                include_workflows=include_workflows,
            )
            self._send(200 if result["ok"] else 422, result)
            return
        if parsed.path == "/protocols/conformance-plan":
            target = query.get("target", ["all"])[0]
            capability_id = query.get("capability_id", [None])[0]
            workflow_path = query.get("workflow_path", query.get("path", [None]))[0]
            result = protocol_conformance_plan(
                runtime.registry,
                target=target,
                capability_id=capability_id,
                workflow_path=workflow_path,
            )
            self._send(200 if result["ok"] else 422, result)
            return
        if parsed.path == "/protocols/lifecycle-suite":
            result = protocol_lifecycle_suite(
                capability_id=query.get("capability_id", ["git.version"])[0],
                workflow_path=query.get("workflow_path", query.get("path", ["workflows/example.json"]))[0],
            )
            self._send(200 if result["ok"] else 422, result)
            return
        if parsed.path == "/protocols/smoke-suite":
            result = protocol_smoke_suite(
                runtime.registry,
                capability_ids=query.get("capability_id") or None,
                workflow_paths=query.get("workflow_path") or query.get("path") or None,
                extra_args=query.get("extra_arg", []),
                dry_run=query.get("dry_run", ["false"])[0].lower() in {"1", "true", "yes"},
                workflow_dry_run=query.get("workflow_dry_run", ["false"])[0].lower() in {"1", "true", "yes"},
                workflow_confirmed=query.get("confirmed", ["false"])[0].lower() in {"1", "true", "yes"},
                include_payloads=query.get("include_payloads", ["false"])[0].lower() in {"1", "true", "yes"},
            )
            self._send(200 if result["ok"] else 422, result)
            return
        if parsed.path == "/protocols/acceptance-queue":
            result = cli_to_cli_acceptance_queue(
                runtime.registry,
                runtime.workflow_runner,
                workflow_paths=query.get("workflow_path") or query.get("path") or None,
                max_workflows=int(query.get("max_workflows", ["50"])[0]),
                run=query.get("run", ["false"])[0].lower() in {"1", "true", "yes"},
                dry_run=query.get("dry_run", ["false"])[0].lower() in {"1", "true", "yes"},
                confirmed=query.get("confirmed", ["false"])[0].lower() in {"1", "true", "yes"},
                include_payloads=query.get("include_payloads", ["false"])[0].lower() in {"1", "true", "yes"},
            )
            self._send(200 if result["ok"] else 422, result)
            return
        if parsed.path == "/protocols/bridge-lab":
            result = bridge_lab_report(
                runtime.registry,
                runtime.workflow_runner,
                workflow_paths=tuple(query.get("workflow_path") or query.get("path") or ()),
                max_workflows=int(query.get("max_workflows", ["10"])[0]),
                run=False,
                dry_run=True,
                confirmed=False,
                include_payloads=False,
                run_smoke_suite=query.get("smoke_suite", ["false"])[0].lower() in {"1", "true", "yes"},
            )
            self._send(200 if result["ok"] else 422, result)
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
        if parsed.path == "/messages/contract":
            workflow_path = query.get("workflow_path", query.get("path", [None]))[0]
            result = workflow_bridge_contract_report(runtime.registry, workflow_path=workflow_path)
            self._send(200 if result["ok"] else 422, result)
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
            status = 200 if result.get("ok") else 403 if not result.get("allowed") else 502
            self._send(status, result)
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
        if self.path == "/protocols/accept-workflow":
            result = cli_to_cli_acceptance_report(
                runtime.registry,
                runtime.workflow_runner,
                payload["workflow_path"],
                run=bool(payload.get("run", False)),
                dry_run=bool(payload.get("dry_run", False)),
                confirmed=bool(payload.get("confirmed", False)),
                include_payloads=bool(payload.get("include_payloads", False)),
            )
            self._send(200 if result["ok"] else 422, result)
            return
        if self.path == "/protocols/acceptance-queue":
            workflow_paths = payload.get("workflow_paths", payload.get("workflow_path", []))
            if isinstance(workflow_paths, str):
                workflow_paths = [workflow_paths]
            if not isinstance(workflow_paths, list) or not all(isinstance(item, str) for item in workflow_paths):
                self._send(400, {"error": "workflow_paths must be a list of strings"})
                return
            result = cli_to_cli_acceptance_queue(
                runtime.registry,
                runtime.workflow_runner,
                workflow_paths=tuple(workflow_paths) or None,
                max_workflows=int(payload.get("max_workflows", 50)),
                run=bool(payload.get("run", False)),
                dry_run=bool(payload.get("dry_run", False)),
                confirmed=bool(payload.get("confirmed", False)),
                include_payloads=bool(payload.get("include_payloads", False)),
            )
            self._send(200 if result["ok"] else 422, result)
            return
        if self.path == "/protocols/bridge-lab":
            workflow_paths = payload.get("workflow_paths", payload.get("workflow_path", []))
            if isinstance(workflow_paths, str):
                workflow_paths = [workflow_paths]
            if not isinstance(workflow_paths, list) or not all(isinstance(item, str) for item in workflow_paths):
                self._send(400, {"error": "workflow_paths must be a list of strings"})
                return
            result = bridge_lab_report(
                runtime.registry,
                runtime.workflow_runner,
                workflow_paths=tuple(workflow_paths),
                max_workflows=int(payload.get("max_workflows", 10)),
                run=bool(payload.get("run", False)),
                dry_run=bool(payload.get("dry_run", True)),
                confirmed=bool(payload.get("confirmed", False)),
                include_payloads=bool(payload.get("include_payloads", False)),
                run_smoke_suite=bool(payload.get("smoke_suite", payload.get("run_smoke_suite", False))),
            )
            self._send(200 if result["ok"] else 422, result)
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
        if self.path == "/runtime/transports/gate":
            manager = PluginManager()
            result = manager.runtime_transport_gate(payload.get("kind", "pty"))
            self._send(200, result)
            return
        if self.path == "/runtime/transports/plan":
            manager = PluginManager()
            plan = manager.runtime_transport_plan(payload.get("kind", "pty"))
            self._send(200, plan.as_dict())
            return
        if self.path == "/runtime/transports/install":
            if not bool(payload.get("confirmed", False)):
                self._send(403, {"error": "runtime transport install requires confirmed=true"})
                return
            manager = PluginManager()
            kind = payload.get("kind", "pty")
            gate = manager.runtime_transport_gate(kind)
            if not gate["ok"]:
                self._send(409, gate)
                return
            plan = manager.runtime_transport_plan(kind)
            result = runtime.plugin_runner.execute(plan)
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
        if self.path == "/plugins/gate":
            manager = PluginManager()
            result = manager.operation_gate(
                payload["plugin_id"],
                action=payload.get("action", "install"),
            )
            self._send(200, result)
            return
        if self.path == "/plugins/check-update":
            manager = PluginManager()
            result = manager.update_check(
                payload["plugin_id"],
                remote=bool(payload.get("remote", False)),
            )
            self._send(200 if result["ready_for_update"] else 409, result)
            return
        if self.path == "/plugins/operation-plan":
            inputs = payload.get("inputs", {})
            if not isinstance(inputs, dict):
                self._send(400, {"error": "inputs must be an object"})
                return
            manager = PluginManager()
            result = manager.operation_plan(
                payload["plugin_id"],
                payload["operation_id"],
                inputs=inputs,
                confirmed=bool(payload.get("confirmed", False)),
            )
            self._send(200 if result["ok"] else 409, result)
            return
        if self.path == "/plugins/execute":
            if not bool(payload.get("confirmed", False)):
                self._send(403, {"error": "plugin execution requires confirmed=true"})
                return
            manager = PluginManager()
            action = payload.get("action", "install")
            if not bool(payload.get("allow_failed_preflight", False)):
                gate = manager.operation_gate(payload["plugin_id"], action=action)
                if not gate["ok"]:
                    self._send(409, gate)
                    return
            plan = manager.plan(
                payload["plugin_id"],
                action=action,
                include_codex_skill=bool(payload.get("include_codex_skill", False)),
            )
            result = runtime.plugin_runner.execute(plan)
            self._send(200 if result["status"] == "completed" else 409, result)
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
        if self.path == "/plugins/cli-anything/probe-harness":
            result = CliAnythingHub().probe_harness(
                payload["harness_name"],
                title=payload.get("title"),
                from_market=bool(payload.get("from_market", True)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/verify-harness":
            result = CliAnythingHub().verify_harness(
                payload["harness_name"],
                title=payload.get("title"),
                from_market=bool(payload.get("from_market", True)),
                include_workflows=bool(payload.get("include_workflows", True)),
                run_smoke_suite=bool(payload.get("run_smoke_suite", False)),
                smoke_extra_args=tuple(payload.get("smoke_extra_args", [])),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/onboard-harness":
            result = CliAnythingHub().onboard_harness(
                payload["harness_name"],
                title=payload.get("title"),
                from_market=bool(payload.get("from_market", True)),
                write=bool(payload.get("write", False)),
                confirmed=bool(payload.get("confirmed", False)),
                install=bool(payload.get("install", False)),
                allow_blocked=bool(payload.get("allow_blocked", False)),
                include_workflows=bool(payload.get("include_workflows", True)),
                run_smoke_suite=bool(payload.get("run_smoke_suite", False)),
                smoke_extra_args=tuple(payload.get("smoke_extra_args", [])),
                operation_runner=runtime.plugin_runner
                if bool(payload.get("install", False)) and bool(payload.get("confirmed", False))
                else None,
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/live-verification":
            harnesses = payload.get("harnesses", ["mermaid", "macrocli"])
            if not isinstance(harnesses, list) or not all(isinstance(item, str) for item in harnesses):
                self._send(400, {"error": "harnesses must be a list of strings"})
                return
            result = CliAnythingHub().live_verification(
                harnesses=tuple(harnesses),
                candidate_query=payload.get("candidate_query", "image"),
                candidate_limit=int(payload.get("candidate_limit", 10)),
                include_candidates=bool(payload.get("include_candidates", True)),
                include_workflows=bool(payload.get("include_workflows", True)),
                run_smoke_suite=bool(payload.get("run_smoke_suite", False)),
                smoke_extra_args=tuple(payload.get("smoke_extra_args", [])),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/mvp-plan":
            workflow_paths = payload.get("workflow_paths", payload.get("workflow_path", []))
            if isinstance(workflow_paths, str):
                workflow_paths = [workflow_paths]
            if not isinstance(workflow_paths, list) or not all(isinstance(item, str) for item in workflow_paths):
                self._send(400, {"error": "workflow_paths must be a list of strings"})
                return
            result = CliAnythingHub().mvp_plan(
                query=payload.get("query", "file"),
                limit=int(payload.get("limit", 20)),
                max_harnesses=int(payload.get("max_harnesses", 5)),
                include_blocked=bool(payload.get("include_blocked", True)),
                workflow_paths=tuple(workflow_paths),
                max_workflows=int(payload.get("max_workflows", 10)),
                registry=runtime.registry,
                workflow_runner=runtime.workflow_runner,
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/bootstrap-plan":
            result = CliAnythingHub().bootstrap_plan(
                harness_name=payload.get("harness_name", payload.get("harness", "mermaid")),
                query=payload.get("query", "file"),
                include_workflows=bool(payload.get("include_workflows", True)),
                workflow_path=payload.get(
                    "workflow_path",
                    "workflows/cli-anything-macrocli-mermaid-routing.example.json",
                ),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/candidates":
            result = CliAnythingHub().candidate_harnesses(
                query=payload.get("query"),
                limit=int(payload.get("limit", 50)),
                with_probes=bool(payload.get("with_probes", False)),
                compact=bool(payload.get("compact", False)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/install-queue":
            result = CliAnythingHub().market_install_queue(
                query=payload.get("query"),
                limit=int(payload.get("limit", 50)),
                max_installs=int(payload.get("max_installs", 10)),
                include_blocked=bool(payload.get("include_blocked", True)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/blocked-plan":
            harnesses = payload.get("harnesses", [])
            if not isinstance(harnesses, list) or not all(isinstance(item, str) for item in harnesses):
                self._send(400, {"error": "harnesses must be a list of strings"})
                return
            result = CliAnythingHub().blocked_harness_plan(
                harnesses=tuple(harnesses),
                query=payload.get("query"),
                limit=int(payload.get("limit", 50)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/repair-plan":
            result = CliAnythingHub().entrypoint_repair_plan(
                payload["harness_name"],
                from_market=bool(payload.get("from_market", True)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/repair-entrypoint":
            smoke_args_raw = payload.get("smoke_args", ["--help"])
            if not isinstance(smoke_args_raw, list) or not all(isinstance(item, str) for item in smoke_args_raw):
                self._send(400, {"error": "smoke_args must be a list of strings"})
                return
            result = CliAnythingHub().repair_entrypoint(
                payload["harness_name"],
                from_market=bool(payload.get("from_market", True)),
                module=payload.get("module"),
                write=bool(payload.get("write", False)),
                confirmed=bool(payload.get("confirmed", False)),
                require_smoke=bool(payload.get("require_smoke", False)),
                smoke_args=tuple(smoke_args_raw),
                smoke_timeout_seconds=int(payload.get("smoke_timeout_seconds", 10)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/promotion-gate":
            smoke_args_raw = payload.get("smoke_extra_args", [])
            if not isinstance(smoke_args_raw, list) or not all(isinstance(item, str) for item in smoke_args_raw):
                self._send(400, {"error": "smoke_extra_args must be a list of strings"})
                return
            result = CliAnythingHub().promotion_gate(
                payload["harness_name"],
                title=payload.get("title"),
                from_market=bool(payload.get("from_market", True)),
                include_workflows=bool(payload.get("include_workflows", True)),
                run_smoke_suite=bool(payload.get("run_smoke_suite", False)),
                smoke_extra_args=tuple(smoke_args_raw),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/adapter-targets":
            result = CliAnythingHub().adapter_targets(
                payload["harness_name"],
                from_market=bool(payload.get("from_market", True)),
                package=payload.get("package"),
                limit=int(payload.get("limit", 20)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/adapter-smoke":
            smoke_args_raw = payload.get("smoke_args", ["--help"])
            if not isinstance(smoke_args_raw, list) or not all(isinstance(item, str) for item in smoke_args_raw):
                self._send(400, {"error": "smoke_args must be a list of strings"})
                return
            result = CliAnythingHub().adapter_target_smoke(
                payload["harness_name"],
                module=payload["module"],
                from_market=bool(payload.get("from_market", True)),
                smoke_args=tuple(smoke_args_raw),
                timeout_seconds=int(payload.get("timeout_seconds", 10)),
                run=bool(payload.get("run", False)),
                confirmed=bool(payload.get("confirmed", False)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/adaptation-gate":
            smoke_args_raw = payload.get("smoke_args", ["--help"])
            if not isinstance(smoke_args_raw, list) or not all(isinstance(item, str) for item in smoke_args_raw):
                self._send(400, {"error": "smoke_args must be a list of strings"})
                return
            result = CliAnythingHub().adaptation_gate(
                payload["harness_name"],
                from_market=bool(payload.get("from_market", True)),
                module=payload.get("module"),
                require_smoke=bool(payload.get("require_smoke", True)),
                run_smoke=bool(payload.get("run_smoke", False)),
                confirmed=bool(payload.get("confirmed", False)),
                smoke_args=tuple(smoke_args_raw),
                smoke_timeout_seconds=int(payload.get("smoke_timeout_seconds", 10)),
            )
            self._send(200 if result["ok"] else 502, result)
            return
        if self.path == "/plugins/cli-anything/adaptation-queue":
            smoke_args_raw = payload.get("smoke_args", ["--help"])
            if not isinstance(smoke_args_raw, list) or not all(isinstance(item, str) for item in smoke_args_raw):
                self._send(400, {"error": "smoke_args must be a list of strings"})
                return
            harnesses = payload.get("harnesses", [])
            if not isinstance(harnesses, list) or not all(isinstance(item, str) for item in harnesses):
                self._send(400, {"error": "harnesses must be a list of strings"})
                return
            result = CliAnythingHub().adaptation_queue(
                harnesses=tuple(harnesses),
                query=payload.get("query"),
                limit=int(payload.get("limit", 20)),
                max_harnesses=int(payload.get("max_harnesses", 5)),
                include_blocked=bool(payload.get("include_blocked", True)),
                require_smoke=bool(payload.get("require_smoke", True)),
                run_smoke=bool(payload.get("run_smoke", False)),
                confirmed=bool(payload.get("confirmed", False)),
                smoke_args=tuple(smoke_args_raw),
                smoke_timeout_seconds=int(payload.get("smoke_timeout_seconds", 10)),
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
            if payload["action"] in {"install", "update"} and not bool(payload.get("allow_blocked", False)):
                gate = hub.harness_operation_gate(
                    payload["action"],
                    payload["harness_name"],
                    from_market=not bool(payload.get("offline", False)),
                )
                if not gate["ok"]:
                    self._send(409, gate)
                    return
            result = runtime.plugin_runner.execute(plan)
            self._send(200 if result["status"] == "completed" else 409, result)
            return
        self._send(404, {"error": "not found", "routes": ROUTE_SUMMARY})


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    server = ThreadingHTTPServer((host, port), CbnRequestHandler)
    token = os.environ.get(SESSION_TOKEN_ENV) or secrets.token_urlsafe(32)
    setattr(server, "session_token", token)
    print(f"CBN daemon API listening on http://{host}:{port}")
    print(f"CBN daemon session token: {token}")
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
