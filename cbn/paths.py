"""Centralized project path handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    config: Path
    manifests: Path
    local_manifests: Path
    workflows: Path
    runtime: Path
    logs: Path
    artifacts: Path
    approvals: Path
    external_plugins: Path
    plugin_registry: Path
    threads: Path
    favorites: Path
    mcp_ingress: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "config": str(self.config),
            "manifests": str(self.manifests),
            "local_manifests": str(self.local_manifests),
            "workflows": str(self.workflows),
            "runtime": str(self.runtime),
            "logs": str(self.logs),
            "artifacts": str(self.artifacts),
            "approvals": str(self.approvals),
            "external_plugins": str(self.external_plugins),
            "plugin_registry": str(self.plugin_registry),
            "threads": str(self.threads),
            "favorites": str(self.favorites),
            "mcp_ingress": str(self.mcp_ingress),
        }


def resolve_project_paths(root: Path | None = None) -> ProjectPaths:
    base = (root or Path(__file__).resolve().parents[1]).resolve()
    runtime = base / "runtime"
    return ProjectPaths(
        root=base,
        config=base / "cbn.yaml",
        manifests=base / "manifests",
        local_manifests=runtime / "manifests",
        workflows=base / "workflows",
        runtime=runtime,
        logs=runtime / "logs",
        artifacts=runtime / "artifacts",
        approvals=runtime / "approvals.jsonl",
        external_plugins=base / "external_plugins",
        plugin_registry=base / "plugins" / "registry",
        threads=runtime / "threads",
        favorites=runtime / "favorites",
        mcp_ingress=runtime / "mcp_ingress",
    )
