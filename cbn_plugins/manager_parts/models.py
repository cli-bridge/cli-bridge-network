"""Plugin manager data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PluginCommand:
    label: str
    argv: tuple[str, ...]
    cwd: str | None = None
    optional: bool = False
    timeout_seconds: int = 600
    env: dict[str, str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "optional": self.optional,
            "timeout_seconds": self.timeout_seconds,
            "env_overrides": sorted((self.env or {}).keys()),
        }


@dataclass(frozen=True)
class PluginPlan:
    plugin_id: str
    action: str
    plugin_dir: str
    commands: tuple[PluginCommand, ...]
    notes: tuple[str, ...] = ()
    verification_commands: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "action": self.action,
            "plugin_dir": self.plugin_dir,
            "commands": [command.as_dict() for command in self.commands],
            "requires_confirmation": True,
            "notes": list(self.notes),
            "verification_commands": list(self.verification_commands),
        }
