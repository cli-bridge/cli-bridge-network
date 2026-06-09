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
import tempfile
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
    timeout_seconds: int = 600

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "optional": self.optional,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class PluginPlan:
    plugin_id: str
    action: str
    plugin_dir: str
    commands: tuple[PluginCommand, ...]
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "action": self.action,
            "plugin_dir": self.plugin_dir,
            "commands": [command.as_dict() for command in self.commands],
            "requires_confirmation": True,
            "notes": list(self.notes),
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


def _same_git_remote(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return _normalize_git_remote(left) == _normalize_git_remote(right)


def _normalize_git_remote(value: str) -> str:
    normalized = value.strip().casefold().replace("\\", "/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.rstrip("/")
