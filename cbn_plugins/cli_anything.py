"""CLI-Anything / CLI-Hub integration helpers.

This module intentionally treats CLI-Anything as an external plugin. It never
vendors upstream code; it only detects `cli-hub`, calls it when available, and
generates CBN manifests for installed or planned harnesses.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn.paths import resolve_project_paths
from cbn_plugins.manager import PluginCommand, PluginPlan


PLUGIN_ID = "cli-anything"


@dataclass(frozen=True)
class CliHubCommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    parsed_json: Any | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "parsed_json": self.parsed_json,
        }


class CliAnythingHub:
    def __init__(self, root: Path | None = None, entrypoint: str = "cli-hub") -> None:
        self.paths = resolve_project_paths(root)
        self.entrypoint = entrypoint

    def status(self) -> dict[str, Any]:
        executable = shutil.which(self.entrypoint)
        repo_dir = self.paths.external_plugins / PLUGIN_ID / "repo"
        version = None
        if executable:
            result = self._run(("--version",), parse_json=False)
            version = (result.stdout or result.stderr).strip() or None
        return {
            "plugin_id": PLUGIN_ID,
            "entrypoint": self.entrypoint,
            "entrypoint_path": executable,
            "entrypoint_available": executable is not None,
            "source_repo_dir": str(repo_dir),
            "source_repo_available": repo_dir.exists(),
            "version": version,
        }

    def list_market(self) -> CliHubCommandResult:
        return self._run(("list", "--json"), parse_json=True)

    def search_market(self, query: str) -> CliHubCommandResult:
        return self._run(("search", query, "--json"), parse_json=True)

    def info(self, harness_name: str) -> CliHubCommandResult:
        return self._run(("info", harness_name), parse_json=False)

    def harness_plan(
        self,
        action: str,
        harness_name: str,
        extra_args: tuple[str, ...] = (),
    ) -> PluginPlan:
        if action not in {"install", "update", "launch"}:
            raise ValueError(f"unsupported CLI-Anything harness action: {action}")
        safe_name = sanitize_harness_name(harness_name)
        if action == "launch":
            argv = (self.entrypoint, "launch", harness_name, *extra_args)
        else:
            argv = (self.entrypoint, action, harness_name)
        return PluginPlan(
            plugin_id=PLUGIN_ID,
            action=f"harness-{action}-{safe_name}",
            plugin_dir=str(self.paths.external_plugins / PLUGIN_ID),
            commands=(
                PluginCommand(
                    label=f"CLI-Anything harness {action}: {harness_name}",
                    argv=argv,
                ),
            ),
        )

    def manifest_for_harness(
        self,
        harness_name: str,
        title: str | None = None,
        risk: str = "read",
    ) -> dict[str, Any]:
        safe_name = sanitize_harness_name(harness_name)
        capability_id = f"cli-anything.{safe_name}.launch"
        return {
            "apiVersion": "bridge.dev/v1alpha1",
            "kind": "ToolManifest",
            "metadata": {
                "id": capability_id,
                "title": title or f"CLI-Anything {harness_name}",
                "labels": {
                    "plugin": PLUGIN_ID,
                    "harness": harness_name,
                },
            },
            "spec": {
                "transport": {
                    "kind": "stdio",
                    "command": self.entrypoint,
                    "argsTemplate": ["launch", harness_name],
                    "cwdPolicy": "workspace",
                },
                "policy": {
                    "risk": risk,
                    "requiresConfirmation": risk in {"privileged", "external-network"},
                    "network": "deny" if risk != "external-network" else "requires-confirmation",
                },
                "output": {
                    "parserRef": "cli-anything.raw",
                    "verified": False,
                },
            },
        }

    def write_harness_manifest(self, harness_name: str, title: str | None = None) -> Path:
        manifest = self.manifest_for_harness(harness_name, title=title)
        safe_name = sanitize_harness_name(harness_name)
        path = self.paths.manifests / f"cli-anything.{safe_name}.launch.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _run(self, args: tuple[str, ...], parse_json: bool) -> CliHubCommandResult:
        executable = shutil.which(self.entrypoint)
        argv = (self.entrypoint, *args)
        if executable is None:
            return CliHubCommandResult(
                argv=argv,
                exit_code=127,
                stdout="",
                stderr=f"{self.entrypoint} is not installed or not on PATH",
            )
        proc = subprocess.run(
            [executable, *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        parsed = None
        if parse_json and proc.stdout.strip():
            try:
                parsed = json.loads(proc.stdout)
            except json.JSONDecodeError:
                parsed = None
        return CliHubCommandResult(
            argv=(executable, *args),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            parsed_json=parsed,
        )


def sanitize_harness_name(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name.strip()).strip("-._")
    if not normalized:
        raise ValueError("harness name cannot be empty")
    return normalized.lower()
