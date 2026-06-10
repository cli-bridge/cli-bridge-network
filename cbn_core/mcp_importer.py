"""Import external MCP tool descriptors into CBN ToolManifest drafts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_core.manifest import MANIFEST_API_VERSION, validate_manifest_dict


def mcp_import_report(
    tool_descriptor: dict[str, Any],
    server_id: str,
    adapter_command: str,
    adapter_args: tuple[str, ...] = (),
    capability_id: str | None = None,
    title: str | None = None,
    parser_ref: str = "raw.text",
    verified: bool = False,
    risk: str = "read",
    requires_confirmation: bool = False,
    network: str = "localhost",
    timeout_seconds: int = 60,
    write: bool = False,
    output_path: Path | None = None,
    known_parser_refs: set[str] | None = None,
) -> dict[str, Any]:
    """Return a ToolManifest import report for one external MCP tool."""

    tool = normalize_mcp_tool_descriptor(tool_descriptor)
    manifest = build_mcp_tool_manifest(
        tool,
        server_id=server_id,
        adapter_command=adapter_command,
        adapter_args=adapter_args,
        capability_id=capability_id,
        title=title,
        parser_ref=parser_ref,
        verified=verified,
        risk=risk,
        requires_confirmation=requires_confirmation,
        network=network,
        timeout_seconds=timeout_seconds,
    )
    target = output_path or _default_manifest_path(manifest["metadata"]["id"])
    validation = validate_manifest_dict(manifest, source_path=target, known_parser_refs=known_parser_refs)
    written = False
    if write:
        if not validation["valid"]:
            return _report(manifest, target, validation, written=False, error="manifest validation failed")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written = True
    return _report(manifest, target, validation, written=written)


def build_mcp_tool_manifest(
    tool: dict[str, Any],
    server_id: str,
    adapter_command: str,
    adapter_args: tuple[str, ...],
    capability_id: str | None,
    title: str | None,
    parser_ref: str,
    verified: bool,
    risk: str,
    requires_confirmation: bool,
    network: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    tool_name = tool["name"]
    resolved_capability_id = capability_id or f"mcp.{_safe_id(server_id)}.{_safe_id(tool_name)}"
    resolved_args = tuple(
        arg.format(server_id=server_id, tool_name=tool_name, capability_id=resolved_capability_id)
        for arg in adapter_args
    )
    input_schema = tool.get("inputSchema", {})
    return {
        "apiVersion": MANIFEST_API_VERSION,
        "kind": "ToolManifest",
        "metadata": {
            "id": resolved_capability_id,
            "title": title or str(tool.get("description") or tool_name),
            "labels": {
                "protocol": "mcp",
                "mcp_server": server_id,
                "mcp_tool": tool_name,
            },
            "annotations": {
                "cbn.import.kind": "mcp-tool",
                "cbn.external_protocol": "mcp",
                "cbn.mcp.server_id": server_id,
                "cbn.mcp.tool_name": tool_name,
                "cbn.mcp.input_schema": json.dumps(input_schema, ensure_ascii=False, sort_keys=True),
                "cbn.mcp.adapter_contract": "stdio/pty adapter command receives static argsTemplate plus cbn call extra_args",
            },
        },
        "spec": {
            "transport": {
                "kind": "stdio",
                "command": adapter_command,
                "argsTemplate": list(resolved_args),
                "cwdPolicy": "workspace",
                "timeoutSeconds": timeout_seconds,
            },
            "policy": {
                "risk": risk,
                "requiresConfirmation": requires_confirmation,
                "network": network,
            },
            "output": {
                "parserRef": parser_ref,
                "verified": verified,
            },
        },
    }


def normalize_mcp_tool_descriptor(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("MCP tool descriptor must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("MCP tool descriptor name is required")
    input_schema = raw.get("inputSchema", raw.get("input_schema", {}))
    if input_schema is None:
        input_schema = {}
    if not isinstance(input_schema, dict):
        raise ValueError("MCP tool descriptor inputSchema must be an object")
    description = raw.get("description", "")
    if description is not None and not isinstance(description, str):
        raise ValueError("MCP tool descriptor description must be a string")
    return {
        "name": name.strip(),
        "description": description or name.strip(),
        "inputSchema": input_schema,
    }


def select_mcp_tool(raw: dict[str, Any], tool_name: str | None = None) -> dict[str, Any]:
    if isinstance(raw.get("tools"), list):
        tools = [item for item in raw["tools"] if isinstance(item, dict)]
        if tool_name:
            for tool in tools:
                if tool.get("name") == tool_name:
                    return normalize_mcp_tool_descriptor(tool)
            raise KeyError(f"MCP tool not found: {tool_name}")
        if len(tools) != 1:
            raise ValueError("MCP descriptor contains multiple tools; pass --tool-name")
        return normalize_mcp_tool_descriptor(tools[0])
    return normalize_mcp_tool_descriptor(raw)


def load_mcp_tool_descriptor(path: Path, tool_name: str | None = None) -> dict[str, Any]:
    return select_mcp_tool(json.loads(path.read_text(encoding="utf-8")), tool_name=tool_name)


def _report(
    manifest: dict[str, Any],
    target: Path,
    validation: dict[str, Any],
    written: bool,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": bool(validation["valid"]) and error is None,
        "kind": "McpImportReport",
        "apiVersion": MANIFEST_API_VERSION,
        "capability_id": manifest["metadata"]["id"],
        "server_id": manifest["metadata"]["labels"]["mcp_server"],
        "tool_name": manifest["metadata"]["labels"]["mcp_tool"],
        "target_path": str(target),
        "written": written,
        "error": error,
        "validation": validation,
        "manifest": manifest,
        "next_commands": [
            f"python -m cbn registry inspect {manifest['metadata']['id']}",
            f"python -m cbn call {manifest['metadata']['id']} --dry-run",
            f"python -m cbn protocol export mcp --capability-id {manifest['metadata']['id']}",
        ]
        if written
        else [
            "review this generated manifest, then rerun the same import command with --write",
            f"python -m cbn protocol export mcp --capability-id {manifest['metadata']['id']}",
        ],
    }


def _default_manifest_path(capability_id: str) -> Path:
    return resolve_project_paths().local_manifests / f"{_safe_id(capability_id)}.json"


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-").casefold() or "mcp"
