"""Import external MCP tool descriptors into CBN ToolManifest drafts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_core.manifest import MANIFEST_API_VERSION, validate_manifest_dict


@dataclass(frozen=True)
class McpManifestSpec:
    tool: dict[str, Any]
    server_id: str
    adapter_command: str
    adapter_args: tuple[str, ...] = ()
    capability_id: str | None = None
    title: str | None = None
    parser_ref: str = "raw.text"
    verified: bool = False
    risk: str = "read"
    requires_confirmation: bool = False
    network: str = "localhost"
    timeout_seconds: int = 60


@dataclass(frozen=True)
class McpImportRequest:
    manifest: McpManifestSpec
    write: bool = False
    output_path: Path | None = None
    known_parser_refs: set[str] | None = None


def mcp_import_report(tool_descriptor: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Return a ToolManifest import report for one external MCP tool."""

    request = mcp_import_request(tool_descriptor, **kwargs)
    manifest = build_mcp_tool_manifest(request.manifest)
    target = request.output_path or _default_manifest_path(manifest["metadata"]["id"])
    validation = validate_manifest_dict(manifest, source_path=target, known_parser_refs=request.known_parser_refs)
    written, error = _write_manifest(manifest, target, write=request.write, valid=bool(validation["valid"]))
    return _report(manifest, target, validation, written=written, error=error)


def mcp_import_request(tool_descriptor: dict[str, Any], **kwargs: Any) -> McpImportRequest:
    manifest_keys = set(McpManifestSpec.__dataclass_fields__) - {"tool"}
    request_keys = {"write", "output_path", "known_parser_refs"}
    unknown = sorted(set(kwargs) - manifest_keys - request_keys)
    if unknown:
        raise TypeError(f"unknown MCP import option(s): {', '.join(unknown)}")
    manifest_values = {key: kwargs[key] for key in manifest_keys if key in kwargs}
    manifest_values["tool"] = normalize_mcp_tool_descriptor(tool_descriptor)
    manifest_values["adapter_args"] = tuple(manifest_values.get("adapter_args", ()))
    return McpImportRequest(
        manifest=McpManifestSpec(**manifest_values),
        write=bool(kwargs.get("write", False)),
        output_path=kwargs.get("output_path"),
        known_parser_refs=kwargs.get("known_parser_refs"),
    )


def build_mcp_tool_manifest(spec: McpManifestSpec) -> dict[str, Any]:
    tool_name = spec.tool["name"]
    resolved_capability_id = spec.capability_id or f"mcp.{_safe_id(spec.server_id)}.{_safe_id(tool_name)}"
    return {
        "apiVersion": MANIFEST_API_VERSION,
        "kind": "ToolManifest",
        "metadata": _mcp_metadata(
            spec.tool,
            server_id=spec.server_id,
            capability_id=resolved_capability_id,
            title=spec.title,
        ),
        "spec": _mcp_spec(spec, tool_name, resolved_capability_id),
    }


def _write_manifest(manifest: dict[str, Any], target: Path, *, write: bool, valid: bool) -> tuple[bool, str | None]:
    if not write:
        return False, None
    if not valid:
        return False, "manifest validation failed"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True, None


def _mcp_metadata(
    tool: dict[str, Any],
    *,
    server_id: str,
    capability_id: str,
    title: str | None,
) -> dict[str, Any]:
    tool_name = tool["name"]
    return {
        "id": capability_id,
        "title": title or str(tool.get("description") or tool_name),
        "labels": {
            "protocol": "mcp",
            "mcp_server": server_id,
            "mcp_tool": tool_name,
        },
        "annotations": _mcp_annotations(tool, server_id=server_id),
    }


def _mcp_annotations(tool: dict[str, Any], *, server_id: str) -> dict[str, str]:
    return {
        "cbn.import.kind": "mcp-tool",
        "cbn.external_protocol": "mcp",
        "cbn.mcp.server_id": server_id,
        "cbn.mcp.tool_name": tool["name"],
        "cbn.mcp.input_schema": json.dumps(tool.get("inputSchema", {}), ensure_ascii=False, sort_keys=True),
        "cbn.mcp.adapter_contract": "stdio/pty adapter command receives static argsTemplate plus cbn call extra_args",
    }


def _mcp_spec(spec: McpManifestSpec, tool_name: str, capability_id: str) -> dict[str, Any]:
    return {
        "transport": _mcp_transport(spec, tool_name, capability_id),
        "policy": {
            "risk": spec.risk,
            "requiresConfirmation": spec.requires_confirmation,
            "network": spec.network,
        },
        "output": {
            "parserRef": spec.parser_ref,
            "verified": spec.verified,
        },
    }


def _mcp_transport(spec: McpManifestSpec, tool_name: str, capability_id: str) -> dict[str, Any]:
    return {
        "kind": "stdio",
        "command": spec.adapter_command,
        "argsTemplate": list(_resolved_adapter_args(spec.adapter_args, spec.server_id, tool_name, capability_id)),
        "cwdPolicy": "workspace",
        "timeoutSeconds": spec.timeout_seconds,
    }


def _resolved_adapter_args(
    adapter_args: tuple[str, ...],
    server_id: str,
    tool_name: str,
    capability_id: str,
) -> tuple[str, ...]:
    return tuple(
        arg.format(server_id=server_id, tool_name=tool_name, capability_id=capability_id)
        for arg in adapter_args
    )


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
