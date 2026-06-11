"""Compatibility re-export for CBN's internal Bridge Contract.

The owner is now :mod:`cbn_core.bridge_contract`; this module remains so older
imports keep working while protocol facade code migrates.
"""

from __future__ import annotations

from cbn_core.bridge_contract import bridge_message_contract, workflow_bridge_contract_report

__all__ = ["bridge_message_contract", "workflow_bridge_contract_report"]
