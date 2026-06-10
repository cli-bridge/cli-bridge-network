"""Append-only local event bus."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class EventBus:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def publish(
        self,
        event_type: str,
        subject: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": str(uuid.uuid4()),
            "ts": now_iso(),
            "type": event_type,
            "subject": subject,
            "correlation_id": correlation_id,
            "payload": payload or {},
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def tail(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]
