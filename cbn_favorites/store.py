"""Favorite workflow cards.

A "card" is a captured workflow + presentation metadata. A draft card comes from a
conversation thread's ``captured_workflow``; promoting it (★ 收藏) copies the workflow
here under ``runtime/favorites/`` with ``favorite=true`` and stamps the thread's
``card_id``. Favorites are re-runnable via the existing ``/workflows/run`` (the
workflow body is a standard WorkflowGraph).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _task_count(workflow: dict[str, Any] | None) -> int:
    if not isinstance(workflow, dict):
        return 0
    spec = workflow.get("spec")
    if not isinstance(spec, dict):
        return 0
    tasks = spec.get("tasks")
    return len(tasks) if isinstance(tasks, list) else 0


class FavoriteStore:
    def __init__(self, favorites_dir: Path) -> None:
        self.dir = Path(favorites_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, card_id: str) -> Path:
        return self.dir / f"{card_id}.json"

    def save(
        self,
        card_id: str,
        title: str,
        workflow: dict[str, Any],
        source_thread_id: str | None = None,
        labels: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "card_id": card_id,
            "title": title or "收藏工作流",
            "workflow": workflow,
            "source_thread_id": source_thread_id,
            "favorite": True,
            "created_at": now_iso(),
            "labels": labels or {},
        }
        self._write(record)
        return record

    def promote_from_thread(
        self,
        thread_store: Any,
        thread_id: str,
        title: str | None = None,
    ) -> dict[str, Any] | None:
        thread = thread_store.get(thread_id)
        if thread is None or not thread.get("captured_workflow"):
            return None
        existing_id = thread.get("card_id")
        if existing_id:
            existing = self.get(existing_id)
            if existing is not None:
                return existing
        card_id = str(uuid.uuid4())
        card = self.save(
            card_id,
            title or thread.get("title") or "收藏工作流",
            thread["captured_workflow"],
            source_thread_id=thread_id,
            labels={"source": "agent-run"},
        )
        thread_store.set_card_id(thread_id, card_id)
        return card

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows.append(self._row(record))
        return rows

    def list_full(self, limit: int = 100) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return records

    def get(self, card_id: str) -> dict[str, Any] | None:
        path = self._path(card_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def delete(self, card_id: str) -> bool:
        path = self._path(card_id)
        if path.exists():
            path.unlink()
            return True
        return False

    @staticmethod
    def _row(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "card_id": record.get("card_id"),
            "title": record.get("title") or "收藏工作流",
            "created_at": record.get("created_at"),
            "source_thread_id": record.get("source_thread_id"),
            "favorite": True,
            "task_count": _task_count(record.get("workflow")),
        }

    def _write(self, record: dict[str, Any]) -> None:
        self._path(record["card_id"]).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
