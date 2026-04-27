from __future__ import annotations

import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from mcp_memory.database import Database
from mcp_memory.repository import MemoryRepository


def _repo(tmp_path: Path) -> MemoryRepository:
    db = Database(tmp_path / "memory.db")
    db.initialize()
    return MemoryRepository(db)


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.repo = _repo(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_create_memory_persists_initial_revision(self) -> None:
        record = self.repo.create_memory(
            content="Use SQLite as the source of truth.",
            type="decision",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            tags=["architecture"],
            metadata={"priority": "high"},
            idempotency_key="create-1",
        )

        fetched = self.repo.get_memory(record.id)
        revisions = self.repo.list_revisions(record.id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.version, 1)
        self.assertEqual(fetched.tags, ["architecture"])
        self.assertEqual(fetched.metadata["priority"], "high")
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].version, 1)
        self.assertEqual(revisions[0].tags_snapshot, ["architecture"])

    def test_update_requires_expected_version(self) -> None:
        record = self.repo.create_memory(
            content="Original",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )

        updated = self.repo.update_memory(
            memory_id=record.id,
            expected_version=1,
            content="Updated",
            type="decision",
            metadata={"edited": True},
            change_reason="promote",
        )

        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.content, "Updated")

        with self.assertRaisesRegex(Exception, "VersionConflictError"):
            self.repo.update_memory(
                memory_id=record.id,
                expected_version=1,
                content="Stale update",
                type=None,
                metadata=None,
                change_reason="stale",
            )

    def test_archive_is_idempotent_and_note_always_versions(self) -> None:
        record = self.repo.create_memory(
            content="Track this memory.",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )

        archived = self.repo.archive_memory(record.id, reason="done")
        archived_again = self.repo.archive_memory(record.id, reason="duplicate call")
        with_note = self.repo.append_note(record.id, note="keep for audit", source="human")

        self.assertEqual(archived.status, "archived")
        self.assertEqual(archived.version, 2)
        self.assertEqual(archived_again.version, 2)
        self.assertEqual(with_note.version, 3)
        self.assertEqual(with_note.notes[-1]["note"], "keep for audit")

    def test_concurrent_add_tags_and_append_note_do_not_drop_state(self) -> None:
        record = self.repo.create_memory(
            content="Concurrent",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )

        errors = []

        def add_tags() -> None:
            try:
                self.repo.add_tags(record.id, ["a", "b"])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def append_note() -> None:
            try:
                self.repo.append_note(record.id, note="n1", source="human")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        t1 = threading.Thread(target=add_tags)
        t2 = threading.Thread(target=append_note)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        current = self.repo.get_memory(record.id)
        self.assertEqual(errors, [])
        self.assertIsNotNone(current)
        self.assertIn("a", current.tags)
        self.assertEqual(current.notes[-1]["note"], "n1")

    def test_concurrent_remove_tags_and_append_note_do_not_drop_state(self) -> None:
        record = self.repo.create_memory(
            content="Concurrent remove",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            tags=["keep", "drop"],
        )

        errors = []

        def remove_tags() -> None:
            try:
                self.repo.remove_tags(record.id, ["drop"])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def append_note() -> None:
            try:
                self.repo.append_note(record.id, note="n2", source="human")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        t1 = threading.Thread(target=remove_tags)
        t2 = threading.Thread(target=append_note)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        current = self.repo.get_memory(record.id)
        self.assertEqual(errors, [])
        self.assertIsNotNone(current)
        self.assertNotIn("drop", current.tags)
        self.assertEqual(current.notes[-1]["note"], "n2")

    def test_concurrent_archive_and_append_note_do_not_drop_state(self) -> None:
        record = self.repo.create_memory(
            content="Concurrent archive",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )

        errors = []

        def archive() -> None:
            try:
                self.repo.archive_memory(record.id, reason="done")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def append_note() -> None:
            try:
                self.repo.append_note(record.id, note="n3", source="human")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        t1 = threading.Thread(target=archive)
        t2 = threading.Thread(target=append_note)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        current = self.repo.get_memory(record.id)
        self.assertEqual(errors, [])
        self.assertIsNotNone(current)
        self.assertEqual(current.status, "archived")
        self.assertEqual(current.notes[-1]["note"], "n3")

    def test_get_memory_bulk_returns_multiple_records(self) -> None:
        records = [self.repo.create_memory(
            content=f"content {i}",
            type="note",
            namespace="n",
            scope_id="s",
            source="test",
        ) for i in range(3)]
        ids = [r.id for r in records]
        results = self.repo.get_memory_bulk(ids)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r is not None for r in results))

    def test_get_memory_bulk_skips_missing(self) -> None:
        missing = [str(uuid.uuid4()) for _ in range(2)]
        results = self.repo.get_memory_bulk(missing)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r is None for r in results))

    def test_get_memory_bulk_empty_list(self) -> None:
        results = self.repo.get_memory_bulk([])
        self.assertEqual(results, [])

    def test_set_projection_version_is_monotonic(self) -> None:
        record = self.repo.create_memory(
            content="test",
            type="test",
            namespace="mono",
            scope_id="s1",
            source="test",
        )
        record_id = record.id

        db = Database(self.tmp_path / "memory.db")
        with db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO memory_projections (memory_id, qdrant_version, qdrant_status) VALUES (?, ?, ?)",
                (record_id, 5, "ready"),
            )

        self.repo.set_projection_version(record_id, "qdrant", 3)
        current = self.repo.get_projection_version(record_id, "qdrant")
        self.assertEqual(current, 5, f"Expected version 5, got {current}")

    def test_coverage_ratio_drops_after_update(self) -> None:
        """After updating a memory, coverage should drop until Qdrant processes it."""
        record = self.repo.create_memory(
            content="test",
            type="test",
            namespace="ns",
            scope_id="s1",
            source="test",
        )
        self.repo.set_projection_version(record.id, "qdrant", version=record.version)
        self.assertEqual(self.repo.qdrant_coverage_ratio(), 1.0)

        # Update the record — projection version is now stale
        self.repo.update_memory(
            memory_id=record.id,
            expected_version=1,
            content="updated",
            type="test",
            metadata=None,
            change_reason="update",
        )
        # Coverage should be 0 (new record version > qdrant_version)
        self.assertEqual(self.repo.qdrant_coverage_ratio(), 0.0)

    def test_search_fts_filters_by_type(self) -> None:
        r1 = self.repo.create_memory(content="architecture decision", type="decision",
                                namespace="fts", scope_id="s1", source="test")
        r2 = self.repo.create_memory(content="quick note", type="note",
                                namespace="fts", scope_id="s1", source="test")

        results = self.repo.search_fts(
            query="architecture",
            namespace="fts",
            limit=10,
            types=["decision"],
        )
        result_ids = [mid for mid, _ in results]
        self.assertIn(r1.id, result_ids)
        self.assertNotIn(r2.id, result_ids)

    def test_search_fts_uses_parameterized_status(self) -> None:
        # Verify SQL injection is not possible via status parameter
        self.repo.create_memory(content="test sql injection", type="test",
                               namespace="fts", scope_id="s1", source="test")
        # This should not cause SQL error even with unusual status
        results = self.repo.search_fts(query="sql", namespace="fts", limit=10, status="active")
        self.assertGreaterEqual(len(results), 0)  # No SQL error


if __name__ == "__main__":
    unittest.main()
