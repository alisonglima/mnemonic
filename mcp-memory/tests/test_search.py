"""Tests for SearchService — coverage indicator and fallback."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp_memory.database import Database
from mcp_memory.models import SearchResult, MemoryRecord, SearchHit
from mcp_memory.outbox import OutboxWorker
from mcp_memory.repository import MemoryRepository
from mcp_memory.search import SearchService, QDRANT_MIN_COVERAGE_RATIO


def _repo(tmp_path: Path) -> MemoryRepository:
    db = Database(tmp_path / "memory.db")
    db.initialize()
    return MemoryRepository(db)


class TestCoverageIndicator(unittest.TestCase):
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


class TestCoverageFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.repo = _repo(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_search_falls_back_to_sqlite_when_coverage_below_threshold(self) -> None:
        """When qdrant_coverage_ratio < threshold, search should use fts_sqlite."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        record = self.repo.create_memory(
            content="low coverage test content",
            type="test", namespace="coverage", scope_id="s1", source="test",
        )

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.enabled = True
        mock_qdrant.is_available.return_value = True
        mock_qdrant.query.return_value = []  # empty — not yet projected

        service = SearchService(self.repo, mock_qdrant, score_threshold=0.5)

        # Simulate low coverage (below 80%)
        with patch.object(self.repo, 'qdrant_coverage_ratio', return_value=0.5):
            result = service.search(query="test", namespace="coverage", limit=5)

        self.assertEqual(
            result.search_mode, "fts_sqlite",
            f"Expected fts_sqlite when coverage is low, got {result.search_mode}"
        )
        self.assertTrue(result.degraded)
        self.assertEqual(result.freshness_seconds, 0)

    def test_search_uses_hybrid_when_coverage_above_threshold(self) -> None:
        """When qdrant_coverage_ratio >= threshold, use hybrid mode."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        record = self.repo.create_memory(
            content="high coverage test",
            type="test", namespace="highcov", scope_id="s1", source="test",
        )

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.enabled = True
        mock_qdrant.is_available.return_value = True
        mock_qdrant.query.return_value = [
            SearchHit(id=record.id, score=0.9, payload={})
        ]

        service = SearchService(self.repo, mock_qdrant, score_threshold=0.5)

        # Simulate high coverage (above 80%)
        with patch.object(self.repo, 'qdrant_coverage_ratio', return_value=0.9):
            result = service.search(query="test", namespace="highcov", limit=5)

        self.assertEqual(result.search_mode, "hybrid_rrf", f"Expected hybrid_rrf, got {result.search_mode}")
        self.assertFalse(result.degraded)
        self.assertEqual(result.freshness_seconds, 0)

    def test_search_falls_back_when_qdrant_unavailable(self) -> None:
        """When Qdrant is not available, use fts_sqlite."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        record = self.repo.create_memory(
            content="unavailable qdrant test",
            type="test", namespace="unavailable", scope_id="s1", source="test",
        )

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.enabled = True  # qdrant is enabled but unreachable
        mock_qdrant.is_available.return_value = False

        service = SearchService(self.repo, mock_qdrant, score_threshold=0.5)

        result = service.search(query="test", namespace="unavailable", limit=5)

        self.assertEqual(result.search_mode, "fts_sqlite")
        # degraded is True because qdrant is enabled but unreachable
        self.assertTrue(result.degraded)
        self.assertEqual(result.freshness_seconds, 0)

    def test_coverage_threshold_is_80_percent(self) -> None:
        """The coverage threshold should be 80 percent."""
        self.assertEqual(QDRANT_MIN_COVERAGE_RATIO, 0.80)

    def test_qdrant_is_fresh_enough_returns_false_when_unavailable(self) -> None:
        """_qdrant_is_fresh_enough should return False when Qdrant is unavailable."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.enabled = True
        mock_qdrant.is_available.return_value = False

        service = SearchService(self.repo, mock_qdrant)

        self.assertFalse(service._qdrant_is_fresh_enough())

    def test_qdrant_is_fresh_enough_returns_true_when_coverage_sufficient(self) -> None:
        """_qdrant_is_fresh_enough should return True when coverage >= threshold."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.enabled = True
        mock_qdrant.is_available.return_value = True

        service = SearchService(self.repo, mock_qdrant)

        with patch.object(self.repo, 'qdrant_coverage_ratio', return_value=0.85):
            self.assertTrue(service._qdrant_is_fresh_enough())

    def test_qdrant_is_fresh_enough_returns_false_when_coverage_insufficient(self) -> None:
        """_qdrant_is_fresh_enough should return False when coverage < threshold."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.enabled = True
        mock_qdrant.is_available.return_value = True

        service = SearchService(self.repo, mock_qdrant)

        with patch.object(self.repo, 'qdrant_coverage_ratio', return_value=0.5):
            self.assertFalse(service._qdrant_is_fresh_enough())

    def test_qdrant_is_fresh_enough_returns_true_when_qdrant_disabled(self) -> None:
        """_qdrant_is_fresh_enough should return True when Qdrant is disabled."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.enabled = False
        mock_qdrant.is_available.return_value = False  # shouldn't be called when disabled

        service = SearchService(self.repo, mock_qdrant)

        # Should return True immediately without checking is_available
        self.assertTrue(service._qdrant_is_fresh_enough())

    def test_search_degraded_false_when_qdrant_disabled(self) -> None:
        """When Qdrant is disabled, search should not be degraded."""
        from mcp_memory.qdrant_store import QdrantProjectionStore

        record = self.repo.create_memory(
            content="disabled qdrant test",
            type="test", namespace="disabled", scope_id="s1", source="test",
        )

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.enabled = False
        mock_qdrant.is_available.return_value = False

        service = SearchService(self.repo, mock_qdrant, score_threshold=0.5)

        result = service.search(query="test", namespace="disabled", limit=5)

        self.assertEqual(result.search_mode, "fts_sqlite")
        self.assertFalse(result.degraded)


