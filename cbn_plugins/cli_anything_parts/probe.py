"""Dependency and readiness probes for CLI-Anything harnesses."""

from __future__ import annotations

import os
import re
import shutil
import socket
import sys
from typing import Any


EMPTY_REQUIREMENTS = {"none", "nothing", "null", "n/a"}
BLOCKING_REQUIREMENT_MARKERS = (
    "api key",
    "apikey",
    "token",
    "secret",
    "credential",
    "account",
    "auth",
    "desktop app",
    "running",
    "server",
    "instance",
    "localhost",
    "127.0.0.1",
    "licensed",
    "license",
    "installation",
    "apt ",
    "brew ",
    "choco ",
    "winget ",
    "set ",
    "env ",
    "environment variable",
    "extension",
    "login",
    "backend",
)


def declared_requires(market_record: dict[str, Any] | None, status: dict[str, Any]) -> str | None:
    if market_record and market_record.get("requires") not in {None, ""}:
        return str(market_record["requires"])
    fields = status.get("cli_hub_info", {}).get("fields", {})
    if isinstance(fields, dict) and fields.get("requires") not in {None, ""}:
        return str(fields["requires"])
    return None


def requirement_assessment(requires: str | None) -> dict[str, Any]:
    if empty_requirement(requires):
        return empty_requirement_assessment(requires)
    signals = blocking_requirement_signals(requires)
    managed_signals = managed_requirement_signals(requires)
    if not signals and managed_signals:
        return managed_requirement_assessment(requires, managed_signals)
    if not signals:
        signals = ["declared requirement"]
    return manual_requirement_assessment(requires, signals)


def empty_requirement(requires: str | None) -> bool:
    return not requires or requires.strip().casefold() in EMPTY_REQUIREMENTS


def empty_requirement_assessment(requires: str | None) -> dict[str, Any]:
    return {
        "declared": requires,
        "external_dependency_free": True,
        "dependency_class": "none",
        "managed_dependency_only": False,
        "manual_dependency_required": False,
        "signals": [],
    }


def blocking_requirement_signals(requires: str) -> list[str]:
    text = requires.casefold()
    return [
        *[marker.strip() for marker in BLOCKING_REQUIREMENT_MARKERS if marker in text],
        *external_app_requirement_signals(requires),
    ]


def managed_requirement_assessment(
    requires: str,
    managed_signals: list[str],
) -> dict[str, Any]:
    return {
        "declared": requires,
        "external_dependency_free": True,
        "dependency_class": "managed-package",
        "managed_dependency_only": True,
        "manual_dependency_required": False,
        "signals": managed_signals,
    }


def manual_requirement_assessment(requires: str, signals: list[str]) -> dict[str, Any]:
    return {
        "declared": requires,
        "external_dependency_free": False,
        "dependency_class": "manual-or-external",
        "managed_dependency_only": False,
        "manual_dependency_required": True,
        "signals": signals,
    }


def managed_requirement_signals(requires: str) -> list[str]:
    text = requires.casefold().strip()
    if not text:
        return []
    signals = managed_runtime_signals(text)
    tokens = managed_requirement_tokens(text)
    package_tokens = managed_package_tokens(tokens)
    leftovers = unmanaged_requirement_tokens(tokens, package_tokens)
    if package_tokens:
        signals.append("managed-packages")
    if signals and not leftovers:
        return sorted(set(signals))
    return []


def managed_runtime_signals(text: str) -> list[str]:
    signals: list[str] = []
    if re.search(r"\bpython\s*[0-9><=~.+-]*", text):
        signals.append("python-runtime")
    if re.search(r"\b(node|npm|npx|pnpm|yarn)\b", text):
        signals.append("node-runtime")
    if re.search(r"\b(pip|uv|poetry|pdm)\b", text):
        signals.append("python-package-manager")
    return signals


def managed_requirement_tokens(text: str) -> list[str]:
    cleaned = re.sub(r"\bpython\s*[0-9><=~.+-]*", "", text)
    cleaned = re.sub(r"\b(node|npm|npx|pnpm|yarn|pip|uv|poetry|pdm)\b", "", cleaned)
    cleaned = re.sub(r"\b(version|package|packages|dependency|dependencies|requires|required)\b", "", cleaned)
    cleaned = re.sub(r"[><=~!^]+", "", cleaned)
    return [token.strip() for token in re.split(r"[,;\s]+", cleaned) if token.strip()]


