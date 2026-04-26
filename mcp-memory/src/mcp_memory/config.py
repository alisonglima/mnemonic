from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class Settings(BaseModel):
    database_path: Path
    vault_path: Path
    mcp_port: int = 8080
    qdrant_url: str = ""
    qdrant_collection: str = "memory_records"
    ollama_url: str = ""

    # Embedding configuration
    embedding_strategy: Literal["hash", "ollama"] = "hash"
    embedding_model: str = "nomic-embed-text"
    embedding_size: int = 768  # Vector dimensions (768 for nomic-embed-text)

    # Search configuration
    search_score_threshold: float = 0.5  # min cosine similarity to include Qdrant hit

    # Namespace and retention configuration
    default_namespace: str = ""
    retention_action: Literal["archive", "none"] = "archive"
    retention_days: int = 30

    # Outbox worker configuration
    outbox_max_workers: int = 4

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.getenv("SQLITE_PATH", "./data/memory.db")),
            vault_path=Path(os.getenv("OBSIDIAN_VAULT", "./obsidian-vault")),
            mcp_port=int(os.getenv("MCP_PORT", "8080")),
            qdrant_url=os.getenv("QDRANT_URL", ""),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "memory_records"),
            ollama_url=os.getenv("OLLAMA_URL", ""),
            embedding_strategy=os.getenv("EMBEDDING_STRATEGY", "hash"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
            embedding_size=int(os.getenv("EMBEDDING_SIZE", "768")),
            search_score_threshold=float(os.getenv("SEARCH_SCORE_THRESHOLD", "0.5")),
            default_namespace=os.getenv("DEFAULT_NAMESPACE", ""),
            retention_action=os.getenv("RETENTION_ACTION", "archive"),
            retention_days=int(os.getenv("RETENTION_DAYS", "30")),
            outbox_max_workers=int(os.getenv("OUTBOX_MAX_WORKERS", "4")),
        )
