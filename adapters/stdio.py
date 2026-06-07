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

        proc = subprocess.run(
            list(request.argv),
            cwd=request.cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        return ToolResult(
            capability_id=request.capability_id,
            allowed=True,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

