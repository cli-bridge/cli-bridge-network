"""stdio subprocess adapter skeleton."""

from __future__ import annotations

import subprocess
import os

from adapters.base import ToolCall, ToolResult


class StdioAdapter:
    def call(self, request: ToolCall) -> ToolResult:
        if request.dry_run:
            return _dry_run_result(request)

        try:
            proc = _run_process(request)
        except subprocess.TimeoutExpired as exc:
            return _timeout_result(request, exc)
        except OSError as exc:
            return _spawn_failed_result(request, exc)
        return _process_result(request, proc)


def _dry_run_result(request: ToolCall) -> ToolResult:
    return ToolResult(
        capability_id=request.capability_id,
        allowed=True,
        exit_code=0,
        stdout=" ".join(request.argv),
        reason="dry-run",
    )


def _run_process(request: ToolCall) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(request.argv),
        cwd=request.cwd,
        env=_subprocess_env(request),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=request.timeout_seconds,
    )


def _subprocess_env(request: ToolCall) -> dict[str, str] | None:
    if not request.env:
        return None
    env = os.environ.copy()
    env.update(request.env)
    return env


def _timeout_result(request: ToolCall, exc: subprocess.TimeoutExpired) -> ToolResult:
    stderr = _timeout_stderr(request, exc)
    return ToolResult(
        capability_id=request.capability_id,
        allowed=True,
        exit_code=124,
        stdout=_timeout_text(exc.stdout),
        stderr=stderr,
        reason="timeout",
    )


def _timeout_stderr(request: ToolCall, exc: subprocess.TimeoutExpired) -> str:
    stderr = _timeout_text(exc.stderr)
    if stderr:
        stderr = f"{stderr}\n"
    return f"{stderr}command timed out after {request.timeout_seconds} seconds"


def _spawn_failed_result(request: ToolCall, exc: OSError) -> ToolResult:
    return ToolResult(
        capability_id=request.capability_id,
        allowed=True,
        exit_code=127,
        stderr=f"{request.argv[0]} failed to start: {exc}",
        reason="spawn-failed",
    )


def _process_result(
    request: ToolCall,
    proc: subprocess.CompletedProcess[str],
) -> ToolResult:
    return ToolResult(
        capability_id=request.capability_id,
        allowed=True,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
