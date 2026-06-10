"""Built-in output parser registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


ParserFn = Callable[[str, str], dict[str, Any]]


@dataclass(frozen=True)
class ParserRecord:
    parser_ref: str
    title: str
    description: str

    def as_dict(self) -> dict[str, str]:
        return {
            "parser_ref": self.parser_ref,
            "title": self.title,
            "description": self.description,
        }


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, tuple[ParserRecord, ParserFn]] = {}

    @classmethod
    def builtins(cls) -> "ParserRegistry":
        registry = cls()
        registry.register("raw.text", "Raw Text", "Return stdout and stderr as text.", parse_raw_text)
        registry.register("json.stdout", "JSON stdout", "Parse stdout as JSON.", parse_json_stdout)
        registry.register(
            "git.version",
            "Git Version",
            "Parse `git --version` output into a version string.",
            parse_git_version,
        )
        registry.register(
            "git.status.short",
            "Git short status",
            "Parse `git status --short` porcelain-ish output into entries.",
            parse_git_status_short,
        )
        registry.register("ffprobe.json", "ffprobe JSON", "Parse ffprobe `-of json` output.", parse_json_stdout)
        registry.register(
            "cli-anything.raw",
            "CLI-Anything raw",
            "Keep CLI-Anything harness output as raw text, but fail on known fatal harness stderr.",
            parse_cli_anything_raw,
        )
        registry.register(
            "cli-anything.mermaid.set_diagram",
            "CLI-Anything Mermaid set diagram",
            "Parse verified Mermaid harness `diagram set` dry-run JSON output.",
            parse_cli_anything_mermaid_set_diagram,
        )
        registry.register(
            "cli-anything.macrocli.backends",
            "CLI-Anything MacroCLI backends",
            "Parse verified MacroCLI `backends --json` output.",
            parse_cli_anything_macrocli_backends,
        )
        registry.register(
            "direct-cli.typed",
            "Direct CLI typed output",
            "Parse direct external CLI probe output into setup, health, version, and command metadata.",
            parse_direct_cli_typed,
        )
        return registry

    def register(
        self,
        parser_ref: str,
        title: str,
        description: str,
        parser: ParserFn,
    ) -> None:
        if parser_ref in self._parsers:
            raise ValueError(f"duplicate parser: {parser_ref}")
        self._parsers[parser_ref] = (ParserRecord(parser_ref, title, description), parser)

    def list(self) -> list[dict[str, str]]:
        return [record.as_dict() for record, _ in self._parsers.values()]

    def inspect(self, parser_ref: str) -> dict[str, str]:
        record, _ = self._require(parser_ref)
        return record.as_dict()

    def parse(self, parser_ref: str | None, stdout: str, stderr: str) -> dict[str, Any]:
        if parser_ref is None:
            parser_ref = "raw.text"
        _, parser = self._require(parser_ref)
        return {
            "parser_ref": parser_ref,
            "ok": True,
            "data": parser(stdout, stderr),
        }

    def _require(self, parser_ref: str) -> tuple[ParserRecord, ParserFn]:
        parser = self._parsers.get(parser_ref)
        if parser is None:
            raise KeyError(f"unknown parser: {parser_ref}")
        return parser


def parse_raw_text(stdout: str, stderr: str) -> dict[str, Any]:
    return {"stdout": stdout, "stderr": stderr}


def parse_cli_anything_raw(stdout: str, stderr: str) -> dict[str, Any]:
    fatal = _cli_anything_fatal_stderr(stderr)
    if fatal:
        raise ValueError(f"CLI-Anything harness failed: {fatal}")
    return {"stdout": stdout, "stderr": stderr}


def parse_json_stdout(stdout: str, stderr: str) -> dict[str, Any]:
    if stderr.strip():
        return {"json": json.loads(stdout), "stderr": stderr}
    return {"json": json.loads(stdout)}


def parse_git_version(stdout: str, stderr: str) -> dict[str, Any]:
    text = stdout.strip()
    prefix = "git version "
    if not text.startswith(prefix):
        raise ValueError(f"unexpected git version output: {text!r}")
    version = text[len(prefix) :].strip()
    if not version:
        raise ValueError("git version output is missing a version")
    data: dict[str, Any] = {"version": version, "raw": text}
    if stderr.strip():
        data["stderr"] = stderr
    return data


def parse_git_status_short(stdout: str, stderr: str) -> dict[str, Any]:
    entries = []
    for line in stdout.splitlines():
        if not line:
            continue
        status = line[:2]
        path = line[3:] if len(line) > 3 else ""
        entries.append(
            {
                "index": status[0],
                "worktree": status[1],
                "path": path,
                "raw": line,
            }
        )
    return {"entries": entries, "stderr": stderr}


def parse_cli_anything_mermaid_set_diagram(stdout: str, stderr: str) -> dict[str, Any]:
    payload = json.loads(stdout)
    if not isinstance(payload, dict):
        raise ValueError("Mermaid set diagram output must be a JSON object")
    if payload.get("action") != "set_diagram":
        raise ValueError(f"unexpected Mermaid action: {payload.get('action')}")
    line_count = payload.get("line_count")
    if not isinstance(line_count, int) or isinstance(line_count, bool):
        raise ValueError("Mermaid set diagram line_count must be an integer")
    data: dict[str, Any] = {
        "action": payload["action"],
        "line_count": line_count,
    }
    if stderr.strip():
        data["stderr"] = stderr
    return data


def parse_cli_anything_macrocli_backends(stdout: str, stderr: str) -> dict[str, Any]:
    payload = json.loads(stdout)
    if not isinstance(payload, dict):
        raise ValueError("MacroCLI backends output must be a JSON object")
    backends: list[dict[str, Any]] = []
    available = 0
    for key, value in sorted(payload.items()):
        if not isinstance(value, dict):
            raise ValueError(f"MacroCLI backend {key} must be an object")
        name = value.get("name")
        priority = value.get("priority")
        is_available = value.get("available")
        if not isinstance(name, str) or not name:
            raise ValueError(f"MacroCLI backend {key} name must be a string")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise ValueError(f"MacroCLI backend {key} priority must be an integer")
        if not isinstance(is_available, bool):
            raise ValueError(f"MacroCLI backend {key} available must be a boolean")
        if is_available:
            available += 1
        backends.append(
            {
                "id": key,
                "name": name,
                "priority": priority,
                "available": is_available,
            }
        )
    data: dict[str, Any] = {
        "backend_count": len(backends),
        "available_count": available,
        "backends": backends,
    }
    if stderr.strip():
        data["stderr"] = stderr
    return data


def parse_direct_cli_typed(stdout: str, stderr: str) -> dict[str, Any]:
    text = stdout.strip()
    err = stderr.strip()
    combined = "\n".join(part for part in (text, err) if part)
    fatal = _direct_cli_fatal_error(combined)
    if fatal:
        raise ValueError(f"direct CLI launcher failed: {fatal}")

    data: dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "output_kind": "empty" if not combined else "text",
        "ready": True,
        "setup_required": False,
        "error_type": None,
        "next_action": None,
    }

    json_payload = _try_json(text)
    if isinstance(json_payload, dict):
        data.update(_parse_direct_cli_json(json_payload))
        data["output_kind"] = "json"
    else:
        data.update(_parse_direct_cli_text(combined))

    if err and data["error_type"] is None:
        data["error_type"] = "stderr"
        data["ready"] = False

    return data


def _parse_direct_cli_json(payload: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {"json": payload}
    if isinstance(payload.get("version"), str):
        data["profile"] = "jimeng" if "commit" in payload else "unknown"
        data["version"] = payload["version"]
        if isinstance(payload.get("commit"), str):
            data["commit"] = payload["commit"]
        if isinstance(payload.get("build_time"), str):
            data["build_time"] = payload["build_time"]
        return data

    if "healthy" in payload:
        healthy = bool(payload.get("healthy"))
        data.update(
            {
                "profile": "caw",
                "action": "status",
                "healthy": healthy,
                "ready": healthy,
                "setup_required": not healthy,
                "error_type": None if healthy else "service_unhealthy",
                "next_action": None if healthy else "configure Cobo Agentic Wallet API URL/key or local service pairing",
            }
        )
        if isinstance(payload.get("healthy_error"), str):
            data["healthy_error"] = payload["healthy_error"]
        return data

    if any(key in payload for key in ("cli_version", "cli_update", "config_file")):
        checks = _doctor_checks_from_json(payload)
        failed = [item for item in checks if item["status"] != "pass"]
        config_missing = any(item["name"] == "config_file" and "not configured" in item.get("message", "") for item in failed)
        data.update(
            {
                "profile": "feishu",
                "action": "doctor",
                "checks": checks,
                "ready": not failed,
                "setup_required": bool(failed),
                "error_type": "config_missing" if config_missing else "doctor_failed" if failed else None,
                "next_action": None
                if not failed
                else "run lark-cli config init --new and complete Feishu/Lark CLI configuration",
            }
        )
        return data

    if "ok" in payload or "status" in payload:
        ok = payload.get("ok")
        status = payload.get("status")
        ready = bool(ok) if isinstance(ok, bool) else status in {"ok", "running", "ready", "healthy"}
        data.update(
            {
                "profile": "obsidian-cli",
                "action": "local-rest-server-status",
                "ready": ready,
                "setup_required": not ready,
                "error_type": None if ready else "local_rest_unavailable",
                "next_action": None if ready else "start Obsidian and configure the Local REST API plugin/API key",
            }
        )
        return data

    return data


def _parse_direct_cli_text(text: str) -> dict[str, Any]:
    lower = text.lower()
    data: dict[str, Any] = {}
    if "lark-cli version" in lower:
        data.update({"profile": "feishu", "action": "version", "version": text.splitlines()[0].strip()})
    elif "lark/feishu cli tool" in lower:
        data.update({"profile": "feishu", "action": "help", "commands": _extract_command_names(text)})
    elif "lark-cli" in lower and "schema" in lower:
        data.update({"profile": "feishu", "action": "schema-help", "commands": _extract_command_names(text)})
    elif "cli version" in lower and "config_file" in lower:
        data.update(
            {
                "profile": "feishu",
                "action": "doctor",
                "ready": False,
                "setup_required": True,
                "error_type": "config_missing" if "not configured" in lower else "doctor_failed",
                "next_action": "run lark-cli config init --new and complete Feishu/Lark CLI configuration",
                "checks": _extract_feishu_doctor_checks(text),
            }
        )
    elif "dreamina official aigc cli tool" in lower:
        data.update({"profile": "jimeng", "action": "help", "commands": _extract_command_names(text)})
    elif "未检测到有效登录态" in text or "dreamina login" in lower:
        data.update(
            {
                "profile": "jimeng",
                "ready": False,
                "setup_required": True,
                "error_type": "auth_required",
                "next_action": "run dreamina login and complete OAuth/device login before live API calls",
            }
        )
    elif "cobo agentic wallet" in lower:
        action = "schema-help" if "schema" in lower and "available commands" not in lower else "help"
        data.update({"profile": "caw", "action": action, "commands": _extract_command_names(text)})
    elif text.strip().startswith("v") and any(ch.isdigit() for ch in text):
        data.update({"profile": "caw", "action": "version", "version": text.splitlines()[0].strip()})
    elif "cli-anything-obsidian" in lower or "usage:" in lower and "obsidian" in lower:
        action = "official-help" if "cli-anything-obsidian" not in lower else "help"
        data.update({"profile": "obsidian-cli", "action": action, "commands": _extract_command_names(text)})
    elif "obsidian" in lower and ("not running" in lower or "connection" in lower or "api key" in lower):
        data.update(
            {
                "profile": "obsidian-cli",
                "ready": False,
                "setup_required": True,
                "error_type": "local_rest_unavailable",
                "next_action": "start Obsidian and configure the Local REST API plugin/API key",
            }
        )
    return data


def _extract_command_names(text: str) -> list[str]:
    commands: list[str] = []
    in_commands = False
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered in {"commands:", "available commands:", "built-in commands:", "generator commands:"}:
            in_commands = True
            continue
        if not in_commands:
            continue
        if not stripped:
            continue
        first = stripped.split()[0]
        if first.endswith(":"):
            continue
        if first.replace("_", "").replace("-", "").isalnum():
            commands.append(first)
    return commands


def _extract_feishu_doctor_checks(text: str) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or "pass" not in stripped.lower() and "fail" not in stripped.lower():
            continue
        parts = stripped.replace(":", " ").split()
        status = "fail" if "fail" in stripped.lower() else "pass"
        name = parts[0] if parts else stripped
        checks.append({"name": name, "status": status, "raw": stripped})
    return checks


def _doctor_checks_from_json(payload: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for name, raw in sorted(payload.items()):
        if isinstance(raw, dict):
            status = raw.get("status")
            message = raw.get("message", "")
            checks.append(
                {
                    "name": str(name),
                    "status": str(status) if isinstance(status, str) and status else "unknown",
                    "message": str(message) if isinstance(message, str) else "",
                }
            )
    return checks


def _try_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _direct_cli_fatal_error(text: str) -> str | None:
    fatal_markers = (
        "failed to start:",
        "is not recognized as an internal or external command",
        "No such file or directory",
        "Traceback (most recent call last):",
        "ModuleNotFoundError:",
        "ImportError:",
        "command not found",
    )
    for marker in fatal_markers:
        if marker in text:
            return marker
    return None


def _cli_anything_fatal_stderr(stderr: str) -> str | None:
    text = stderr.strip()
    if not text:
        return None
    fatal_markers = (
        "NoConsoleScreenBufferError",
        "Traceback (most recent call last):",
        "Exception:",
        "Error:",
        "ModuleNotFoundError:",
        "ImportError:",
    )
    for marker in fatal_markers:
        if marker in text:
            return marker
    return None
