from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock
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

    def test_project_qdrant_embeds_in_worker(self) -> None:
        """_project_qdrant calls embedder and upsert_with_vector with pre-computed vector."""
        mock_qdrant = MagicMock()
        mock_qdrant.enabled = True
        mock_qdrant.is_available.return_value = True
        mock_qdrant._embedder = lambda x: [0.1] * 768

        record = self.repo.create_memory(
            content="Journal entry", type="decision", namespace="project",
            scope_id="mnemonic", source="human",
        )

        worker = OutboxWorker(self.repo, qdrant_store=mock_qdrant, max_workers=1)
        worker._embedder = lambda x: [0.1] * 768
        worker._embedding_fingerprint = lambda: "ollama:nomic-embed-text:768"

        event = self.repo.list_due_outbox()[0]
        worker._project_qdrant(event)

        mock_qdrant.upsert_with_vector.assert_called_once()
        mock_qdrant.upsert.assert_not_called()

    def test_project_qdrant_skips_when_hash_unmodified(self) -> None:
        """When content_hash and fingerprint unchanged, skip embedding entirely."""
        mock_qdrant = MagicMock()
        mock_qdrant.enabled = True
        mock_qdrant.is_available.return_value = True

        record = self.repo.create_memory(
            content="Journal entry", type="decision", namespace="project",
            scope_id="mnemonic", source="human",
        )

        # Pre-set content_hash and fingerprint
        db = Database(self.tmp_path / "memory.db")
        with db.connect() as conn:
            conn.execute("""
                UPDATE memory_projections
                SET qdrant_content_hash = ?, qdrant_embedding_fingerprint = ?
                WHERE memory_id = ?
            """, (record.content_hash, "ollama:nomic-embed-text:768", record.id))

        worker = OutboxWorker(self.repo, qdrant_store=mock_qdrant, max_workers=1)
        worker._embedder = lambda x: [0.1] * 768
        worker._embedding_fingerprint = lambda: "ollama:nomic-embed-text:768"

        event = self.repo.list_due_outbox()[0]
        worker._project_qdrant(event)

        # Ollama should NOT be called — hash unchanged
        mock_qdrant.upsert_with_vector.assert_not_called()
        mock_qdrant.upsert.assert_not_called()

    def test_reschedule_outbox_event_dead_letters_after_max_retries(self) -> None:
        """After MAX_EMBEDDING_RETRIES, event is dead-lettered with processed_at set."""
        from mcp_memory.repository import MAX_EMBEDDING_RETRIES

        mock_qdrant = MagicMock()
        mock_qdrant.enabled = True

        record = self.repo.create_memory(
            content="Journal entry", type="decision", namespace="project",
            scope_id="mnemonic", source="human",
        )

        event = self.repo.list_due_outbox()[0]

        # Retry MAX_EMBEDDING_RETRIES times via direct reschedule call
        for _ in range(MAX_EMBEDDING_RETRIES):
            self.repo.reschedule_outbox_event(event.id, delay_seconds=0, error="Ollama down")

        # After max retries, event should be dead-lettered
        # Verify via direct DB query — processed_at now set (suppressed from re-pickup)
        db = Database(self.tmp_path / "memory.db")
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_outbox WHERE id = ?", (event.id,)
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["attempt_count"], MAX_EMBEDDING_RETRIES)
        self.assertIn("DEAD_LETTER", row["error"] or "")
        self.assertIsNotNone(row["processed_at"], "Dead-lettered event must have processed_at set")

        # Verify suppression — event NOT in due outbox (worker cannot re-poll)
        due = self.repo.list_due_outbox()
        self.assertFalse(any(e.id == event.id for e in due), "Dead-lettered event must not be re-polled")

        state = self.repo.get_projection_state(record.id)
        self.assertEqual(state["qdrant_status"], "error")
        self.assertIn("DEAD_LETTER", state["last_error"] or "")


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

    def test_upsert_with_vector_called_when_no_newer_event(self) -> None:
        """Normal path: active record + no newer pending event → upsert_with_vector is called."""
        mock_qdrant = self._make_mock_qdrant()
        worker = OutboxWorker(self.repo, qdrant_store=mock_qdrant, max_workers=1)
        # Ensure embedder is available (used by _project_qdrant)
        from mcp_memory.embedding import HashEmbeddingProvider
        worker._embedder = HashEmbeddingProvider(size=768).embed
        worker._embedding_fingerprint = lambda: "hash:768"

        record = self.repo.create_memory(
            content="important context", type="fact",
            namespace="ns", scope_id="s", source="agent",
        )

        worker.process_pending()

        mock_qdrant.upsert_with_vector.assert_called_once()
        mock_qdrant.upsert.assert_not_called()

    def test_upsert_skipped_when_newer_event_pending(self) -> None:
        """Active record + newer pending event → upsert (Ollama) must be skipped."""
        mock_qdrant = self._make_mock_qdrant()
        worker = OutboxWorker(self.repo, qdrant_store=mock_qdrant, max_workers=1)
        from mcp_memory.embedding import HashEmbeddingProvider
        worker._embedder = HashEmbeddingProvider(size=768).embed
        worker._embedding_fingerprint = lambda: "hash:768"

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

        mock_qdrant.upsert_with_vector.assert_not_called()
        mock_qdrant.upsert.assert_not_called()

    def test_delete_still_called_when_record_inactive(self) -> None:
        """Inactive (retracted) record → delete must be called even if newer event exists."""
        mock_qdrant = self._make_mock_qdrant()
        worker = OutboxWorker(self.repo, qdrant_store=mock_qdrant, max_workers=1)
        from mcp_memory.embedding import HashEmbeddingProvider
        worker._embedder = HashEmbeddingProvider(size=768).embed
        worker._embedding_fingerprint = lambda: "hash:768"

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


