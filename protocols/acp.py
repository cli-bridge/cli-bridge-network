"""ACP export boundary.

This is an MVP descriptor mapper, not a full ACP wire server.
"""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import CapabilityManifest

EXPORT_NAME = "acp"


def capability_to_tool(manifest: CapabilityManifest) -> dict[str, Any]:
    return {
        "id": manifest.capability_id,
        "title": manifest.title,
        "kind": "tool",
        "transport": manifest.transport.kind,
        "input": {
            "extra_args": "string[]",
            "dry_run": "boolean",
            "approval_id": "string?",
        },
        "output": {
            "message": "BridgeMessage",
            "parser_ref": manifest.output.parser_ref,
        },
        "policy": {
            "risk": manifest.policy.risk,
            "requires_confirmation": manifest.policy.requires_confirmation,
            "network": manifest.policy.network,
        },
    }


def export_capabilities(manifests: list[CapabilityManifest]) -> dict[str, Any]:
    return {
        "protocol": EXPORT_NAME,
        "wire_compatible": False,
        "tools": [capability_to_tool(manifest) for manifest in manifests],
    }
