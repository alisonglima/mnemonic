from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


class TestSearchAdvancedFilters(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.tools = _tools(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_search_with_created_after_filter(self) -> None:
        # Create a record
        self.tools.write(
            content="Test record",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )

        # Search with created_after filter (should include the record)
        result = self.tools.search(
            query="Test",
            namespace="project",
            scope_id="mnemonic",
            created_after="2020-01-01T00:00:00Z",
        )
        self.assertGreaterEqual(len(result["items"]), 1)

        # Search with created_after filter in the future (should not include)
        result = self.tools.search(
            query="Test",
            namespace="project",
            scope_id="mnemonic",
            created_after="2099-01-01T00:00:00Z",
        )
        self.assertEqual(len(result["items"]), 0)

    def test_search_with_created_before_filter(self) -> None:
        # Create a record
        self.tools.write(
            content="Test record before",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )

        # Search with created_before filter in the past (should not include)
        result = self.tools.search(
            query="Test",
            namespace="project",
            scope_id="mnemonic",
            created_before="2020-01-01T00:00:00Z",
        )
        self.assertEqual(len(result["items"]), 0)

    def test_search_with_date_range(self) -> None:
        # Create a record
        self.tools.write(
            content="Test record range",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )

        # Search with full date range
        result = self.tools.search(
            query="Test",
            namespace="project",
            scope_id="mnemonic",
            created_after="2020-01-01T00:00:00Z",
            created_before="2099-12-31T23:59:59Z",
        )
        self.assertGreaterEqual(len(result["items"]), 1)

    def test_search_with_status_filter(self) -> None:
        # Create a record and archive it
        created = self.tools.write(
            content="Status filter test",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )
        memory_id = created["record"].id
        self.tools.archive(memory_id, reason="testing")

        # Search with status=active (should not include archived)
        result = self.tools.search(
            query="Status",
            namespace="project",
            scope_id="mnemonic",
            status="active",
        )
        for item in result["items"]:
            self.assertEqual(item.status, "active")

        # Search with status=archived (should only include archived)
        result = self.tools.search(
            query="Status",
            namespace="project",
            scope_id="mnemonic",
            status="archived",
        )
        for item in result["items"]:
            self.assertEqual(item.status, "archived")

    def test_search_with_offset(self) -> None:
        # Create multiple records
        for i in range(5):
            self.tools.write(
                content=f"Record number {i}",
                type="fact",
                namespace="project",
                scope_id="mnemonic",
                source="human",
            )

        # Search with limit=2
        result = self.tools.search(
            query="Record",
            namespace="project",
            scope_id="mnemonic",
            limit=2,
        )
        self.assertEqual(len(result["items"]), 2)

        # Search with limit=2 and offset=2
        result = self.tools.search(
            query="Record",
            namespace="project",
            scope_id="mnemonic",
            limit=2,
            offset=2,
        )
        self.assertEqual(len(result["items"]), 2)

    def test_search_with_offset_and_date_filter(self) -> None:
        # Create multiple records
        for i in range(5):
            self.tools.write(
                content=f"Offset test record {i}",
                type="fact",
                namespace="project",
                scope_id="mnemonic",
                source="human",
            )

        # Search with offset and date filter
        result = self.tools.search(
            query="Offset",
            namespace="project",
            scope_id="mnemonic",
            limit=10,
            offset=2,
            created_after="2020-01-01T00:00:00Z",
        )
        self.assertGreaterEqual(len(result["items"]), 3)


if __name__ == "__main__":
    unittest.main()
