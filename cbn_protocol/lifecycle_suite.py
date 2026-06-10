"""Lifecycle and error-boundary checks for protocol facades."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from cbn.version import __version__
from cbn_protocol.a2a_http import A2A_PROTOCOL_VERSION, agent_card, handle_a2a_jsonrpc_request
from cbn_protocol.acp_stdio import ACP_PROTOCOL_VERSION, AcpStdioAgent
from cbn_protocol.mcp_stdio import MCP_PROTOCOL_VERSION, McpStdioServer


def protocol_lifecycle_suite(
    capability_id: str = "git.version",
    workflow_path: str = "workflows/example.json",
) -> dict[str, Any]:
    """Run bounded lifecycle/error checks for current MVP protocol facades."""

    reports = {
        "mcp": _mcp_lifecycle(capability_id),
        "a2a": _a2a_lifecycle(capability_id),
        "acp": _acp_lifecycle(capability_id, workflow_path),
    }
    summary = _summary(reports)
    return {
        "ok": summary["failed_count"] == 0,
        "kind": "ProtocolLifecycleSuiteReport",
        "capability_id": capability_id,
        "workflow_path": workflow_path,
        "wire_compatible": summary["failed_count"] == 0,
        "external_protocol_boundary": "Local official-shape lifecycle checks for implemented MCP stdio, A2A HTTP+JSON, and ACP stdio surfaces.",
        "summary": summary,
        "protocols": reports,
        "failures": [
            check
            for report in reports.values()
            for check in report["checks"]
            if not check["ok"]
        ],
        "next_steps": _next_steps(summary),
    }


def _mcp_lifecycle(capability_id: str) -> dict[str, Any]:
    server = McpStdioServer()
    initialized = server.handle_line(_json({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    checks = [
        _check(
            "mcp.initialize",
            _result(server.handle_line(_json(
                {
                    "jsonrpc": "2.0",
                    "id": "mcp-init",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "cbn-lifecycle", "version": __version__},
                    },
                }
            ))),
            "initialize returns serverInfo and protocolVersion",
        ),
        _check(
            "mcp.initialized_notification",
            initialized is None,
            "notifications/initialized is accepted without a response",
        ),
        _check(
            "mcp.ping",
            _result(server.handle_line(_json({"jsonrpc": "2.0", "id": "mcp-ping", "method": "ping"}))) == {},
            "ping returns an empty result object",
        ),
        _check(
            "mcp.tools_list",
            any(
                tool.get("name") == capability_id
                for tool in _result(
                    server.handle_line(_json({"jsonrpc": "2.0", "id": "mcp-tools", "method": "tools/list", "params": {}}))
                ).get("tools", [])
            ),
            "tools/list includes the selected capability",
        ),
        _check(
            "mcp.unknown_method_error",
            _error_code(server.handle_line(_json({"jsonrpc": "2.0", "id": "mcp-missing", "method": "missing/method"}))) == -32601,
            "unknown methods return JSON-RPC method-not-found",
        ),
        _check(
            "mcp.invalid_params_error",
            _error_code(server.handle_line(_json({"jsonrpc": "2.0", "id": "mcp-bad-call", "method": "tools/call", "params": {}}))) == -32602,
            "invalid tools/call params return JSON-RPC invalid-params",
        ),
    ]
    return _report("mcp", checks)


def _a2a_lifecycle(capability_id: str) -> dict[str, Any]:
    card = agent_card("http://127.0.0.1:8787")
    message_response = handle_a2a_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "a2a-message",
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
                        "dry_run": True,
                    }
                },
            },
        }
    )
    checks = [
        _check(
            "a2a.agent_card",
            card.get("protocolVersion") == A2A_PROTOCOL_VERSION
            and any(skill.get("id") == capability_id for skill in card.get("skills", [])),
            "AgentCard advertises protocolVersion and selected capability skill",
        ),
        _check(
            "a2a.message_send",
            message_response.get("result", {}).get("status", {}).get("state") == "TASK_STATE_COMPLETED",
            "SendMessage returns a completed task for a dry-run capability call",
        ),
        _check(
            "a2a.get_task",
            _result(
                handle_a2a_jsonrpc_request(
                    {
                        "jsonrpc": "2.0",
                        "id": "a2a-get",
                        "method": "GetTask",
                        "params": {"id": message_response.get("result", {}).get("id")},
                    }
                )
            ).get("id")
            == message_response.get("result", {}).get("id"),
            "GetTask returns a previously created task",
        ),
        _check(
            "a2a.task_not_cancelable_error",
            _error_code(
                handle_a2a_jsonrpc_request(
                    {
                        "jsonrpc": "2.0",
                        "id": "a2a-cancel",
                        "method": "CancelTask",
                        "params": {"id": message_response.get("result", {}).get("id")},
                    }
                )
            )
            == -32002,
            "CancelTask maps completed task cancellation to A2A TaskNotCancelableError",
        ),
        _check(
            "a2a.invalid_params_error",
            _error_code(handle_a2a_jsonrpc_request({"jsonrpc": "2.0", "id": "a2a-bad", "method": "SendMessage", "params": []})) == -32602,
            "invalid params return JSON-RPC invalid-params",
        ),
    ]
    return _report("a2a", checks)


def _acp_lifecycle(capability_id: str, workflow_path: str) -> dict[str, Any]:
    agent = AcpStdioAgent()
    initialize = agent.handle_line(
        _json(
            {
                "jsonrpc": "2.0",
                "id": "acp-init",
                "method": "initialize",
                "params": {
                    "protocolVersion": ACP_PROTOCOL_VERSION,
                    "clientCapabilities": {"fs": {"readTextFile": True}, "terminal": False},
                    "clientInfo": {"name": "cbn-lifecycle", "version": __version__},
                },
            }
        )
    )
    session = agent.handle_line(
        _json(
            {
                "jsonrpc": "2.0",
                "id": "acp-session",
                "method": "session/new",
                "params": {
                    "cwd": str(Path.cwd()),
                    "mcpServers": [],
                    "additionalDirectories": [],
                },
            }
        )
    )
    session_id = _result(session).get("sessionId")
    prompt = agent.handle_line(
        _json(
            {
                "jsonrpc": "2.0",
                "id": "acp-prompt",
                "method": "session/prompt",
                "params": {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": "Run CBN capability"}],
                    "_meta": {"cbn": {"capability_id": capability_id, "dry_run": True}},
                },
            }
        )
    )
    cancel = agent.handle_line(
        _json(
            {
                "jsonrpc": "2.0",
                "id": "acp-cancel",
                "method": "session/cancel",
                "params": {"sessionId": session_id},
            }
        )
    )
    checks = [
        _check(
            "acp.initialize",
            _result(initialize).get("agentInfo", {}).get("name") == "CLI Bridge Network",
            "initialize returns agentInfo and protocolVersion",
        ),
        _check(
            "acp.session_new",
            isinstance(session_id, str) and bool(session_id),
            "session/new creates a session id",
        ),
        _check(
            "acp.session_prompt",
            _result(prompt).get("stopReason") == "end_turn"
            and _result(prompt).get("_meta", {}).get("cbn", {}).get("capability_id") == capability_id,
            "session/prompt executes a dry-run capability call",
        ),
        _check(
            "acp.session_cancel",
            _result(cancel) == {},
            "session/cancel returns an empty result object",
        ),
        _check(
            "acp.unknown_method_error",
            _error_code(agent.handle_line(_json({"jsonrpc": "2.0", "id": "acp-missing", "method": "session/load"}))) == -32601,
            "unsupported session lifecycle methods return JSON-RPC method-not-found",
        ),
        _check(
            "acp.invalid_params_error",
            _error_code(
                agent.handle_line(
                    _json(
                        {
                            "jsonrpc": "2.0",
                            "id": "acp-bad-prompt",
                            "method": "session/prompt",
                            "params": {"sessionId": "missing", "prompt": []},
                        }
                    )
                )
            )
            == -32602,
            "invalid session references return JSON-RPC invalid-params",
        ),
    ]
    return {
        **_report("acp", checks),
        "workflow_path": workflow_path,
    }


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _result(response: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def _error_code(response: dict[str, Any] | None) -> int | None:
    if not isinstance(response, dict):
        return None
    error = response.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, int) else None


def _check(check_id: str, ok: bool, evidence: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "ok": bool(ok),
        "status": "passed" if ok else "failed",
        "evidence": evidence,
    }


def _report(protocol: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check for check in checks if not check["ok"]]
    return {
        "ok": not failed,
        "protocol": protocol,
        "wire_compatible": not failed,
        "check_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "failed_count": len(failed),
        "checks": checks,
    }


def _summary(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "protocol_count": len(reports),
        "check_count": sum(int(report["check_count"]) for report in reports.values()),
        "passed_count": sum(int(report["passed_count"]) for report in reports.values()),
        "failed_count": sum(int(report["failed_count"]) for report in reports.values()),
        "wire_compatible_protocol_count": sum(1 for report in reports.values() if report.get("wire_compatible")),
        "by_protocol": {
            protocol: {
                "passed": report["passed_count"],
                "failed": report["failed_count"],
            }
            for protocol, report in reports.items()
        },
    }


def _next_steps(summary: dict[str, Any]) -> list[str]:
    if summary["failed_count"]:
        return [
            "Fix failed lifecycle checks before using these facades as adapter readiness baselines.",
            "Keep wire_compatible=false until local lifecycle checks pass.",
        ]
    return [
        "Use lifecycle-suite as the local regression gate before protocol smoke-suite and wire-conformance.",
        "Run third-party SDK/client conformance before release certification.",
    ]
