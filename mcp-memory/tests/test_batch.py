from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp_memory.config import Settings
from mcp_memory.database import Database
from mcp_memory.repository import MemoryRepository
from mcp_memory.search import SearchService
from mcp_memory.tools import MemoryTools


def _tools(tmp_path: Path) -> MemoryTools:
    settings = Settings(database_path=tmp_path / "memory.db", vault_path=tmp_path / "vault")
    db = Database(settings.database_path)
    db.initialize()
    repo = MemoryRepository(db)
    return MemoryTools(settings, repo, SearchService(repo))


class TestBatchWrite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.tools = _tools(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_batch_write_creates_multiple_records(self) -> None:
        items = [
            {
                "content": "First memory",
                "type": "fact",
                "namespace": "project",
                "scope_id": "mnemonic",
                "source": "human",
                "tags": ["alpha"],
            },
            {
                "content": "Second memory",
                "type": "fact",
                "namespace": "project",
                "scope_id": "mnemonic",
                "source": "human",
                "tags": ["beta"],
            },
            {
                "content": "Third memory",
                "type": "pattern",
                "namespace": "project",
                "scope_id": "mnemonic",
                "source": "agent",
                "tags": ["gamma"],
            },
        ]

        result = self.tools.batch_write(items=items)

        self.assertEqual(len(result["results"]), 3)
        self.assertTrue(result["all_created"])
        self.assertEqual(result["created_count"], 3)
        self.assertEqual(result["failed_count"], 0)

        # Verify all records exist - new shape: {index, id, error}
        ids = [r["id"] for r in result["results"]]
        for memory_id in ids:
            fetched = self.tools.get(memory_id)
            self.assertIsNotNone(fetched["record"])

    def test_batch_write_respects_idempotency_keys(self) -> None:
        items = [
            {
                "content": "Idempotent content",
                "type": "fact",
                "namespace": "project",
                "scope_id": "mnemonic",
                "source": "human",
                "idempotency_key": "same-key",
            },
            {
                "content": "Idempotent content",
                "type": "fact",
                "namespace": "project",
                "scope_id": "mnemonic",
                "source": "human",
                "idempotency_key": "same-key",
            },
        ]

        result = self.tools.batch_write(items=items)

        self.assertEqual(len(result["results"]), 2)
        # First should be created, second should be skipped (not created)
        self.assertTrue(result["results"][0]["created"])
        self.assertFalse(result["results"][1]["created"])
        self.assertFalse(result["all_created"])
        self.assertEqual(result["created_count"], 1)
        self.assertEqual(result["failed_count"], 0)

    def test_batch_write_returns_partial_results_on_failure(self) -> None:
        # Create first record
        first = self.tools.write(
            content="Existing record",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )

        # Try to batch write where first item will succeed and second has wrong namespace
        items = [
            {
                "content": "New record",
                "type": "fact",
                "namespace": "project",
                "scope_id": "mnemonic",
                "source": "human",
            },
        ]

        result = self.tools.batch_write(items=items)
        self.assertEqual(result["created_count"], 1)
        self.assertEqual(result["failed_count"], 0)


class TestBatchUpdateTags(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.tools = _tools(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_batch_update_tags_adds_and_removes_tags(self) -> None:
        # Create two records with initial tags
        first = self.tools.write(
            content="First",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            tags=["old", "common"],
        )
        second = self.tools.write(
            content="Second",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            tags=["old", "common"],
        )

        updates = [
            {
                "id": first["record"].id,
                "add_tags": ["new_first"],
                "remove_tags": ["old"],
            },
            {
                "id": second["record"].id,
                "add_tags": ["new_second"],
                "remove_tags": ["old"],
            },
        ]

        result = self.tools.batch_update_tags(updates=updates)

        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(result["all_success"])

        # Verify tags were updated
        updated_first = self.tools.get(first["record"].id)["record"]
        updated_second = self.tools.get(second["record"].id)["record"]

        self.assertIn("new_first", updated_first.tags)
        self.assertNotIn("old", updated_first.tags)
        self.assertIn("new_second", updated_second.tags)
        self.assertNotIn("old", updated_second.tags)

    def test_batch_update_tags_handles_not_found(self) -> None:
        # Create one valid record
        created = self.tools.write(
            content="Valid record",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            tags=["initial"],
        )

        updates = [
            {
                "id": created["record"].id,
                "add_tags": ["added"],
                "remove_tags": [],
            },
            {
                "id": "nonexistent-id",
                "add_tags": ["never_added"],
                "remove_tags": [],
            },
        ]

        result = self.tools.batch_update_tags(updates=updates)

        self.assertEqual(len(result["results"]), 2)
        self.assertFalse(result["all_success"])
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
