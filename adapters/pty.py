"""PTY adapter placeholder.

Windows ConPTY and Unix PTY behavior need separate implementations. Keep this
boundary explicit instead of hiding interactive terminal handling inside stdio.
"""

from __future__ import annotations

from adapters.base import ToolCall, ToolResult


class PtyAdapter:
    def call(self, request: ToolCall) -> ToolResult:
        return ToolResult(
            capability_id=request.capability_id,
            allowed=False,
            exit_code=None,
            reason="PTY adapter is not implemented yet",
        )

