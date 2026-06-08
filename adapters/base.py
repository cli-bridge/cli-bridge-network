"""Adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ToolCall:
    capability_id: str
    argv: tuple[str, ...]
    cwd: str | None = None
    dry_run: bool = False
    timeout_seconds: int = 30
    env: dict[str, str] | None = None


@dataclass(frozen=True)
class ToolResult:
    capability_id: str
    allowed: bool
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    reason: str = "allowed"


class ToolAdapter(Protocol):
    def call(self, request: ToolCall) -> ToolResult:
        ...
