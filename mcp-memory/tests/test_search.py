"""Tests for SearchService — freshness indicator and staleness fallback."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp_memory.database import Database
from mcp_memory.models import SearchResult, MemoryRecord, SearchHit
from mcp_memory.outbox import OutboxWorker
from mcp_memory.repository import MemoryRepository
from mcp_memory.search import SearchService, QRANT_STALENESS_THRESHOLD_SECONDS


def _repo(tmp_path: Path) -> MemoryRepository:
    db = Database(tmp_path / "memory.db")
    db.initialize()
    return MemoryRepository(db)


class TestFreshnessIndicator(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.repo = _repo(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_search_result_includes_freshness_seconds(self) -> None:
        """SearchResult should include freshness_seconds field."""
        result = SearchResult(items=[], search_mode="hybrid", degraded=False, freshness_seconds=5)
        self.assertEqual(result.freshness_seconds, 5)

    def test_search_result_freshness_seconds_defaults_to_zero(self) -> None:
        """SearchResult.freshness_seconds defaults to 0."""
        result = SearchResult(items=[], search_mode="hybrid", degraded=False)
        self.assertEqual(result.freshness_seconds, 0)


class TestStalenessFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.repo = _repo(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_search_falls_back_to_sqlite_when_qdrant_stale(self) -> None:
        """When oldest_pending_age > threshold, search should use fallback_sqlite."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        record = self.repo.create_memory(
            content="stale qdrant test content",
            type="test", namespace="freshness", scope_id="s1", source="test",
        )

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.is_available.return_value = True
        mock_qdrant.query.return_value = []  # empty — not yet projected

        service = SearchService(self.repo, mock_qdrant, score_threshold=0.5)

        # Override pending metrics to simulate staleness
        with patch.object(self.repo, 'oldest_pending_age_seconds', return_value=15):
            with patch.object(self.repo, 'pending_outbox_count', return_value=100):
                result = service.search(query="test", namespace="freshness", limit=5)

        self.assertEqual(
            result.search_mode, "fts_sqlite",
            f"Expected fts_sqlite when Qdrant is stale, got {result.search_mode}"
        )
        self.assertTrue(result.degraded)
        self.assertEqual(result.freshness_seconds, 15)

    def test_search_uses_hybrid_when_qdrant_fresh(self) -> None:
        """When Qdrant is fresh (oldest_pending < threshold), use hybrid mode."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        record = self.repo.create_memory(
            content="fresh qdrant test",
            type="test", namespace="fresh", scope_id="s1", source="test",
        )

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.is_available.return_value = True
        mock_qdrant.query.return_value = [
            SearchHit(id=record.id, score=0.9, payload={})
        ]

        service = SearchService(self.repo, mock_qdrant, score_threshold=0.5)

        with patch.object(self.repo, 'oldest_pending_age_seconds', return_value=2):
            with patch.object(self.repo, 'pending_outbox_count', return_value=5):
                result = service.search(query="test", namespace="fresh", limit=5)

        self.assertEqual(result.search_mode, "hybrid", f"Expected hybrid, got {result.search_mode}")
        self.assertFalse(result.degraded)
        self.assertEqual(result.freshness_seconds, 2)

    def test_search_falls_back_when_qdrant_unavailable(self) -> None:
        """When Qdrant is not available, use fallback_sqlite."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        record = self.repo.create_memory(
            content="unavailable qdrant test",
            type="test", namespace="unavailable", scope_id="s1", source="test",
        )

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.is_available.return_value = False
        mock_qdrant.enabled = True  # qdrant is enabled but unreachable

        service = SearchService(self.repo, mock_qdrant, score_threshold=0.5)

        with patch.object(self.repo, 'oldest_pending_age_seconds', return_value=0):
            with patch.object(self.repo, 'pending_outbox_count', return_value=0):
                result = service.search(query="test", namespace="unavailable", limit=5)

        self.assertEqual(result.search_mode, "fts_sqlite")
        # degraded is True because qdrant is enabled but unreachable
        self.assertTrue(result.degraded)
        self.assertEqual(result.freshness_seconds, 0)

    def test_freshness_threshold_is_10_seconds(self) -> None:
        """The staleness threshold should be 10 seconds."""
        self.assertEqual(QRANT_STALENESS_THRESHOLD_SECONDS, 10)

    def test_qdrant_freshness_returns_zero_when_no_pending_events(self) -> None:
        """_qdrant_freshness_seconds should return 0 when queue is empty."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.is_available.return_value = True

        service = SearchService(self.repo, mock_qdrant)

        with patch.object(self.repo, 'pending_outbox_count', return_value=0):
            freshness = service._qdrant_freshness_seconds()

        self.assertEqual(freshness, 0)


if __name__ == "__main__":
    unittest.main()