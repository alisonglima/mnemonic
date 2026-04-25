from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    database_path: Path
    vault_path: Path
    mcp_port: int = 8080
    qdrant_url: str = ""
    qdrant_collection: str = "memory_records"
    ollama_url: str = ""

    # Embedding configuration
    embedding_strategy: str = "hash"  # "hash" or "ollama"
    embedding_model: str = "nomic-embed-text"

    # Namespace and retention configuration
    default_namespace: str = "default"
    retention_action: str = "delete"  # "delete" or "archive"
    retention_days: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.getenv("SQLITE_PATH", "./memory.db")),
            vault_path=Path(os.getenv("OBSIDIAN_VAULT", "./obsidian-vault")),
            mcp_port=int(os.getenv("MCP_PORT", "8080")),
            qdrant_url=os.getenv("QDRANT_URL", ""),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "memory_records"),
            ollama_url=os.getenv("OLLAMA_URL", ""),
            embedding_strategy=os.getenv("EMBEDDING_STRATEGY", "hash"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
            default_namespace=os.getenv("DEFAULT_NAMESPACE", "default"),
            retention_action=os.getenv("RETENTION_ACTION", "delete"),
            retention_days=int(os.getenv("RETENTION_DAYS", "30")),
        )
