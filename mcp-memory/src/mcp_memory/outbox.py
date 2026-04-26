from __future__ import annotations

import threading
import time
from typing import Callable

from mcp_memory.models import OutboxEvent
from mcp_memory.obsidian_store import ObsidianProjectionStore
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository


class OutboxWorker:
    def __init__(
        self,
        repository: MemoryRepository,
        qdrant_store: QdrantProjectionStore = None,
        obsidian_store: ObsidianProjectionStore = None,
    ):
        self.repository = repository
        self.qdrant_store = qdrant_store or QdrantProjectionStore(enabled=False)
        self.obsidian_store = obsidian_store

    def record_projection_version(self, memory_id: str, projection: str, version: int) -> None:
        self.repository.set_projection_version(memory_id, projection, version)

    def apply_projection_event(self, event: OutboxEvent, handler: Callable[[OutboxEvent], None]) -> bool:
        projection = "qdrant" if "qdrant" in event.event_type else "obsidian"
        current_version = self.repository.get_projection_version(event.memory_id, projection)
        if current_version >= event.target_version:
            self.repository.mark_outbox_processed(event.id)
            return False
        handler(event)
        self.repository.set_projection_version(event.memory_id, projection, event.target_version)
        self.repository.mark_outbox_processed(event.id)
        return True

    def process_pending(self) -> None:
        for event in self.repository.list_due_outbox():
            try:
                self.apply_projection_event(event, self._handler_for(event))
            except Exception as exc:  # noqa: BLE001
                projection = "qdrant" if "qdrant" in event.event_type else "obsidian"
                self.repository.set_projection_error(event.memory_id, projection, str(exc))
                delay_seconds = min(300, max(5, 5 * (event.attempt_count + 1)))
                self.repository.reschedule_outbox_event(event.id, delay_seconds=delay_seconds, error=str(exc))

    def run_forever(self, stop_event: threading.Event, poll_interval_seconds: float = 1.0) -> None:
        while not stop_event.is_set():
            self.process_pending()
            stop_event.wait(poll_interval_seconds)

    def _handler_for(self, event: OutboxEvent) -> Callable[[OutboxEvent], None]:
        if event.event_type == "project_obsidian":
            return self._project_obsidian
        return self._project_qdrant

    def _project_qdrant(self, event: OutboxEvent) -> None:
        if not self.qdrant_store.enabled:
            raise RuntimeError("qdrant unavailable")
        record = self.repository.get_memory(event.memory_id)
        if record is None:
            return
        if record.status in {"active", "archived"}:
            # A newer pending event means the record will change again soon.
            # Skip the embedding to avoid wasting CPU on a state that will be superseded.
            if self.repository.has_newer_pending_outbox_event(event.memory_id, event.target_version):
                return
            self.qdrant_store.upsert(record)
        else:
            self.qdrant_store.delete(record.id)

    def _project_obsidian(self, event: OutboxEvent) -> None:
        if self.obsidian_store is None:
            return
        record = self.repository.get_memory(event.memory_id)
        if record is None:
            return
        if record.obsidian_projection and record.status != "deleted":
            self.obsidian_store.materialize_journal(record)
