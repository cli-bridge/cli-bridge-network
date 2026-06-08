"""stdio subprocess adapter skeleton."""

from __future__ import annotations

import subprocess

from adapters.base import ToolCall, ToolResult


class StdioAdapter:
    def call(self, request: ToolCall) -> ToolResult:
        if request.dry_run:
            return ToolResult(
                capability_id=request.capability_id,
                allowed=True,
                exit_code=0,
                stdout=" ".join(request.argv),
                reason="dry-run",
            )

        try:
            proc = subprocess.run(
                list(request.argv),
                cwd=request.cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=request.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _timeout_text(exc.stdout)
            stderr = _timeout_text(exc.stderr)
            if stderr:
                stderr = f"{stderr}\n"
            stderr = f"{stderr}command timed out after {request.timeout_seconds} seconds"
            return ToolResult(
                capability_id=request.capability_id,
                allowed=True,
                exit_code=124,
                stdout=stdout,
                stderr=stderr,
                reason="timeout",
            )
        except OSError as exc:
            return ToolResult(
                capability_id=request.capability_id,
                allowed=True,
                exit_code=127,
                stderr=f"{request.argv[0]} failed to start: {exc}",
                reason="spawn-failed",
            )
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
