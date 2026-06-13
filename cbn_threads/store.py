"""Persisted conversation threads for the Workflow Agent chat.

Each thread is one JSON file under ``runtime/threads/``. A thread stores the chat
messages (user turn + streamed agent events) and, later, the workflow captured from
the run. This replaces the hardcoded/fake left-nav "Agent Sessions" list with real,
durable chat threads.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# Cap any single event payload we persist so a thread file stays manageable even
# when a capability returns a large stdout.
_MAX_PAYLOAD_CHARS = 6000


def _truncate_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: _truncate_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_truncate_payload(item) for item in payload]
    if isinstance(payload, str) and len(payload) > _MAX_PAYLOAD_CHARS:
        return payload[:_MAX_PAYLOAD_CHARS] + f"…<truncated {len(payload) - _MAX_PAYLOAD_CHARS} chars>"
    return payload


class ThreadStore:
    def __init__(self, threads_dir: Path) -> None:
        self.dir = Path(threads_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, thread_id: str) -> Path:
        return self.dir / f"{thread_id}.json"

    def create(self, message: str, permission_mode: str) -> dict[str, Any]:
        thread_id = str(uuid.uuid4())
        ts = now_iso()
        title = (message or "").strip().replace("\n", " ")[:80] or "新对话"
        record: dict[str, Any] = {
            "thread_id": thread_id,
            "title": title,
            "created_at": ts,
            "updated_at": ts,
            "permission_mode": permission_mode,
            "messages": [self._user_message(message, ts)] if message else [],
            "captured_workflow": None,
            "card_id": None,
        }
        self._write(record)
        return record

    def append_user_message(self, thread_id: str, message: str) -> dict[str, Any] | None:
        """Continue an existing thread with a new user turn (multi-turn chat)."""
        record = self.get(thread_id)
        if record is None:
            return None
        record["messages"].append(self._user_message(message, now_iso()))
        record["updated_at"] = now_iso()
        self._write(record)
        return record

    @staticmethod
    def _user_message(message: str, ts: str) -> dict[str, Any]:
        return {"role": "user", "kind": "text", "payload": {"text": message}, "ts": ts}

    def append_event(self, thread_id: str, role: str, kind: str, payload: Any) -> dict[str, Any] | None:
        record = self.get(thread_id)
        if record is None:
            return None
        record["messages"].append(
            {"role": role, "kind": kind, "payload": _truncate_payload(payload), "ts": now_iso()}
        )
        record["updated_at"] = now_iso()
        self._write(record)
        return record

    def set_captured_workflow(self, thread_id: str, workflow: dict[str, Any] | None) -> dict[str, Any] | None:
        record = self.get(thread_id)
        if record is None:
            return None
        record["captured_workflow"] = workflow
        record["updated_at"] = now_iso()
        self._write(record)
        return record

    def set_card_id(self, thread_id: str, card_id: str | None) -> dict[str, Any] | None:
        record = self.get(thread_id)
        if record is None:
            return None
        record["card_id"] = card_id
        record["updated_at"] = now_iso()
        self._write(record)
        return record

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        files = sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        rows: list[dict[str, Any]] = []
        for path in files[:limit]:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows.append(self._row(record))
        return rows

    def get(self, thread_id: str) -> dict[str, Any] | None:
        path = self._path(thread_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def delete(self, thread_id: str) -> bool:
        path = self._path(thread_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def _row(self, record: dict[str, Any]) -> dict[str, Any]:
        messages = record.get("messages") or []
        tone = self._derive_tone(record, messages)
        return {
            "thread_id": record.get("thread_id"),
            "title": record.get("title") or "新对话",
            "updated_at": record.get("updated_at"),
            "message_count": len(messages),
            "has_workflow": bool(record.get("captured_workflow")),
            "tone": tone,
            "permission_mode": record.get("permission_mode"),
        }

    @staticmethod
    def _derive_tone(record: dict[str, Any], messages: list[dict[str, Any]]) -> str:
        if record.get("captured_workflow"):
            return "ok"
        for message in reversed(messages):
            if message.get("role") == "assistant_event" and message.get("kind") == "error":
                return "warn"
            if message.get("role") == "assistant_event":
                break
        return "idle"

    def _write(self, record: dict[str, Any]) -> None:
        self._path(record["thread_id"]).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
