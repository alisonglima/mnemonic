from __future__ import annotations

from collections import OrderedDict
from typing import List, Optional

from mcp_memory.models import MemoryRecord, SearchResult
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository


class SearchService:
    def __init__(self, repository: MemoryRepository, qdrant_store: Optional[QdrantProjectionStore] = None):
        self.repository = repository
        self.qdrant_store = qdrant_store or QdrantProjectionStore(enabled=False)

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
    ) -> SearchResult:
        if include_retracted:
            items = self.repository.search_records(
                query=query,
                namespace=namespace,
                scope_id=scope_id,
                types=types,
                include_archived=include_archived,
                include_retracted=True,
                limit=limit,
            )
            return SearchResult(items=items, search_mode="fallback_sqlite", degraded=False)

        qdrant_available = self.qdrant_store.is_available()
        qdrant_hits = []
        if qdrant_available:
            qdrant_hits = self.qdrant_store.query(
                query=query,
                namespace=namespace,
                scope_id=scope_id,
                types=types,
                include_archived=include_archived,
                limit=limit,
            )
        items = self.repository.search_records(
            query=query,
            namespace=namespace,
            scope_id=scope_id,
            types=types,
            include_archived=include_archived,
            include_retracted=False,
            limit=limit,
        )
        if not qdrant_available:
            return SearchResult(items=items, search_mode="fallback_sqlite", degraded=True)

        merged: "OrderedDict[str, MemoryRecord]" = OrderedDict()
        for hit in qdrant_hits:
            record = self.repository.get_memory(hit.id)
            if record is not None:
                merged[record.id] = record
        for record in items:
            merged.setdefault(record.id, record)
        return SearchResult(items=list(merged.values())[:limit], search_mode="hybrid", degraded=False)
