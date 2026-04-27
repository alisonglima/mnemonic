from __future__ import annotations

from collections import OrderedDict
import re
from typing import Dict, List, Optional, Tuple

from mcp_memory.models import MemoryRecord, SearchResult
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository


QDRANT_MIN_COVERAGE_RATIO = 0.80  # Use hybrid_rrf if >=80% of vectors are current


def expand_query(query: str) -> str:
    """Deterministically expand query for FTS5. Returns FTS query string with OR."""
    if not query or not query.strip():
        return query

    expansions = [query]

    # Singular/plural
    if query.endswith('s') and len(query) > 2:
        expansions.append(query[:-1])
    elif not query.endswith('s'):
        expansions.append(query + 's')

    # Common agent synonyms
    synonyms = {
        'db': ['database', 'postgres', 'postgresql'],
        'embed': ['embedding', 'embedded', 'embeddings'],
        'decision': ['adr', 'architecture decision'],
        'mem': ['memory', 'persistent'],
        'config': ['configuration'],
        'auth': ['authentication', 'authorization'],
        'api': ['interface'],
        'python': ['programming', 'script', 'code'],
        'context': ['background', 'history', 'prior', 'session'],
        'search': ['query', 'find', 'retrieve', 'lookup'],
        'write': ['save', 'store', 'create', 'record'],
    }
    query_lower = query.lower()
    for term, syns in synonyms.items():
        if term in query_lower:
            expansions.extend(syns)

    # Path tokenization
    if '/' in query or '_' in query:
        tokens = re.split(r'[/_\-\.]+', query)
        expansions.extend([t for t in tokens if len(t) > 1])

    # Deduplicate
    seen = set()
    unique = []
    for e in expansions:
        if e not in seen:
            seen.add(e)
            unique.append(e)

    # Return FTS OR query string
    return " OR ".join(unique)


def rrf_fusion(
    fts_results: List[Tuple[str, float]],  # (memory_id, bm25_rank)
    vector_ids: List[str],  # memory_ids in rank order
    k: int = 30,
) -> List[str]:
    """Reciprocal Rank Fusion over FTS and vector results.

    Args:
        fts_results: List of (memory_id, bm25_rank) from search_fts
        vector_ids: List of memory_ids from Qdrant (ordered by cosine similarity)
        k: RRF smoothing parameter (default 30)

    Returns:
        List of memory_ids sorted by fused RRF score (descending)
    """

    scores: Dict[str, float] = {}

    # FTS: rank by position (lower bm25 = better, but position matters more)
    for rank, (memory_id, _) in enumerate(fts_results):
        scores[memory_id] = scores.get(memory_id, 0) + 1 / (k + rank)

    # Vector: rank by position
    for rank, memory_id in enumerate(vector_ids):
        scores[memory_id] = scores.get(memory_id, 0) + 1 / (k + rank)

    # Sort by fused score descending
    return sorted(scores.keys(), key=lambda id: scores[id], reverse=True)


class SearchService:
    def __init__(
        self,
        repository: MemoryRepository,
        qdrant_store: Optional[QdrantProjectionStore] = None,
        score_threshold: float = 0.0,
    ):
        self.repository = repository
        self.qdrant_store = qdrant_store or QdrantProjectionStore(enabled=False)
        self.score_threshold = score_threshold

    def _qdrant_is_fresh_enough(
        self,
        namespace: Optional[str] = None,
        scope_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> bool:
        """Return True if Qdrant has sufficient coverage for hybrid search."""
        if not self.qdrant_store.enabled:
            return True
        if not self.qdrant_store.is_available():
            return False
        coverage = self.repository.qdrant_coverage_ratio(
            namespace=namespace, scope_id=scope_id,
            include_archived=include_archived,
        )
        return coverage >= QDRANT_MIN_COVERAGE_RATIO

    def search(
        self,
        *,
        query: str,
        namespace: str,
        scope_id: Optional[str] = None,
        types: Optional[List[str]] = None,
        limit: int = 5,
        include_archived: bool = False,
        include_retracted: bool = False,
        offset: int = 0,
        status: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        updated_after: Optional[str] = None,
        updated_before: Optional[str] = None,
    ) -> SearchResult:
        # When filters are used, always use SQLite
        if status or created_after or created_before or updated_after or updated_before or offset > 0 or include_retracted:
            items = self.repository.search_records(
                query=query, namespace=namespace, scope_id=scope_id, types=types,
                include_archived=include_archived, include_retracted=include_retracted,
                limit=limit, offset=offset, status=status,
                created_after=created_after, created_before=created_before,
                updated_after=updated_after, updated_before=updated_before,
            )
            return SearchResult(items=items, search_mode="fallback_sqlite", degraded=False, freshness_seconds=0)

        qdrant_available = self.qdrant_store.is_available()
        coverage_ok = self._qdrant_is_fresh_enough(
            namespace=namespace, scope_id=scope_id,
            include_archived=include_archived,
        )

        if not qdrant_available or not coverage_ok:
            fts_results = self.repository.search_fts(
                query=query, namespace=namespace, limit=limit * 3,
                scope_id=scope_id, types=types, status=status,
                include_archived=include_archived, expand=True,
            )
            memory_ids = [id for id, _ in fts_results]
            records = [r for r in self.repository.get_memory_bulk(memory_ids) if r is not None]
            return SearchResult(
                items=records[:limit],
                search_mode="fts_sqlite",
                degraded=self.qdrant_store.enabled and (not qdrant_available or not coverage_ok),
                freshness_seconds=0,
            )

        # Hybrid RRF mode
        fts_results = self.repository.search_fts(
            query=query, namespace=namespace, limit=100,
            scope_id=scope_id, types=types, status="active",
            include_archived=include_archived, expand=True,
        )

        vector_hits = self.qdrant_store.query(
            query=query,  # Raw query — qdrant_store.query() embeds it via Ollama before querying Qdrant
            namespace=namespace, scope_id=scope_id,
            types=types, include_archived=include_archived, limit=100,
            score_threshold=self.score_threshold,
        )
        vector_ids = [hit.id for hit in vector_hits]

        # RRF fusion
        fused_ids = rrf_fusion(fts_results, vector_ids, k=30)

        # Bulk hydration
        fused_records = self.repository.get_memory_bulk(fused_ids)
        record_map = {r.id: r for r in fused_records if r is not None}
        # Filter archived records unless explicitly requested
        if not include_archived:
            record_map = {k: v for k, v in record_map.items() if v.status != 'archived'}
        items = [record_map[id] for id in fused_ids if id in record_map][:limit]

        return SearchResult(
            items=items,
            search_mode="hybrid_rrf",
            degraded=False,
            freshness_seconds=0,
        )
