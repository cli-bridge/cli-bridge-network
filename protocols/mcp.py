"""MCP export boundary.

This is an MVP descriptor mapper, not a full MCP wire server.
"""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import CapabilityManifest

EXPORT_NAME = "mcp"


def capability_to_tool(manifest: CapabilityManifest) -> dict[str, Any]:
    return {
        "name": manifest.capability_id,
        "description": manifest.title,
        "inputSchema": {
            "type": "object",
            "properties": {
                "extra_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments appended after the manifest argsTemplate.",
                },
                "dry_run": {"type": "boolean"},
                "approval_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "_meta": {
            "cbn": {
                "transport": manifest.transport.kind,
                "risk": manifest.policy.risk,
                "requires_confirmation": manifest.policy.requires_confirmation,
                "parser_ref": manifest.output.parser_ref,
                "verified": manifest.output.verified,
            }
        },
    }


def export_capabilities(manifests: list[CapabilityManifest]) -> dict[str, Any]:
    return {
        "protocol": EXPORT_NAME,
        "wire_compatible": False,
        "tools": [capability_to_tool(manifest) for manifest in manifests],
    }
