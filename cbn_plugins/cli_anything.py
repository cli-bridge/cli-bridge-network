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
from cbn_core.manifest import validate_manifest_dict
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
RISK_ORDER = ("read", "write-workspace", "external-network", "privileged")
RUNTIME_TEXT_KEYS = ("description", "requires")
LOCAL_NETWORK_MARKERS = (
    "localhost",
    "127.0.0.1",
    "::1",
)
EXTERNAL_NETWORK_MARKERS = (
    "api key",
    "apikey",
    "access token",
    "auth token",
    "bearer token",
    "google_cloud_project",
    "gemini_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "vertex ai",
    "gemini",
    "openai",
    "anthropic",
    "replicate",
    "huggingface",
    "cloud",
)
WRITE_WORKSPACE_MARKERS = (
    "generate",
    "generation",
    "export",
    "convert",
    "transcode",
    "render",
    "edit",
    "image",
    "video",
    "svg",
    "raster",
    "painting",
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
        market_record = self.market_record_for_harness(harness_name) if from_market else None
        market_name = str((market_record or {}).get("name") or harness_name)
        safe_name = sanitize_harness_name(market_name)
        capability_id = f"cli-anything.{safe_name}.launch"
        manifest_path = self.paths.manifests / f"{capability_id}.json"
        info_result = self.info(harness_name)
        info_fields = _parse_info_fields(info_result.stdout)
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
            "market_name": market_name,
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
        if action not in {"install", "update", "uninstall", "launch"}:
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
        policy = infer_market_policy(market_record, requested_risk=risk)
        if policy["reasons"]:
            annotations["cli-anything.policy_inference"] = json.dumps(
                policy["reasons"],
                ensure_ascii=False,
                sort_keys=True,
            )
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
                    "risk": policy["risk"],
                    "requiresConfirmation": policy["requires_confirmation"],
                    "network": policy["network"],
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
        path = self.paths.manifests / f"{manifest['metadata']['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def adapt_harness(
        self,
        harness_name: str,
        title: str | None = None,
        from_market: bool = False,
        write: bool = False,
    ) -> dict[str, Any]:
        market_record = self.market_record_for_harness(harness_name) if from_market else None
        if from_market and market_record is None:
            return {
                "ok": False,
                "error": "CLI-Anything market record not found",
                "plugin_id": PLUGIN_ID,
                "harness_name": harness_name,
                "from_market": True,
            }
        manifest = self.manifest_for_harness(harness_name, title=title, market_record=market_record)
        capability_id = manifest["metadata"]["id"]
        manifest_path = self.paths.manifests / f"{capability_id}.json"
        written = None
        if write:
            written = self.write_harness_manifest(harness_name, title=title, market_record=market_record)
            manifest_path = written
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "harness_name": harness_name,
            "from_market": from_market,
            "market_record_available": market_record is not None,
            "write": write,
            "written": str(written) if written else None,
            "manifest_path": str(manifest_path),
            "manifest": manifest,
            "validation": validate_manifest_dict(manifest, source_path=manifest_path),
            "status": self.harness_status(harness_name, from_market=from_market),
            "next_commands": [
                f"python -m cbn plugin harness cli-anything status {harness_name} --from-market",
                f"python -m cbn plugin harness cli-anything install {harness_name} --yes",
                f"python -m cbn call {capability_id} --dry-run",
                f"python -m cbn protocol export all --capability-id {capability_id}",
            ],
        }

    def sync_market(
        self,
        query: str | None = None,
        limit: int = 50,
        write: bool = False,
    ) -> dict[str, Any]:
        result = self.search_market(query) if query else self.list_market()
        records = _market_records_from_result(result.parsed_json)
        if result.exit_code != 0:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "query": query,
                "write": write,
                "error": "CLI-Anything market command failed",
                "market": result.as_dict(),
                "records": [],
                "manifests": [],
            }
        if records is None:
            return {
                "ok": False,
                "plugin_id": PLUGIN_ID,
                "query": query,
                "write": write,
                "error": "CLI-Anything market command did not return a supported JSON list shape",
                "market": result.as_dict(),
                "records": [],
                "manifests": [],
            }
        bounded_limit = max(0, min(limit, 500))
        selected = records[:bounded_limit]
        manifests = []
        for record in selected:
            harness_name = str(record.get("name") or record.get("display_name") or "").strip()
            if not harness_name:
                manifests.append(
                    {
                        "ok": False,
                        "error": "market record is missing name/display_name",
                        "market_record": record,
                    }
                )
                continue
            manifest = self.manifest_for_harness(harness_name, market_record=record)
            capability_id = manifest["metadata"]["id"]
            path = self.paths.manifests / f"{capability_id}.json"
            written = None
            if write:
                written = self.write_harness_manifest(harness_name, market_record=record)
                path = written
            validation = validate_manifest_dict(manifest, source_path=path)
            manifests.append(
                {
                    "ok": True,
                    "harness_name": harness_name,
                    "capability_id": capability_id,
                    "manifest_path": str(path),
                    "written": str(written) if written else None,
                    "manifest": manifest,
                    "validation": validation,
                }
            )
        imported = [item for item in manifests if item.get("ok")]
        return {
            "ok": True,
            "plugin_id": PLUGIN_ID,
            "query": query,
            "write": write,
            "limit": bounded_limit,
            "market_count": len(records),
            "selected_count": len(selected),
            "importable_count": len(imported),
            "market": result.as_dict(),
            "manifests": manifests,
            "next_commands": [
                "python -m cbn registry search cli-anything",
                "python -m cbn protocol export all --capability-id <capability_id>",
                "python -m cbn plugin harness cli-anything install <harness> --yes",
            ],
        }

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


