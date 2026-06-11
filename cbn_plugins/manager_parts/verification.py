"""Plugin plan verification helpers."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_command(argv: tuple[str, ...], timeout_seconds: int) -> dict[str, Any]:
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
    plan: Any,
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
    result = run_command(tuple(parsed["argv"]), timeout_seconds=timeout_seconds)
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
