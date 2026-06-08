"""A2A export boundary.

This is an MVP descriptor mapper, not a full A2A wire server.
"""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import CapabilityManifest

EXPORT_NAME = "a2a"


def capability_to_skill(manifest: CapabilityManifest) -> dict[str, Any]:
    return {
        "id": manifest.capability_id,
        "name": manifest.title,
        "description": f"CBN capability exported from {manifest.transport.kind}.",
        "inputModes": ["application/json"],
        "outputModes": ["application/json"],
        "tags": [
            f"risk:{manifest.policy.risk}",
            f"transport:{manifest.transport.kind}",
        ],
        "cbn": {
            "requires_confirmation": manifest.policy.requires_confirmation,
            "parser_ref": manifest.output.parser_ref,
            "verified": manifest.output.verified,
        },
    }


def export_capabilities(manifests: list[CapabilityManifest]) -> dict[str, Any]:
    return {
        "protocol": EXPORT_NAME,
        "wire_compatible": False,
        "agentCard": {
            "name": "CLI Bridge Network",
            "description": "Local-first CBN capability export descriptor.",
            "skills": [capability_to_skill(manifest) for manifest in manifests],
        },
    }