def infer_market_policy(
    market_record: dict[str, Any] | None,
    requested_risk: str = "read",
) -> dict[str, Any]:
    risk = requested_risk
    network = "deny"
    reasons: list[str] = []
    if market_record:
        runtime_text = _market_runtime_text(market_record)
        if _has_local_network_signal(runtime_text):
            network = "localhost"
            reasons.append("runtime mentions local service or localhost dependency")
        if _has_external_network_signal(runtime_text):
            risk = _max_risk(risk, "external-network")
            network = "requires-confirmation"
            reasons.append("runtime mentions external API, cloud service, token, or API key")
        if _has_write_workspace_signal(runtime_text):
            risk = _max_risk(risk, "write-workspace")
            reasons.append("runtime appears to generate, edit, render, convert, or export artifacts")
    requires_confirmation = risk in {"privileged", "external-network"}
    if risk in {"privileged", "external-network"}:
        network = "requires-confirmation" if risk == "external-network" else network
    return {
        "risk": risk,
        "requires_confirmation": requires_confirmation,
        "network": network,
        "reasons": reasons,
    }


def _market_records_from_result(parsed_json: Any) -> list[dict[str, Any]] | None:
    if isinstance(parsed_json, list):
        records = parsed_json
    elif isinstance(parsed_json, dict):
        records = None
        for key in ("items", "harnesses", "tools", "results", "data"):
            value = parsed_json.get(key)
            if isinstance(value, list):
                records = value
                break
        if records is None:
            return None
    else:
        return None
    return [item for item in records if isinstance(item, dict)]


def _market_runtime_text(market_record: dict[str, Any]) -> str:
    values = []
    for key in RUNTIME_TEXT_KEYS:
        value = market_record.get(key)
        if value:
            values.append(str(value))
    return "\n".join(values).casefold()


def _has_local_network_signal(text: str) -> bool:
    return any(marker in text for marker in LOCAL_NETWORK_MARKERS)


def _has_external_network_signal(text: str) -> bool:
    if any(marker in text for marker in EXTERNAL_NETWORK_MARKERS):
        return True
    for match in re.findall(r"https?://[^\s)]+", text):
        if not any(local in match for local in LOCAL_NETWORK_MARKERS):
            return True
    return False


def _has_write_workspace_signal(text: str) -> bool:
    return any(marker in text for marker in WRITE_WORKSPACE_MARKERS)


def _max_risk(left: str, right: str) -> str:
    try:
        left_rank = RISK_ORDER.index(left)
        right_rank = RISK_ORDER.index(right)
    except ValueError as exc:
        raise ValueError(f"unknown risk level for CLI-Anything policy inference: {exc}") from exc
    return left if left_rank >= right_rank else right
