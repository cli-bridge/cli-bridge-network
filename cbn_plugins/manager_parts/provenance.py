"""Plugin provenance helpers."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from cbn_plugins.manager_parts.verification import run_command


def repo_provenance(repo_dir: Path, expected_remote: str) -> dict[str, Any]:
    if not repo_dir.exists():
        return _repo_state(
            exists=False,
            is_git=False,
            expected_remote=expected_remote,
        )
    if not (repo_dir / ".git").exists():
        return _repo_state(
            exists=True,
            is_git=False,
            expected_remote=expected_remote,
        )

    errors: list[str] = []
    remote = _git_value(repo_dir, ("config", "--get", "remote.origin.url"), errors)
    branch = _git_value(repo_dir, ("rev-parse", "--abbrev-ref", "HEAD"), errors)
    head = _git_value(repo_dir, ("rev-parse", "HEAD"), errors)
    status_short = _git_value(repo_dir, ("status", "--short"), errors, allow_empty=True)
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


def pip_package_provenance(package: str) -> dict[str, Any]:
    proc = run_command((sys.executable, "-m", "pip", "show", package), timeout_seconds=30)
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


def entrypoint_provenance(entrypoint: str) -> dict[str, Any]:
    path = shutil.which(entrypoint)
    version = None
    version_exit_code = None
    version_stderr = None
    if path:
        proc = run_command((path, "--version"), timeout_seconds=10)
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


def parse_ls_remote_head(text: str) -> str | None:
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "HEAD":
            return parts[0]
    return None


def _repo_state(
    exists: bool,
    is_git: bool,
    expected_remote: str,
) -> dict[str, Any]:
    return {
        "exists": exists,
        "is_git": is_git,
        "expected_remote": expected_remote,
        "remote_url": None,
        "remote_matches_expected": None,
        "branch": None,
        "head": None,
        "dirty": None,
        "status_short": None,
        "errors": [],
    }


def _git_value(
    repo_dir: Path,
    args: tuple[str, ...],
    errors: list[str],
    allow_empty: bool = False,
) -> str | None:
    proc = run_command(("git", "-C", str(repo_dir), *args), timeout_seconds=10)
    if proc["exit_code"] != 0:
        errors.append(f"git {' '.join(args)} failed: {proc['stderr'] or proc['stdout']}")
        return "" if allow_empty else None
    value = proc["stdout"].strip()
    if value or allow_empty:
        return value
    return None


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
