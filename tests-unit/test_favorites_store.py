"""Unit tests for FavoriteStore + card-row building (no HTTP/daemon)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cbn_favorites.store import FavoriteStore
from cbn_threads.store import ThreadStore


class _FakeThreadStore:
    """Minimal ThreadStore-compatible facade backed by a real ThreadStore."""

    def __init__(self, dir: Path) -> None:
        self._inner = ThreadStore(dir)

    def get(self, thread_id): return self._inner.get(thread_id)
    def set_card_id(self, thread_id, card_id): return self._inner.set_card_id(thread_id, card_id)


class FavoriteStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.threads_dir = Path(self._tmp.name) / "threads"
        self.favorites_dir = Path(self._tmp.name) / "favorites"
        self.thread_store = ThreadStore(self.threads_dir)
        self.bridge = _FakeThreadStore(self.threads_dir)
        self.favorites = FavoriteStore(self.favorites_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _workflow(self, uses: str = "git.version") -> dict:
        return {
            "apiVersion": "bridge.dev/v1alpha1",
            "kind": "Workflow",
            "metadata": {"id": "w", "title": "W"},
            "spec": {"tasks": [{"id": "step-01-x", "uses": uses, "args": [], "argsFrom": [], "needs": []}]},
        }

    def test_save_list_get_delete_round_trip(self) -> None:
        card = self.favorites.save("c1", "My workflow", self._workflow())
        self.assertEqual(card["favorite"], True)
        rows = self.favorites.list()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["card_id"], "c1")
        self.assertEqual(rows[0]["task_count"], 1)
        self.assertEqual(self.favorites.get("c1")["title"], "My workflow")
        self.assertTrue(self.favorites.delete("c1"))
        self.assertEqual(self.favorites.list(), [])

    def test_promote_from_thread_copies_workflow_and_stamps_card_id(self) -> None:
        thread = self.thread_store.create("do a thing", "full")
        self.thread_store.set_captured_workflow(thread["thread_id"], self._workflow("jimeng.user_credit"))
        promoted = self.favorites.promote_from_thread(self.bridge, thread["thread_id"], title="即梦余额")
        self.assertIsNotNone(promoted)
        self.assertTrue(promoted["favorite"])
        self.assertEqual(promoted["source_thread_id"], thread["thread_id"])
        # thread now references the card
        self.assertEqual(self.thread_store.get(thread["thread_id"])["card_id"], promoted["card_id"])
        # promote again is idempotent -> returns the same card
        again = self.favorites.promote_from_thread(self.bridge, thread["thread_id"])
        self.assertEqual(again["card_id"], promoted["card_id"])
        # the draft disappears from cards (it's now a favorite)
        self.assertEqual(len(self.favorites.list()), 1)

    def test_promote_without_workflow_returns_none(self) -> None:
        thread = self.thread_store.create("no workflow here", "full")
        self.assertIsNone(self.favorites.promote_from_thread(self.bridge, thread["thread_id"]))


if __name__ == "__main__":
    unittest.main()
