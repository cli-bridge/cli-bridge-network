"""External plugin manager.

The model follows the extension pattern used by SD WebUI-style launchers:
the core repository keeps only a small registry, while third-party plugin code
is cloned or installed into an ignored local directory and updated separately.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_plugins.manifest import PluginManifest


@dataclass(frozen=True)
class PluginCommand:
    label: str
    argv: tuple[str, ...]
    cwd: str | None = None
    optional: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "optional": self.optional,
        }


@dataclass(frozen=True)
class PluginPlan:
    plugin_id: str
    action: str
    plugin_dir: str
    commands: tuple[PluginCommand, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "action": self.action,
            "plugin_dir": self.plugin_dir,
            "commands": [command.as_dict() for command in self.commands],
            "requires_confirmation": True,
        }


class PluginManager:
    def __init__(self, root: Path | None = None) -> None:
        self.paths = resolve_project_paths(root)

    def _manifest_path(self, plugin_id: str) -> Path:
        return self.paths.plugin_registry / f"{plugin_id}.json"

    def load_manifest(self, plugin_id: str) -> PluginManifest:
        manifest_path = self._manifest_path(plugin_id)
        if not manifest_path.exists():
            raise KeyError(f"unknown plugin: {plugin_id}")
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        return PluginManifest.from_dict(raw)

    def list_plugins(self) -> list[dict[str, Any]]:
        plugins: list[dict[str, Any]] = []
        for path in sorted(self.paths.plugin_registry.glob("*.json")):
            manifest = self.load_manifest(path.stem)
            data = manifest.as_dict()
            data["installed"] = self._is_installed(manifest)
            plugins.append(data)
        return plugins

    def plugin_info(self, plugin_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(plugin_id)
        data = manifest.as_dict()
        data["installed"] = self._is_installed(manifest)
        data["plugin_dir"] = str(self.paths.external_plugins / manifest.plugin_id)
        return data

    def plan(
        self,
        plugin_id: str,
        action: str,
        include_codex_skill: bool = False,
    ) -> PluginPlan:
        manifest = self.load_manifest(plugin_id)
        plugin_dir = self.paths.external_plugins / manifest.plugin_id
        repo_dir = manifest.repo_dir(self.paths.external_plugins)
        commands: list[PluginCommand] = []

        if action not in {"install", "update"}:
            raise ValueError(f"unsupported plugin action: {action}")

        for package in manifest.pip_packages:
            commands.append(
                PluginCommand(
                    label=f"Install or upgrade {package}",
                    argv=(sys.executable, "-m", "pip", "install", "--upgrade", package),
                )
            )

        if action == "install":
            commands.append(
                PluginCommand(
                    label="Clone plugin source repository",
                    argv=("git", "clone", "--depth", "1", manifest.repository, str(repo_dir)),
                )
            )
        else:
            commands.append(
                PluginCommand(
                    label="Update plugin source repository",
                    argv=("git", "-C", str(repo_dir), "pull", "--ff-only"),
                )
            )

        if include_codex_skill and manifest.optional_codex_skill_script:
            script_path = repo_dir / manifest.optional_codex_skill_script
            if script_path.suffix.lower() == ".ps1":
                argv = (
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                )
            else:
                argv = ("bash", str(script_path))
            commands.append(
                PluginCommand(
                    label="Install optional Codex skill",
                    argv=argv,
                    optional=True,
                )
            )

        return PluginPlan(
            plugin_id=manifest.plugin_id,
            action=action,
            plugin_dir=str(plugin_dir),
            commands=tuple(commands),
        )

    def execute_plan(self, plan: PluginPlan) -> dict[str, Any]:
        self.paths.external_plugins.mkdir(parents=True, exist_ok=True)
        plugin_dir = Path(plan.plugin_dir)
        plugin_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, Any]] = []
        for command in plan.commands:
            if command.label.startswith("Clone") and (plugin_dir / "repo").exists():
                results.append(
                    {
                        "label": command.label,
                        "skipped": True,
                        "reason": "repository already exists",
                    }
                )
                continue
            proc = subprocess.run(
                list(command.argv),
                cwd=command.cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            results.append(
                {
                    "label": command.label,
                    "argv": list(command.argv),
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[-4000:],
                    "stderr": proc.stderr[-4000:],
                }
            )
            if proc.returncode != 0 and not command.optional:
                break
        return {"plugin_id": plan.plugin_id, "action": plan.action, "results": results}

    def _is_installed(self, manifest: PluginManifest) -> bool:
        repo_exists = manifest.repo_dir(self.paths.external_plugins).exists()
        entrypoints_exist = all(shutil.which(entrypoint) for entrypoint in manifest.entrypoints)
        return repo_exists or entrypoints_exist

