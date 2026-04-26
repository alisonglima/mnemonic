from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp_memory.config import Settings
from mcp_memory.database import Database
from mcp_memory.repository import MemoryRepository
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.search import SearchService
from mcp_memory.tools import MemoryTools


def _tools(tmp_path: Path) -> MemoryTools:
    settings = Settings(database_path=tmp_path / "memory.db", vault_path=tmp_path / "vault")
    db = Database(settings.database_path)
    db.initialize()
    repo = MemoryRepository(db)
    return MemoryTools(settings, repo, SearchService(repo))


def _tools_with_qdrant_url(tmp_path: Path) -> MemoryTools:
    settings = Settings(
        database_path=tmp_path / "memory.db",
        vault_path=tmp_path / "vault",
        qdrant_url="http://127.0.0.1:65530",
    )
    db = Database(settings.database_path)
    db.initialize()
    repo = MemoryRepository(db)
    return MemoryTools(settings, repo, SearchService(repo, QdrantProjectionStore(url=settings.qdrant_url)))


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.tools = _tools(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_write_returns_payload_mismatch_flags(self) -> None:
        first = self.tools.write(
            content="Same idempotent write",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            idempotency_key="same-key",
        )
        replay = self.tools.write(
            content="Same idempotent write",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            idempotency_key="same-key",
        )
        mismatch = self.tools.write(
            content="Different payload",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            idempotency_key="same-key",
        )

        self.assertTrue(first["created"])
        self.assertFalse(replay["created"])
        self.assertFalse(replay["payload_mismatch"])
        self.assertFalse(mismatch["created"])
        self.assertTrue(mismatch["payload_mismatch"])

    def test_health_reports_dependency_states(self) -> None:
        health = self.tools.health()

        self.assertEqual(health["sqlite"], "up")
        self.assertEqual(health["worker"], "up")
        self.assertTrue(health["degraded"])
        self.assertGreaterEqual(health["pending_events"], 0)

    def test_tool_flow_supports_get_search_and_status_transitions(self) -> None:
        created = self.tools.write(
            content="Created via tool flow",
            type="decision",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            tags=["initial"],
            obsidian_projection=True,
        )
        memory_id = created["record"].id

        fetched = self.tools.get(memory_id)
        search = self.tools.search(query="Created", namespace="project", scope_id="mnemonic")
        updated = self.tools.update(
            id=memory_id,
            expected_version=1,
            content="Updated via tool flow",
            type="pattern",
            metadata={"edited": True},
            change_reason="refine",
        )
        archived = self.tools.archive(memory_id, reason="keep")
        tagged = self.tools.add_tags(memory_id, ["refined"])
        noted = self.tools.append_note(memory_id, "Important note", "human")
        retracted = self.tools.retract(memory_id, expected_version=updated["record"].version + 3, reason="superseded")
        deleted = self.tools.delete(memory_id, expected_version=retracted["record"].version, reason="cleanup")

        self.assertEqual(fetched["record"].id, memory_id)
        self.assertEqual(search["items"][0].id, memory_id)
        self.assertEqual(updated["record"].version, 2)
        self.assertEqual(archived["record"].status, "archived")
        self.assertIn("refined", tagged["record"].tags)
        self.assertEqual(noted["record"].notes[-1]["note"], "Important note")
        self.assertEqual(retracted["record"].status, "retracted")
        self.assertEqual(deleted["record"].status, "deleted")

    def test_journal_creates_obsidian_projected_record(self) -> None:
        result = self.tools.journal(
            title="Decision title",
            content="Journal content",
            journal_type="decision",
            namespace="project",
            scope_id="mnemonic",
            source="human",
            tags=["journal"],
        )
        # Projection is async — worker must run before file exists on disk.
        self.tools.worker.process_pending()

        self.assertTrue(result["record"].obsidian_projection)
        self.assertEqual(result["record"].type, "decision")
        self.assertTrue((self.tmp_path / "vault" / "memory" / f"{result['record'].id}.md").exists())

    def test_get_returns_projection_state_and_health_counts_backlog(self) -> None:
        created = self.tools.write(
            content="Projection state check",
            type="fact",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )

        fetched = self.tools.get(created["record"].id)
        health = self.tools.health()

        self.assertIn("projection_state", fetched)
        self.assertIn("qdrant_status", fetched["projection_state"])
        self.assertGreaterEqual(health["pending_events"], 1)

    def test_unreachable_qdrant_url_still_reports_degraded(self) -> None:
        tools = _tools_with_qdrant_url(self.tmp_path)

        health = tools.health()
        result = tools.search(query="anything", namespace="project", scope_id="mnemonic")

        self.assertEqual(health["qdrant"], "down")
        self.assertTrue(health["degraded"])
        self.assertEqual(result["search_mode"], "fallback_sqlite")
        # degraded is False when queue is empty (no staleness), even if qdrant is down
        self.assertFalse(result["degraded"])


def test_write_does_not_block_on_qdrant_projection(tmp_path):
    """write() must return after SQLite commit without waiting for Qdrant."""
    settings = Settings(database_path=tmp_path / "memory.db", vault_path=tmp_path / "vault")
    db = Database(settings.database_path)
    db.initialize()
    repository = MemoryRepository(db)
    qdrant_store = QdrantProjectionStore(enabled=False)
    tools = MemoryTools(settings, repository, SearchService(repository, qdrant_store))

    process_calls = []
    original = tools.worker.process_pending
    tools.worker.process_pending = lambda: process_calls.append(1) or original()

    tools.write(
        content="test content",
        type="test",
        namespace="ns",
        scope_id="s",
        source="test",
    )

    assert process_calls == [], "write() must not call process_pending() inline"


if __name__ == "__main__":
    unittest.main()
