from __future__ import annotations

from mcp_memory.config import Settings
from mcp_memory.database import Database
from mcp_memory.embedding import EmbeddingConfig, create_embedding_provider
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository


def main() -> int:
    settings = Settings.from_env()
    db = Database(settings.database_path)
    db.initialize()
    repository = MemoryRepository(db)

    # Create embedding configuration and provider
    embedding_config = EmbeddingConfig(
        ollama_url=settings.ollama_url,
        embedding_model=settings.embedding_model,
        embedding_strategy=settings.embedding_strategy,
    )
    embedding_provider = create_embedding_provider(embedding_config)

    qdrant = QdrantProjectionStore(
        enabled=bool(settings.qdrant_url),
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        embedding_provider=embedding_provider,
        vector_strategy=settings.embedding_strategy,
    )
    if not qdrant.enabled:
        return 0
    for record in repository.list_records():
        if record.status in {"active", "archived"}:
            qdrant.upsert(record)
            repository.set_projection_version(record.id, "qdrant", record.version)
        else:
            qdrant.delete(record.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