if __name__ == "__main__":
    unittest.main()


def test_query_expansion_includes_plural():
    from mcp_memory.search import expand_query
    result = expand_query("dogs")
    terms = [t.strip() for t in result.split(" OR ")]
    assert "dog" in terms  # plural → singular
    assert "dogs" in terms  # original

def test_query_expansion_includes_synonyms():
    from mcp_memory.search import expand_query
    result = expand_query("embed")
    terms = [t.strip() for t in result.split(" OR ")]
    assert "embedding" in terms, f"Expected 'embedding' in terms, got: {terms}"

def test_expand_query_returns_string_for_fts():
    from mcp_memory.search import expand_query
    result = expand_query("postgres")
    assert isinstance(result, str)
    terms = [t.strip() for t in result.split(" OR ")]
    assert "postgres" in terms


def test_rrf_fusion_ranks_both_sources():
    from mcp_memory.search import rrf_fusion
    # FTS results: (memory_id, bm25_rank) — lower rank = better match
    fts_results = [
        ("a", 1.5),
        ("b", 2.3),
        ("c", 3.1),
    ]
    # Vector results: just memory_ids in rank order
    vector_ids = ["b", "d", "e"]
    fused = rrf_fusion(fts_results, vector_ids, k=60)

    # b should be first (present in both, high rank from both)
    assert fused[0] == "b"
    # a and c should follow (only in FTS)
    assert fused[1] in ["a", "c"]


def test_qdrant_coverage_ratio_empty_db():
    """qdrant_coverage_ratio should return 1.0 for empty DB."""
    repo = _repo(Path(tempfile.mkdtemp()))
    ratio = repo.qdrant_coverage_ratio()
    assert ratio == 1.0, f"Expected 1.0 for empty DB, got {ratio}"


def test_hybrid_rrf_uses_zero_score_threshold() -> None:
    """Hybrid RRF must use score_threshold=0.0 regardless of config — RRF handles relevance via rank."""
    from mcp_memory.qdrant_store import QdrantProjectionStore
    from unittest.mock import MagicMock, patch

    captured_threshold = []

    def track_query(**kwargs):
        captured_threshold.append(kwargs.get("score_threshold"))
        return []

    tmpdir = tempfile.TemporaryDirectory()
    try:
        tmp_path = Path(tmpdir.name)
        repo = _repo(tmp_path)

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.enabled = True
        mock_qdrant.is_available.return_value = True
        mock_qdrant.query = track_query

        service = SearchService(repo, qdrant_store=mock_qdrant, score_threshold=0.5)

        with patch.object(repo, 'qdrant_coverage_ratio', return_value=0.9):
            result = service.search(query="test", namespace="ns", limit=5)

        assert captured_threshold, "Qdrant.query must have been called"
        assert captured_threshold[0] == 0.0, (
            f"hybrid_rrf must use score_threshold=0.0, got {captured_threshold[0]}"
        )
        assert result.search_mode == "hybrid_rrf", (
            f"Expected hybrid_rrf search mode, got {result.search_mode}"
        )
    finally:
        tmpdir.cleanup()


def test_non_hybrid_path_respects_score_threshold() -> None:
    """FTS fallback path must still respect the configured score_threshold."""
    from mcp_memory.qdrant_store import QdrantProjectionStore
    from unittest.mock import MagicMock

    captured_threshold = []

    def track_query(**kwargs):
        captured_threshold.append(kwargs.get("score_threshold"))
        return []

    tmpdir = tempfile.TemporaryDirectory()
    try:
        tmp_path = Path(tmpdir.name)
        repo = _repo(tmp_path)

        mock_qdrant = MagicMock(spec=QdrantProjectionStore)
        mock_qdrant.enabled = True
        mock_qdrant.is_available.return_value = True
        mock_qdrant.query = track_query

        # Create a record without projecting it → namespace has 1 unindexed record →
        # coverage_ratio drops to 0.0, forcing FTS fallback.
        repo.create_memory(
            content="unindexed record",
            type="test", namespace="ns", scope_id="s", source="test",
        )

        service = SearchService(repo, qdrant_store=mock_qdrant, score_threshold=0.5)

        result = service.search(query="test", namespace="ns", limit=5)

        # Qdrant.query should NOT have been called (FTS path doesn't call Qdrant)
        assert len(captured_threshold) == 0, (
            f"FTS fallback must not call Qdrant.query, got {len(captured_threshold)} calls"
        )
        assert result.search_mode == "fts_sqlite", (
            f"Expected fts_sqlite search mode, got {result.search_mode}"
        )
    finally:
        tmpdir.cleanup()
