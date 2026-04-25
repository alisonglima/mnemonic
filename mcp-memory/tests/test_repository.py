from __future__ import annotations

import tempfile
import threading
import unittest
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


if __name__ == "__main__":
    unittest.main()
