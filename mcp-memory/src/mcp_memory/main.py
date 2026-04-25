from __future__ import annotations

import argparse
import sys
import threading

from fastmcp import FastMCP
from mcp_memory.config import Settings
from mcp_memory.database import Database
from mcp_memory.embedding import EmbeddingConfig, create_embedding_provider
from mcp_memory.errors import InvalidRequestError, MemoryError, NotFoundError, VersionConflictError
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository
from mcp_memory.search import SearchService
from mcp_memory.tools import MemoryTools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="mcp-memory service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--serve", action="store_true")
    return parser


def build_tools() -> MemoryTools:
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

    qdrant_store = QdrantProjectionStore(
        enabled=bool(settings.qdrant_url),
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        embedding_provider=embedding_provider,
        vector_strategy=settings.embedding_strategy,
    )
    return MemoryTools(settings, repository, SearchService(repository, qdrant_store))


def run_worker(stop_event: threading.Event) -> None:
    tools = build_tools()
    tools.worker.run_forever(stop_event)


def build_mcp_server() -> FastMCP:
    tools = build_tools()
    mcp = FastMCP("memory")

    def safe_call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NotFoundError as exc:
            return {"error": {"code": "not_found", "message": str(exc), "retryable": False}}
        except VersionConflictError as exc:
            return {"error": {"code": "version_conflict", "message": str(exc), "retryable": True}}
        except InvalidRequestError as exc:
            return {"error": {"code": "invalid_request", "message": str(exc), "retryable": False}}
        except MemoryError as exc:
            return {"error": {"code": "internal_error", "message": str(exc), "retryable": False}}
        except Exception as exc:  # noqa: BLE001
            return {"error": {"code": "internal_error", "message": str(exc), "retryable": False}}

    @mcp.tool(name="memory.search")
    def memory_search(query: str, namespace: str, scope_id: str = None, limit: int = 5, include_archived: bool = False, include_retracted: bool = False, offset: int = 0, status: str = None, created_after: str = None, created_before: str = None, updated_after: str = None, updated_before: str = None):
        return safe_call(
            tools.search,
            query=query,
            namespace=namespace,
            scope_id=scope_id,
            limit=limit,
            include_archived=include_archived,
            include_retracted=include_retracted,
            offset=offset,
            status=status,
            created_after=created_after,
            created_before=created_before,
            updated_after=updated_after,
            updated_before=updated_before,
        )

    @mcp.tool(name="memory.get")
    def memory_get(id: str):
        return safe_call(tools.get, id)

    @mcp.tool(name="memory.write")
    def memory_write(content: str, type: str, namespace: str, scope_id: str, source: str, tags: list = None, idempotency_key: str = None, metadata: dict = None):
        return safe_call(
            tools.write,
            content=content,
            type=type,
            namespace=namespace,
            scope_id=scope_id,
            source=source,
            tags=tags,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )

    @mcp.tool(name="memory.health")
    def memory_health():
        return safe_call(tools.health)

    @mcp.tool(name="memory.update")
    def memory_update(id: str, expected_version: int, content: str = None, type: str = None, metadata: dict = None, change_reason: str = "update"):
        return safe_call(
            tools.update,
            id=id,
            expected_version=expected_version,
            content=content,
            type=type,
            metadata=metadata,
            change_reason=change_reason,
        )

    @mcp.tool(name="memory.retract")
    def memory_retract(id: str, expected_version: int, reason: str):
        return safe_call(tools.retract, id, expected_version=expected_version, reason=reason)

    @mcp.tool(name="memory.delete")
    def memory_delete(id: str, expected_version: int, reason: str):
        return safe_call(tools.delete, id, expected_version=expected_version, reason=reason)

    @mcp.tool(name="memory.journal")
    def memory_journal(title: str, content: str, journal_type: str, namespace: str, scope_id: str, source: str, tags: list = None):
        return safe_call(
            tools.journal,
            title=title,
            content=content,
            journal_type=journal_type,
            namespace=namespace,
            scope_id=scope_id,
            source=source,
            tags=tags,
        )

    @mcp.tool(name="memory.archive")
    def memory_archive(id: str, reason: str = None):
        return safe_call(tools.archive, id, reason=reason)

    @mcp.tool(name="memory.add_tags")
    def memory_add_tags(id: str, tags: list):
        return safe_call(tools.add_tags, id, tags)

    @mcp.tool(name="memory.remove_tags")
    def memory_remove_tags(id: str, tags: list):
        return safe_call(tools.remove_tags, id, tags)

    @mcp.tool(name="memory.append_note")
    def memory_append_note(id: str, note: str, source: str):
        return safe_call(tools.append_note, id, note, source)

    @mcp.tool(name="memory.batch_write")
    def memory_batch_write(items: list):
        return safe_call(tools.batch_write, items=items)

    @mcp.tool(name="memory.batch_update_tags")
    def memory_batch_update_tags(updates: list):
        return safe_call(tools.batch_update_tags, updates=updates)

    return mcp


def main() -> int:
    args = build_parser().parse_args()
    if args.serve:
        settings = Settings.from_env()
        print(f"Starting mcp-memory on {args.host}:{args.port}", file=sys.stderr)
        print(f"  SQLite: {settings.database_path}", file=sys.stderr)
        print(f"  Obsidian vault: {settings.vault_path}", file=sys.stderr)
        print(f"  Qdrant: {settings.qdrant_url or 'disabled'}", file=sys.stderr)
        print(f"  Embedding strategy: {settings.embedding_strategy}", file=sys.stderr)
        print(f"  Embedding model: {settings.embedding_model}", file=sys.stderr)
        stop_event = threading.Event()
        worker = threading.Thread(target=run_worker, args=(stop_event,), daemon=True)
        worker.start()
        server = build_mcp_server()
        try:
            server.run(transport="sse", host=args.host, port=args.port)
        finally:
            stop_event.set()
            worker.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
