"""Deterministic launch profiles for locally installed external CLIs.

This module is intentionally small: manifests call it to resolve known local
entrypoints, while Adapter Agent synthesis stays out of the MVP runtime path.
"""

from __future__ import annotations

import argparse
import codecs
import contextlib
import json
import os
import re
import select
import socket
import subprocess
import sys
import threading
import uuid
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
    if _is_wsl_dreamina_command(command) and _should_trace_dreamina_command(command):
        return _run_wsl_dreamina_command(command, trace_writes=True)
    if _is_wsl_dreamina_command(command):
        return _run_wsl_dreamina_command(command, trace_writes=False)
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


def _run_wsl_dreamina_command(command: list[str], *, trace_writes: bool) -> int:
    bridge = _maybe_start_wsl_proxy_bridge()
    try:
        resolved = _dreamina_command_with_env(command, bridge.proxy_url if bridge else None)
        trace_path = f"/tmp/cbn-dreamina-{uuid.uuid4().hex}.trace"
        if trace_writes and _wsl_command_exists("strace"):
            resolved = [
                *resolved[:2],
                "strace",
                "-f",
                "-e",
                "write",
                "-s",
                "500",
                "-o",
                trace_path,
                *resolved[2:],
            ]
        else:
            trace_path = ""
        proc = subprocess.run(
            resolved,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stderr = proc.stderr
        if trace_path and proc.returncode != 0:
            diagnostics = _dreamina_trace_diagnostics(trace_path)
            if diagnostics:
                stderr = "\n".join(part for part in (stderr.rstrip(), diagnostics) if part) + "\n"
        sys.stdout.write(proc.stdout)
        sys.stderr.write(stderr)
        return int(proc.returncode)
    except OSError as exc:
        print(f"{command[0]} failed to start: {exc}", file=sys.stderr)
        return 127
    finally:
        if bridge:
            bridge.close()


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
        ExternalCliAction(
            "feishu",
            "im-message-send",
            "Send a Feishu/Lark message (interactive card or text). args=['--data','{\"receive_id\":\"ou_...\",\"msg_type\":\"interactive|text\",\"content\":\"<json string>\"}']",
            lambda root: [_lark_cli(root), "api", "POST", "/open-apis/im/v1/messages?receive_id_type=open_id"],
        ),
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


@dataclass
class _ProxyBridge:
    proxy_url: str
    _server: socket.socket

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._server.close()


def _is_wsl_dreamina_command(command: list[str]) -> bool:
    return len(command) >= 3 and command[0] == "wsl" and command[1] == "--" and command[2].endswith("/dreamina")


def _should_trace_dreamina_command(command: list[str]) -> bool:
    return len(command) >= 4 and command[3] in {
        "frames2video",
        "image2image",
        "image2video",
        "image_upscale",
        "multiframe2video",
        "multimodal2video",
        "text2image",
        "text2video",
    }


def _dreamina_command_with_env(command: list[str], proxy_url: str | None) -> list[str]:
    if not proxy_url:
        return command
    return [
        command[0],
        command[1],
        "env",
        f"http_proxy={proxy_url}",
        f"https_proxy={proxy_url}",
        f"all_proxy={proxy_url}",
        f"HTTP_PROXY={proxy_url}",
        f"HTTPS_PROXY={proxy_url}",
        f"ALL_PROXY={proxy_url}",
        *command[2:],
    ]


def _maybe_start_wsl_proxy_bridge() -> _ProxyBridge | None:
    configured = os.environ.get("CBN_DREAMINA_WSL_PROXY")
    if configured:
        return _ProxyBridge(configured, _closed_socket())

    proxy = _windows_loopback_proxy()
    if proxy is None:
        return None
    wsl_host = _wsl_default_gateway()
    if not wsl_host:
        return None
    server = _start_tcp_forwarder(("0.0.0.0", 0), proxy)
    port = server.getsockname()[1]
    return _ProxyBridge(f"http://{wsl_host}:{port}", server)


def _windows_loopback_proxy() -> tuple[str, int] | None:
    env_proxy = os.environ.get("CBN_WINDOWS_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    parsed = _parse_proxy_endpoint(env_proxy)
    if parsed:
        return parsed
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return None
            raw, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError:
        return None
    return _parse_proxy_endpoint(str(raw))


def _parse_proxy_endpoint(raw: str | None) -> tuple[str, int] | None:
    if not raw:
        return None
    value = raw.strip()
    if ";" in value:
        parts = [part for part in value.split(";") if part]
        preferred = next((part.split("=", 1)[1] for part in parts if part.lower().startswith("https=")), "")
        value = preferred or parts[0].split("=", 1)[-1]
    value = value.removeprefix("http://").removeprefix("https://")
    host, sep, port_text = value.rpartition(":")
    if not sep:
        return None
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return None
    try:
        port = int(port_text)
    except ValueError:
        return None
    return ("127.0.0.1", port)


def _wsl_default_gateway() -> str:
    try:
        proc = subprocess.run(
            ["wsl", "--", "ip", "route", "show", "default"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    match = re.search(r"\bvia\s+(\d+\.\d+\.\d+\.\d+)\b", proc.stdout)
    return match.group(1) if match else ""


def _start_tcp_forwarder(bind: tuple[str, int], target: tuple[str, int]) -> socket.socket:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(bind)
    server.listen(50)

    def accept_loop() -> None:
        while True:
            try:
                client, _ = server.accept()
                upstream = socket.create_connection(target, timeout=10)
            except OSError:
                break
            threading.Thread(target=_pump_sockets, args=(client, upstream), daemon=True).start()

    threading.Thread(target=accept_loop, daemon=True).start()
    return server


def _pump_sockets(left: socket.socket, right: socket.socket) -> None:
    sockets = (left, right)
    try:
        while True:
            readable, _, _ = select.select(sockets, [], [], 120)
            if not readable:
                return
            for sock in readable:
                chunk = sock.recv(65536)
                if not chunk:
                    return
                (right if sock is left else left).sendall(chunk)
    except OSError:
        pass
    finally:
        for sock in sockets:
            with contextlib.suppress(OSError):
                sock.close()


def _closed_socket() -> socket.socket:
    sock = socket.socket()
    sock.close()
    return sock


def _wsl_command_exists(command: str) -> bool:
    try:
        proc = subprocess.run(
            ["wsl", "--", "which", command],
            text=True,
            encoding="utf-8",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _dreamina_trace_diagnostics(trace_path: str) -> str:
    try:
        proc = subprocess.run(
            ["wsl", "--", "cat", trace_path],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    finally:
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(["wsl", "--", "rm", "-f", trace_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    messages = _extract_dreamina_trace_messages(proc.stdout)
    if not messages:
        return ""
    return "dreamina diagnostic: " + " | ".join(messages)


def _extract_dreamina_trace_messages(trace: str) -> list[str]:
    messages: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'write\(\d+,\s+"((?:[^"\\]|\\.)*)",\s+\d+', trace):
        decoded = _decode_strace_string(match.group(1)).strip()
        if not _looks_like_dreamina_diagnostic(decoded) or decoded in seen:
            continue
        seen.add(decoded)
        messages.append(decoded)
    return messages


def _decode_strace_string(value: str) -> str:
    try:
        raw = codecs.decode(value, "unicode_escape").encode("latin1", errors="ignore")
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return value


def _looks_like_dreamina_diagnostic(text: str) -> bool:
    if not text or len(text) > 1000:
        return False
    markers = (
        "dreamina_cli",
        "do request:",
        "未检测到有效登录态",
        "current account",
        "AigcComplianceConfirmationRequired",
        "permission",
        "权限",
    )
    return any(marker in text for marker in markers)


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
