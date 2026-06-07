"""Validation helpers for manifests and workflows."""

from __future__ import annotations


VALID_RISKS = {"read", "write-workspace", "privileged", "external-network"}


def validate_risk(risk: str) -> None:
    if risk not in VALID_RISKS:
        raise ValueError(f"unknown risk level: {risk}")

