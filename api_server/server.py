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
from cbn_demo.killer import DEFAULT_KILLER_WORKFLOW_PATH, killer_demo_report
from cbn_demo.network_connect import DEFAULT_AGENT_CONNECT_MESSAGE, network_acceptance_report, network_connect_package
from cbn_core.import_catalog import cli_registration_surface
from cbn_core.manifest import validate_manifest_path
from cbn_execution.graph import WorkflowGraph
from cbn_parsers.fixtures import run_parser_fixtures
from cbn_parsers.registry import ParserRegistry
from cbn_protocol.acceptance import cli_to_cli_acceptance_report
from cbn_protocol.acceptance_queue import cli_to_cli_acceptance_queue
from cbn_protocol.a2a_http import agent_card, handle_a2a_jsonrpc_request
from cbn_core.bridge_contract import workflow_bridge_contract_report
from cbn_protocol.bridge_lab import bridge_lab_report
from cbn_core.message import bridge_args_from_selectors, validate_bridge_message
from cbn_core.selector import select_bridge_value
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
from cbn_protocol.wire_conformance import protocol_wire_conformance_suite
from cbn_runtime.context import build_runtime
from cbn_workflow.catalog import inspect_workflow, list_workflows
from cbn_adapter_agent.llm_validation import stream_with_glm
from cbn_adapter_agent.nodes import build_adapter_agent_node_bundle
from cbn_adapter_agent.orchestrator import (
    DEFAULT_WORKFLOW_PATH,
    ORCHESTRATION_SYSTEM_PROMPT,
    build_orchestration_context,
    build_orchestration_turn,
    fallback_message,
    llm_content_covers_fallbacks,
)
from cbn_adapter_agent.tool_use import run_setup_tool, store_session_secret
from cbn_adapter_agent.real_loop import run_agent_loop
from cbn_adapter_agent.tool_call_plan import build_agent_tool_call_plan
from cbn_adapter_agent.workflow_request import build_agent_workflow_request_plan
from cbn_plugins.cli_anything import CliAnythingHub
from cbn_plugins.manager import PluginManager
from cbn_tools.direct_cli_readiness import direct_cli_readiness_report


ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}
SESSION_TOKEN_ENV = "CBN_DAEMON_SESSION_TOKEN"
SESSION_TOKEN_REQUIRED_ENV = "CBN_DAEMON_REQUIRE_SESSION_TOKEN"


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
    {"method": "GET", "path": "/plugins/cli-anything/catalog"},
    {"method": "GET", "path": "/plugins/cli-anything/preflight"},
    {"method": "GET", "path": "/plugins/cli-anything/provenance"},
    {"method": "GET", "path": "/plugins/cli-anything/update-check"},
    {"method": "GET", "path": "/imports/catalog"},
    {"method": "GET", "path": "/audit"},
    {"method": "GET", "path": "/events"},
    {"method": "GET", "path": "/artifacts"},
    {"method": "GET", "path": "/parsers"},
    {"method": "GET", "path": "/parsers/fixtures"},
    {"method": "GET", "path": "/direct-cli/readiness"},
    {"method": "GET", "path": "/.well-known/agent-card.json"},
    {"method": "GET", "path": "/protocols"},
    {"method": "GET", "path": "/protocols/workflows"},
    {"method": "GET", "path": "/protocols/check"},
    {"method": "GET", "path": "/protocols/matrix"},
    {"method": "GET", "path": "/protocols/readiness"},
    {"method": "GET", "path": "/protocols/conformance-plan"},
    {"method": "GET", "path": "/protocols/lifecycle-suite"},
    {"method": "GET", "path": "/protocols/wire-conformance"},
    {"method": "GET", "path": "/protocols/smoke-suite"},
    {"method": "GET", "path": "/protocols/acceptance-queue"},
    {"method": "GET", "path": "/protocols/bridge-lab"},
    {"method": "GET", "path": "/demo/killer"},
    {"method": "GET", "path": "/network/connect-package"},
    {"method": "GET", "path": "/network/quickstart"},
    {"method": "GET", "path": "/network/acceptance"},
    {"method": "GET", "path": "/network/launch-contract"},
    {"method": "GET", "path": "/network/entry-profile"},
    {"method": "GET", "path": "/network/harness-agent"},
    {"method": "GET", "path": "/network/sdk-bootstrap"},
    {"method": "GET", "path": "/network/consumer-manifest"},
    {"method": "GET", "path": "/network/readiness"},
    {"method": "POST", "path": "/network/verify"},
    {"method": "POST", "path": "/protocols/accept-workflow"},
    {"method": "POST", "path": "/protocols/acceptance-queue"},
    {"method": "POST", "path": "/protocols/bridge-lab"},
    {"method": "POST", "path": "/demo/killer"},
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
    {"method": "GET", "path": "/adapter-agent/node-bundle"},
    {"method": "POST", "path": "/adapter-agent/workflow-request-plan"},
    {"method": "POST", "path": "/adapter-agent/orchestrate"},
    {"method": "POST", "path": "/adapter-agent/orchestrate-stream"},
    {"method": "POST", "path": "/adapter-agent/tool-call-plan"},
    {"method": "POST", "path": "/adapter-agent/tool-use"},
    {"method": "POST", "path": "/adapter-agent/run"},
    {"method": "POST", "path": "/runtime/transports/gate"},
    {"method": "POST", "path": "/runtime/transports/plan"},
    {"method": "POST", "path": "/runtime/transports/install"},
    {"method": "POST", "path": "/plugins/gate"},
    {"method": "POST", "path": "/plugins/check-update"},
    {"method": "POST", "path": "/plugins/operation-plan"},
    {"method": "POST", "path": "/plugins/verify-plan"},
    {"method": "POST", "path": "/plugins/plan"},
    {"method": "POST", "path": "/plugins/execute"},
    {"method": "POST", "path": "/plugins/cli-anything/market"},
    {"method": "POST", "path": "/plugins/cli-anything/install"},
    {"method": "POST", "path": "/plugins/cli-anything/import-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/adapt-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/prepare-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/evaluate-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/probe-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/verify-harness"},
    {"method": "POST", "path": "/plugins/cli-anything/verify-harness-plan"},
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