class TestParallelProcessing(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.repo = _repo(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_processes_events_concurrently(self) -> None:
        """Events should be dispatched to the thread pool, not processed sequentially."""
        # Create multiple records to generate multiple events
        for i in range(3):
            self.repo.create_memory(
                content=f"concurrent test {i}",
                type="test",
                namespace="parallel",
                scope_id=f"s{i}",
                source="test",
            )
        pending = self.repo.list_due_outbox()
        self.assertGreaterEqual(len(pending), 1)

        handled_by: list = []
        lock = threading.Lock()
        original_project_qdrant = OutboxWorker._project_qdrant

        def tracking_project_qdrant(self, event):
            with lock:
                handled_by.append(threading.current_thread().name)
            time.sleep(0.05)  # simulate I/O
            return original_project_qdrant(self, event)

        worker = OutboxWorker(self.repo, max_workers=3)
        worker._project_qdrant = lambda e: tracking_project_qdrant(worker, e)  # type: ignore[method-assign]
        worker.process_pending()

        unique_threads = set(handled_by)
        self.assertGreater(
            len(unique_threads), 1,
            f"Events processed by single thread {unique_threads}. Expected parallel dispatch.",
        )

    def test_max_workers_respected(self) -> None:
        """Worker should not spawn more threads than max_workers."""
        worker = OutboxWorker(self.repo, max_workers=2)
        self.assertEqual(worker._executor._max_workers, 2)

    def test_shutdown_works(self) -> None:
        """shutdown() should cleanly stop the executor."""
        worker = OutboxWorker(self.repo, max_workers=2)
        worker.shutdown(wait=True)
        self.assertTrue(worker._executor._shutdown)

    def test_apply_projection_event_error_reschedules(self) -> None:
        """On projection error, event should be rescheduled with backoff."""
        record = self.repo.create_memory(
            content="error test",
            type="test",
            namespace="parallel",
            scope_id="s2",
            source="test",
        )
        events = self.repo.list_due_outbox()
        self.assertGreaterEqual(len(events), 1)
        evt = events[0]

        error_worker = OutboxWorker(self.repo, max_workers=1)
        error_worker._project_qdrant = lambda e: (_ for _ in ()).throw(RuntimeError("simulated"))  # type: ignore[method-assign]

        # Should not raise — errors are caught internally
        error_worker.process_pending()

        # Event should have been rescheduled (not marked processed)
        db2 = Database(self.tmp_path / "memory.db")
        with db2.connect() as conn:
            row = conn.execute(
                "SELECT error, attempt_count FROM memory_outbox WHERE id = ?", (evt.id,)
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["attempt_count"], 1)
        self.assertIsNotNone(row["error"])


if __name__ == "__main__":
    unittest.main()
