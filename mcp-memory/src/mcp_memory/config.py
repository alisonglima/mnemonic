from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    database_path: Path
    vault_path: Path
    mcp_port: int = 8080
    qdrant_url: str = ""
    qdrant_collection: str = "memory_records"
    ollama_url: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.getenv("SQLITE_PATH", "./memory.db")),
            vault_path=Path(os.getenv("OBSIDIAN_VAULT", "./obsidian-vault")),
            mcp_port=int(os.getenv("MCP_PORT", "8080")),
            qdrant_url=os.getenv("QDRANT_URL", ""),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "memory_records"),
            ollama_url=os.getenv("OLLAMA_URL", ""),
        )
