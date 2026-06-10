"""External plugin manager.

The model follows the extension pattern used by SD WebUI-style launchers:
the core repository keeps only a small registry, while third-party plugin code
is cloned or installed into an ignored local directory and updated separately.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.pty import pty_backend_status
from cbn.paths import resolve_project_paths
from cbn_plugins.manifest import PluginManifest


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


@dataclass(frozen=True)
class PreflightCheck:
    check_id: str
    ok: bool
    severity: str
    message: str
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "ok": self.ok,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
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

    def operation_catalog(self, plugin_id: str | None = None) -> dict[str, Any]:
        manifests = [self.load_manifest(plugin_id)] if plugin_id else [
            self.load_manifest(path.stem)
            for path in sorted(self.paths.plugin_registry.glob("*.json"))
        ]
        catalogs = [self._operation_catalog_for_manifest(manifest) for manifest in manifests]
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
        operation = next(
            (item for item in catalog["operations"] if item.get("id") == operation_id),
            None,
        )
        if operation is None:
            raise KeyError(f"unknown plugin operation: {plugin_id}/{operation_id}")
        provided_inputs = dict(inputs or {})
        command, command_missing = _resolve_string_template(str(operation.get("command") or ""), provided_inputs)
        payload, payload_missing = _resolve_value_template(operation.get("payload_template", {}), provided_inputs)
        missing_inputs = sorted(set([*command_missing, *payload_missing]))
        blockers = [f"missing input: {name}" for name in missing_inputs]
        validation = catalog["validation"]
        if not validation["ok"]:
            blockers.extend(f"catalog invalid: {error}" for error in validation["errors"])
        side_effecting = operation.get("kind") in {"execute", "write"}
        if side_effecting and not confirmed:
            blockers.append("operation requires confirmed=true before dispatch")
        if side_effecting and confirmed and isinstance(payload, dict):
            payload.setdefault("confirmed", True)
        api = operation.get("api") if isinstance(operation.get("api"), dict) else None
        api_request = _operation_api_request(api, payload)
        return {
            "ok": not blockers,
            "kind": "PluginProviderOperationPlan",
            "plugin_api_version": catalog["plugin_api_version"],
            "plugin_id": plugin_id,
            "provider": catalog["provider"],
            "operation_id": operation_id,
            "operation_kind": operation.get("kind"),
            "confirmed": confirmed,
            "dispatch_ready": not blockers,
            "requires_confirmation": bool(operation.get("requires_confirmation")),
            "side_effects": operation.get("side_effects", []),
            "inputs": provided_inputs,
            "required_inputs": operation.get("required_inputs", []),
            "missing_inputs": missing_inputs,
            "blockers": blockers,
            "operation": operation,
            "resolved_command": command,
            "resolved_payload": payload,
            "api_request": api_request,
            "validation": validation,
            "next_commands": [
                f"python -m cbn plugin operation-plan {plugin_id} {operation_id}",
                command,
            ],
        }

    def provenance(self, plugin_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(plugin_id)
        plugin_dir = self.paths.external_plugins / manifest.plugin_id
        repo_dir = manifest.repo_dir(self.paths.external_plugins)
        repository = self._repo_provenance(repo_dir, expected_remote=manifest.repository)
        packages = [self._pip_package_provenance(package) for package in manifest.pip_packages]
        entrypoints = [self._entrypoint_provenance(entrypoint) for entrypoint in manifest.entrypoints]
        warnings: list[str] = []
        blockers: list[str] = []

        if repository["exists"] and not repository["is_git"]:
            blockers.append("plugin repo directory exists but is not a git checkout")
        if repository.get("remote_url") and not repository.get("remote_matches_expected"):
            blockers.append("plugin repo remote does not match registry source")
        if repository.get("dirty"):
            warnings.append("plugin source checkout has uncommitted changes")
        for package in packages:
            if not package["installed"]:
                warnings.append(f"pip package is not installed: {package['package']}")
        for entrypoint in entrypoints:
            if not entrypoint["available"]:
                warnings.append(f"entrypoint is not available on PATH: {entrypoint['entrypoint']}")

        return {
            "plugin_id": manifest.plugin_id,
            "title": manifest.title,
            "installed": self._is_installed(manifest),
            "plugin_dir": str(plugin_dir),
            "repo_dir": str(repo_dir),
            "expected_repository": manifest.repository,
            "repository": repository,
            "pip_packages": packages,
            "entrypoints": entrypoints,
            "ready_for_entrypoints": all(item["available"] for item in entrypoints),
            "ready_for_cli_hub": all(item["available"] for item in entrypoints),
            "source_downloaded": bool(repository["exists"] and repository["is_git"]),
            "source_trusted": (
                None
                if not repository["exists"]
                else bool(repository["is_git"] and repository.get("remote_matches_expected"))
            ),
            "warnings": warnings,
            "blockers": blockers,
            "next_commands": [
                f"python -m cbn plugin preflight {manifest.plugin_id}",
                f"python -m cbn plugin install {manifest.plugin_id} --yes",
                f"python -m cbn plugin provenance {manifest.plugin_id}",
                f"python -m cbn plugin update {manifest.plugin_id} --yes",
            ],
        }

    def update_check(self, plugin_id: str, remote: bool = False) -> dict[str, Any]:
        manifest = self.load_manifest(plugin_id)
        provenance = self.provenance(plugin_id)
        repository = dict(provenance["repository"])
        remote_probe: dict[str, Any] = {
            "requested": remote,
            "checked": False,
            "available": None,
            "head": None,
            "exit_code": None,
            "stderr": "",
        }
        update_available: bool | None = None
        blockers: list[str] = []
        warnings = list(provenance["warnings"])

        if not repository["exists"]:
            blockers.append("plugin source repository is not downloaded")
        elif not repository["is_git"]:
            blockers.append("plugin repo directory exists but is not a git checkout")
        elif repository.get("remote_matches_expected") is False:
            blockers.append("plugin source repository is not trusted")

        if remote and repository["exists"] and repository["is_git"]:
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

        package_checks = [
            {
                "package": package["package"],
                "installed": package["installed"],
                "current_version": package.get("version"),
                "latest_version": None,
                "update_available": None,
                "note": "PyPI latest-version probing is intentionally not performed by default.",
            }
            for package in provenance["pip_packages"]
        ]
        entrypoint_checks = [
            {
                "entrypoint": entrypoint["entrypoint"],
                "available": entrypoint["available"],
                "path": entrypoint.get("path"),
                "version": entrypoint.get("version"),
            }
            for entrypoint in provenance["entrypoints"]
        ]
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
            "packages": package_checks,
            "entrypoints": entrypoint_checks,
            "blockers": blockers,
            "warnings": warnings,
            "next_commands": [
                f"python -m cbn plugin check-update {manifest.plugin_id} --remote",
                f"python -m cbn plugin gate {manifest.plugin_id} --action update",
                f"python -m cbn plugin update {manifest.plugin_id} --yes",
            ],
        }

    def preflight(self, plugin_id: str) -> dict[str, Any]:
        manifest = self.load_manifest(plugin_id)
        plugin_dir = self.paths.external_plugins / manifest.plugin_id
        repo_dir = manifest.repo_dir(self.paths.external_plugins)
        checks = [
            self._check_python(),
            self._check_pip(),
            self._check_executable("git", required=True),
            self._check_external_plugins_dir(),
            self._check_repo_state(repo_dir),
            self._check_entrypoints(manifest.entrypoints),
        ]
        for package in manifest.pip_packages:
            checks.append(self._check_pip_package(package))
        required_ok = all(check.ok for check in checks if check.severity == "error")
        return {
            "plugin_id": manifest.plugin_id,
            "ready": required_ok,
            "installed": self._is_installed(manifest),
            "plugin_dir": str(plugin_dir),
            "repo_dir": str(repo_dir),
            "checks": [check.as_dict() for check in checks],
            "next_commands": [
                f"python -m cbn plugin plan {manifest.plugin_id}",
                f"python -m cbn plugin install {manifest.plugin_id} --yes",
                f"python -m cbn plugin status {manifest.plugin_id}",
            ],
        }

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
            pip_check = self._check_pip()
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

        verification_commands = [
            f"python -m cbn plugin provenance {manifest.plugin_id}",
            f"python -m cbn plugin status {manifest.plugin_id}",
            f"python -m cbn plugin check-update {manifest.plugin_id}",
        ]
        if manifest.plugin_id == "cli-anything":
            verification_commands.extend(
                [
                    "python -m cbn plugin market cli-anything list",
                    "python -m cbn plugin bootstrap-plan cli-anything --no-workflows",
                ]
            )
        return PluginPlan(
            plugin_id=manifest.plugin_id,
            action=action,
            plugin_dir=str(plugin_dir),
            commands=tuple(commands),
            verification_commands=tuple(verification_commands),
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

    def _operation_catalog_for_manifest(self, manifest: PluginManifest) -> dict[str, Any]:
        operations = _enrich_operations(
            _dedupe_operations(
                [
                    *_generic_plugin_operations(manifest),
                    *[operation.as_dict() for operation in manifest.operations],
                    *_provider_operations(manifest),
                ]
            )
        )
        by_kind: dict[str, int] = {}
        for operation in operations:
            kind = str(operation.get("kind", "unknown"))
            by_kind[kind] = by_kind.get(kind, 0) + 1
        return {
            "ok": True,
            "kind": "PluginProviderOperationCatalog",
            "plugin_api_version": manifest.plugin_api_version,
            "plugin_id": manifest.plugin_id,
            "provider": manifest.provider,
            "title": manifest.title,
            "installed": self._is_installed(manifest),
            "operation_kinds": ["report", "gate", "plan", "execute", "write"],
            "operations": operations,
            "summary": {
                "operation_count": len(operations),
                "by_kind": by_kind,
                "requires_confirmation_count": sum(
                    1 for operation in operations if operation.get("requires_confirmation")
                ),
                "write_or_execute_count": sum(
                    1 for operation in operations if operation.get("kind") in {"execute", "write"}
                ),
            },
            "validation": _validate_operation_catalog(manifest, operations),
            "next_commands": [
                f"python -m cbn plugin operations {manifest.plugin_id}",
                f"python -m cbn plugin validate-operations {manifest.plugin_id}",
                f"python -m cbn plugin gate {manifest.plugin_id} --action install",
                f"python -m cbn plugin plan {manifest.plugin_id}",
            ],
        }

    def _is_installed(self, manifest: PluginManifest) -> bool:
        repo_exists = manifest.repo_dir(self.paths.external_plugins).exists()
        entrypoints_exist = all(shutil.which(entrypoint) for entrypoint in manifest.entrypoints)
        return repo_exists or entrypoints_exist

    def _check_python(self) -> PreflightCheck:
        return PreflightCheck(
            check_id="python.runtime",
            ok=True,
            severity="error",
            message="Python runtime is available.",
            details={"executable": sys.executable, "version": sys.version.split()[0]},
        )

    def _check_pip(self) -> PreflightCheck:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ok = proc.returncode == 0
        return PreflightCheck(
            check_id="python.pip",
            ok=ok,
            severity="error",
            message="pip is available." if ok else "pip is not available through the current Python.",
            details={
                "argv": [sys.executable, "-m", "pip", "--version"],
                "exit_code": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            },
        )

    def _check_executable(self, executable: str, required: bool) -> PreflightCheck:
        path = shutil.which(executable)
        return PreflightCheck(
            check_id=f"executable.{executable}",
            ok=path is not None,
            severity="error" if required else "warning",
            message=f"{executable} is available." if path else f"{executable} is not on PATH.",
            details={"path": path},
        )

    def _check_external_plugins_dir(self) -> PreflightCheck:
        try:
            self.paths.external_plugins.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.paths.external_plugins,
                mode="w",
                encoding="utf-8",
                delete=True,
            ) as f:
                f.write("cbn preflight\n")
            return PreflightCheck(
                check_id="external_plugins.writable",
                ok=True,
                severity="error",
                message="external_plugins is writable.",
                details={"path": str(self.paths.external_plugins)},
            )
        except OSError as exc:
            return PreflightCheck(
                check_id="external_plugins.writable",
                ok=False,
                severity="error",
                message="external_plugins is not writable.",
                details={"path": str(self.paths.external_plugins), "error": str(exc)},
            )

    def _check_repo_state(self, repo_dir: Path) -> PreflightCheck:
        if not repo_dir.exists():
            return PreflightCheck(
                check_id="plugin.repo",
                ok=True,
                severity="warning",
                message="Plugin source repository is not cloned yet.",
                details={"repo_dir": str(repo_dir), "exists": False},
            )
        ok = (repo_dir / ".git").exists()
        return PreflightCheck(
            check_id="plugin.repo",
            ok=ok,
            severity="warning",
            message="Plugin source repository exists." if ok else "Plugin repo dir exists but is not a git checkout.",
            details={"repo_dir": str(repo_dir), "exists": True, "is_git": ok},
        )

    def _check_entrypoints(self, entrypoints: tuple[str, ...]) -> PreflightCheck:
        found = {entrypoint: shutil.which(entrypoint) for entrypoint in entrypoints}
        ok = all(path is not None for path in found.values())
        return PreflightCheck(
            check_id="plugin.entrypoints",
            ok=ok,
            severity="warning",
            message="Plugin entrypoints are available." if ok else "Plugin entrypoints are not all on PATH.",
            details={"entrypoints": found},
        )

    def _check_pip_package(self, package: str) -> PreflightCheck:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "show", package],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ok = proc.returncode == 0
        return PreflightCheck(
            check_id=f"pip_package.{package}",
            ok=ok,
            severity="warning",
            message=f"{package} is installed." if ok else f"{package} is not installed.",
            details={
                "package": package,
                "exit_code": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            },
        )

    def _repo_provenance(self, repo_dir: Path, expected_remote: str) -> dict[str, Any]:
        if not repo_dir.exists():
            return {
                "exists": False,
                "is_git": False,
                "expected_remote": expected_remote,
                "remote_url": None,
                "remote_matches_expected": None,
                "branch": None,
                "head": None,
                "dirty": None,
                "status_short": None,
                "errors": [],
            }
        is_git = (repo_dir / ".git").exists()
        if not is_git:
            return {
                "exists": True,
                "is_git": False,
                "expected_remote": expected_remote,
                "remote_url": None,
                "remote_matches_expected": None,
                "branch": None,
                "head": None,
                "dirty": None,
                "status_short": None,
                "errors": [],
            }

        errors: list[str] = []
        remote = self._git_value(repo_dir, ("config", "--get", "remote.origin.url"), errors)
        branch = self._git_value(repo_dir, ("rev-parse", "--abbrev-ref", "HEAD"), errors)
        head = self._git_value(repo_dir, ("rev-parse", "HEAD"), errors)
        status_short = self._git_value(repo_dir, ("status", "--short"), errors, allow_empty=True)
        return {
            "exists": True,
            "is_git": True,
            "expected_remote": expected_remote,
            "remote_url": remote,
            "remote_matches_expected": _same_git_remote(remote, expected_remote) if remote else False,
            "branch": branch,
            "head": head,
            "dirty": bool(status_short),
            "status_short": status_short,
            "errors": errors,
        }

    def _git_value(
        self,
        repo_dir: Path,
        args: tuple[str, ...],
        errors: list[str],
        allow_empty: bool = False,
    ) -> str | None:
        proc = _run_command(("git", "-C", str(repo_dir), *args), timeout_seconds=10)
        if proc["exit_code"] != 0:
            errors.append(f"git {' '.join(args)} failed: {proc['stderr'] or proc['stdout']}")
            return "" if allow_empty else None
        value = proc["stdout"].strip()
        if value or allow_empty:
            return value
        return None

    def _pip_package_provenance(self, package: str) -> dict[str, Any]:
        proc = _run_command((sys.executable, "-m", "pip", "show", package), timeout_seconds=30)
        fields = _parse_key_value_lines(proc["stdout"]) if proc["exit_code"] == 0 else {}
        return {
            "package": package,
            "installed": proc["exit_code"] == 0,
            "version": fields.get("version"),
            "location": fields.get("location"),
            "summary": fields.get("summary"),
            "metadata": fields,
            "exit_code": proc["exit_code"],
            "stderr": proc["stderr"],
        }

    def _entrypoint_provenance(self, entrypoint: str) -> dict[str, Any]:
        path = shutil.which(entrypoint)
        version = None
        version_exit_code = None
        version_stderr = None
        if path:
            proc = _run_command((path, "--version"), timeout_seconds=10)
            version_exit_code = proc["exit_code"]
            version_stderr = proc["stderr"]
            version = (proc["stdout"] or proc["stderr"]).strip() or None
        return {
            "entrypoint": entrypoint,
            "available": path is not None,
            "path": path,
            "version": version,
            "version_exit_code": version_exit_code,
            "version_stderr": version_stderr,
        }


def _run_command(argv: tuple[str, ...], timeout_seconds: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            list(argv),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _decode_timeout_value(exc.stdout)
        stderr = _decode_timeout_value(exc.stderr)
        return {
            "exit_code": 124,
            "stdout": stdout[-4000:],
            "stderr": (stderr + f"\ncommand timed out after {timeout_seconds} seconds").strip(),
        }
    except OSError as exc:
        return {
            "exit_code": 127,
            "stdout": "",
            "stderr": f"{argv[0]} failed to start: {exc}",
        }
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def verification_report_for_plan(
    plan: PluginPlan,
    report_kind: str,
    run: bool = False,
    timeout_seconds: int = 60,
    next_commands: tuple[str, ...] = (),
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks = [
        _verification_check(command, run=run, timeout_seconds=timeout_seconds)
        for command in plan.verification_commands
    ]
    unsafe_count = sum(1 for check in checks if not check["safe_to_run"])
    executed_count = sum(1 for check in checks if check["status"] == "completed")
    failed_count = sum(1 for check in checks if check["status"] == "failed")
    blocked_count = sum(1 for check in checks if check["status"] == "blocked")
    report = {
        "ok": unsafe_count == 0 and failed_count == 0 and blocked_count == 0,
        "kind": report_kind,
        "plugin_api_version": "cbn.plugin.v1",
        "plugin_id": plan.plugin_id,
        "action": plan.action,
        "run": run,
        "timeout_seconds": timeout_seconds,
        "ready_to_run": unsafe_count == 0,
        "plan": plan.as_dict(),
        "summary": {
            "check_count": len(checks),
            "safe_count": len(checks) - unsafe_count,
            "unsafe_count": unsafe_count,
            "executed_count": executed_count,
            "failed_count": failed_count,
            "blocked_count": blocked_count,
        },
        "checks": checks,
        "next_commands": list(next_commands),
    }
    if extra:
        report.update(extra)
    return report


def _verification_check(command: str, run: bool, timeout_seconds: int) -> dict[str, Any]:
    parsed = _parse_verification_command(command)
    safe = parsed["safe"]
    check: dict[str, Any] = {
        "command": command,
        "argv": list(parsed["argv"]),
        "safe_to_run": safe,
        "reason": parsed["reason"],
        "status": "planned",
    }
    if not safe:
        check["status"] = "blocked"
        return check
    if not run:
        return check
    result = _run_command(tuple(parsed["argv"]), timeout_seconds=timeout_seconds)
    check.update(
        {
            "status": "completed" if result["exit_code"] == 0 else "failed",
            "exit_code": result["exit_code"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }
    )
    return check


def _parse_verification_command(command: str) -> dict[str, Any]:
    try:
        argv = shlex.split(command, posix=os.name != "nt")
    except ValueError as exc:
        return {"argv": (), "safe": False, "reason": f"command parse failed: {exc}"}
    if not argv:
        return {"argv": (), "safe": False, "reason": "empty command"}
    normalized = _normalize_cbn_python_argv(tuple(argv))
    if normalized is None:
        return {
            "argv": tuple(argv),
            "safe": False,
            "reason": "verification command must use python -m cbn",
        }
    safe, reason = _is_read_only_cbn_verification(tuple(normalized))
    return {"argv": tuple(normalized), "safe": safe, "reason": reason}


def _normalize_cbn_python_argv(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    executable = Path(argv[0]).name.casefold()
    if executable not in {"python", "python.exe", "py", "py.exe"} and Path(sys.executable).name.casefold() != executable:
        return None
    if len(argv) < 3 or argv[1:3] != ("-m", "cbn"):
        return None
    return (sys.executable, *argv[1:])


def _is_read_only_cbn_verification(argv: tuple[str, ...]) -> tuple[bool, str]:
    if any(flag in argv for flag in ("--yes", "--write", "--install", "--run", "--remote")):
        return False, "verification command contains a side-effecting or network flag"
    if len(argv) < 4:
        return False, "verification command is missing a cbn subcommand"
    command = argv[3]
    tail = argv[4:]
    if command == "plugin":
        return _is_read_only_plugin_verification(tail)
    if command == "runtime" and len(tail) >= 2 and tail[0] == "transport":
        return True, "runtime transport status is read-only"
    if command == "protocol" and tail and tail[0] in {"smoke-suite", "readiness", "wire-conformance"}:
        return True, "protocol verification is read-only"
    if command == "call" and "--dry-run" in tail:
        return True, "capability dry-run is read-only"
    return False, f"unsupported verification subcommand: {command}"


def _is_read_only_plugin_verification(tail: tuple[str, ...]) -> tuple[bool, str]:
    if not tail:
        return False, "plugin verification command is missing an operation"
    operation = tail[0]
    if operation in {"provenance", "status", "check-update", "bootstrap-plan", "verify-harness"}:
        return True, f"plugin {operation} is read-only"
    if operation == "market":
        return True, "plugin market inspection is read-only"
    if operation == "harness" and len(tail) >= 3 and tail[2] == "status":
        return True, "plugin harness status is read-only"
    return False, f"unsupported plugin verification operation: {operation}"


def _decode_timeout_value(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _parse_key_value_lines(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().casefold().replace("-", "_")
        if key:
            fields[key] = value.strip()
    return fields


def _parse_ls_remote_head(text: str) -> str | None:
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "HEAD":
            return parts[0]
    return None


def _same_git_remote(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return _normalize_git_remote(left) == _normalize_git_remote(right)


def _normalize_git_remote(value: str) -> str:
    normalized = value.strip().casefold().replace("\\", "/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.rstrip("/")


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


def _generic_plugin_operations(manifest: PluginManifest) -> list[dict[str, Any]]:
    plugin_id = manifest.plugin_id
    return [
        _operation("info", "Plugin Metadata", "report", f"python -m cbn plugin info {plugin_id}"),
        _operation(
            "preflight",
            "Install Preflight",
            "report",
            f"python -m cbn plugin preflight {plugin_id}",
            api={"method": "GET", "path": f"/plugins/{plugin_id}/preflight"} if plugin_id == "cli-anything" else None,
        ),
        _operation(
            "provenance",
            "Source Provenance",
            "report",
            f"python -m cbn plugin provenance {plugin_id}",
            api={"method": "GET", "path": f"/plugins/{plugin_id}/provenance"} if plugin_id == "cli-anything" else None,
        ),
        _operation(
            "check-update",
            "Check Updates",
            "report",
            f"python -m cbn plugin check-update {plugin_id}",
            api={"method": "POST", "path": "/plugins/check-update"},
            payload_template={"plugin_id": plugin_id, "remote": False},
            input_schema={"remote": "boolean"},
        ),
        _operation(
            "install-gate",
            "Install Gate",
            "gate",
            f"python -m cbn plugin gate {plugin_id} --action install",
            api={"method": "POST", "path": "/plugins/gate"},
            payload_template={"plugin_id": plugin_id, "action": "install"},
        ),
        _operation(
            "update-gate",
            "Update Gate",
            "gate",
            f"python -m cbn plugin gate {plugin_id} --action update",
            api={"method": "POST", "path": "/plugins/gate"},
            payload_template={"plugin_id": plugin_id, "action": "update"},
        ),
        _operation(
            "install-plan",
            "Install Plan",
            "plan",
            f"python -m cbn plugin plan {plugin_id}",
            api={"method": "POST", "path": "/plugins/plan"},
            payload_template={"plugin_id": plugin_id, "action": "install"},
        ),
        _operation(
            "update-plan",
            "Update Plan",
            "plan",
            f"python -m cbn plugin plan {plugin_id} --action update",
            api={"method": "POST", "path": "/plugins/plan"},
            payload_template={"plugin_id": plugin_id, "action": "update"},
        ),
        _operation(
            "verify-plan",
            "Post-Operation Verification",
            "report",
            f"python -m cbn plugin verify-plan {plugin_id}",
            api={"method": "POST", "path": "/plugins/verify-plan"},
            payload_template={"plugin_id": plugin_id, "action": "install", "run": False},
            input_schema={"action": "string", "run": "boolean"},
        ),
        _operation(
            "install-execute",
            "Install",
            "execute",
            f"python -m cbn plugin install {plugin_id} --yes",
            api={"method": "POST", "path": "/plugins/execute"},
            requires_confirmation=True,
            side_effects=("subprocess", "external_plugins", "pip", "git"),
            payload_template={"plugin_id": plugin_id, "action": "install", "confirmed": True},
        ),
        _operation(
            "update-execute",
            "Update",
            "execute",
            f"python -m cbn plugin update {plugin_id} --yes",
            api={"method": "POST", "path": "/plugins/execute"},
            requires_confirmation=True,
            side_effects=("subprocess", "external_plugins", "pip", "git"),
            payload_template={"plugin_id": plugin_id, "action": "update", "confirmed": True},
        ),
    ]


def _provider_operations(manifest: PluginManifest) -> list[dict[str, Any]]:
    if manifest.provider != "cli-anything" and manifest.plugin_id != "cli-anything":
        return []
    plugin_id = manifest.plugin_id
    return [
        _operation(
            "status",
            "CLI-Hub Status",
            "report",
            f"python -m cbn plugin status {plugin_id}",
            api={"method": "GET", "path": f"/plugins/{plugin_id}/status"},
        ),
        _operation(
            "market-list",
            "Market List",
            "report",
            f"python -m cbn plugin market {plugin_id} list",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/market"},
            payload_template={"command": "list"},
        ),
        _operation(
            "candidates",
            "Rank Candidates",
            "report",
            f"python -m cbn plugin candidates {plugin_id} --query file --limit 20 --compact",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/candidates"},
            payload_template={"query": "file", "limit": 20, "compact": True},
            input_schema={"query": "string", "limit": "integer", "compact": "boolean"},
        ),
        _operation(
            "install-queue",
            "Install Queue",
            "gate",
            f"python -m cbn plugin install-queue {plugin_id} --query file --limit 20 --max-installs 5",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/install-queue"},
            payload_template={"query": "file", "limit": 20, "max_installs": 5, "include_blocked": True},
        ),
        _operation(
            "blocked-plan",
            "Blocked Plan",
            "gate",
            f"python -m cbn plugin blocked-plan {plugin_id} --query file --limit 20",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/blocked-plan"},
            payload_template={"query": "file", "limit": 20},
        ),
        _operation(
            "repair-plan",
            "Repair Plan",
            "report",
            f"python -m cbn plugin repair-plan {plugin_id} <harness>",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/repair-plan"},
            payload_template={"harness_name": "<harness>", "from_market": True},
        ),
        _operation(
            "adapter-targets",
            "Adapter Targets",
            "report",
            f"python -m cbn plugin adapter-targets {plugin_id} <harness> --from-market",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/adapter-targets"},
            payload_template={"harness_name": "<harness>", "from_market": True, "limit": 20},
        ),
        _operation(
            "adapter-smoke",
            "Adapter Smoke",
            "execute",
            f"python -m cbn plugin adapter-smoke {plugin_id} <harness> --module <module> --run --yes",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/adapter-smoke"},
            requires_confirmation=True,
            side_effects=("subprocess", "runtime/artifacts"),
            payload_template={
                "harness_name": "<harness>",
                "module": "<module>",
                "run": True,
                "confirmed": True,
                "smoke_args": ["--help"],
            },
        ),
        _operation(
            "repair-entrypoint",
            "Repair Entrypoint",
            "write",
            f"python -m cbn plugin repair-entrypoint {plugin_id} <harness> --module <module> --write --yes",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/repair-entrypoint"},
            requires_confirmation=True,
            side_effects=("external_plugins/entrypoints", "runtime/manifests", "audit", "events"),
            payload_template={
                "harness_name": "<harness>",
                "module": "<module>",
                "write": True,
                "confirmed": True,
                "smoke_args": ["--help"],
            },
        ),
        _operation(
            "adaptation-gate",
            "Adaptation Gate",
            "gate",
            f"python -m cbn plugin adaptation-gate {plugin_id} <harness> --from-market",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/adaptation-gate"},
            payload_template={"harness_name": "<harness>", "from_market": True, "require_smoke": True},
        ),
        _operation(
            "adaptation-queue",
            "Adaptation Queue",
            "gate",
            f"python -m cbn plugin adaptation-queue {plugin_id} --query file --max-harnesses 5",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/adaptation-queue"},
            payload_template={"query": "file", "limit": 20, "max_harnesses": 5, "include_blocked": True},
        ),
        _operation(
            "promotion-gate",
            "Promotion Gate",
            "gate",
            f"python -m cbn plugin promotion-gate {plugin_id} <harness> --from-market",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/promotion-gate"},
            payload_template={"harness_name": "<harness>", "from_market": True},
        ),
        _operation(
            "live-verification",
            "Live Verification",
            "report",
            f"python -m cbn plugin live-verification {plugin_id}",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/live-verification"},
            payload_template={"harnesses": ["mermaid", "macrocli"], "candidate_query": "file"},
        ),
        _operation(
            "mvp-plan",
            "MVP Plan",
            "report",
            f"python -m cbn plugin mvp-plan {plugin_id} --query file --limit 20 --max-harnesses 5",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/mvp-plan"},
            payload_template={"query": "file", "limit": 20, "max_harnesses": 5, "include_blocked": True},
        ),
        _operation(
            "bootstrap-plan",
            "Bootstrap Plan",
            "plan",
            f"python -m cbn plugin bootstrap-plan {plugin_id} --harness mermaid --query file",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/bootstrap-plan"},
            payload_template={"harness_name": "mermaid", "query": "file", "include_workflows": True},
        ),
        _operation(
            "harness-verify-plan",
            "Harness Post-Operation Verification",
            "report",
            f"python -m cbn plugin verify-harness-plan {plugin_id} install <harness>",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/verify-harness-plan"},
            payload_template={"action": "install", "harness_name": "<harness>", "run": False},
            input_schema={"harness": "string", "action": "string", "run": "boolean"},
        ),
        _operation(
            "harness-install",
            "Harness Install",
            "execute",
            f"python -m cbn plugin harness {plugin_id} install <harness> --yes",
            api={"method": "POST", "path": f"/plugins/{plugin_id}/harness"},
            requires_confirmation=True,
            side_effects=("subprocess", "pip", "cli-hub"),
            payload_template={"action": "install", "harness_name": "<harness>", "confirmed": True},
        ),
    ]


def _operation(
    operation_id: str,
    title: str,
    kind: str,
    command: str,
    api: dict[str, str] | None = None,
    requires_confirmation: bool = False,
    side_effects: tuple[str, ...] = (),
    input_schema: dict[str, Any] | None = None,
    payload_template: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _enrich_operation_descriptor({
        "id": operation_id,
        "title": title,
        "kind": kind,
        "command": command,
        "api": api,
        "requires_confirmation": requires_confirmation,
        "side_effects": list(side_effects),
        "input_schema": input_schema or {},
        "payload_template": payload_template or {},
    })


def _dedupe_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for operation in operations:
        operation_id = str(operation.get("id", ""))
        if not operation_id or operation_id in seen:
            continue
        selected.append(operation)
        seen.add(operation_id)
    return selected


def _enrich_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_enrich_operation_descriptor(operation) for operation in operations]


def _enrich_operation_descriptor(operation: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(operation)
    command = enriched.get("command", "")
    payload = enriched.get("payload_template", {})
    required_inputs = sorted(_required_inputs_for_templates(command, payload))
    input_schema = enriched.get("input_schema", {})
    if input_schema is None:
        input_schema = {}
    if isinstance(input_schema, dict):
        input_schema = dict(input_schema)
        for name in required_inputs:
            input_schema.setdefault(name, "string")
    enriched["required_inputs"] = required_inputs
    enriched["input_schema"] = input_schema
    enriched["input_count"] = len(required_inputs)
    enriched["has_required_inputs"] = bool(required_inputs)
    return enriched


def _required_inputs_for_templates(command: Any, payload: Any) -> set[str]:
    inputs: set[str] = set()
    if isinstance(command, str):
        inputs.update(_PLACEHOLDER_RE.findall(command))
    _collect_placeholders(payload, inputs)
    return inputs


def _collect_placeholders(value: Any, inputs: set[str]) -> None:
    if isinstance(value, str):
        inputs.update(_PLACEHOLDER_RE.findall(value))
    elif isinstance(value, list):
        for item in value:
            _collect_placeholders(item, inputs)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_placeholders(item, inputs)


_OPERATION_KINDS = {"report", "gate", "plan", "execute", "write"}


def _validate_operation_catalog(manifest: PluginManifest, operations: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if manifest.plugin_api_version != "cbn.plugin.v1":
        errors.append(f"unsupported plugin_api_version: {manifest.plugin_api_version}")
    if not manifest.provider:
        errors.append("provider is required")
    seen: set[str] = set()
    for index, operation in enumerate(operations):
        prefix = f"operations[{index}]"
        operation_id = operation.get("id")
        if not isinstance(operation_id, str) or not operation_id:
            errors.append(f"{prefix}.id is required")
            operation_id = f"<missing:{index}>"
        elif operation_id in seen:
            errors.append(f"duplicate operation id: {operation_id}")
        seen.add(str(operation_id))
        kind = operation.get("kind")
        if kind not in _OPERATION_KINDS:
            errors.append(f"{prefix}.kind is invalid: {kind}")
        required_inputs = operation.get("required_inputs", [])
        input_schema = operation.get("input_schema", {})
        if not isinstance(required_inputs, list) or not all(isinstance(item, str) for item in required_inputs):
            errors.append(f"{prefix}.required_inputs must be a list of strings")
            required_inputs = []
        if not isinstance(input_schema, dict):
            errors.append(f"{prefix}.input_schema must be an object")
            input_schema = {}
        for name in required_inputs:
            if name not in input_schema:
                errors.append(f"{prefix}.input_schema is missing required input: {name}")
        command = operation.get("command")
        api = operation.get("api")
        if not isinstance(command, str) or not command:
            errors.append(f"{prefix}.command is required")
        if api is not None:
            _validate_operation_api(prefix, api, kind, errors)
        elif kind in {"execute", "write"}:
            warnings.append(f"{prefix}.api is missing for side-effecting operation {operation_id}")
        side_effects = operation.get("side_effects", [])
        if kind in {"execute", "write"}:
            if operation.get("requires_confirmation") is not True:
                errors.append(f"{prefix}.requires_confirmation must be true for {kind}")
            if not isinstance(side_effects, list) or not side_effects:
                errors.append(f"{prefix}.side_effects must be non-empty for {kind}")
            payload = operation.get("payload_template", {})
            if isinstance(payload, dict) and payload.get("confirmed") is False:
                errors.append(f"{prefix}.payload_template.confirmed cannot be false for {kind}")
        elif operation.get("requires_confirmation"):
            warnings.append(f"{prefix}.requires_confirmation is true for non-side-effect kind {kind}")
        if not isinstance(operation.get("payload_template", {}), dict):
            errors.append(f"{prefix}.payload_template must be an object")
    return {
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def _validate_operation_api(prefix: str, api: Any, kind: Any, errors: list[str]) -> None:
    if not isinstance(api, dict):
        errors.append(f"{prefix}.api must be an object when present")
        return
    method = api.get("method")
    path = api.get("path")
    if method not in {"GET", "POST"}:
        errors.append(f"{prefix}.api.method must be GET or POST")
    if not isinstance(path, str) or not path.startswith("/"):
        errors.append(f"{prefix}.api.path must start with /")
    if kind in {"execute", "write"} and method != "POST":
        errors.append(f"{prefix}.api.method must be POST for {kind}")


def _catalog_list_validation(catalogs: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    for catalog in catalogs:
        validation = catalog.get("validation", {})
        errors.extend(f"{catalog.get('plugin_id')}: {error}" for error in validation.get("errors", []))
        warnings.extend(f"{catalog.get('plugin_id')}: {warning}" for warning in validation.get("warnings", []))
    return {
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


_PLACEHOLDER_RE = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>")


def _resolve_string_template(template: str, inputs: dict[str, Any]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in inputs:
            missing.append(key)
            return match.group(0)
        return str(inputs[key])

    return _PLACEHOLDER_RE.sub(replace, template), missing


def _resolve_value_template(value: Any, inputs: dict[str, Any]) -> tuple[Any, list[str]]:
    if isinstance(value, str):
        exact = _PLACEHOLDER_RE.fullmatch(value)
        if exact:
            key = exact.group(1)
            if key not in inputs:
                return value, [key]
            return inputs[key], []
        return _resolve_string_template(value, inputs)
    if isinstance(value, list):
        resolved_items = []
        missing: list[str] = []
        for item in value:
            resolved, item_missing = _resolve_value_template(item, inputs)
            resolved_items.append(resolved)
            missing.extend(item_missing)
        return resolved_items, missing
    if isinstance(value, dict):
        resolved_dict: dict[str, Any] = {}
        missing: list[str] = []
        for key, item in value.items():
            resolved, item_missing = _resolve_value_template(item, inputs)
            resolved_dict[key] = resolved
            missing.extend(item_missing)
        return resolved_dict, missing
    return value, []


def _operation_api_request(api: dict[str, Any] | None, payload: Any) -> dict[str, Any] | None:
    if not api:
        return None
    method = api.get("method")
    path = api.get("path")
    request = {
        "method": method,
        "path": path,
    }
    if method == "POST":
        request["json"] = payload if isinstance(payload, dict) else {}
    else:
        request["query"] = payload if isinstance(payload, dict) else {}
    return request
