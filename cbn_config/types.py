"""Typed configuration objects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CbnConfig:
    project_name: str = "CLI Bridge Network"
    command_name: str = "cbn"
    default_transport: str = "stdio"
    enabled_exports: tuple[str, ...] = ("cli",)
    feature_flags: dict[str, bool] = field(default_factory=dict)

