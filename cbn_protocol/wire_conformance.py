"""Local wire-conformance checks for MCP, A2A, and ACP facades.

The suite validates the official wire shapes CBN implements locally. It is
deliberately separate from smoke tests so readiness can distinguish protocol
wire contracts from end-to-end tool execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cbn.version import __version__
from cbn_protocol.a2a_http import A2A_PROTOCOL_VERSION, agent_card, handle_a2a_jsonrpc_request
from cbn_protocol.acp_stdio import ACP_PROTOCOL_VERSION, AcpStdioAgent
from cbn_protocol.mcp_stdio import MCP_PROTOCOL_VERSION, McpStdioServer


PROTOCOLS = ("mcp", "a2a", "acp")


def protocol_wire_conformance_suite(
    target: str = "all",
    capability_id: str = "git.version",
) -> dict[str, Any]:
    targets = PROTOCOLS if target == "all" else (target,)
    unknown = [item for item in targets if item not in PROTOCOLS]
    if unknown:
        raise KeyError(f"unknown protocol conformance target: {unknown[0]}")
    protocols: dict[str, Any] = {}
    for protocol in targets:
        if protocol == "mcp":
            protocols[protocol] = _mcp_checks(capability_id)
        elif protocol == "a2a":
            protocols[protocol] = _a2a_checks(capability_id)
        elif protocol == "acp":
            protocols[protocol] = _acp_checks(capability_id)
    check_count = sum(item["summary"]["check_count"] for item in protocols.values())
    failed_count = sum(item["summary"]["failed_count"] for item in protocols.values())
    wire_count = sum(1 for item in protocols.values() if item["wire_compatible"])
    return {
        "ok": failed_count == 0,
        "apiVersion": "bridge.dev/v1alpha1",
        "kind": "ProtocolWireConformanceReport",
        "scope": "project",
        "target": target,
        "capability_id": capability_id,
        "wire_compatible": failed_count == 0 and wire_count == len(targets),
        "external_protocol_boundary": (
            "Local official-shape wire conformance for implemented MCP stdio, A2A HTTP+JSON, "
            "and ACP stdio surfaces; third-party SDK certification is still a separate release gate."
        ),
        "summary": {
            "protocol_count": len(targets),
            "wire_compatible_protocol_count": wire_count,
            "check_count": check_count,
            "passed_count": check_count - failed_count,
            "failed_count": failed_count,
        },
        "protocols": protocols,
        "next_steps": [
            "Run third-party SDK/client conformance before release certification.",
            "Keep adding cases here whenever a protocol facade exposes a new lifecycle method.",
        ],
    }


def _mcp_checks(capability_id: str) -> dict[str, Any]:
    server = McpStdioServer()
    checks: list[dict[str, Any]] = []
    init = server.handle_line(
        _json(
            {
                "jsonrpc": "2.0",
                "id": "mcp-init",
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "cbn-wire-suite", "version": __version__},
                },
            }
        )
    )
    checks.append(
        _check(
            "mcp.initialize",
            _is_result(init)
            and init["result"].get("protocolVersion") == MCP_PROTOCOL_VERSION
            and isinstance(init["result"].get("serverInfo"), dict)
            and isinstance(init["result"].get("capabilities", {}).get("tools"), dict),
            {"response": init},
        )
    )
    checks.append(
        _check(
            "mcp.initialized_notification",
            server.handle_line(_json({"jsonrpc": "2.0", "method": "notifications/initialized"})) is None,
            {},
        )
    )
    listed = server.handle_line(_json({"jsonrpc": "2.0", "id": "mcp-list", "method": "tools/list", "params": {}}))
    tools = listed.get("result", {}).get("tools", []) if isinstance(listed, dict) else []
    checks.append(
        _check(
            "mcp.tools_list_shape",
            _is_result(listed)
            and isinstance(tools, list)
            and any(tool.get("name") == capability_id for tool in tools)
            and all(isinstance(tool.get("inputSchema"), dict) for tool in tools),
            {"tool_count": len(tools)},
        )
    )
    called = server.handle_line(
        _json(
            {
                "jsonrpc": "2.0",
                "id": "mcp-call",
                "method": "tools/call",
                "params": {"name": capability_id, "arguments": {}},
            }
        )
    )
    result = called.get("result", {}) if isinstance(called, dict) else {}
    checks.append(
        _check(
            "mcp.tools_call_result_shape",
            _is_result(called)
            and isinstance(result.get("content"), list)
            and isinstance(result.get("structuredContent"), dict)
            and isinstance(result.get("isError"), bool),
            {"isError": result.get("isError")},
        )
    )
    checks.append(
        _check(
            "mcp.error_boundaries",
            _error_code(server.handle_line("{")) == -32700
            and _error_code(server.handle_line(_json({"jsonrpc": "2.0", "id": "bad", "method": "missing"}))) == -32601
            and _error_code(server.handle_line(_json({"jsonrpc": "2.0", "id": "bad", "method": "tools/call", "params": {}}))) == -32602,
            {},
        )
    )
    return _protocol_report("mcp", checks)


def _a2a_checks(capability_id: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    card = agent_card("http://127.0.0.1:8787")
    checks.append(
        _check(
            "a2a.agent_card_shape",
            card.get("protocolVersion") == A2A_PROTOCOL_VERSION
            and card.get("supportedInterfaces", [{}])[0].get("protocolBinding") == "HTTP+JSON"
            and isinstance(card.get("capabilities"), dict)
            and any(skill.get("id") == capability_id for skill in card.get("skills", [])),
            {"protocolVersion": card.get("protocolVersion")},
        )
    )
    send = handle_a2a_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "a2a-send",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "message-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "version"}],
                },
                "metadata": {"cbn": {"capability_id": capability_id}},
            },
        }
    )
    task = send.get("result", {}) if isinstance(send, dict) else {}
    task_id = task.get("id")
    checks.append(
        _check(
            "a2a.send_message_task_shape",
            _is_result(send)
            and isinstance(task_id, str)
            and task.get("taskId") == task_id
            and task.get("status", {}).get("state") == "TASK_STATE_COMPLETED"
            and task.get("status", {}).get("message", {}).get("role") == "ROLE_AGENT",
            {"task_id": task_id, "state": task.get("status", {}).get("state")},
        )
    )
    fetched = handle_a2a_jsonrpc_request(
        {"jsonrpc": "2.0", "id": "a2a-get", "method": "GetTask", "params": {"id": task_id}}
    )
    checks.append(
        _check(
            "a2a.get_task",
            _is_result(fetched) and fetched.get("result", {}).get("id") == task_id,
            {"task_id": task_id},
        )
    )
    missing = handle_a2a_jsonrpc_request(
        {"jsonrpc": "2.0", "id": "a2a-missing", "method": "GetTask", "params": {"id": "missing"}}
    )
    cancel = handle_a2a_jsonrpc_request(
        {"jsonrpc": "2.0", "id": "a2a-cancel", "method": "CancelTask", "params": {"id": task_id}}
    )
    checks.append(
        _check(
            "a2a.error_mappings",
            _error_code(missing) == -32001 and _error_code(cancel) == -32002,
            {"missing": missing, "cancel": cancel},
        )
    )
    return _protocol_report("a2a", checks)


def _acp_checks(capability_id: str) -> dict[str, Any]:
    agent = AcpStdioAgent()
    checks: list[dict[str, Any]] = []
    init = agent.handle_line(
        _json(
            {
                "jsonrpc": "2.0",
                "id": "acp-init",
                "method": "initialize",
                "params": {
                    "protocolVersion": ACP_PROTOCOL_VERSION,
                    "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                    "clientInfo": {"name": "cbn-wire-suite", "version": __version__},
                },
            }
        )
    )
    checks.append(
        _check(
            "acp.initialize_shape",
            _is_result(init)
            and init["result"].get("protocolVersion") == ACP_PROTOCOL_VERSION
            and isinstance(init["result"].get("agentCapabilities"), dict)
            and isinstance(init["result"].get("authMethods"), list)
            and isinstance(init["result"].get("agentInfo"), dict),
            {"response": init},
        )
    )
    session = agent.handle_line(
        _json(
            {
                "jsonrpc": "2.0",
                "id": "acp-session",
                "method": "session/new",
                "params": {"cwd": str(Path.cwd()), "mcpServers": []},
            }
        )
    )
    session_id = session.get("result", {}).get("sessionId") if isinstance(session, dict) else None
    checks.append(
        _check(
            "acp.session_new_shape",
            _is_result(session) and isinstance(session_id, str),
            {"session_id": session_id},
        )
    )
    prompt = agent.handle_line(
        _json(
            {
                "jsonrpc": "2.0",
                "id": "acp-prompt",
                "method": "session/prompt",
                "params": {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": "version"}],
                    "_meta": {"cbn": {"capability_id": capability_id}},
                },
            }
        )
    )
    checks.append(
        _check(
            "acp.session_prompt_shape",
            _is_result(prompt)
            and prompt.get("result", {}).get("stopReason") == "end_turn"
            and isinstance(prompt.get("result", {}).get("_meta", {}).get("cbn"), dict),
            {"stopReason": prompt.get("result", {}).get("stopReason") if isinstance(prompt, dict) else None},
        )
    )
    checks.append(
        _check(
            "acp.notification_and_error_boundaries",
            agent.handle_line(_json({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": session_id}})) is None
            and _error_code(
                agent.handle_line(
                    _json({"jsonrpc": "2.0", "id": "bad-session", "method": "session/new", "params": {"cwd": "relative"}})
                )
            )
            == -32602
            and _error_code(agent.handle_line("{")) == -32700,
            {},
        )
    )
    return _protocol_report("acp", checks)


def _protocol_report(protocol: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [item for item in checks if not item["ok"]]
    return {
        "protocol": protocol,
        "wire_compatible": not failed,
        "summary": {
            "check_count": len(checks),
            "passed_count": len(checks) - len(failed),
            "failed_count": len(failed),
        },
        "checks": checks,
    }


def _check(check_id: str, ok: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"id": check_id, "ok": bool(ok), "evidence": evidence}


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _is_result(response: Any) -> bool:
    return isinstance(response, dict) and response.get("jsonrpc") == "2.0" and isinstance(response.get("result"), dict)


def _error_code(response: Any) -> int | None:
    if not isinstance(response, dict):
        return None
    error = response.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, int) and not isinstance(code, bool) else None
