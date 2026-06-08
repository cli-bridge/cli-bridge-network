"""Validation helpers for manifests and workflows."""

from __future__ import annotations

from cbn_core.manifest import VALID_MANIFEST_RISKS

VALID_RISKS = VALID_MANIFEST_RISKS


def validate_risk(risk: str) -> None:
    if risk not in VALID_RISKS:
        raise ValueError(f"unknown risk level: {risk}")
