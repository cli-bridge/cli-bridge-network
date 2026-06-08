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
MARKET_LABEL_KEYS = ("category", "_source", "package_manager", "platform")
MARKET_ANNOTATION_KEYS = (
    "display_name",
    "version",
    "description",
    "requires",
    "homepage",
    "docs_url",
    "source_url",
    "install_cmd",
    "update_cmd",
    "uninstall_cmd",
    "entry_point",
    "skill_md",
    "npm_package",
    "npx_cmd",
    "contributors",
)


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

    def harness_status(self, harness_name: str, from_market: bool = False) -> dict[str, Any]:
        safe_name = sanitize_harness_name(harness_name)
        capability_id = f"cli-anything.{safe_name}.launch"
        manifest_path = self.paths.manifests / f"{capability_id}.json"
        info_result = self.info(harness_name)
        info_fields = _parse_info_fields(info_result.stdout)
        market_record = self.market_record_for_harness(harness_name) if from_market else None
        entry_point = (
            info_fields.get("entry_point")
            or str((market_record or {}).get("entry_point") or "")
            or None
        )
        status_text = info_fields.get("status")
        installed = _is_installed_status(status_text)
        entrypoint_path = shutil.which(entry_point) if entry_point else None
        return {
            "plugin_id": PLUGIN_ID,
            "harness_name": harness_name,
            "safe_name": safe_name,
            "capability_id": capability_id,
            "manifest_path": str(manifest_path),
            "manifest_imported": manifest_path.exists(),
            "cli_hub_available": info_result.exit_code != 127,
            "cli_hub_info": {
                "argv": list(info_result.argv),
                "exit_code": info_result.exit_code,
                "status": status_text,
                "fields": info_fields,
            },
            "market_record_available": market_record is not None,
            "market_record": market_record,
            "entry_point": entry_point,
            "entrypoint_path": entrypoint_path,
            "entrypoint_available": entrypoint_path is not None,
            "installed": installed,
            "launch_ready": bool(installed and entrypoint_path),
        }

    def market_record_for_harness(self, harness_name: str) -> dict[str, Any] | None:
        result = self.search_market(harness_name)
        if result.exit_code != 0 or not isinstance(result.parsed_json, list):
            return None
        safe_name = sanitize_harness_name(harness_name)
        candidates = [item for item in result.parsed_json if isinstance(item, dict)]
        for item in candidates:
            if _matches_sanitized_name(item.get("name"), safe_name):
                return item
        for item in candidates:
            if _matches_sanitized_name(item.get("display_name"), safe_name):
                return item
        return candidates[0] if candidates else None

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
        market_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        market_record = market_record or {}
        market_name = str(market_record.get("name") or harness_name)
        display_name = str(market_record.get("display_name") or market_name)
        safe_name = sanitize_harness_name(market_name)
        capability_id = f"cli-anything.{safe_name}.launch"
        labels = {
            "plugin": PLUGIN_ID,
            "harness": market_name,
        }
        labels.update(_market_labels(market_record))
        annotations = _market_annotations(market_record)
        return {
            "apiVersion": "bridge.dev/v1alpha1",
            "kind": "ToolManifest",
            "metadata": {
                "id": capability_id,
                "title": title or f"CLI-Anything {display_name}",
                "labels": labels,
                "annotations": annotations,
            },
            "spec": {
                "transport": {
                    "kind": "stdio",
                    "command": self.entrypoint,
                    "argsTemplate": ["launch", market_name],
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

    def write_harness_manifest(
        self,
        harness_name: str,
        title: str | None = None,
        market_record: dict[str, Any] | None = None,
    ) -> Path:
        manifest = self.manifest_for_harness(harness_name, title=title, market_record=market_record)
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


def _matches_sanitized_name(value: Any, expected: str) -> bool:
    if value is None:
        return False
    try:
        return sanitize_harness_name(str(value)) == expected
    except ValueError:
        return False


def _parse_info_fields(stdout: str) -> dict[str, str]:
    fields = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = re.sub(r"[^a-z0-9]+", "_", key.strip().casefold()).strip("_")
        value = value.strip()
        if key and value:
            fields[key] = value
    return fields


def _is_installed_status(status_text: str | None) -> bool:
    if not status_text:
        return False
    normalized = status_text.strip().casefold()
    return normalized == "installed" or normalized.startswith("installed ")


def _market_labels(market_record: dict[str, Any]) -> dict[str, str]:
    labels = {}
    for key in MARKET_LABEL_KEYS:
        value = market_record.get(key)
        if value is None or value == "":
            continue
        labels[key.strip("_")] = str(value)
    return labels


def _market_annotations(market_record: dict[str, Any]) -> dict[str, str]:
    annotations = {}
    for key in MARKET_ANNOTATION_KEYS:
        value = market_record.get(key)
        if value is None or value == "":
            continue
        annotation_key = f"cli-anything.{key}"
        if isinstance(value, (dict, list)):
            annotations[annotation_key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            annotations[annotation_key] = str(value)
    return annotations
