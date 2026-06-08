"""Shared CBN descriptor payloads for protocol exports."""

from __future__ import annotations

from typing import Any

from cbn_core.manifest import CapabilityManifest


def cbn_descriptor(manifest: CapabilityManifest) -> dict[str, Any]:
    return {
        "apiVersion": "bridge.dev/v1alpha1",
        "capability_id": manifest.capability_id,
        "title": manifest.title,
        "transport": {
            "kind": manifest.transport.kind,
            "command": manifest.transport.command,
            "args_template": list(manifest.transport.args_template),
            "cwd_policy": manifest.transport.cwd_policy,
            "timeout_seconds": manifest.transport.timeout_seconds,
        },
        "policy": {
            "risk": manifest.policy.risk,
            "requires_confirmation": manifest.policy.requires_confirmation,
            "network": manifest.policy.network,
        },
        "output": {
            "message_kind": "BridgeMessage",
            "channel": "capability.output",
            "parser_ref": manifest.output.parser_ref,
            "verified": manifest.output.verified,
        },
        "labels": dict(manifest.labels),
        "annotations": dict(manifest.annotations),
        "source_path": str(manifest.source_path) if manifest.source_path else None,
    }