def managed_package_tokens(tokens: list[str]) -> list[str]:
    return [
        token
        for token in tokens
        if re.match(r"^@?[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)?$", token)
        and not re.fullmatch(r"\d+(\.\d+)*\+?", token)
    ]


def unmanaged_requirement_tokens(tokens: list[str], package_tokens: list[str]) -> list[str]:
    return [
        token
        for token in tokens
        if token not in package_tokens and not re.fullmatch(r"\d+(\.\d+)*\+?", token)
    ]


def external_app_requirement_signals(requires: str) -> list[str]:
    text = requires.casefold()
    app_markers = (
        "blender",
        "libreoffice",
        "ffmpeg",
        "gimp",
        "inkscape",
        "sketch",
        "stata",
        "wavetone",
        "chrome",
        "chromium",
        "calibre",
        "comfyui",
        "draw.io",
        "drawio",
        "freecad",
        "godot",
        "joplin",
        "kdenlive",
        "krita",
        "musescore",
        "obsidian",
        "obs-studio",
        "ollama",
    )
    signals = []
    for marker in app_markers:
        pattern = r"(?<![a-z0-9_.-])" + re.escape(marker) + r"(?![a-z0-9_.-])"
        if re.search(pattern, text):
            signals.append(f"external-app:{marker}")
    return signals


def platform_assessment(market_record: dict[str, Any] | None, requires: str | None) -> dict[str, Any]:
    host_platform = sys.platform
    text = "\n".join(
        str(value)
        for value in (
            (market_record or {}).get("platform"),
            requires,
        )
        if value
    ).casefold()
    incompatible = False
    if "macos" in text or "darwin" in text:
        incompatible = not host_platform.startswith("darwin")
    if "linux" in text and not host_platform.startswith("linux"):
        incompatible = True
    if "windows" in text and not host_platform.startswith("win"):
        incompatible = True
    return {
        "host": host_platform,
        "compatible": not incompatible,
        "signals": text.splitlines(),
    }


def readiness_summary(probes: list[dict[str, Any]], install_candidate: bool) -> dict[str, Any]:
    blockers = [
        probe
        for probe in probes
        if probe["status"] in {"missing", "unavailable", "manual_required"}
        and probe["severity"] == "blocker"
    ]
    return {
        "ready": bool(install_candidate) and len(blockers) == 0,
        "probe_blocker_count": len(blockers),
        "probes": probes,
    }


def readiness_blocker_probes(readiness: dict[str, Any]) -> list[dict[str, Any]]:
    probes = readiness.get("probes")
    if not isinstance(probes, list):
        return []
    blockers = []
    for probe in probes:
        if not isinstance(probe, dict):
            continue
        if (
            probe.get("status") in {"missing", "unavailable", "manual_required"}
            and probe.get("severity") == "blocker"
        ):
            blockers.append(probe)
    return blockers


def dependency_probes(requires: str | None, entry_point: Any) -> list[dict[str, Any]]:
    requirement = (requires or "").strip()
    assessment = requirement_assessment(requirement)
    probes: list[dict[str, Any]] = [declared_requirement_probe(requirement, assessment)]
    probes.extend(command_requirement_probes(requirement))
    entrypoint_probe = entrypoint_requirement_probe(entry_point)
    if entrypoint_probe is not None:
        probes.append(entrypoint_probe)
    probes.extend(env_requirement_probes(requirement))
    probes.extend(localhost_requirement_probes(requirement))
    manual_probe = manual_account_requirement_probe(requirement)
    if manual_probe is not None:
        probes.append(manual_probe)
    return probes


