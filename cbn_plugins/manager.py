"""External plugin manager.

The model follows the extension pattern used by SD WebUI-style launchers:
the core repository keeps only a small registry, while third-party plugin code
is cloned or installed into an ignored local directory and updated separately.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.pty import pty_backend_status
from cbn.paths import resolve_project_paths
from cbn_plugins.manifest import PluginManifest
from cbn_plugins.manager_parts.catalog import (
    catalog_list_validation as _catalog_list_validation,
    operation_api_request as _operation_api_request,
    operation_catalog_for_manifest as _operation_catalog_for_manifest,
    resolve_string_template as _resolve_string_template,
    resolve_value_template as _resolve_value_template,
)
from cbn_plugins.manager_parts.models import PluginCommand, PluginPlan
from cbn_plugins.manager_parts.preflight import (
    PreflightCheck,
    check_pip as _check_pip,
    preflight_report as _preflight_report,
)
from cbn_plugins.manager_parts.provenance import (
    entrypoint_provenance as _entrypoint_provenance,
    parse_ls_remote_head as _parse_ls_remote_head,
    pip_package_provenance as _pip_package_provenance,
    repo_provenance as _repo_provenance,
)
from cbn_plugins.manager_parts.verification import (
    run_command as _run_command,
    verification_report_for_plan,
)


@dataclass(frozen=True)
class OperationPlanPayloadInput:
    catalog: dict[str, Any]
    plugin_id: str
    operation_id: str
    operation: dict[str, Any]
    provided_inputs: dict[str, Any]
    resolution: dict[str, Any]
    payload: Any
    api_request: dict[str, Any] | None
    blockers: list[str]
    validation: dict[str, Any]
    confirmed: bool


@dataclass(frozen=True)
class PluginProvenancePayloadInput:
    manifest: PluginManifest
    plugin_dir: Path
    repo_dir: Path
    repository: dict[str, Any]
    packages: list[dict[str, Any]]
    entrypoints: list[dict[str, Any]]
    warnings: list[str]
    blockers: list[str]
    installed: bool


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

    def operation_catalog(self, plugin_id: str | None = None) -> dict[str, Any]:
        manifests = [self.load_manifest(plugin_id)] if plugin_id else [
            self.load_manifest(path.stem)
            for path in sorted(self.paths.plugin_registry.glob("*.json"))
        ]
        catalogs = [
            _operation_catalog_for_manifest(manifest, installed=self._is_installed(manifest))
            for manifest in manifests
        ]
        if plugin_id:
            return catalogs[0]
        return {
            "ok": True,
            "kind": "PluginProviderOperationCatalogList",
            "plugin_api_version": "cbn.plugin.v1",
            "plugin_count": len(catalogs),
            "catalogs": catalogs,
            "summary": {
                "operation_count": sum(item["summary"]["operation_count"] for item in catalogs),
                "provider_count": len({item["provider"] for item in catalogs}),
            },
            "validation": _catalog_list_validation(catalogs),
        }

    def validate_operation_catalog(self, plugin_id: str | None = None) -> dict[str, Any]:
        catalog = self.operation_catalog(plugin_id)
        if plugin_id:
            reports = [catalog]
            validation = catalog["validation"]
        else:
            reports = catalog["catalogs"]
            validation = catalog["validation"]
        return {
            "ok": bool(validation["ok"]),
            "kind": "PluginProviderOperationCatalogValidation",
            "plugin_api_version": "cbn.plugin.v1",
            "plugin_id": plugin_id,
            "plugin_count": len(reports),
            "summary": {
                "operation_count": sum(report["summary"]["operation_count"] for report in reports),
                "error_count": validation["error_count"],
                "warning_count": validation["warning_count"],
            },
            "reports": [
                {
                    "plugin_id": report["plugin_id"],
                    "provider": report["provider"],
                    "validation": report["validation"],
                }
                for report in reports
            ],
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        }

    def operation_plan(
        self,
        plugin_id: str,
        operation_id: str,
        inputs: dict[str, Any] | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        catalog = self.operation_catalog(plugin_id)
        operation = _require_catalog_operation(catalog, plugin_id, operation_id)
        provided_inputs = dict(inputs or {})
        resolution = _resolve_operation_inputs(operation, provided_inputs)
        validation = dict(catalog["validation"])
        blockers = _operation_plan_blockers(operation, validation, resolution["missing_inputs"], confirmed)
        payload = _operation_payload(operation, resolution["payload"], confirmed)
        api = operation.get("api") if isinstance(operation.get("api"), dict) else None
        api_request = _operation_api_request(api, payload)
        return _operation_plan_payload(OperationPlanPayloadInput(
            catalog=catalog,
            plugin_id=plugin_id,
            operation_id=operation_id,
            operation=operation,
            provided_inputs=provided_inputs,
            resolution=resolution,
            payload=payload,
            api_request=api_request,
            blockers=blockers,
            validation=validation,
            confirmed=confirmed,
        ))

    def provenance(self, plugin_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(plugin_id)
        plugin_dir = self.paths.external_plugins / manifest.plugin_id
        repo_dir = manifest.repo_dir(self.paths.external_plugins)
        repository = _repo_provenance(repo_dir, expected_remote=manifest.repository)
        packages = [_pip_package_provenance(package) for package in manifest.pip_packages]
        entrypoints = [_entrypoint_provenance(entrypoint) for entrypoint in manifest.entrypoints]
        warnings, blockers = _provenance_issues(repository, packages, entrypoints)
        return _provenance_payload(PluginProvenancePayloadInput(
            manifest=manifest,
            plugin_dir=plugin_dir,
            repo_dir=repo_dir,
            repository=repository,
            packages=packages,
            entrypoints=entrypoints,
            warnings=warnings,
            blockers=blockers,
            installed=self._is_installed(manifest),
        ))

    def update_check(self, plugin_id: str, remote: bool = False) -> dict[str, Any]:
        manifest = self.load_manifest(plugin_id)
        provenance = self.provenance(plugin_id)
        repository = dict(provenance["repository"])
        remote_probe, update_available, probe_warnings = self._remote_update_probe(manifest, repository, remote)
        blockers = _update_repository_blockers(repository)
        warnings = [*provenance["warnings"], *probe_warnings]
        ready_for_update = len(blockers) == 0
        return {
            "plugin_id": manifest.plugin_id,
            "title": manifest.title,
            "installed": provenance["installed"],
            "ready_for_update": ready_for_update,
            "source_downloaded": provenance["source_downloaded"],
            "source_trusted": provenance["source_trusted"],
            "repository": {
                "repo_dir": provenance["repo_dir"],
                "remote_url": repository.get("remote_url"),
                "branch": repository.get("branch"),
                "head": repository.get("head"),
                "dirty": repository.get("dirty"),
                "remote_matches_expected": repository.get("remote_matches_expected"),
                "remote_probe": remote_probe,
                "update_available": update_available,
            },
            "packages": _package_update_checks(provenance["pip_packages"]),
            "entrypoints": _entrypoint_update_checks(provenance["entrypoints"]),
            "blockers": blockers,
            "warnings": warnings,
            "next_commands": _update_check_next_commands(manifest.plugin_id),
        }

    def _remote_update_probe(
        self,
        manifest: PluginManifest,
        repository: dict[str, Any],
        remote: bool,
    ) -> tuple[dict[str, Any], bool | None, list[str]]:
        remote_probe = _empty_remote_probe(remote)
        update_available: bool | None = None
        warnings: list[str] = []
        if not (remote and repository["exists"] and repository["is_git"]):
            return remote_probe, update_available, warnings
        repo_dir = manifest.repo_dir(self.paths.external_plugins)
        probe = _run_command(("git", "-C", str(repo_dir), "ls-remote", "origin", "HEAD"), timeout_seconds=30)
        remote_probe["checked"] = True
        remote_probe["exit_code"] = probe["exit_code"]
        remote_probe["stderr"] = probe["stderr"]
        if probe["exit_code"] == 0:
            remote_head = _parse_ls_remote_head(probe["stdout"])
            remote_probe["head"] = remote_head
            remote_probe["available"] = remote_head is not None
            if remote_head and repository.get("head"):
                update_available = remote_head != repository["head"]
        else:
            remote_probe["available"] = False
            warnings.append("remote update check failed")
        return remote_probe, update_available, warnings

    def preflight(self, plugin_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(plugin_id)
        plugin_dir = self.paths.external_plugins / manifest.plugin_id
        repo_dir = manifest.repo_dir(self.paths.external_plugins)
        return _preflight_report(
            manifest,
            plugin_dir=plugin_dir,
            repo_dir=repo_dir,
            external_plugins_dir=self.paths.external_plugins,
            installed=self._is_installed(manifest),
        )

    def operation_gate(self, plugin_id: str, action: str) -> dict[str, Any]:
        if action not in {"install", "update"}:
            return {
                "ok": True,
                "plugin_id": plugin_id,
                "action": action,
                "gated": False,
                "blockers": [],
            }
        preflight = self.preflight(plugin_id)
        provenance = self.provenance(plugin_id)
        blockers = [
            f"preflight failed: {check['check_id']}"
            for check in preflight["checks"]
            if check["severity"] == "error" and not check["ok"]
        ]
        if action == "update":
            if not provenance["source_downloaded"]:
                blockers.append("plugin source repository is not downloaded")
            if provenance["source_trusted"] is False:
                blockers.append("plugin source repository is not trusted")
        return {
            "ok": len(blockers) == 0,
            "plugin_id": plugin_id,
            "action": action,
            "gated": True,
            "blockers": blockers,
            "preflight": preflight,
            "provenance": provenance,
            "override_flag": "--allow-failed-preflight",
        }

    def runtime_transport_status(self, kind: str) -> dict[str, Any]:
        if kind != "pty":
            raise ValueError(f"unsupported runtime transport: {kind}")
        status = dict(pty_backend_status())
        status["ready"] = bool(status["available"])
        status["managed_dependency"] = _runtime_transport_dependency(kind)
        status["next_commands"] = _runtime_transport_next_commands(kind, status)
        return status

    def runtime_transport_gate(self, kind: str) -> dict[str, Any]:
        status = self.runtime_transport_status(kind)
        blockers: list[str] = []
        checks: list[dict[str, Any]] = []

        if status["ready"]:
            return {
                "ok": True,
                "kind": kind,
                "gated": True,
                "blockers": [],
                "status": status,
                "checks": checks,
            }

        if kind == "pty" and os.name == "nt":
            pip_check = _check_pip()
            checks.append(pip_check.as_dict())
            if not pip_check.ok:
                blockers.append("preflight failed: python.pip")
        else:
            blockers.append(f"runtime transport is not installable by CBN: {kind}")

        return {
            "ok": len(blockers) == 0,
            "kind": kind,
            "gated": True,
            "blockers": blockers,
            "status": status,
            "checks": checks,
            "override_flag": None,
        }

    def runtime_transport_plan(self, kind: str) -> PluginPlan:
        status = self.runtime_transport_status(kind)
        plugin_dir = self.paths.external_plugins / ".runtime" / kind
        dependency = status["managed_dependency"]
        commands: list[PluginCommand] = []
        notes: list[str] = [
            f"Runtime transport: {kind}",
            f"Backend: {status['backend']}",
        ]

        if status["ready"]:
            notes.append("Runtime transport backend is already available; no install command is needed.")
        elif kind == "pty" and os.name == "nt" and dependency:
            commands.append(
                PluginCommand(
                    label=f"Install optional runtime backend {dependency}",
                    argv=(sys.executable, "-m", "pip", "install", "--upgrade", dependency),
                    timeout_seconds=600,
                )
            )
            notes.append("Windows PTY launch support requires pywinpty.")
        else:
            notes.append("No managed install command is available for this platform.")

        return PluginPlan(
            plugin_id=f"runtime.{kind}",
            action=f"install-runtime-{kind}",
            plugin_dir=str(plugin_dir),
            commands=tuple(commands),
            notes=tuple(notes),
            verification_commands=(
                f"python -m cbn runtime transport {kind}",
                "python -m cbn protocol smoke-suite --workflow-dry-run",
            ),
        )

    def plan(
        self,
        plugin_id: str,
        action: str,
        include_codex_skill: bool = False,
    ) -> PluginPlan:
        _ensure_plugin_action(action)
        manifest = self.load_manifest(plugin_id)
        plugin_dir = self.paths.external_plugins / manifest.plugin_id
        repo_dir = manifest.repo_dir(self.paths.external_plugins)
        commands = [
            *_pip_install_commands(manifest),
            _source_command(manifest, repo_dir, action),
            *_optional_codex_skill_commands(manifest, repo_dir, include_codex_skill),
        ]
        return PluginPlan(
            plugin_id=manifest.plugin_id,
            action=action,
            plugin_dir=str(plugin_dir),
            commands=tuple(commands),
            verification_commands=tuple(_plugin_verification_commands(manifest.plugin_id)),
        )

    def verify_plan(
        self,
        plugin_id: str,
        action: str = "install",
        include_codex_skill: bool = False,
        run: bool = False,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        plan = self.plan(
            plugin_id,
            action=action,
            include_codex_skill=include_codex_skill,
        )
        return verification_report_for_plan(
            plan,
            report_kind="PluginPlanVerificationReport",
            run=run,
            timeout_seconds=timeout_seconds,
            next_commands=(
                f"python -m cbn plugin verify-plan {plugin_id} --action {action}",
                f"python -m cbn plugin verify-plan {plugin_id} --action {action} --run",
            ),
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


def _require_catalog_operation(
    catalog: dict[str, Any],
    plugin_id: str,
    operation_id: str,
) -> dict[str, Any]:
    operation = next(
        (item for item in catalog["operations"] if item.get("id") == operation_id),
        None,
    )
    if operation is None:
        raise KeyError(f"unknown plugin operation: {plugin_id}/{operation_id}")
    return operation


def _resolve_operation_inputs(
    operation: dict[str, Any],
    provided_inputs: dict[str, Any],
) -> dict[str, Any]:
    command, command_missing = _resolve_string_template(str(operation.get("command") or ""), provided_inputs)
    payload, payload_missing = _resolve_value_template(operation.get("payload_template", {}), provided_inputs)
    return {
        "command": command,
        "payload": payload,
        "missing_inputs": sorted(set([*command_missing, *payload_missing])),
    }


def _operation_plan_blockers(
    operation: dict[str, Any],
    validation: dict[str, Any],
    missing_inputs: list[str],
    confirmed: bool,
) -> list[str]:
    blockers = [f"missing input: {name}" for name in missing_inputs]
    if not validation["ok"]:
        blockers.extend(f"catalog invalid: {error}" for error in validation["errors"])
    if _operation_has_side_effects(operation) and not confirmed:
        blockers.append("operation requires confirmed=true before dispatch")
    return blockers


def _operation_has_side_effects(operation: dict[str, Any]) -> bool:
    return operation.get("kind") in {"execute", "write"}


def _operation_payload(
    operation: dict[str, Any],
    payload: Any,
    confirmed: bool,
) -> Any:
    if _operation_has_side_effects(operation) and confirmed and isinstance(payload, dict):
        payload.setdefault("confirmed", True)
    return payload


def _operation_plan_payload(data: OperationPlanPayloadInput) -> dict[str, Any]:
    command = data.resolution["command"]
    return {
        "ok": not data.blockers,
        "kind": "PluginProviderOperationPlan",
        "plugin_api_version": data.catalog["plugin_api_version"],
        "plugin_id": data.plugin_id,
        "provider": data.catalog["provider"],
        "operation_id": data.operation_id,
        "operation_kind": data.operation.get("kind"),
        "confirmed": data.confirmed,
        "dispatch_ready": not data.blockers,
        "requires_confirmation": bool(data.operation.get("requires_confirmation")),
        "side_effects": data.operation.get("side_effects", []),
        "inputs": data.provided_inputs,
        "required_inputs": data.operation.get("required_inputs", []),
        "missing_inputs": data.resolution["missing_inputs"],
        "blockers": data.blockers,
        "operation": data.operation,
        "resolved_command": command,
        "resolved_payload": data.payload,
        "api_request": data.api_request,
        "validation": data.validation,
        "next_commands": [
            f"python -m cbn plugin operation-plan {data.plugin_id} {data.operation_id}",
            command,
        ],
    }


def _provenance_issues(
    repository: dict[str, Any],
    packages: list[dict[str, Any]],
    entrypoints: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    blockers: list[str] = []
    if repository["exists"] and not repository["is_git"]:
        blockers.append("plugin repo directory exists but is not a git checkout")
    if repository.get("remote_url") and not repository.get("remote_matches_expected"):
        blockers.append("plugin repo remote does not match registry source")
    if repository.get("dirty"):
        warnings.append("plugin source checkout has uncommitted changes")
    warnings.extend(_missing_package_warnings(packages))
    warnings.extend(_missing_entrypoint_warnings(entrypoints))
    return warnings, blockers


def _missing_package_warnings(packages: list[dict[str, Any]]) -> list[str]:
    return [
        f"pip package is not installed: {package['package']}"
        for package in packages
        if not package["installed"]
    ]


def _missing_entrypoint_warnings(entrypoints: list[dict[str, Any]]) -> list[str]:
    return [
        f"entrypoint is not available on PATH: {entrypoint['entrypoint']}"
        for entrypoint in entrypoints
        if not entrypoint["available"]
    ]


def _provenance_payload(report: PluginProvenancePayloadInput) -> dict[str, Any]:
    manifest = report.manifest
    return {
        "plugin_id": manifest.plugin_id,
        "title": manifest.title,
        "installed": report.installed,
        "plugin_dir": str(report.plugin_dir),
        "repo_dir": str(report.repo_dir),
        "expected_repository": manifest.repository,
        "repository": report.repository,
        "pip_packages": report.packages,
        "entrypoints": report.entrypoints,
        "ready_for_entrypoints": all(item["available"] for item in report.entrypoints),
        "ready_for_cli_hub": all(item["available"] for item in report.entrypoints),
        "source_downloaded": bool(report.repository["exists"] and report.repository["is_git"]),
        "source_trusted": _source_trusted(report.repository),
        "warnings": report.warnings,
        "blockers": report.blockers,
        "next_commands": _provenance_next_commands(manifest.plugin_id),
    }


def _source_trusted(repository: dict[str, Any]) -> bool | None:
    if not repository["exists"]:
        return None
    return bool(repository["is_git"] and repository.get("remote_matches_expected"))


def _provenance_next_commands(plugin_id: str) -> list[str]:
    return [
        f"python -m cbn plugin preflight {plugin_id}",
        f"python -m cbn plugin install {plugin_id} --yes",
        f"python -m cbn plugin provenance {plugin_id}",
        f"python -m cbn plugin update {plugin_id} --yes",
    ]


def _empty_remote_probe(remote: bool) -> dict[str, Any]:
    return {
        "requested": remote,
        "checked": False,
        "available": None,
        "head": None,
        "exit_code": None,
        "stderr": "",
    }


def _update_repository_blockers(repository: dict[str, Any]) -> list[str]:
    if not repository["exists"]:
        return ["plugin source repository is not downloaded"]
    if not repository["is_git"]:
        return ["plugin repo directory exists but is not a git checkout"]
    if repository.get("remote_matches_expected") is False:
        return ["plugin source repository is not trusted"]
    return []


def _package_update_checks(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "package": package["package"],
            "installed": package["installed"],
            "current_version": package.get("version"),
            "latest_version": None,
            "update_available": None,
            "note": "PyPI latest-version probing is intentionally not performed by default.",
        }
        for package in packages
    ]


def _entrypoint_update_checks(entrypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "entrypoint": entrypoint["entrypoint"],
            "available": entrypoint["available"],
            "path": entrypoint.get("path"),
            "version": entrypoint.get("version"),
        }
        for entrypoint in entrypoints
    ]


def _update_check_next_commands(plugin_id: str) -> list[str]:
    return [
        f"python -m cbn plugin check-update {plugin_id} --remote",
        f"python -m cbn plugin gate {plugin_id} --action update",
        f"python -m cbn plugin update {plugin_id} --yes",
    ]


def _ensure_plugin_action(action: str) -> None:
    if action not in {"install", "update"}:
        raise ValueError(f"unsupported plugin action: {action}")


def _pip_install_commands(manifest: PluginManifest) -> list[PluginCommand]:
    return [
        PluginCommand(
            label=f"Install or upgrade {package}",
            argv=(sys.executable, "-m", "pip", "install", "--upgrade", package),
        )
        for package in manifest.pip_packages
    ]


def _source_command(manifest: PluginManifest, repo_dir: Path, action: str) -> PluginCommand:
    if action == "install":
        return PluginCommand(
            label="Clone plugin source repository",
            argv=("git", "clone", "--depth", "1", manifest.repository, str(repo_dir)),
        )
    return PluginCommand(
        label="Update plugin source repository",
        argv=("git", "-C", str(repo_dir), "pull", "--ff-only"),
    )


def _optional_codex_skill_commands(
    manifest: PluginManifest,
    repo_dir: Path,
    include_codex_skill: bool,
) -> list[PluginCommand]:
    if not (include_codex_skill and manifest.optional_codex_skill_script):
        return []
    script_path = repo_dir / manifest.optional_codex_skill_script
    return [
        PluginCommand(
            label="Install optional Codex skill",
            argv=_codex_skill_argv(script_path),
            optional=True,
        )
    ]


def _codex_skill_argv(script_path: Path) -> tuple[str, ...]:
    if script_path.suffix.lower() != ".ps1":
        return ("bash", str(script_path))
    return (
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
    )


def _plugin_verification_commands(plugin_id: str) -> list[str]:
    commands = [
        f"python -m cbn plugin provenance {plugin_id}",
        f"python -m cbn plugin status {plugin_id}",
        f"python -m cbn plugin check-update {plugin_id}",
    ]
    if plugin_id == "cli-anything":
        commands.extend(
            [
                "python -m cbn plugin market cli-anything list",
                "python -m cbn plugin bootstrap-plan cli-anything --no-workflows",
            ]
        )
    return commands


def _runtime_transport_dependency(kind: str) -> str | None:
    if kind == "pty" and os.name == "nt":
        return "pywinpty>=2.0"
    return None


def _runtime_transport_next_commands(kind: str, status: dict[str, Any]) -> list[str]:
    commands = [
        f"python -m cbn runtime transport {kind}",
        f"python -m cbn runtime transport {kind} --plan",
    ]
    if not status["ready"] and _runtime_transport_dependency(kind):
        commands.append(f"python -m cbn runtime transport {kind} --install --yes")
    return commands
