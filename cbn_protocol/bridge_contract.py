"""Compatibility re-export for CBN's internal Bridge Contract.

The owner is now :mod:`cbn_core.bridge_contract`; this module remains so older
imports keep working while protocol facade code migrates.
"""

from __future__ import annotations

from cbn_core.bridge_contract import (
    artifact_contract,
    bridge_message_contract,
    tool_manifest_contract,
    workflow_bridge_contract_report,
    workflow_selector_contract,
)

__all__ = [
    "artifact_contract",
    "bridge_message_contract",
    "tool_manifest_contract",
    "workflow_bridge_contract_report",
    "workflow_selector_contract",
]
