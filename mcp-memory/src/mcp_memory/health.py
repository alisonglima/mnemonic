from __future__ import annotations

from pathlib import Path
from typing import Dict
from urllib.request import urlopen

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
        ollama_status = self._ollama_status()
        vector_strategy = self.settings.embedding_strategy
        embedding_degraded = ollama_status == "down" and vector_strategy == "ollama"
        return {
            "sqlite": "up" if sqlite_up else "down",
            "qdrant": qdrant_status,
            "ollama": ollama_status,
            "worker": "up",
            "obsidian_projection": "up" if vault_up else "down",
            "degraded": qdrant_status != "up" or not vault_up,
            "vector_strategy": vector_strategy,
            "embedding_degraded": embedding_degraded,
            "pending_events": self.repository.pending_outbox_count(),
            "oldest_pending_age_seconds": self.repository.oldest_pending_age_seconds(),
        }

    def _ollama_status(self) -> str:
        if not self.settings.ollama_url:
            return "down"
        try:
            with urlopen(f"{self.settings.ollama_url}/api/tags", timeout=1) as resp:
                if 200 <= resp.status < 300:
                    return "up"
                return "down"
        except Exception:  # noqa: BLE001
            return "down"
