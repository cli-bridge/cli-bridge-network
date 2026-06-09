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
