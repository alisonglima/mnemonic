from __future__ import annotations

from collections import OrderedDict
from typing import List, Optional

from mcp_memory.models import MemoryRecord, SearchResult
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository


# Freshness threshold in seconds — if Qdrant projection is older than this, use SQLite fallback
QRANT_STALENESS_THRESHOLD_SECONDS = 10


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

    def _qdrant_freshness_seconds(self) -> int:
        """Return how many seconds the oldest pending outbox event has been waiting.

        Returns 0 if no pending events (Qdrant is fully caught up).
        """
        count = self.repository.pending_outbox_count()
        if count == 0:
            return 0
        return self.repository.oldest_pending_age_seconds()

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
        freshness_seconds = self._qdrant_freshness_seconds()
        qdrant_stale = freshness_seconds > QRANT_STALENESS_THRESHOLD_SECONDS

        # Always use SQLite as the authoritative source for results
        items = self.repository.search_records(
            query=query, namespace=namespace, scope_id=scope_id, types=types,
            include_archived=include_archived, include_retracted=False,
            limit=limit, offset=offset,
        )

        if not qdrant_available or qdrant_stale:
            # Qdrant unavailable or too stale — use FTS5 for better full-text search
            fts_ids = self.repository.search_fts(query=query, namespace=namespace, limit=limit * 3)
            merged: "OrderedDict[str, MemoryRecord]" = OrderedDict()
            for memory_id in fts_ids:
                record = self.repository.get_memory(memory_id)
                if record and record.status in {"active", "archived"}:
                    merged[record.id] = record
            degraded = qdrant_stale or (not qdrant_available and self.qdrant_store.enabled)
            return SearchResult(
                items=list(merged.values())[:limit],
                search_mode="fts_sqlite",
                degraded=degraded,
                freshness_seconds=freshness_seconds,
            )

        # Qdrant is available and fresh — use hybrid merge
        qdrant_hits = self.qdrant_store.query(
            query=query,
            namespace=namespace,
            scope_id=scope_id,
            types=types,
            include_archived=include_archived,
            limit=limit,
            score_threshold=self.score_threshold,
        )

        merged: "OrderedDict[str, MemoryRecord]" = OrderedDict()
        for hit in qdrant_hits:
            record = self.repository.get_memory(hit.id)
            if record is not None:
                merged[record.id] = record
        for record in items:
            merged.setdefault(record.id, record)
        return SearchResult(
            items=list(merged.values())[:limit],
            search_mode="hybrid",
            degraded=False,
            freshness_seconds=freshness_seconds,
        )