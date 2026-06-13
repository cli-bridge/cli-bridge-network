"""Deterministic launch profiles for locally installed external CLIs.

This module is intentionally small: manifests call it to resolve known local
entrypoints, while Adapter Agent synthesis stays out of the MVP runtime path.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ExternalCliAction:
    profile: str
    action: str
    title: str
    argv_factory: Callable[[Path], list[str]]

    @property
    def key(self) -> tuple[str, str]:
        return (self.profile, self.action)

    def argv(self, root: Path = PROJECT_ROOT) -> list[str]:
        return self.argv_factory(root)

    def as_record(self, root: Path = PROJECT_ROOT) -> dict[str, object]:
        return {
            "profile": self.profile,
            "action": self.action,
            "title": self.title,
            "argv": self.argv(root),
        }


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps(list_actions(), ensure_ascii=False, indent=2))
        return 0
    if not args.profile or not args.action:
        parser.error("profile and action are required unless --list is used")
    command = _resolve_command(args)
    if command is None:
        return 2
    if args.print_plan:
        print(json.dumps(_plan_payload(args, command), ensure_ascii=False, indent=2))
        return 0
    return _run_resolved_command(command)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m cbn_tools.external_cli")
    parser.add_argument("profile", nargs="?", help="Profile id such as feishu, jimeng, caw, obsidian-cli.")
    parser.add_argument("action", nargs="?", help="Action id within the profile.")
    parser.add_argument("extra_args", nargs=argparse.REMAINDER, help="Arguments passed to the resolved CLI.")
    parser.add_argument("--list", action="store_true", help="List known profile actions as JSON.")
    parser.add_argument("--print-plan", action="store_true", help="Print the resolved argv without executing it.")
    return parser


def _resolve_command(args: argparse.Namespace) -> list[str] | None:
    try:
        action = require_action(args.profile, args.action)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return None
    return action.argv() + list(args.extra_args)


def _plan_payload(args: argparse.Namespace, command: list[str]) -> dict[str, object]:
    return {"profile": args.profile, "action": args.action, "argv": command}


def _run_resolved_command(command: list[str]) -> int:
    try:
        proc = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        print(f"{command[0]} failed to start: {exc}", file=sys.stderr)
        return 127

    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return int(proc.returncode)


def list_actions(root: Path = PROJECT_ROOT) -> list[dict[str, object]]:
    return [action.as_record(root) for action in _actions()]


def require_action(profile: str, action: str) -> ExternalCliAction:
    by_key = {item.key: item for item in _actions()}
    try:
        return by_key[(profile, action)]
    except KeyError as exc:
        known = ", ".join(f"{item.profile}.{item.action}" for item in _actions())
        raise KeyError(f"unknown external CLI action {profile}.{action}; known actions: {known}") from exc


def _actions() -> tuple[ExternalCliAction, ...]:
    return (
        *_feishu_actions(),
        *_obsidian_actions(),
        *_jimeng_actions(),
        *_caw_actions(),
    )


def _feishu_actions() -> tuple[ExternalCliAction, ...]:
    return (
        ExternalCliAction("feishu", "version", "Feishu/Lark CLI version", lambda root: [_lark_cli(root), "--version"]),
        ExternalCliAction("feishu", "help", "Feishu/Lark CLI help", lambda root: [_lark_cli(root), "--help"]),
        ExternalCliAction("feishu", "doctor", "Feishu/Lark CLI doctor", lambda root: [_lark_cli(root), "doctor"]),
        ExternalCliAction("feishu", "schema-help", "Feishu/Lark CLI schema help", lambda root: [_lark_cli(root), "schema", "--help"]),
    )


def _obsidian_actions() -> tuple[ExternalCliAction, ...]:
    return (
        ExternalCliAction("obsidian-cli", "official-help", "Obsidian official CLI help", lambda root: [_obsidian_cli(), "--help"]),
        ExternalCliAction("obsidian-cli", "local-rest-help", "Obsidian Local REST harness help", lambda root: [_obsidian_rest_cli(root), "--help"]),
        ExternalCliAction(
            "obsidian-cli",
            "local-rest-server-status",
            "Obsidian Local REST server status",
            lambda root: [_obsidian_rest_cli(root), "--json", "server", "status"],
        ),
        ExternalCliAction(
            "obsidian-cli",
            "local-rest-note-read",
            "Obsidian Local REST note read",
            lambda root: [_obsidian_rest_cli(root), "--json", "vault", "read"],
        ),
    )


def _jimeng_actions() -> tuple[ExternalCliAction, ...]:
    return (
        ExternalCliAction("jimeng", "version", "Jimeng/Dreamina CLI version", lambda root: _dreamina(root) + ["version"]),
        ExternalCliAction("jimeng", "help", "Jimeng/Dreamina CLI help", lambda root: _dreamina(root) + ["--help"]),
        ExternalCliAction("jimeng", "login", "Jimeng/Dreamina OAuth login", lambda root: _dreamina(root) + ["login"]),
        ExternalCliAction(
            "jimeng",
            "login-headless",
            "Jimeng/Dreamina headless OAuth login",
            lambda root: _dreamina(root) + ["login", "--headless"],
        ),
        ExternalCliAction(
            "jimeng",
            "login-check",
            "Jimeng/Dreamina OAuth device-code polling",
            lambda root: _dreamina(root) + ["login", "checklogin"],
        ),
        ExternalCliAction("jimeng", "user-credit", "Jimeng/Dreamina user credit", lambda root: _dreamina(root) + ["user_credit"]),
        ExternalCliAction("jimeng", "list-task", "Jimeng/Dreamina task list", lambda root: _dreamina(root) + ["list_task"]),
        ExternalCliAction("jimeng", "query-result", "Jimeng/Dreamina query result", lambda root: _dreamina(root) + ["query_result"]),
        ExternalCliAction("jimeng", "text2image-submit", "Jimeng/Dreamina text2image submit", lambda root: _dreamina(root) + ["text2image"]),
    )


def _caw_actions() -> tuple[ExternalCliAction, ...]:
    return (
        ExternalCliAction("caw", "version", "Cobo Agentic Wallet version", lambda root: _caw(root) + ["--version"]),
        ExternalCliAction("caw", "help", "Cobo Agentic Wallet help", lambda root: _caw(root) + ["--help"]),
        ExternalCliAction("caw", "status", "Cobo Agentic Wallet status", lambda root: _caw(root) + ["status"]),
        ExternalCliAction("caw", "schema-help", "Cobo Agentic Wallet schema help", lambda root: _caw(root) + ["schema", "--help"]),
    )


def _lark_cli(root: Path) -> str:
    return _env_or_existing(
        "CBN_LARK_CLI",
        root / "external_plugins" / "cli-anything" / "npm-global" / "lark-cli.cmd",
        "lark-cli",
    )


def _obsidian_rest_cli(root: Path) -> str:
    return _env_or_existing(
        "CBN_OBSIDIAN_REST_CLI",
        root / "external_plugins" / "cli-anything" / "hub-venv" / "Scripts" / "cli-anything-obsidian.exe",
        "cli-anything-obsidian",
    )


def _obsidian_cli() -> str:
    env_value = os.environ.get("CBN_OBSIDIAN_CLI")
    if env_value:
        return env_value
    default = Path("D:/Programs/Obsidian/Obsidian.com")
    if default.exists():
        return str(default)
    return "obsidian"


def _dreamina(root: Path) -> list[str]:
    env_value = os.environ.get("CBN_DREAMINA_CLI")
    if env_value:
        return [env_value]
    local = root / "external_plugins" / "jimeng" / "wsl-bin" / "dreamina"
    if os.name == "nt":
        return ["wsl", "--", _wsl_path(local)]
    return [str(local)]


def _caw(root: Path) -> list[str]:
    env_value = os.environ.get("CBN_CAW_CLI")
    if env_value:
        return [env_value]
    local = root / "external_plugins" / "cobo-agentic-wallet" / "wsl-bin" / "caw"
    if os.name == "nt":
        return ["wsl", "--", _wsl_path(local)]
    return [str(local)]


def _env_or_existing(env_name: str, local_path: Path, fallback: str) -> str:
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value
    if local_path.exists():
        return str(local_path)
    return fallback


def _wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        return resolved.as_posix()
    parts = [part for part in resolved.parts[1:]]
    return "/mnt/" + drive + "/" + "/".join(parts)


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
