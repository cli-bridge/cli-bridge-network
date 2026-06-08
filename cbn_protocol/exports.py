"""Protocol export registry for CBN capabilities."""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import CapabilityManifest, ManifestRegistry
from protocols import a2a, acp, mcp


PROTOCOL_EXPORTS = {
    "mcp": mcp.export_capabilities,
    "a2a": a2a.export_capabilities,
    "acp": acp.export_capabilities,
}


def list_protocol_exports() -> list[dict[str, Any]]:
    return [
        {
            "protocol": name,
            "wire_compatible": False,
            "description": "MVP descriptor export; not a full protocol server.",
        }
        for name in sorted(PROTOCOL_EXPORTS)
    ]


def export_protocol(
    registry: ManifestRegistry,
    protocol: str,
    capability_id: str | None = None,
) -> dict[str, Any]:
    if protocol not in PROTOCOL_EXPORTS:
        raise KeyError(f"unknown protocol export: {protocol}")
    manifests: list[CapabilityManifest]
    if capability_id:
        manifests = [registry.require(capability_id)]
    else:
        manifests = registry.list()
    return PROTOCOL_EXPORTS[protocol](manifests)


def export_all_protocols(
    registry: ManifestRegistry,
    capability_id: str | None = None,
) -> dict[str, Any]:
    return {
        "exports": {
            protocol: export_protocol(registry, protocol, capability_id=capability_id)
            for protocol in sorted(PROTOCOL_EXPORTS)
        }
    }
