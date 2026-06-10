"""Plugin manifest types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PluginOperation:
    operation_id: str
    title: str
    kind: str
    command: str | None
    api_method: str | None
    api_path: str | None
    requires_confirmation: bool
    side_effects: tuple[str, ...]
    input_schema: dict[str, Any]
    payload_template: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PluginOperation":
        api = raw.get("api", {}) if isinstance(raw.get("api"), dict) else {}
        return cls(
            operation_id=raw["id"],
            title=raw.get("title", raw["id"]),
            kind=raw.get("kind", "report"),
            command=raw.get("command"),
            api_method=api.get("method"),
            api_path=api.get("path"),
            requires_confirmation=bool(raw.get("requires_confirmation", False)),
            side_effects=tuple(raw.get("side_effects", [])),
            input_schema=raw.get("input_schema", {}),
            payload_template=raw.get("payload_template", {}),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.operation_id,
            "title": self.title,
            "kind": self.kind,
            "command": self.command,
            "api": {
                "method": self.api_method,
                "path": self.api_path,
            }
            if self.api_method or self.api_path
            else None,
            "requires_confirmation": self.requires_confirmation,
            "side_effects": list(self.side_effects),
            "input_schema": self.input_schema,
            "payload_template": self.payload_template,
        }


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    title: str
    description: str
    plugin_api_version: str
    provider: str
    repository: str
    pip_packages: tuple[str, ...]
    entrypoints: tuple[str, ...]
    permissions: tuple[str, ...]
    install_modes: tuple[str, ...]
    operations: tuple[PluginOperation, ...]
    optional_codex_skill_script: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PluginManifest":
        install = raw.get("install", {})
        source = raw.get("source", {})
        integrations = raw.get("integrations", {})
        codex = integrations.get("codex_skill", {})
        return cls(
            plugin_id=raw["id"],
            title=raw["title"],
            description=raw.get("description", ""),
            plugin_api_version=raw.get("plugin_api_version", "cbn.plugin.v1"),
            provider=raw.get("provider", raw["id"]),
            repository=source["repository"],
            pip_packages=tuple(install.get("pip_packages", [])),
            entrypoints=tuple(raw.get("entrypoints", [])),
            permissions=tuple(raw.get("permissions", [])),
            install_modes=tuple(install.get("modes", raw.get("install_modes", []))),
            operations=tuple(
                PluginOperation.from_dict(item)
                for item in raw.get("operations", [])
                if isinstance(item, dict)
            ),
            optional_codex_skill_script=codex.get("script"),
        )

    def repo_dir(self, external_plugins_dir: Path) -> Path:
        return external_plugins_dir / self.plugin_id / "repo"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.plugin_id,
            "title": self.title,
            "description": self.description,
            "plugin_api_version": self.plugin_api_version,
            "provider": self.provider,
            "repository": self.repository,
            "pip_packages": list(self.pip_packages),
            "entrypoints": list(self.entrypoints),
            "permissions": list(self.permissions),
            "install_modes": list(self.install_modes),
            "operations": [operation.as_dict() for operation in self.operations],
            "optional_codex_skill_script": self.optional_codex_skill_script,
        }
