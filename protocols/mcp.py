"""MCP export boundary.

This is an MVP descriptor mapper, not a full MCP wire server.
"""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import CapabilityManifest
from protocols.common import cbn_descriptor

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
            "cbn": cbn_descriptor(manifest)
        },
    }


def export_capabilities(manifests: list[CapabilityManifest]) -> dict[str, Any]:
    return {
        "protocol": EXPORT_NAME,
        "wire_compatible": False,
        "tools": [capability_to_tool(manifest) for manifest in manifests],
    }