def declared_requirement_probe(
    requirement: str,
    assessment: dict[str, Any],
) -> dict[str, Any]:
    if assessment["external_dependency_free"]:
        return {
            "id": "declared-requirements",
            "kind": "requirements",
            "status": "satisfied",
            "severity": "info",
            "detail": requirement or "no declared requirements",
            "dependency_class": assessment["dependency_class"],
            "signals": assessment["signals"],
        }
    return {
        "id": "declared-requirements",
        "kind": "requirements",
        "status": "declared",
        "severity": "blocker",
        "detail": requirement,
        "dependency_class": assessment["dependency_class"],
        "signals": assessment["signals"],
    }


def command_requirement_probes(requirement: str) -> list[dict[str, Any]]:
    return [command_requirement_probe(command) for command in requirement_commands(requirement)]


def command_requirement_probe(command: str) -> dict[str, Any]:
    path = shutil.which(command)
    return {
        "id": f"command:{command}",
        "kind": "command",
        "name": command,
        "status": "available" if path else "missing",
        "severity": "info" if path else "blocker",
        "path": path,
    }


def entrypoint_requirement_probe(entry_point: Any) -> dict[str, Any] | None:
    if not isinstance(entry_point, str) or not entry_point:
        return None
    path = shutil.which(entry_point)
    return {
        "id": f"entrypoint:{entry_point}",
        "kind": "entrypoint",
        "name": entry_point,
        "status": "available" if path else "missing",
        "severity": "info" if path else "warning",
        "path": path,
    }


def env_requirement_probes(requirement: str) -> list[dict[str, Any]]:
    return [env_requirement_probe(env_name) for env_name in requirement_env_vars(requirement)]


def env_requirement_probe(env_name: str) -> dict[str, Any]:
    present = bool(os.environ.get(env_name))
    return {
        "id": f"env:{env_name}",
        "kind": "env",
        "name": env_name,
        "status": "available" if present else "missing",
        "severity": "info" if present else "blocker",
    }


def localhost_requirement_probes(requirement: str) -> list[dict[str, Any]]:
    return [
        localhost_requirement_probe(host, port)
        for host, port in requirement_localhost_ports(requirement)
    ]


def localhost_requirement_probe(host: str, port: int) -> dict[str, Any]:
    available = localhost_port_available(host, port)
    return {
        "id": f"localhost:{host}:{port}",
        "kind": "localhost",
        "host": host,
        "port": port,
        "status": "available" if available else "unavailable",
        "severity": "info" if available else "blocker",
    }


def manual_account_requirement_probe(requirement: str) -> dict[str, Any] | None:
    if not requires_manual_account_or_key(requirement):
        return None
    return {
        "id": "manual-account-or-api-key",
        "kind": "manual",
        "status": "manual_required",
        "severity": "blocker",
        "detail": "declared requirement mentions account, login, token, or API key",
    }


def requirement_commands(requirement: str) -> list[str]:
    commands: list[str] = []
    text = requirement.strip()
    if not text:
        return commands
    package_match = re.match(r"^\s*([a-zA-Z][a-zA-Z0-9_.-]+)\s*\(", text)
    if package_match:
        commands.append(package_match.group(1))
    for marker in ("apt install", "brew install", "choco install", "winget install"):
        if marker in text.casefold():
            before_marker = text[: text.casefold().find(marker)].strip()
            if before_marker and re.match(r"^[a-zA-Z][a-zA-Z0-9_.-]+$", before_marker.split()[0]):
                commands.append(before_marker.split()[0])
    if re.search(r"\buv\b", text.casefold()):
        commands.append("uv")
    return sorted(set(commands))


def requirement_env_vars(requirement: str) -> list[str]:
    if not requirement:
        return []
    env_vars = re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", requirement)
    return sorted(set(env_vars))


def requirement_localhost_ports(requirement: str) -> list[tuple[str, int]]:
    ports: list[tuple[str, int]] = []
    for match in re.finditer(r"(localhost|127\.0\.0\.1|\[?::1\]?):(\d{2,5})", requirement, flags=re.IGNORECASE):
        host = match.group(1).strip("[]")
        port = int(match.group(2))
        if 0 < port < 65536:
            ports.append((host, port))
    return sorted(set(ports))


def localhost_port_available(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def requires_manual_account_or_key(requirement: str) -> bool:
    text = requirement.casefold()
    return any(marker in text for marker in ("account", "login", "api key", "token", "secret"))
