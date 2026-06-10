"""Execution queue placeholder."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueItem:
    item_id: str
    capability_id: str


class ExecutionQueue:
    def __init__(self) -> None:
        self._items: deque[QueueItem] = deque()

    def put(self, item: QueueItem) -> None:
        self._items.append(item)

    def get(self) -> QueueItem | None:
        if not self._items:
            return None
        return self._items.popleft()