NETWORK_PAYLOAD_ROUTES: dict[str, tuple[tuple[str, ...], str | None]] = {
    "/network/connect-package": ((), None),
    "/network/quickstart": (("consumer_quickstart",), "NetworkConnectQuickstart"),
    "/network/acceptance": (("consumer_quickstart", "acceptance"), "NetworkConnectionAcceptance"),
    "/network/launch-contract": (("consumer_launch_contract",), "ConsumerLaunchContract"),
    "/network/entry-profile": (("network_entry_profile",), "NetworkEntryProfile"),
    "/network/harness-agent": (("network_harness_agent",), "NetworkHarnessAgent"),
    "/network/sdk-bootstrap": (("consumer_sdk_bootstrap",), "ConsumerSdkBootstrap"),
    "/network/consumer-manifest": (("consumer_manifest",), "NetworkConsumerManifest"),
    "/network/readiness": (("mvp_readiness",), "KillerMvpReadiness"),
}


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
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _send_stream_headers(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        cors_origin = self._cors_origin()
        if cors_origin:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-CBN-Session")
        self.end_headers()

    def _write_stream_event(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.wfile.write(body + b"\n")
        self.wfile.flush()

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

    def _adapter_agent_env(self) -> dict[str, str]:
        env_store = getattr(self.server, "adapter_agent_env", None)
        if env_store is None:
            env_store = {}
            setattr(self.server, "adapter_agent_env", env_store)
        return env_store

    def _handle_adapter_agent_stream(self, payload: dict[str, Any]) -> None:
        context = self._adapter_agent_stream_context(payload)
        if context is None:
            return
        self._send_stream_headers()
        self._write_adapter_agent_plan_event(context)
        if not bool(payload.get("use_glm", True)):
            self._write_adapter_agent_glm_disabled(context)
            return
        content, stream_meta = self._stream_adapter_agent_glm(context)
        self._write_adapter_agent_final_turn(context, content, stream_meta)

    def _adapter_agent_stream_context(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        workflow_path = payload.get("workflow_path") or payload.get("path") or DEFAULT_WORKFLOW_PATH
        message = payload.get("message", "")
        if not isinstance(workflow_path, str) or not workflow_path:
            self._send_error(400, "bad_request", "workflow_path must be a non-empty string")
            return None
        if not isinstance(message, str):
            self._send_error(400, "bad_request", "message must be a string")
            return None
        return build_orchestration_context(message=message, workflow_path=workflow_path)

    def _write_adapter_agent_plan_event(self, context: dict[str, Any]) -> None:
        plan_turn = _adapter_agent_turn_from_context(
            context,
            assistant_message="Preparing Adapter Agent turn...",
            glm={"ok": False, "streaming": True, "content": ""},
            glm_content_accepted=False,
        )
        self._write_stream_event({"type": "plan", "payload": plan_turn})

    def _write_adapter_agent_glm_disabled(self, context: dict[str, Any]) -> None:
        fallback = fallback_message(context)
        final_turn = _adapter_agent_turn_from_context(
            context,
            assistant_message=fallback,
            glm={"ok": False, "skipped": True, "reason": "GLM disabled by request"},
            glm_content_accepted=False,
        )
        self._write_stream_event({"type": "fallback", "text": fallback})
        self._write_stream_event({"type": "turn", "payload": final_turn})
        self._write_stream_event({"type": "done", "ok": True, "glm_content_accepted": False})

    def _stream_adapter_agent_glm(self, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        content_parts: list[str] = []
        stream_meta: dict[str, Any] = {"ok": True, "streaming": True}
        for event in stream_with_glm(context, system_prompt=ORCHESTRATION_SYSTEM_PROMPT):
            stream_meta = self._handle_adapter_agent_glm_event(event, content_parts, stream_meta)
        return "".join(content_parts), stream_meta

    def _handle_adapter_agent_glm_event(
        self,
        event: dict[str, Any],
        content_parts: list[str],
        stream_meta: dict[str, Any],
    ) -> dict[str, Any]:
        event_type = event.get("type")
        if event_type == "delta":
            text = str(event.get("text", ""))
            if text:
                content_parts.append(text)
                self._write_stream_event({"type": "delta", "text": text})
        elif event_type == "error":
            error_message = event.get("error") or event.get("reason") or event.get("body_summary")
            stream_meta = {"ok": False, "streaming": True, "error": error_message}
            self._write_stream_event({"type": "error", "error": error_message})
        elif event_type == "done":
            stream_meta.update(
                {
                    "ok": stream_meta.get("ok", True),
                    "model": event.get("model"),
                    "endpoint": event.get("endpoint"),
                }
            )
        return stream_meta

    def _write_adapter_agent_final_turn(
        self,
        context: dict[str, Any],
        content: str,
        stream_meta: dict[str, Any],
    ) -> None:
        accepted = llm_content_covers_fallbacks(content, context["auth_fallbacks"])
        assistant_message = content if accepted else fallback_message(context)
        if not accepted:
            self._write_stream_event({"type": "fallback", "text": assistant_message})
        final_turn = _adapter_agent_turn_from_context(
            context,
            assistant_message=assistant_message,
            glm={**stream_meta, "content_chars": len(content)},
            glm_content_accepted=accepted,
        )
        self._write_stream_event({"type": "turn", "payload": final_turn})
        self._write_stream_event({"type": "done", "ok": True, "glm_content_accepted": accepted})

    def _handle_adapter_agent_tool_use(self, payload: dict[str, Any]) -> None:
        runtime = build_runtime()
        action = payload.get("action")
        if action == "store-secret":
            result = store_session_secret(
                self._adapter_agent_env(),
                name=_required_string(payload, "name"),
                value=_required_string(payload, "value"),
                audit_log=runtime.audit_log,
                event_bus=runtime.event_bus,
            )
            self._send(200 if result["ok"] else 400, result)
            return
        if action == "run-setup-tool":
            workflow_path = payload.get("workflow_path") or payload.get("path") or DEFAULT_WORKFLOW_PATH
            if not isinstance(workflow_path, str) or not workflow_path:
                self._send_error(400, "bad_request", "workflow_path must be a non-empty string")
                return
            result = run_setup_tool(
                workflow_path=workflow_path,
                setup_id=_required_string(payload, "setup_id"),
                command_id=_required_string(payload, "command_id"),
                env_store=self._adapter_agent_env(),
                timeout_seconds=int(payload.get("timeout_seconds", 30)),
                audit_log=runtime.audit_log,
                event_bus=runtime.event_bus,
            )
            self._send(200 if result["ok"] else 409, result)
            return
        self._send_error(400, "bad_request", f"unknown Adapter Agent tool-use action: {action}")

    def _handle_adapter_agent_run(self, payload: dict[str, Any]) -> None:
        message = payload.get("message", "")
        permission = payload.get("permission") or payload.get("permission_mode") or "full"
        if not isinstance(message, str) or not message.strip():
            self._send_error(400, "bad_request", "message must be a non-empty string")
            return
        runtime = build_runtime()
        runtime.executor.session_env.update(self._adapter_agent_env())
        self._send_stream_headers()
        try:
            run_agent_loop(
                message=message,
                permission=str(permission),
                executor=runtime.executor,
                registry=runtime.registry,
                env_store=self._adapter_agent_env(),
                on_event=self._write_stream_event,
                audit_log=runtime.audit_log,
                event_bus=runtime.event_bus,
            )
        except Exception as exc:  # keep the stream well-formed even on a loop crash
            self._write_stream_event({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
            self._write_stream_event({"type": "done", "ok": False})

    def _handle_cli_anything_install(self, payload: dict[str, Any]) -> None:
        import subprocess

        name = str(payload.get("name", "")).strip()
        if not name:
            self._send_error(400, "bad_request", "name is required")
            return
        hub = CliAnythingHub()
        entrypoint = hub.status().get("entrypoint_path") or "cli-hub"
        self._send_stream_headers()
        self._write_stream_event({"type": "start", "name": name})
        try:
            proc = subprocess.Popen(
                [entrypoint, "install", name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            stdout = proc.stdout
            if stdout is not None:
                for line in stdout:
                    self._write_stream_event({"type": "line", "text": line.rstrip("\n")[:500]})
            rc = proc.wait()
            self._write_stream_event({"type": "done", "name": name, "exit_code": rc, "ok": rc == 0})
        except Exception as exc:
            self._write_stream_event({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
            self._write_stream_event({"type": "done", "ok": False})

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
        expected = _server_session_token(self.server)
        if expected is None:
            return True
        token = self._session_token_from_headers()
        if secrets.compare_digest(token, expected):
            return True
        self._send_error(403, "session_denied", "valid daemon session token required")
        return False

    def _session_token_from_headers(self) -> str:
        token = self.headers.get("X-CBN-Session", "")
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
        return token

    def _handle_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if self._handle_static_GET(parsed.path, query):
            return
        runtime = build_runtime()
        if self._handle_runtime_GET(parsed.path, query, runtime):
            return
        if self._handle_protocol_GET(parsed.path, query, runtime):
            return
        if self._handle_demo_network_GET(parsed.path, query, runtime):
            return
        if self._handle_misc_GET(parsed.path, query, runtime):
            return
        self._send(404, {"error": "not found", "routes": ROUTE_SUMMARY})

    def _handle_static_GET(self, path: str, query: dict[str, list[str]]) -> bool:
        if path == "/health":
            self._send_health()
            return True
        if path == "/.well-known/agent-card.json":
            self._send(200, agent_card(_base_url(self)))
            return True
        if path in _STATIC_GET_ROUTES:
            _STATIC_GET_ROUTES[path](self, query)
            return True
        return False

    def _send_health(self) -> None:
        token_required = _server_session_token(self.server) is not None
        self._send(
            200,
            health_payload(
                session_token_required=token_required,
                session_token_supplied=bool(self._session_token_from_headers()),
                session_token_mode="required" if token_required else "local_default_disabled",
                session_token_source=_server_session_token_source(self.server),
                local_session_token_default=bool(getattr(self.server, "local_session_token_default", False)),
            ),
        )

    def _handle_runtime_GET(self, path: str, query: dict[str, list[str]], runtime: Any) -> bool:
        if path == "/registry":
            self._send_registry_GET(query, runtime)
            return True
        if path in _RUNTIME_GET_ROUTES:
            _RUNTIME_GET_ROUTES[path](self, query, runtime)
            return True
        return False

    def _send_registry_GET(self, query: dict[str, list[str]], runtime: Any) -> None:
        capability_id = query.get("capability_id", [None])[0]
        search_query = query.get("q", [None])[0]
        if capability_id:
            self._send(200, runtime.registry.require(capability_id).as_record())
        elif search_query is not None:
            self._send(200, runtime.registry.search(search_query, limit=int(query.get("limit", ["20"])[0])))
        else:
            self._send(200, [manifest.as_record() for manifest in runtime.registry.list()])

    def _handle_protocol_GET(self, path: str, query: dict[str, list[str]], runtime: Any) -> bool:
        if path in _PROTOCOL_GET_ROUTES:
            _PROTOCOL_GET_ROUTES[path](self, query, runtime)
            return True
        return False

    def _handle_demo_network_GET(self, path: str, query: dict[str, list[str]], runtime: Any) -> bool:
        if path == "/demo/killer":
            self._send_killer_demo_GET(query, runtime)
            return True
        if path in NETWORK_PAYLOAD_ROUTES:
            result = _network_connect_package_from_query(self, runtime, query)
            payload, expected_kind = _network_payload(result, path)
            self._send(200 if _network_payload_ok(result, payload, expected_kind) else 422, payload)
            return True
        return False

    def _send_killer_demo_GET(self, query: dict[str, list[str]], runtime: Any) -> None:
        result = killer_demo_report(
            runtime.registry,
            runtime.workflow_runner,
            workflow_path=query.get("workflow_path", query.get("path", [DEFAULT_KILLER_WORKFLOW_PATH]))[0],
            run=_query_bool(query, "run", default=True),
            dry_run=_query_bool(query, "dry_run", default=True),
            confirmed=_query_bool(query, "confirmed", default=False),
            include_payloads=_query_bool(query, "include_payloads", default=False),
            run_smoke_suite=_query_bool(query, "smoke_suite", default=True),
            event_tail=runtime.event_bus.tail(limit=30),
            audit_tail=runtime.audit_log.tail(limit=30),
            artifact_list=runtime.artifact_store.list(limit=30),
        )
        self._send(200 if result["ok"] else 422, result)

    def _handle_misc_GET(self, path: str, query: dict[str, list[str]], runtime: Any) -> bool:
        if path == "/approvals":
            self._send_approvals_GET(query, runtime)
            return True
        if path == "/workflows":
            self._send_workflows_GET(query, runtime)
            return True
        if path == "/messages/contract":
            workflow_path = query.get("workflow_path", query.get("path", [None]))[0]
            result = workflow_bridge_contract_report(runtime.registry, workflow_path=workflow_path)
            self._send(200 if result["ok"] else 422, result)
            return True
        if path == "/adapter-agent/node-bundle":
            self._send_adapter_agent_node_bundle_GET(query)
            return True
        return False

    def _send_approvals_GET(self, query: dict[str, list[str]], runtime: Any) -> None:
        approval_id = query.get("approval_id", [None])[0]
        if approval_id:
            self._send(200, runtime.approval_store.inspect(approval_id))
        else:
            limit = int(query.get("limit", ["50"])[0])
            status = query.get("status", [None])[0]
            self._send(200, runtime.approval_store.list(status=status, limit=limit))

    def _send_workflows_GET(self, query: dict[str, list[str]], runtime: Any) -> None:
        path = query.get("path", [None])[0]
        if path:
            result = inspect_workflow(Path(path), registry=runtime.registry)
            self._send(200 if result["valid"] else 422, result)
        else:
            self._send(200, list_workflows(registry=runtime.registry))

    def _send_adapter_agent_node_bundle_GET(self, query: dict[str, list[str]]) -> None:
        workflow_path = query.get("workflow_path", query.get("path", [DEFAULT_WORKFLOW_PATH]))[0]
        if not workflow_path:
            self._send_error(400, "bad_request", "workflow_path must be a non-empty string")
            return
        self._send(
            200,
            build_adapter_agent_node_bundle(
                workflow_path=workflow_path,
                message=query.get("message", [""])[0],
                profiles=_query_profiles(query),
            ),
        )

    def _handle_core_POST(self, payload: dict[str, Any], runtime: Any) -> bool:
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
            return True
        if self.path == "/a2a":
            self._send(200, handle_a2a_jsonrpc_request(payload))
            return True
        if self.path in _MESSAGE_POST_ROUTES:
            _MESSAGE_POST_ROUTES[self.path](self, payload)
            return True
        if self.path == "/approvals/decide":
            self._send_approval_decision_POST(payload, runtime)
            return True
        return False

    def _send_approval_decision_POST(self, payload: dict[str, Any], runtime: Any) -> None:
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

    def _handle_protocol_demo_POST(self, payload: dict[str, Any], runtime: Any) -> bool:
        if self.path in _PROTOCOL_POST_ROUTES:
            _PROTOCOL_POST_ROUTES[self.path](self, payload, runtime)
            return True
        if self.path == "/demo/killer":
            self._send_killer_demo_POST(payload, runtime)
            return True
        if self.path == "/network/verify":
            self._send_network_verify_POST(payload, runtime)
            return True
        return False

    def _send_killer_demo_POST(self, payload: dict[str, Any], runtime: Any) -> None:
        result = killer_demo_report(
            runtime.registry,
            runtime.workflow_runner,
            workflow_path=str(payload.get("workflow_path") or payload.get("path") or DEFAULT_KILLER_WORKFLOW_PATH),
            run=bool(payload.get("run", True)),
            dry_run=bool(payload.get("dry_run", True)),
            confirmed=bool(payload.get("confirmed", False)),
            include_payloads=bool(payload.get("include_payloads", False)),
            run_smoke_suite=bool(payload.get("smoke_suite", payload.get("run_smoke_suite", True))),
            event_tail=runtime.event_bus.tail(limit=30),
            audit_tail=runtime.audit_log.tail(limit=30),
            artifact_list=runtime.artifact_store.list(limit=30),
        )
        self._send(200 if result["ok"] else 422, result)

    def _send_network_verify_POST(self, payload: dict[str, Any], runtime: Any) -> None:
        result = network_acceptance_report(
            runtime.registry,
            **self._network_verify_POST_params(payload),
        )
        self._send(200 if result["ok"] else 422, result)

    def _network_verify_POST_params(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_token = _payload_alias(payload, "session_token", "sessionToken") or self.headers.get("X-CBN-Session")
        return {
            "workflow_path": _payload_alias(payload, "workflow_path", "path", default=DEFAULT_KILLER_WORKFLOW_PATH),
            "base_url": _payload_alias(payload, "base_url", "daemon_url", default=_base_url(self)),
            "studio_url": _payload_alias(payload, "studio_url", default="http://127.0.0.1:5177"),
            "dashboard_url": _payload_alias(payload, "dashboard_url", "dashboardUrl", default="http://127.0.0.1:5173"),
            "session_token": str(session_token) if session_token else None,
            "agent_message": _payload_alias(payload, "message", default=DEFAULT_AGENT_CONNECT_MESSAGE),
            "timeout_seconds": float(payload.get("timeout_seconds", 8.0)),
        }

    def _handle_workflow_POST(self, payload: dict[str, Any], runtime: Any) -> bool:
        if self.path not in {"/workflows/validate", "/workflows/plan", "/workflows/run"}:
            return False
        graph = WorkflowGraph.from_dict(payload["workflow"]) if "workflow" in payload else WorkflowGraph.from_file(Path(payload["path"]))
        if self.path == "/workflows/validate":
            graph.validate()
            self._send(200, {"valid": True, "workflow_id": graph.workflow_id})
        elif self.path == "/workflows/plan":
            self._send(200, runtime.workflow_runner.plan(graph))
        else:
            result = runtime.workflow_runner.run(
                graph,
                dry_run=bool(payload.get("dry_run", False)),
                confirmed=bool(payload.get("confirmed", False)),
            )
            self._send(200 if result["status"] == "completed" else 409, result)
        return True

    def _handle_adapter_runtime_POST(self, payload: dict[str, Any], runtime: Any) -> bool:
        if self.path in _ADAPTER_AGENT_POST_ROUTES:
            _ADAPTER_AGENT_POST_ROUTES[self.path](self, payload)
            return True
        if self.path in _RUNTIME_TRANSPORT_POST_ROUTES:
            _RUNTIME_TRANSPORT_POST_ROUTES[self.path](self, payload, runtime)
            return True
        return False

    def _handle_plugin_manager_POST(self, payload: dict[str, Any], runtime: Any) -> bool:
        if self.path in _PLUGIN_MANAGER_POST_ROUTES:
            _PLUGIN_MANAGER_POST_ROUTES[self.path](self, payload, runtime)
            return True
        return False

    def _handle_POST(self) -> None:
        runtime = build_runtime()
        runtime.executor.session_env.update(self._adapter_agent_env())
        payload = self._read_json()
        if self._handle_core_POST(payload, runtime):
            return
        if self._handle_protocol_demo_POST(payload, runtime):
            return
        if self._handle_workflow_POST(payload, runtime):
            return
        if self._handle_adapter_runtime_POST(payload, runtime):
            return
        if self._handle_plugin_manager_POST(payload, runtime):
            return
        if self.path in _CLI_ANYTHING_POST_ROUTES:
            _CLI_ANYTHING_POST_ROUTES[self.path](self, payload, runtime)
            return
        self._send(404, {"error": "not found", "routes": ROUTE_SUMMARY})


def _get_plugins(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    handler._send(200, PluginManager().list_plugins())


def _get_plugin_operations(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    handler._send(200, PluginManager().operation_catalog(query.get("plugin_id", [None])[0]))


def _get_plugin_operations_validate(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    result = PluginManager().validate_operation_catalog(query.get("plugin_id", [None])[0])
    handler._send(200 if result["ok"] else 422, result)


def _get_cli_anything_status(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    handler._send(200, CliAnythingHub().status())


def _get_cli_anything_catalog(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    """CLI-Anything market catalog + plugin status for the dedicated market panel."""
    import json as _json

    hub = CliAnythingHub()
    status = hub.status()
    result = hub.list_market()
    catalog: list[dict[str, object]] = []
    parsed = getattr(result, "parsed_json", None)
    if isinstance(parsed, list):
        catalog = parsed
    else:
        stdout = getattr(result, "stdout", "") or ""
        try:
            data = _json.loads(stdout)
            if isinstance(data, list):
                catalog = data
        except (ValueError, TypeError):
            catalog = []
    handler._send(200, {"status": status, "catalog": catalog})


def _get_cli_anything_preflight(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    handler._send(200, PluginManager().preflight("cli-anything"))


def _get_cli_anything_provenance(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    handler._send(200, PluginManager().provenance("cli-anything"))


def _get_cli_anything_update_check(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    result = PluginManager().update_check("cli-anything", remote=_query_bool(query, "remote", default=False))
    handler._send(200 if result["ready_for_update"] else 409, result)


def _get_imports_catalog(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    handler._send(200, cli_registration_surface())


def _get_runtime_transports(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    kind = query.get("kind", ["pty"])[0]
    handler._send(200, PluginManager().runtime_transport_status(kind))


def _get_registry_validate(handler: CbnRequestHandler, query: dict[str, list[str]]) -> None:
    result = validate_manifest_path(Path(query.get("path", ["manifests"])[0]), known_parser_refs=_known_parser_refs())
    handler._send(200 if result["valid"] else 422, result)


_STATIC_GET_ROUTES = {
    "/plugins": _get_plugins,
    "/plugins/operations": _get_plugin_operations,
    "/plugins/operations/validate": _get_plugin_operations_validate,
    "/plugins/cli-anything/status": _get_cli_anything_status,
    "/plugins/cli-anything/catalog": _get_cli_anything_catalog,
    "/plugins/cli-anything/preflight": _get_cli_anything_preflight,
    "/plugins/cli-anything/provenance": _get_cli_anything_provenance,
    "/plugins/cli-anything/update-check": _get_cli_anything_update_check,
    "/imports/catalog": _get_imports_catalog,
    "/runtime/transports": _get_runtime_transports,
    "/registry/validate": _get_registry_validate,
}


def _get_audit(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    handler._send(200, runtime.audit_log.tail())


def _get_events(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    handler._send(200, runtime.event_bus.tail(limit=int(query.get("limit", ["50"])[0])))


def _get_artifacts(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    artifact_id = query.get("artifact_id", [None])[0]
    if artifact_id:
        handler._send(200, runtime.artifact_store.inspect(artifact_id))
    else:
        handler._send(200, runtime.artifact_store.list(limit=int(query.get("limit", ["50"])[0])))


def _get_parsers(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    parser_ref = query.get("parser_ref", [None])[0]
    if parser_ref:
        handler._send(200, runtime.parser_registry.inspect(parser_ref))
    else:
        handler._send(200, runtime.parser_registry.list())


def _get_parser_fixtures(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    result = run_parser_fixtures(
        Path(query.get("path", ["parser_fixtures"])[0]),
        parser_ref=query.get("parser_ref", [None])[0],
        registry=runtime.parser_registry,
    )
    handler._send(200 if result["ok"] else 422, result)


def _get_direct_cli_readiness(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    result = direct_cli_readiness_report(runtime, fixture_path=Path(query.get("path", ["parser_fixtures"])[0]))
    handler._send(200 if result["ok"] else 422, result)


_RUNTIME_GET_ROUTES = {
    "/audit": _get_audit,
    "/events": _get_events,
    "/artifacts": _get_artifacts,
    "/parsers": _get_parsers,
    "/parsers/fixtures": _get_parser_fixtures,
    "/direct-cli/readiness": _get_direct_cli_readiness,
}


def _get_protocols(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    target = query.get("target", [None])[0]
    capability_id = query.get("capability_id", [None])[0]
    if target == "all":
        handler._send(200, export_all_protocols(runtime.registry, capability_id=capability_id))
    elif target:
        handler._send(200, export_protocol(runtime.registry, target, capability_id=capability_id))
    else:
        handler._send(200, list_protocol_exports())


def _get_protocol_workflows(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    target = query.get("target", ["all"])[0]
    workflow_path = query.get("path", [None])[0]
    if target == "all":
        handler._send(200, export_all_workflow_protocols(runtime.registry, workflow_path=workflow_path))
    else:
        handler._send(200, export_workflow_protocol(runtime.registry, target, workflow_path=workflow_path))


def _get_protocol_check(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    handler._send(
        200,
        check_protocol(
            runtime.registry,
            query.get("target", ["all"])[0],
            capability_id=query.get("capability_id", [None])[0],
            workflow_path=query.get("path", query.get("workflow_path", [None]))[0],
        ),
    )


def _get_protocol_matrix(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    handler._send(200, protocol_matrix(runtime.registry, include_workflows=_query_bool(query, "include_workflows", default=False)))


def _get_protocol_readiness(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    result = protocol_readiness_report(
        runtime.registry,
        workflow_path=query.get("workflow_path", query.get("path", [None]))[0],
        include_workflows=_query_bool(query, "include_workflows", default=True),
    )
    handler._send(200 if result["ok"] else 422, result)


def _get_protocol_conformance_plan(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    result = protocol_conformance_plan(
        runtime.registry,
        target=query.get("target", ["all"])[0],
        capability_id=query.get("capability_id", [None])[0],
        workflow_path=query.get("workflow_path", query.get("path", [None]))[0],
    )
    handler._send(200 if result["ok"] else 422, result)


def _get_protocol_lifecycle_suite(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    result = protocol_lifecycle_suite(
        capability_id=query.get("capability_id", ["git.version"])[0],
        workflow_path=query.get("workflow_path", query.get("path", ["workflows/example.json"]))[0],
    )
    handler._send(200 if result["ok"] else 422, result)


def _get_protocol_wire_conformance(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    result = protocol_wire_conformance_suite(
        target=query.get("target", ["all"])[0],
        capability_id=query.get("capability_id", ["git.version"])[0],
    )
    handler._send(200 if result["ok"] else 422, result)


def _get_protocol_smoke_suite(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    result = protocol_smoke_suite(
        runtime.registry,
        capability_ids=query.get("capability_id") or None,
        workflow_paths=query.get("workflow_path") or query.get("path") or None,
        extra_args=query.get("extra_arg", []),
        dry_run=_query_bool(query, "dry_run", default=False),
        workflow_dry_run=_query_bool(query, "workflow_dry_run", default=False),
        workflow_confirmed=_query_bool(query, "confirmed", default=False),
        include_payloads=_query_bool(query, "include_payloads", default=False),
    )
    handler._send(200 if result["ok"] else 422, result)


def _get_protocol_acceptance_queue(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    result = cli_to_cli_acceptance_queue(
        runtime.registry,
        runtime.workflow_runner,
        workflow_paths=query.get("workflow_path") or query.get("path") or None,
        max_workflows=int(query.get("max_workflows", ["50"])[0]),
        run=_query_bool(query, "run", default=False),
        dry_run=_query_bool(query, "dry_run", default=False),
        confirmed=_query_bool(query, "confirmed", default=False),
        include_payloads=_query_bool(query, "include_payloads", default=False),
    )
    handler._send(200 if result["ok"] else 422, result)


def _get_protocol_bridge_lab(handler: CbnRequestHandler, query: dict[str, list[str]], runtime: Any) -> None:
    result = bridge_lab_report(
        runtime.registry,
        runtime.workflow_runner,
        workflow_paths=tuple(query.get("workflow_path") or query.get("path") or ()),
        max_workflows=int(query.get("max_workflows", ["10"])[0]),
        run=False,
        dry_run=True,
        confirmed=False,
        include_payloads=False,
        run_smoke_suite=_query_bool(query, "smoke_suite", default=False),
    )
    handler._send(200 if result["ok"] else 422, result)


_PROTOCOL_GET_ROUTES = {
    "/protocols": _get_protocols,
    "/protocols/workflows": _get_protocol_workflows,
    "/protocols/check": _get_protocol_check,
    "/protocols/matrix": _get_protocol_matrix,
    "/protocols/readiness": _get_protocol_readiness,
    "/protocols/conformance-plan": _get_protocol_conformance_plan,
    "/protocols/lifecycle-suite": _get_protocol_lifecycle_suite,
    "/protocols/wire-conformance": _get_protocol_wire_conformance,
    "/protocols/smoke-suite": _get_protocol_smoke_suite,
    "/protocols/acceptance-queue": _get_protocol_acceptance_queue,
    "/protocols/bridge-lab": _get_protocol_bridge_lab,
}


def _post_message_validate(handler: CbnRequestHandler, payload: dict[str, Any]) -> None:
    result = validate_bridge_message(payload["message"])
    handler._send(200 if result["valid"] else 422, result)


def _post_message_select(handler: CbnRequestHandler, payload: dict[str, Any]) -> None:
    try:
        handler._send(200, select_bridge_value(payload["message"], payload["selector"]))
    except (KeyError, IndexError, ValueError) as exc:
        handler._send(400, {"error": str(exc), "selector": payload.get("selector")})


def _post_message_args(handler: CbnRequestHandler, payload: dict[str, Any]) -> None:
    try:
        selectors = payload["selectors"]
        if not isinstance(selectors, list) or not all(isinstance(item, str) for item in selectors):
            handler._send(400, {"error": "selectors must be a list of strings"})
            return
        result = bridge_args_from_selectors(payload["message"], selectors)
        handler._send(200 if result["valid"] else 422, result)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        handler._send(400, {"error": str(exc), "selectors": payload.get("selectors")})


_MESSAGE_POST_ROUTES = {
    "/messages/validate": _post_message_validate,
    "/messages/select": _post_message_select,
    "/messages/args": _post_message_args,
}


def _payload_workflow_paths(payload: dict[str, Any]) -> tuple[str, ...] | None:
    workflow_paths = payload.get("workflow_paths", payload.get("workflow_path", []))
    if isinstance(workflow_paths, str):
        workflow_paths = [workflow_paths]
    if not isinstance(workflow_paths, list) or not all(isinstance(item, str) for item in workflow_paths):
        raise ValueError("workflow_paths must be a list of strings")
    return tuple(workflow_paths) or None


def _post_protocol_accept_workflow(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = cli_to_cli_acceptance_report(
        runtime.registry,
        runtime.workflow_runner,
        payload["workflow_path"],
        run=bool(payload.get("run", False)),
        dry_run=bool(payload.get("dry_run", False)),
        confirmed=bool(payload.get("confirmed", False)),
        include_payloads=bool(payload.get("include_payloads", False)),
    )
    handler._send(200 if result["ok"] else 422, result)


def _post_protocol_acceptance_queue(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    try:
        workflow_paths = _payload_workflow_paths(payload)
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
        return
    result = cli_to_cli_acceptance_queue(
        runtime.registry,
        runtime.workflow_runner,
        workflow_paths=workflow_paths,
        max_workflows=int(payload.get("max_workflows", 50)),
        run=bool(payload.get("run", False)),
        dry_run=bool(payload.get("dry_run", False)),
        confirmed=bool(payload.get("confirmed", False)),
        include_payloads=bool(payload.get("include_payloads", False)),
    )
    handler._send(200 if result["ok"] else 422, result)


def _post_protocol_bridge_lab(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    try:
        workflow_paths = _payload_workflow_paths(payload)
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
        return
    result = bridge_lab_report(
        runtime.registry,
        runtime.workflow_runner,
        workflow_paths=workflow_paths or (),
        max_workflows=int(payload.get("max_workflows", 10)),
        run=bool(payload.get("run", False)),
        dry_run=bool(payload.get("dry_run", True)),
        confirmed=bool(payload.get("confirmed", False)),
        include_payloads=bool(payload.get("include_payloads", False)),
        run_smoke_suite=bool(payload.get("smoke_suite", payload.get("run_smoke_suite", False))),
    )
    handler._send(200 if result["ok"] else 422, result)


_PROTOCOL_POST_ROUTES = {
    "/protocols/accept-workflow": _post_protocol_accept_workflow,
    "/protocols/acceptance-queue": _post_protocol_acceptance_queue,
    "/protocols/bridge-lab": _post_protocol_bridge_lab,
}


def _payload_workflow_and_message(
    handler: CbnRequestHandler,
    payload: dict[str, Any],
    *,
    default_workflow: str,
) -> tuple[str, str] | None:
    workflow_path = payload.get("workflow_path") or payload.get("path") or default_workflow
    message = payload.get("message", "")
    if not isinstance(workflow_path, str) or not workflow_path:
        handler._send_error(400, "bad_request", "workflow_path must be a non-empty string")
        return None
    if not isinstance(message, str):
        handler._send_error(400, "bad_request", "message must be a string")
        return None
    return workflow_path, message


def _post_adapter_orchestrate(handler: CbnRequestHandler, payload: dict[str, Any]) -> None:
    values = _payload_workflow_and_message(handler, payload, default_workflow=DEFAULT_WORKFLOW_PATH)
    if values is None:
        return
    workflow_path, message = values
    result = build_orchestration_turn(
        message=message,
        workflow_path=workflow_path,
        use_glm=bool(payload.get("use_glm", True)),
    )
    handler._send(200, result)


def _post_adapter_orchestrate_stream(handler: CbnRequestHandler, payload: dict[str, Any]) -> None:
    handler._handle_adapter_agent_stream(payload)


def _post_adapter_tool_call_plan(handler: CbnRequestHandler, payload: dict[str, Any]) -> None:
    values = _payload_workflow_and_message(handler, payload, default_workflow=DEFAULT_WORKFLOW_PATH)
    if values is None:
        return
    workflow_path, message = values
    handler._send(200, build_agent_tool_call_plan(workflow_path=workflow_path, message=message))


def _post_adapter_workflow_request_plan(handler: CbnRequestHandler, payload: dict[str, Any]) -> None:
    values = _payload_workflow_and_message(handler, payload, default_workflow=DEFAULT_KILLER_WORKFLOW_PATH)
    if values is None:
        return
    workflow_path, message = values
    result = build_agent_workflow_request_plan(
        workflow_path=workflow_path,
        message=message,
        base_url=_base_url(handler),
        dry_run=bool(payload.get("dry_run", True)),
        confirmed=bool(payload.get("confirmed", False)),
    )
    handler._send(200, result)


def _post_adapter_tool_use(handler: CbnRequestHandler, payload: dict[str, Any]) -> None:
    handler._handle_adapter_agent_tool_use(payload)


def _post_adapter_agent_run(handler: CbnRequestHandler, payload: dict[str, Any]) -> None:
    handler._handle_adapter_agent_run(payload)


_ADAPTER_AGENT_POST_ROUTES = {
    "/adapter-agent/orchestrate": _post_adapter_orchestrate,
    "/adapter-agent/orchestrate-stream": _post_adapter_orchestrate_stream,
    "/adapter-agent/tool-call-plan": _post_adapter_tool_call_plan,
    "/adapter-agent/workflow-request-plan": _post_adapter_workflow_request_plan,
    "/adapter-agent/tool-use": _post_adapter_tool_use,
    "/adapter-agent/run": _post_adapter_agent_run,
}


def _post_runtime_transport_gate(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    handler._send(200, PluginManager().runtime_transport_gate(payload.get("kind", "pty")))


def _post_runtime_transport_plan(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    handler._send(200, PluginManager().runtime_transport_plan(payload.get("kind", "pty")).as_dict())


def _post_runtime_transport_install(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    if not bool(payload.get("confirmed", False)):
        handler._send(403, {"error": "runtime transport install requires confirmed=true"})
        return
    manager = PluginManager()
    kind = payload.get("kind", "pty")
    gate = manager.runtime_transport_gate(kind)
    if not gate["ok"]:
        handler._send(409, gate)
        return
    result = runtime.plugin_runner.execute(manager.runtime_transport_plan(kind))
    handler._send(200 if result["status"] == "completed" else 409, result)


_RUNTIME_TRANSPORT_POST_ROUTES = {
    "/runtime/transports/gate": _post_runtime_transport_gate,
    "/runtime/transports/plan": _post_runtime_transport_plan,
    "/runtime/transports/install": _post_runtime_transport_install,
}


def _post_plugin_plan(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    plan = PluginManager().plan(
        payload["plugin_id"],
        action=payload.get("action", "install"),
        include_codex_skill=bool(payload.get("include_codex_skill", False)),
    )
    handler._send(200, plan.as_dict())


def _post_plugin_gate(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = PluginManager().operation_gate(payload["plugin_id"], action=payload.get("action", "install"))
    handler._send(200, result)


def _post_plugin_check_update(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = PluginManager().update_check(payload["plugin_id"], remote=bool(payload.get("remote", False)))
    handler._send(200 if result["ready_for_update"] else 409, result)


def _post_plugin_operation_plan(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    inputs = payload.get("inputs", {})
    if not isinstance(inputs, dict):
        handler._send(400, {"error": "inputs must be an object"})
        return
    result = PluginManager().operation_plan(
        payload["plugin_id"],
        payload["operation_id"],
        inputs=inputs,
        confirmed=bool(payload.get("confirmed", False)),
    )
    handler._send(200 if result["ok"] else 409, result)


def _post_plugin_verify_plan(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = PluginManager().verify_plan(
        payload["plugin_id"],
        action=payload.get("action", "install"),
        include_codex_skill=bool(payload.get("include_codex_skill", False)),
        run=bool(payload.get("run", False)),
        timeout_seconds=int(payload.get("timeout_seconds", 60)),
    )
    handler._send(200 if result["ok"] else 409, result)


def _post_plugin_execute(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    if not bool(payload.get("confirmed", False)):
        handler._send(403, {"error": "plugin execution requires confirmed=true"})
        return
    manager = PluginManager()
    action = payload.get("action", "install")
    if not bool(payload.get("allow_failed_preflight", False)):
        gate = manager.operation_gate(payload["plugin_id"], action=action)
        if not gate["ok"]:
            handler._send(409, gate)
            return
    plan = manager.plan(
        payload["plugin_id"],
        action=action,
        include_codex_skill=bool(payload.get("include_codex_skill", False)),
    )
    result = runtime.plugin_runner.execute(plan)
    handler._send(200 if result["status"] == "completed" else 409, result)


_PLUGIN_MANAGER_POST_ROUTES = {
    "/plugins/plan": _post_plugin_plan,
    "/plugins/gate": _post_plugin_gate,
    "/plugins/check-update": _post_plugin_check_update,
    "/plugins/operation-plan": _post_plugin_operation_plan,
    "/plugins/verify-plan": _post_plugin_verify_plan,
    "/plugins/execute": _post_plugin_execute,
}


def _string_list_payload(payload: dict[str, Any], field: str, default: list[str] | None = None) -> list[str]:
    value = payload.get(field, default or [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return value


def _post_cli_anything_market(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    hub = CliAnythingHub()
    command = payload.get("command", "list")
    if command == "list":
        result = hub.list_market()
    elif command == "search":
        result = hub.search_market(payload["query"])
    elif command == "info":
        result = hub.info(payload["harness_name"])
    else:
        handler._send(400, {"error": f"unsupported market command: {command}"})
        return
    handler._send(200 if result.exit_code == 0 else 502, result.as_dict())


def _post_cli_anything_import_harness(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    hub = CliAnythingHub()
    market_record = None
    if bool(payload.get("from_market", False)):
        market_record = hub.market_record_for_harness(payload["harness_name"])
        if market_record is None:
            handler._send(
                502,
                {
                    "error": "CLI-Anything market record not found",
                    "plugin_id": "cli-anything",
                    "harness_name": payload["harness_name"],
                },
            )
            return
    manifest = hub.manifest_for_harness(payload["harness_name"], title=payload.get("title"), market_record=market_record)
    if bool(payload.get("write", False)):
        if not bool(payload.get("confirmed", False)):
            handler._send(403, {"error": "manifest write requires confirmed=true"})
            return
        path = hub.write_harness_manifest(payload["harness_name"], title=payload.get("title"), market_record=market_record)
        handler._send(200, {"written": str(path), "manifest": manifest})
    else:
        handler._send(200, manifest)


def _post_cli_anything_adapt_harness(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    write = bool(payload.get("write", False))
    if write and not bool(payload.get("confirmed", False)):
        handler._send(403, {"error": "manifest write requires confirmed=true"})
        return
    result = CliAnythingHub().adapt_harness(
        payload["harness_name"],
        title=payload.get("title"),
        from_market=bool(payload.get("from_market", False)),
        write=write,
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_prepare_harness(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = CliAnythingHub().prepare_harness(
        payload["harness_name"],
        title=payload.get("title"),
        from_market=bool(payload.get("from_market", False)),
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_evaluate_harness(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = CliAnythingHub().evaluate_harness(
        payload["harness_name"],
        title=payload.get("title"),
        from_market=bool(payload.get("from_market", True)),
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_probe_harness(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = CliAnythingHub().probe_harness(
        payload["harness_name"],
        title=payload.get("title"),
        from_market=bool(payload.get("from_market", True)),
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_verify_harness(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = CliAnythingHub().verify_harness(
        payload["harness_name"],
        title=payload.get("title"),
        from_market=bool(payload.get("from_market", True)),
        include_workflows=bool(payload.get("include_workflows", True)),
        run_smoke_suite=bool(payload.get("run_smoke_suite", False)),
        smoke_extra_args=tuple(payload.get("smoke_extra_args", [])),
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_verify_harness_plan(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    try:
        extra_args = _string_list_payload(payload, "extra_args")
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
        return
    result = CliAnythingHub().verify_harness_plan(
        payload.get("action", "install"),
        payload["harness_name"],
        extra_args=tuple(extra_args),
        run=bool(payload.get("run", False)),
        timeout_seconds=int(payload.get("timeout_seconds", 60)),
    )
    handler._send(200 if result["ok"] else 409, result)


def _post_cli_anything_onboard_harness(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    installing = bool(payload.get("install", False)) and bool(payload.get("confirmed", False))
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
        operation_runner=runtime.plugin_runner if installing else None,
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_live_verification(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    try:
        harnesses = _string_list_payload(payload, "harnesses", ["mermaid", "macrocli"])
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
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
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_mvp_plan(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    try:
        workflow_paths = _string_list_payload(payload, "workflow_paths", [])
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
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
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_bootstrap_plan(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = CliAnythingHub().bootstrap_plan(
        harness_name=payload.get("harness_name", payload.get("harness", "mermaid")),
        query=payload.get("query", "file"),
        include_workflows=bool(payload.get("include_workflows", True)),
        workflow_path=payload.get("workflow_path", "workflows/cli-anything-macrocli-mermaid-routing.example.json"),
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_candidates(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = CliAnythingHub().candidate_harnesses(
        query=payload.get("query"),
        limit=int(payload.get("limit", 50)),
        with_probes=bool(payload.get("with_probes", False)),
        compact=bool(payload.get("compact", False)),
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_install_queue(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = CliAnythingHub().market_install_queue(
        query=payload.get("query"),
        limit=int(payload.get("limit", 50)),
        max_installs=int(payload.get("max_installs", 10)),
        include_blocked=bool(payload.get("include_blocked", True)),
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_blocked_plan(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    try:
        harnesses = _string_list_payload(payload, "harnesses")
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
        return
    result = CliAnythingHub().blocked_harness_plan(
        harnesses=tuple(harnesses),
        query=payload.get("query"),
        limit=int(payload.get("limit", 50)),
    )
    handler._send(200, result)


def _post_cli_anything_repair_plan(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = CliAnythingHub().entrypoint_repair_plan(
        _required_string(payload, "harness_name"),
        from_market=bool(payload.get("from_market", True)),
    )
    handler._send(200 if result.get("ok") else 502, result)


def _post_cli_anything_repair_entrypoint(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    write = bool(payload.get("write", False))
    if write and not bool(payload.get("confirmed", False)):
        handler._send_error(403, "confirmation_required", "entrypoint repair writes require confirmed=true")
        return
    try:
        smoke_args = _string_list_payload(payload, "smoke_args", ["--help"])
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
        return
    result = CliAnythingHub().repair_entrypoint(
        _required_string(payload, "harness_name"),
        from_market=bool(payload.get("from_market", True)),
        module=payload.get("module"),
        write=write,
        confirmed=bool(payload.get("confirmed", False)),
        require_smoke=bool(payload.get("require_smoke", False)),
        smoke_args=tuple(smoke_args),
        smoke_timeout_seconds=int(payload.get("smoke_timeout_seconds", 10)),
    )
    handler._send(_operation_execution_status(result), result)


def _post_cli_anything_promotion_gate(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    try:
        smoke_extra_args = _string_list_payload(payload, "smoke_extra_args")
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
        return
    result = CliAnythingHub().promotion_gate(
        payload["harness_name"],
        title=payload.get("title"),
        from_market=bool(payload.get("from_market", True)),
        include_workflows=bool(payload.get("include_workflows", True)),
        run_smoke_suite=bool(payload.get("run_smoke_suite", False)),
        smoke_extra_args=tuple(smoke_extra_args),
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_adapter_targets(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    result = CliAnythingHub().adapter_targets(
        _required_string(payload, "harness_name"),
        from_market=bool(payload.get("from_market", True)),
        package=payload.get("package"),
        limit=int(payload.get("limit", 20)),
    )
    handler._send(200 if result.get("ok") else 502, result)


def _post_cli_anything_adapter_smoke(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    run = bool(payload.get("run", False))
    if run and not bool(payload.get("confirmed", False)):
        handler._send_error(403, "confirmation_required", "adapter smoke execution requires confirmed=true")
        return
    try:
        smoke_args = _string_list_payload(payload, "smoke_args", ["--help"])
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
        return
    result = CliAnythingHub().adapter_target_smoke(
        _required_string(payload, "harness_name"),
        module=_required_string(payload, "module"),
        from_market=bool(payload.get("from_market", True)),
        smoke_args=tuple(smoke_args),
        timeout_seconds=int(payload.get("timeout_seconds", 10)),
        run=run,
        confirmed=bool(payload.get("confirmed", False)),
    )
    handler._send(_operation_execution_status(result), result)


def _post_cli_anything_adaptation_gate(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    run_smoke = bool(payload.get("run_smoke", False))
    if run_smoke and not bool(payload.get("confirmed", False)):
        handler._send_error(403, "confirmation_required", "adaptation gate smoke execution requires confirmed=true")
        return
    try:
        smoke_args = _string_list_payload(payload, "smoke_args", ["--help"])
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
        return
    result = CliAnythingHub().adaptation_gate(
        _required_string(payload, "harness_name"),
        from_market=bool(payload.get("from_market", True)),
        module=payload.get("module"),
        require_smoke=bool(payload.get("require_smoke", True)),
        run_smoke=run_smoke,
        confirmed=bool(payload.get("confirmed", False)),
        smoke_args=tuple(smoke_args),
        smoke_timeout_seconds=int(payload.get("smoke_timeout_seconds", 10)),
    )
    handler._send(200, result)


def _post_cli_anything_adaptation_queue(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    run_smoke = bool(payload.get("run_smoke", False))
    confirmed = bool(payload.get("confirmed", False))
    if run_smoke and not confirmed:
        handler._send_error(403, "confirmation_required", "adaptation queue smoke execution requires confirmed=true")
        return
    try:
        smoke_args = _string_list_payload(payload, "smoke_args", ["--help"])
        harnesses = _string_list_payload(payload, "harnesses")
    except ValueError as exc:
        handler._send(400, {"error": str(exc)})
        return
    include_blocked = bool(payload.get("include_blocked", True))
    if run_smoke and not harnesses and include_blocked:
        handler._send_error(
            409,
            "blocked",
            "adaptation queue smoke execution requires explicit harnesses or include_blocked=false",
        )
        return
    result = CliAnythingHub().adaptation_queue(
        harnesses=tuple(harnesses),
        query=payload.get("query"),
        limit=int(payload.get("limit", 20)),
        max_harnesses=int(payload.get("max_harnesses", 5)),
        include_blocked=include_blocked,
        require_smoke=bool(payload.get("require_smoke", True)),
        run_smoke=run_smoke,
        confirmed=confirmed,
        smoke_args=tuple(smoke_args),
        smoke_timeout_seconds=int(payload.get("smoke_timeout_seconds", 10)),
    )
    handler._send(200, result)


def _post_cli_anything_sync_market(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    write = bool(payload.get("write", False))
    if write and not bool(payload.get("confirmed", False)):
        handler._send(403, {"error": "manifest write requires confirmed=true"})
        return
    result = CliAnythingHub().sync_market(
        query=payload.get("query"),
        limit=int(payload.get("limit", 50)),
        write=write,
    )
    handler._send(200 if result["ok"] else 502, result)


def _post_cli_anything_harness(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    hub = CliAnythingHub()
    if payload["action"] == "status":
        handler._send(
            200,
            hub.harness_status(payload["harness_name"], from_market=bool(payload.get("from_market", False))),
        )
        return
    plan = hub.harness_plan(payload["action"], payload["harness_name"], extra_args=tuple(payload.get("extra_args", [])))
    if not bool(payload.get("confirmed", False)):
        handler._send(200, plan.as_dict())
        return
    if payload["action"] in {"install", "update"} and not bool(payload.get("allow_blocked", False)):
        gate = hub.harness_operation_gate(
            payload["action"],
            payload["harness_name"],
            from_market=not bool(payload.get("offline", False)),
        )
        if not gate["ok"]:
            handler._send(409, gate)
            return
    result = runtime.plugin_runner.execute(plan)
    handler._send(200 if result["status"] == "completed" else 409, result)


def _post_cli_anything_install(handler: CbnRequestHandler, payload: dict[str, Any], runtime: Any) -> None:
    handler._handle_cli_anything_install(payload)


_CLI_ANYTHING_POST_ROUTES = {
    "/plugins/cli-anything/market": _post_cli_anything_market,
    "/plugins/cli-anything/install": _post_cli_anything_install,
    "/plugins/cli-anything/import-harness": _post_cli_anything_import_harness,
    "/plugins/cli-anything/adapt-harness": _post_cli_anything_adapt_harness,
    "/plugins/cli-anything/prepare-harness": _post_cli_anything_prepare_harness,
    "/plugins/cli-anything/evaluate-harness": _post_cli_anything_evaluate_harness,
    "/plugins/cli-anything/probe-harness": _post_cli_anything_probe_harness,
    "/plugins/cli-anything/verify-harness": _post_cli_anything_verify_harness,
    "/plugins/cli-anything/verify-harness-plan": _post_cli_anything_verify_harness_plan,
    "/plugins/cli-anything/onboard-harness": _post_cli_anything_onboard_harness,
    "/plugins/cli-anything/live-verification": _post_cli_anything_live_verification,
    "/plugins/cli-anything/mvp-plan": _post_cli_anything_mvp_plan,
    "/plugins/cli-anything/bootstrap-plan": _post_cli_anything_bootstrap_plan,
    "/plugins/cli-anything/candidates": _post_cli_anything_candidates,
    "/plugins/cli-anything/install-queue": _post_cli_anything_install_queue,
    "/plugins/cli-anything/blocked-plan": _post_cli_anything_blocked_plan,
    "/plugins/cli-anything/repair-plan": _post_cli_anything_repair_plan,
    "/plugins/cli-anything/repair-entrypoint": _post_cli_anything_repair_entrypoint,
    "/plugins/cli-anything/promotion-gate": _post_cli_anything_promotion_gate,
    "/plugins/cli-anything/adapter-targets": _post_cli_anything_adapter_targets,
    "/plugins/cli-anything/adapter-smoke": _post_cli_anything_adapter_smoke,
    "/plugins/cli-anything/adaptation-gate": _post_cli_anything_adaptation_gate,
    "/plugins/cli-anything/adaptation-queue": _post_cli_anything_adaptation_queue,
    "/plugins/cli-anything/sync-market": _post_cli_anything_sync_market,
    "/plugins/cli-anything/harness": _post_cli_anything_harness,
}


def _adapter_agent_turn_from_context(
    context: dict[str, Any],
    *,
    assistant_message: str,
    glm: dict[str, Any],
    glm_content_accepted: bool,
) -> dict[str, Any]:
    initialization = context["workflow_initialization"]
    return {
        "kind": "AdapterAgentOrchestrationTurn",
        "apiVersion": "bridge.dev/v1alpha1",
        "ok": initialization["ok"],
        "status": initialization["status"],
        "workflow_path": context["workflow_path"],
        "message_redacted": context["message_redacted"],
        "assistant_message": assistant_message,
        "recommended_next_action": context["recommended_next_action"],
        "workflow_initialization": initialization,
        "cli_routes": context["cli_routes"],
        "auth_fallbacks": context["auth_fallbacks"],
        "continuation": initialization["continuation"],
        "glm_content_accepted": glm_content_accepted,
        "glm": glm,
    }


def serve(
    host: str = "127.0.0.1",
    port: int = 8787,
    *,
    session_token: str | None = None,
    require_session_token: bool | None = None,
) -> None:
    server = ThreadingHTTPServer((host, port), CbnRequestHandler)
    token = _resolve_session_token(
        host=host,
        explicit_token=session_token,
        require_session_token=require_session_token,
    )
    setattr(server, "session_token", token)
    setattr(server, "session_token_source", _session_token_source(host, token, explicit_token=session_token))
    setattr(server, "local_session_token_default", _is_local_bind_host(host))
    print(f"CBN daemon API listening on http://{host}:{port}")
    if token:
        source = getattr(server, "session_token_source", "configured")
        print(f"CBN daemon session token gate: enabled ({source})")
        if source == "generated":
            print(f"CBN daemon session token: {token}")
    else:
        print("CBN daemon session token gate: disabled for local-first demo use")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("CBN daemon API stopped")
    finally:
        server.server_close()


def _resolve_session_token(
    *,
    host: str,
    explicit_token: str | None = None,
    require_session_token: bool | None = None,
) -> str | None:
    if require_session_token is False:
        return None
    token = explicit_token or os.environ.get(SESSION_TOKEN_ENV)
    if token:
        return token
    if require_session_token is None:
        required_from_env = _env_bool(os.environ.get(SESSION_TOKEN_REQUIRED_ENV))
        require_session_token = required_from_env if required_from_env is not None else not _is_local_bind_host(host)
    if require_session_token:
        return secrets.token_urlsafe(32)
    return None


def _env_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return None


def _is_local_bind_host(host: str) -> bool:
    return host.strip().lower() in ALLOWED_ORIGIN_HOSTS


def _server_session_token(server: Any) -> str | None:
    token = getattr(server, "session_token", None)
    return token if isinstance(token, str) and token else None


def _server_session_token_source(server: Any) -> str:
    source = getattr(server, "session_token_source", None)
    if isinstance(source, str) and source:
        return source
    return "configured" if _server_session_token(server) is not None else "none"


def _session_token_source(host: str, token: str | None, *, explicit_token: str | None = None) -> str:
    if not token:
        return "none"
    if explicit_token or os.environ.get(SESSION_TOKEN_ENV):
        return "configured"
    if not _is_local_bind_host(host) or _env_bool(os.environ.get(SESSION_TOKEN_REQUIRED_ENV)) is True:
        return "generated"
    return "configured"


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


def _payload_alias(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = payload.get(key)
        if value:
            return value
    return default


def _network_connect_package_from_query(
    handler: BaseHTTPRequestHandler,
    runtime: Any,
    query: dict[str, list[str]],
) -> dict[str, Any]:
    session_token = (
        query.get("session_token", query.get("sessionToken", [None]))[0]
        or handler.headers.get("X-CBN-Session")
    )
    return network_connect_package(
        runtime.registry,
        workflow_path=query.get("workflow_path", query.get("path", [DEFAULT_KILLER_WORKFLOW_PATH]))[0],
        base_url=_base_url(handler),
        studio_url=query.get("studio_url", query.get("studioUrl", ["http://127.0.0.1:5177"]))[0],
        dashboard_url=query.get("dashboard_url", query.get("dashboardUrl", ["http://127.0.0.1:5173"]))[0],
        session_token=session_token,
        agent_message=query.get("message", [DEFAULT_AGENT_CONNECT_MESSAGE])[0],
    )


def _network_payload(result: dict[str, Any], route: str) -> tuple[Any, str | None]:
    keys, expected_kind = NETWORK_PAYLOAD_ROUTES[route]
    payload: Any = result
    for key in keys:
        payload = payload.get(key, {}) if isinstance(payload, dict) else {}
    return payload, expected_kind


def _network_payload_ok(result: dict[str, Any], payload: Any, expected_kind: str | None) -> bool:
    if not result.get("ok"):
        return False
    if expected_kind is None:
        return True
    return isinstance(payload, dict) and payload.get("kind") == expected_kind


def _query_profiles(query: dict[str, list[str]]) -> tuple[str, ...] | None:
    values = query.get("profile") or query.get("profiles") or []
    profiles: list[str] = []
    for value in values:
        for item in value.split(","):
            profile = item.strip()
            if profile:
                profiles.append(profile)
    return tuple(profiles) or None


def _query_bool(query: dict[str, list[str]], name: str, *, default: bool) -> bool:
    raw = query.get(name, [str(default).lower()])[0]
    return raw.strip().lower() in {"1", "true", "yes"}


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing required string field: {field}")
    return value


def _operation_execution_status(result: dict[str, Any]) -> int:
    if not result.get("ok", False):
        return 502
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    status = execution.get("status")
    if status in {"blocked", "requires_confirmation"}:
        return 409
    if status in {"failed", "timeout", "spawn_failed"}:
        return 502
    return 200
