from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from mcp_memory.database import Database
from mcp_memory.outbox import OutboxWorker
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository


def _repo(tmp_path: Path) -> MemoryRepository:
    db = Database(tmp_path / "memory.db")
    db.initialize()
    return MemoryRepository(db)


class OutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.repo = _repo(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_write_enqueues_projection_events(self) -> None:
        record = self.repo.create_memory(
            content="Journal entry",
            type="decision",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            obsidian_projection=True,
        )

        events = self.repo.list_pending_outbox()
        event_types = {event.event_type for event in events}

        self.assertTrue(record.id)
        self.assertIn("project_qdrant", event_types)
        self.assertIn("project_obsidian", event_types)

    def test_stale_projection_event_is_skipped(self) -> None:
        record = self.repo.create_memory(
            content="Version one",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )
        self.repo.update_memory(
            memory_id=record.id,
            expected_version=1,
            content="Version two",
            type=None,
            metadata=None,
            change_reason="update",
        )

        worker = OutboxWorker(self.repo)
        worker.record_projection_version(record.id, "qdrant", 2)

        stale_event = self.repo.enqueue_projection_event(record.id, "project_qdrant", target_version=1)
        skipped = worker.apply_projection_event(stale_event, lambda event: None)

        self.assertFalse(skipped)

    def test_failed_projection_is_retried_with_backoff(self) -> None:
        self.repo.create_memory(
            content="Needs qdrant",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )

        worker = OutboxWorker(self.repo)
        worker.process_pending()

        pending = self.repo.list_pending_outbox()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].attempt_count, 1)
        self.assertEqual(self.repo.get_projection_state(pending[0].memory_id)["qdrant_status"], "error")

    def test_process_pending_ignores_not_due_events(self) -> None:
        record = self.repo.create_memory(
            content="Manual event",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )
        event = self.repo.enqueue_projection_event(record.id, "project_qdrant", target_version=5)
        self.repo.reschedule_outbox_event(event.id, delay_seconds=120, error="wait")

        worker = OutboxWorker(self.repo)
        worker.process_pending()

        pending = [item for item in self.repo.list_pending_outbox() if item.id == event.id]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].attempt_count, 1)

    def test_worker_loop_drains_due_obsidian_event(self) -> None:
        record = self.repo.create_memory(
            content="Loop projection",
            type="decision",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            obsidian_projection=True,
        )

        worker = OutboxWorker(self.repo)
        worker.process_pending()

        state = self.repo.get_projection_state(record.id)
        self.assertEqual(state["obsidian_status"], "ready")


class OutboxEmbeddingSkipTests(unittest.TestCase):
    """When a newer pending outbox event exists, skip the embedding call."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.repo = _repo(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _make_mock_qdrant(self):
        from unittest.mock import MagicMock
        from mcp_memory.embedding import HashEmbeddingProvider
        store = MagicMock(spec=QdrantProjectionStore)
        store.enabled = True
        store.is_available.return_value = True
        store._embedder = HashEmbeddingProvider(size=8).embed
        return store

    def test_upsert_called_when_no_newer_event(self) -> None:
        """Normal path: active record + no newer pending event → upsert (embed) is called."""
        mock_qdrant = self._make_mock_qdrant()
        worker = OutboxWorker(self.repo, qdrant_store=mock_qdrant)

        record = self.repo.create_memory(
            content="important context", type="fact",
            namespace="ns", scope_id="s", source="agent",
        )

        worker.process_pending()

        mock_qdrant.upsert.assert_called_once()

    def test_upsert_skipped_when_newer_event_pending(self) -> None:
        """Active record + newer pending event → upsert (Ollama) must be skipped."""
        mock_qdrant = self._make_mock_qdrant()
        worker = OutboxWorker(self.repo, qdrant_store=mock_qdrant)

        record = self.repo.create_memory(
            content="will be deleted soon", type="fact",
            namespace="ns", scope_id="s", source="agent",
        )
        # Simulate a newer event being queued (e.g., from an update or delete)
        self.repo.enqueue_projection_event(record.id, "project_qdrant", target_version=2)

        # Only process the FIRST event (target_version=1); the second is still pending
        events = self.repo.list_due_outbox()
        first_event = next(e for e in events if e.target_version == 1)
        worker.apply_projection_event(first_event, worker._handler_for(first_event))

        mock_qdrant.upsert.assert_not_called()

    def test_delete_still_called_when_record_inactive(self) -> None:
        """Inactive (retracted) record → delete must be called even if newer event exists."""
        mock_qdrant = self._make_mock_qdrant()
        worker = OutboxWorker(self.repo, qdrant_store=mock_qdrant)

        record = self.repo.create_memory(
            content="ephemeral", type="fact",
            namespace="ns", scope_id="s", source="agent",
        )
        self.repo.retract_memory(record.id, expected_version=1, reason="cleanup")
        # Clear the event from retract to test independently
        for event in self.repo.list_due_outbox():
            if event.memory_id == record.id:
                # Add a fresh event simulating a later state check
                test_event = self.repo.enqueue_projection_event(
                    record.id, "project_qdrant", target_version=99
                )
                worker.apply_projection_event(test_event, worker._handler_for(test_event))
                break

        mock_qdrant.delete.assert_called_once()
        mock_qdrant.upsert.assert_not_called()


class QdrantStoreTests(unittest.TestCase):
    def test_unreachable_qdrant_is_unavailable(self) -> None:
        store = QdrantProjectionStore(enabled=True, url="http://127.0.0.1:65530")

        self.assertFalse(store.is_available())
        self.assertEqual(store.health(), "down")

        with self.assertRaises(RuntimeError):
            store.upsert(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
