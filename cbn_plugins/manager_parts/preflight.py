"""Plugin preflight helpers."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbn_plugins.manifest import PluginManifest


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


def preflight_report(
    manifest: PluginManifest,
    plugin_dir: Path,
    repo_dir: Path,
    external_plugins_dir: Path,
    installed: bool,
) -> dict[str, Any]:
    checks = [
        check_python(),
        check_pip(),
        check_executable("git", required=True),
        check_external_plugins_dir(external_plugins_dir),
        check_repo_state(repo_dir),
        check_entrypoints(manifest.entrypoints),
    ]
    for package in manifest.pip_packages:
        checks.append(check_pip_package(package))
    required_ok = all(check.ok for check in checks if check.severity == "error")
    return {
        "plugin_id": manifest.plugin_id,
        "ready": required_ok,
        "installed": installed,
        "plugin_dir": str(plugin_dir),
        "repo_dir": str(repo_dir),
        "checks": [check.as_dict() for check in checks],
        "next_commands": [
            f"python -m cbn plugin plan {manifest.plugin_id}",
            f"python -m cbn plugin install {manifest.plugin_id} --yes",
            f"python -m cbn plugin status {manifest.plugin_id}",
        ],
    }


def check_python() -> PreflightCheck:
    return PreflightCheck(
        check_id="python.runtime",
        ok=True,
        severity="error",
        message="Python runtime is available.",
        details={"executable": sys.executable, "version": sys.version.split()[0]},
    )


def check_pip() -> PreflightCheck:
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


def check_executable(executable: str, required: bool) -> PreflightCheck:
    path = shutil.which(executable)
    return PreflightCheck(
        check_id=f"executable.{executable}",
        ok=path is not None,
        severity="error" if required else "warning",
        message=f"{executable} is available." if path else f"{executable} is not on PATH.",
        details={"path": path},
    )


def check_external_plugins_dir(external_plugins_dir: Path) -> PreflightCheck:
    try:
        external_plugins_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=external_plugins_dir,
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
            details={"path": str(external_plugins_dir)},
        )
    except OSError as exc:
        return PreflightCheck(
            check_id="external_plugins.writable",
            ok=False,
            severity="error",
            message="external_plugins is not writable.",
            details={"path": str(external_plugins_dir), "error": str(exc)},
        )


def check_repo_state(repo_dir: Path) -> PreflightCheck:
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


def check_entrypoints(entrypoints: tuple[str, ...]) -> PreflightCheck:
    found = {entrypoint: shutil.which(entrypoint) for entrypoint in entrypoints}
    ok = all(path is not None for path in found.values())
    return PreflightCheck(
        check_id="plugin.entrypoints",
        ok=ok,
        severity="warning",
        message="Plugin entrypoints are available." if ok else "Plugin entrypoints are not all on PATH.",
        details={"entrypoints": found},
    )


def check_pip_package(package: str) -> PreflightCheck:
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
