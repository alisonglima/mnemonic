from __future__ import annotations

from pathlib import Path
from typing import Dict

from mcp_memory.config import Settings
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository


class HealthService:
    def __init__(self, settings: Settings, repository: MemoryRepository, qdrant_store: QdrantProjectionStore):
        self.settings = settings
        self.repository = repository
        self.qdrant_store = qdrant_store

    def status(self) -> Dict[str, object]:
        sqlite_up = self.settings.database_path.exists()
        vault_up = Path(self.settings.vault_path).exists()
        qdrant_status = self.qdrant_store.health()
        return {
            "sqlite": "up" if sqlite_up else "down",
            "qdrant": qdrant_status,
            "ollama": "down",
            "worker": "up",
            "obsidian_projection": "up" if vault_up else "down",
            "degraded": qdrant_status != "up" or not vault_up,
            "pending_events": self.repository.pending_outbox_count(),
            "oldest_pending_age_seconds": self.repository.oldest_pending_age_seconds(),
        }
