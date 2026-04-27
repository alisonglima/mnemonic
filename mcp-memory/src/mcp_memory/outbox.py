from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

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
        max_workers: int = 4,
    ):
        self.repository = repository
        self.qdrant_store = qdrant_store or QdrantProjectionStore(enabled=False)
        self.obsidian_store = obsidian_store
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="outbox-"
        )
        if qdrant_store and hasattr(qdrant_store, "_embedding_provider"):
            self._embedder = qdrant_store._embedding_provider.embed
        else:
            self._embedder = None

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
        events = self.repository.list_due_outbox()
        if not events:
            return
        futures = []
        for event in events:
            futures.append(self._executor.submit(self._process_single, event))
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception:  # noqa: BLE001
                pass  # Errors are already recorded inside _process_single

    def _process_single(self, event: OutboxEvent) -> None:
        try:
            self.apply_projection_event(event, self._handler_for(event))
        except Exception as exc:  # noqa: BLE001
            projection = "qdrant" if "qdrant" in event.event_type else "obsidian"
            self.repository.set_projection_error(event.memory_id, projection, str(exc))
            delay_seconds = min(300, max(5, 5 * (event.attempt_count + 1)))
            self.repository.reschedule_outbox_event(event.id, delay_seconds=delay_seconds, error=str(exc))

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def run_forever(
        self,
        stop_event: threading.Event,
        poll_interval_seconds: float = 1.0,
        checkpoint_interval_seconds: float = 30.0,
    ) -> None:
        """Run outbox processing loop with periodic WAL checkpointing.

        Note: Checkpoint interval is best-effort — checked after process_pending()
        returns. With a large backlog the gap between checkpoints can exceed
        checkpoint_interval_seconds. This is safe: WAL grows but writes continue.
        """
        last_checkpoint_at = time.monotonic()
        while not stop_event.is_set():
            self.process_pending()
            now = time.monotonic()
            if now - last_checkpoint_at >= checkpoint_interval_seconds:
                try:
                    self.repository.database.run_wal_checkpoint()
                except Exception:
                    logger.warning("WAL checkpoint failed", exc_info=True)
                last_checkpoint_at = now
            stop_event.wait(poll_interval_seconds)

    def _handler_for(self, event: OutboxEvent) -> Callable[[OutboxEvent], None]:
        if event.event_type == "project_obsidian":
            return self._project_obsidian
        return self._project_qdrant

    def _project_qdrant(self, event: OutboxEvent) -> None:
        if not self.qdrant_store.enabled:
            raise RuntimeError("qdrant unavailable")
        if self._embedder is None:
            raise RuntimeError("no embedder configured — set embedder on qdrant_store or OutboxWorker")
        record = self.repository.get_memory(event.memory_id)
        if record is None:
            return

        if record.status not in {"active", "archived"}:
            self.qdrant_store.delete(record.id)
            self.repository.mark_outbox_processed(event.id)
            return

        if self.repository.has_newer_pending_outbox_event(event.memory_id, event.target_version):
            return

        proj_state = self.repository.get_projection_state(event.memory_id)
        fingerprint = self._embedding_fingerprint()

        if (proj_state["qdrant_content_hash"] == record.content_hash and
            proj_state["qdrant_embedding_fingerprint"] == fingerprint):
            self.repository.mark_outbox_processed(event.id)
            return

        try:
            vector = self._embedder(record.content)
            self.qdrant_store.upsert_with_vector(record, vector)
            self.repository.update_projection_state(
                event.memory_id,
                qdrant_version=event.target_version,
                qdrant_content_hash=record.content_hash,
                qdrant_embedding_fingerprint=fingerprint,
                qdrant_status="ready",
                last_error=None,
            )
            self.repository.mark_outbox_processed(event.id)
        except Exception as exc:
            self.repository.update_projection_state(
                event.memory_id,
                qdrant_status="error",
                last_error=str(exc),
            )
            raise

    def _embedding_fingerprint(self) -> str:
        prov = getattr(self.qdrant_store, "_embedding_provider", None)
        if prov is not None:
            name = getattr(prov, "name", "unknown")
            size = getattr(prov, "size", 0)
            return f"{name}:{size}"
        return "unknown:0"

    def _project_obsidian(self, event: OutboxEvent) -> None:
        if self.obsidian_store is None:
            return
        record = self.repository.get_memory(event.memory_id)
        if record is None:
            return
        if record.obsidian_projection and record.status != "deleted":
            self.obsidian_store.materialize_journal(record)
