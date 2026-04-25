from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp_memory.config import Settings
from mcp_memory.database import Database
from mcp_memory.models import MemoryRecord
from mcp_memory.obsidian_store import ObsidianProjectionStore


def _make_record(
    content: str = "Test content",
    status: str = "active",
    namespace: str = "test",
    type: str = "fact",
    tags: list = None,
) -> MemoryRecord:
    if tags is None:
        tags = ["test"]
    return MemoryRecord(
        id="test-id-123",
        content=content,
        type=type,
        namespace=namespace,
        scope_id="test-scope",
        source="human",
        status=status,
        version=1,
        content_hash="abc123",
        tags=tags,
        notes=[],
        metadata={},
        obsidian_projection=True,
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


class TestObsidianProjectionStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.store = ObsidianProjectionStore(self.tmp_path / "vault")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_materialize_journal_creates_file(self) -> None:
        record = _make_record(content="Journal entry content")
        path = self.store.materialize_journal(record)
        self.assertTrue(path.exists())
        self.assertTrue((self.tmp_path / "vault" / f"{record.id}.md").exists())

    def test_materialize_journal_writes_frontmatter(self) -> None:
        record = _make_record(content="Frontmatter test", type="decision", tags=["important", "decision"])
        path = self.store.materialize_journal(record)
        content = path.read_text(encoding="utf-8")
        self.assertIn("---", content)
        self.assertIn(f"id: {record.id}", content)
        self.assertIn(f"version: {record.version}", content)
        self.assertIn(f"type: {record.type}", content)
        self.assertIn(f"status: {record.status}", content)
        self.assertIn(f"namespace: {record.namespace}", content)
        self.assertIn(f"tags:", content)
        self.assertIn("- important", content)
        self.assertIn("- decision", content)
        self.assertIn("\n---\n", content)
        self.assertIn(record.content, content)

    def test_materialize_creates_status_subdir(self) -> None:
        record = _make_record(status="archived")
        path = self.store.materialize_journal(record)
        # Should create archived/ subdir
        self.assertTrue((self.tmp_path / "vault" / "archived" / f"{record.id}.md").exists())

    def test_materialize_retracted_creates_retracted_subdir(self) -> None:
        record = _make_record(status="retracted")
        path = self.store.materialize_journal(record)
        self.assertTrue((self.tmp_path / "vault" / "retracted" / f"{record.id}.md").exists())

    def test_materialize_deleted_creates_deleted_subdir(self) -> None:
        record = _make_record(status="deleted")
        path = self.store.materialize_journal(record)
        self.assertTrue((self.tmp_path / "vault" / "deleted" / f"{record.id}.md").exists())

    def test_frontmatter_includes_scope_id(self) -> None:
        record = _make_record()
        self.store.materialize_journal(record)
        content = (self.tmp_path / "vault" / f"{record.id}.md").read_text(encoding="utf-8")
        self.assertIn(f"scope_id: {record.scope_id}", content)

    def test_frontmatter_includes_created_and_updated(self) -> None:
        record = _make_record()
        self.store.materialize_journal(record)
        content = (self.tmp_path / "vault" / f"{record.id}.md").read_text(encoding="utf-8")
        self.assertIn(f"created_at: {record.created_at}", content)
        self.assertIn(f"updated_at: {record.updated_at}", content)

    def test_health_reports_up_for_existing_vault(self) -> None:
        record = _make_record()
        self.store.materialize_journal(record)
        self.assertEqual(self.store.health(), "up")

    def test_health_reports_down_for_missing_vault(self) -> None:
        store = ObsidianProjectionStore(self.tmp_path / "nonexistent")
        self.assertEqual(store.health(), "down")


if __name__ == "__main__":
    unittest.main()
