"""Capture a Workflow Agent run as a reusable WorkflowGraph.

As the agent drives capabilities (``run_capability`` tool calls), this accumulator
records each call. ``build()`` turns the sequence into a linear-chain WorkflowGraph
(each task ``needs`` the previous one, using the exact argv the agent passed) that
``/workflows/run`` can re-execute as-is — i.e. the captured workflow is a faithful,
re-runnable replay of what the agent did.

The MVP keeps data-flow as an ordered ``needs`` chain (no ``argsFrom`` selectors) so
the graph always validates. Richer data-flow edges (selectors that thread upstream
payloads into downstream argv) are a later increment.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Iterable


def _safe_id_segment(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value).strip()).strip("-._")
    return safe or "cap"


class WorkflowCapture:
    def __init__(self, title: str = "Agent-captured workflow") -> None:
        self._title = title
        self._calls: list[tuple[str, tuple[str, ...]]] = []

    def record_capability_call(self, capability_id: str, args: Iterable[Any] | None) -> None:
        if not capability_id:
            return
        argv = tuple(str(arg) for arg in (args or []))
        self._calls.append((str(capability_id), argv))

    @property
    def call_count(self) -> int:
        return len(self._calls)

    def build(self) -> dict[str, Any] | None:
        if not self._calls:
            return None
        tasks: list[dict[str, Any]] = []
        for index, (capability_id, argv) in enumerate(self._calls, start=1):
            task_id = f"step-{index:02d}-{_safe_id_segment(capability_id)}"
            tasks.append(
                {
                    "id": task_id,
                    "uses": capability_id,
                    "args": list(argv),
                    "argsFrom": [],
                    "needs": [tasks[-1]["id"]] if tasks else [],
                }
            )
        return {
            "apiVersion": "bridge.dev/v1alpha1",
            "kind": "Workflow",
            "metadata": {
                "id": f"agent-capture-{uuid.uuid4().hex[:8]}",
                "title": self._title,
            },
            "spec": {"tasks": tasks},
        }
