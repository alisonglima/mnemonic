from __future__ import annotations

from typing import Any, Dict, List, Optional

from mcp_memory.config import Settings
from mcp_memory.errors import NotFoundError
from mcp_memory.health import HealthService
from mcp_memory.obsidian_store import ObsidianProjectionStore
from mcp_memory.outbox import OutboxWorker
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository, _hash_content
from mcp_memory.search import SearchService


class MemoryTools:
    def __init__(self, settings: Settings, repository: MemoryRepository, search_service: SearchService):
        self.settings = settings
        self.repository = repository
        self.search_service = search_service
        self.qdrant_store = getattr(search_service, "qdrant_store", QdrantProjectionStore(enabled=bool(settings.qdrant_url), url=settings.qdrant_url, collection_name=settings.qdrant_collection))
        self.obsidian_store = ObsidianProjectionStore(settings.vault_path)
        self.worker = OutboxWorker(repository, self.qdrant_store, self.obsidian_store)
        self.health_service = HealthService(settings, repository, self.qdrant_store)

    def get(self, memory_id: str) -> Dict[str, Any]:
        record = self.repository.get_memory(memory_id)
        if record is None:
            raise NotFoundError("not_found")
        return {
            "record": record,
            "projection_state": self.repository.get_projection_state(memory_id),
        }

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
    ) -> Dict[str, Any]:
        result = self.search_service.search(
            query=query,
            namespace=namespace,
            scope_id=scope_id,
            types=types,
            limit=limit,
            include_archived=include_archived,
            include_retracted=include_retracted,
        )
        return {
            "items": result.items,
            "search_mode": result.search_mode,
            "degraded": result.degraded,
        }

    def write(
        self,
        *,
        content: str,
        type: str,
        namespace: str,
        scope_id: str,
        source: str,
        tags: Optional[List[str]] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        obsidian_projection: bool = False,
    ) -> Dict[str, Any]:
        existing = self.repository.find_idempotency_match(
            namespace=namespace,
            scope_id=scope_id,
            source=source,
            idempotency_key=idempotency_key,
        )
        if existing:
            mismatch = any(
                [
                    existing.content != content,
                    existing.type != type,
                    (metadata or {}) != existing.metadata,
                ]
            )
            return {
                "record": existing,
                "created": False,
                "payload_mismatch": mismatch,
                "possible_duplicate": False,
                "degraded": True,
            }

        duplicate = self.repository.find_exact_duplicate(
            namespace=namespace,
            scope_id=scope_id,
            content_hash=_hash_content(content),
        )
        record = self.repository.create_memory(
            content=content,
            type=type,
            namespace=namespace,
            scope_id=scope_id,
            source=source,
            tags=tags,
            metadata=metadata,
            idempotency_key=idempotency_key,
            obsidian_projection=obsidian_projection,
        )
        self.worker.process_pending()
        return {
            "record": record,
            "created": True,
            "payload_mismatch": False,
            "possible_duplicate": duplicate is not None,
            "degraded": True,
        }

    def update(
        self,
        *,
        id: str,
        expected_version: int,
        content: Optional[str],
        type: Optional[str],
        metadata: Optional[Dict[str, Any]],
        change_reason: str,
    ) -> Dict[str, Any]:
        record = self.repository.update_memory(
            memory_id=id,
            expected_version=expected_version,
            content=content,
            type=type,
            metadata=metadata,
            change_reason=change_reason,
        )
        self.worker.process_pending()
        return {"record": record}

    def archive(self, id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        record = self.repository.archive_memory(id, reason=reason)
        self.worker.process_pending()
        return {"record": record}

    def retract(self, id: str, *, expected_version: int, reason: str) -> Dict[str, Any]:
        record = self.repository.retract_memory(id, expected_version=expected_version, reason=reason)
        self.worker.process_pending()
        return {"record": record}

    def delete(self, id: str, *, expected_version: int, reason: str) -> Dict[str, Any]:
        record = self.repository.delete_memory(id, expected_version=expected_version, reason=reason)
        self.worker.process_pending()
        return {"record": record}

    def add_tags(self, id: str, tags: List[str]) -> Dict[str, Any]:
        record = self.repository.add_tags(id, tags)
        self.worker.process_pending()
        return {"record": record}

    def remove_tags(self, id: str, tags: List[str]) -> Dict[str, Any]:
        record = self.repository.remove_tags(id, tags)
        self.worker.process_pending()
        return {"record": record}

    def append_note(self, id: str, note: str, source: str) -> Dict[str, Any]:
        record = self.repository.append_note(id, note=note, source=source)
        self.worker.process_pending()
        return {"record": record}

    def journal(
        self,
        *,
        title: str,
        content: str,
        journal_type: str,
        namespace: str,
        scope_id: str,
        source: str,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        body = f"# {title}\n\n{content}"
        return self.write(
            content=body,
            type=journal_type,
            namespace=namespace,
            scope_id=scope_id,
            source=source,
            tags=tags,
            obsidian_projection=True,
        )

    def health(self) -> Dict[str, Any]:
        return self.health_service.status()
