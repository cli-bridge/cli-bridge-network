"""Plugin manifest types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    title: str
    description: str
    repository: str
    pip_packages: tuple[str, ...]
    entrypoints: tuple[str, ...]
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
            repository=source["repository"],
            pip_packages=tuple(install.get("pip_packages", [])),
            entrypoints=tuple(raw.get("entrypoints", [])),
            optional_codex_skill_script=codex.get("script"),
        )

    def repo_dir(self, external_plugins_dir: Path) -> Path:
        return external_plugins_dir / self.plugin_id / "repo"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.plugin_id,
            "title": self.title,
            "description": self.description,
            "repository": self.repository,
            "pip_packages": list(self.pip_packages),
            "entrypoints": list(self.entrypoints),
            "optional_codex_skill_script": self.optional_codex_skill_script,
        }

