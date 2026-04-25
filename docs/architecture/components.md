# Components

## `mcp_memory.main`

**Type:** Module / entrypoint

The CLI entrypoint. Parses `--host`, `--port`, `--serve`. When `--serve` is given, it starts the FastMCP HTTP server and a background outbox worker thread.

```
python -m mcp_memory.main --host 0.0.0.0 --port 8080 --serve
```

Key responsibilities:
- Register all MCP tools with the FastMCP server.
- Start the outbox worker thread.
- Handle graceful shutdown (signal the stop event, join the worker).

## `MemoryTools`

**Type:** Class (`mcp_memory.tools`)

Orchestrates all MCP tool operations. Holds references to `Settings`, `MemoryRepository`, `SearchService`, `QdrantProjectionStore`, `ObsidianProjectionStore`, `OutboxWorker`, and `HealthService`.

Every tool method calls through to `MemoryRepository` for the SQLite write, then triggers `OutboxWorker.process_pending()` to dispatch async projection events.

## `MemoryRepository`

**Type:** Class (`mcp_memory.repository`)

SQLite access layer and source-of-truth abstraction.

Key methods:
- `create_memory` / `get_memory` / `update_memory` / `archive_memory` / `retract_memory` / `delete_memory`
- `add_tags` / `remove_tags` / `append_note`
- `search_records` — SQLite full-text search with filters
- `list_due_outbox` / `mark_outbox_processed` / `reschedule_outbox_event`
- `set_projection_version` / `set_projection_error`
- `_hash_content` — SHA-256 content hash used for idempotency and vector projection

## `SearchService`

**Type:** Class (`mcp_memory.search`)

Coordinates hybrid search. Takes `repository` and `qdrant_store`. If Qdrant is unavailable or `include_retracted=True`, falls back to SQLite-only. Otherwise merges Qdrant vector hits with SQLite results by record ID.

## `QdrantProjectionStore`

**Type:** Class (`mcp_memory.qdrant_store`)

Manages the Qdrant collection.

- `is_available()` — checks Qdrant connectivity
- `ensure_collection()` — creates collection if missing
- `upsert(record)` — writes a record as a vector point (8-dim SHA-256 hash of content)
- `delete(memory_id)` — removes a point
- `query(...)` — searches the collection

**Vector strategy:** Deterministic SHA-256 hash projection via `simple_embed()`. Not a semantic embedding model. Provides rough similarity grouping.

The embedder uses the first 8 bytes of the SHA-256 digest of the lowercased content, normalized to `[-1, 1]`.

## `ObsidianProjectionStore`

**Type:** Class (`mcp_memory.obsidian_store`)

Projects memory records to Markdown files in a local vault.

- `materialize_journal(record)` — writes `{vault_path}/{record.id}.md` with YAML frontmatter and record content

## `OutboxWorker`

**Type:** Class (`mcp_memory.outbox`)

Background worker that processes pending projection events.

- `run_forever(stop_event, poll_interval_seconds=1.0)` — main loop
- `process_pending()` — processes all due outbox events
- `_project_qdrant(event)` — upserts to Qdrant or deletes if record is retracted/deleted
- `_project_obsidian(event)` — writes Markdown to vault

## `HealthService`

**Type:** Class (via `mcp_memory.health`)

Returns system status for `memory.health`:
- `sqlite` — SQLite file exists
- `qdrant` — Qdrant `/healthz` returns 2xx
- `ollama` — currently reported as `down`; Ollama is configured but not used by runtime logic
- `worker` — outbox worker status
- `obsidian_projection` — Obsidian vault path exists
- `degraded` — true when Qdrant or Obsidian projection is unavailable
- `pending_events` — count of unprocessed outbox events
- `oldest_pending_age_seconds` — age of the oldest pending event

## Database schema (SQLite)

Key tables:
- `memory_records` — primary record table
- `memory_revisions` — immutable revision log
- `memory_outbox` — pending projection events
- `memory_projections` — per-projection sync state
