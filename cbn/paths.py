"""Centralized project path handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    config: Path
    manifests: Path
    workflows: Path
    runtime: Path
    logs: Path
    external_plugins: Path
    plugin_registry: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "config": str(self.config),
            "manifests": str(self.manifests),
            "workflows": str(self.workflows),
            "runtime": str(self.runtime),
            "logs": str(self.logs),
            "external_plugins": str(self.external_plugins),
            "plugin_registry": str(self.plugin_registry),
        }


def resolve_project_paths(root: Path | None = None) -> ProjectPaths:
    base = (root or Path(__file__).resolve().parents[1]).resolve()
    return ProjectPaths(
        root=base,
        config=base / "cbn.yaml",
        manifests=base / "manifests",
        workflows=base / "workflows",
        runtime=base / "runtime",
        logs=base / "runtime" / "logs",
        external_plugins=base / "external_plugins",
        plugin_registry=base / "plugins" / "registry",
    )
