# Architecture Overview

Mnemonic is a local-first AI memory server. It stores structured memory records in SQLite, projects records to Qdrant for approximate similarity search, projects journal/queued Obsidian records to Markdown, and exposes memory tools via an MCP HTTP server.

## Core principles

1. **SQLite is the source of truth.** Every record, version, and tag lives in SQLite. Qdrant and Obsidian are projections only.
2. **Async projection via outbox.** Qdrant projections and opt-in Obsidian projections are handled by an asynchronous outbox worker that runs in a background thread. MCP tool calls do not block on projection completion.
3. **Optimistic concurrency.** Every mutation requires the expected version of the record. Conflicting writes return a version conflict error rather than silently overwriting.
4. **Degraded mode.** If Qdrant is unavailable, search falls back to SQLite-only mode without interrupting service.

## Component layers

```
┌──────────────────────────────────────────────────────────────┐
│                     MCP HTTP Server                          │
│                  (FastMCP + mcp_memory.main)                 │
└──────────────────────────┬───────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │  SQLite  │  │  Qdrant  │  │ Obsidian │
        │ (source) │  │ (vector) │  │  (vault) │
        └──────────┘  └──────────┘  └──────────┘
```

## Component responsibilities

| Component | Responsibility |
|---|---|
| `mcp_memory.main` | FastMCP HTTP server entrypoint. Parses CLI args, builds the tool registry, runs the server and the outbox worker thread. |
| `MemoryTools` | Orchestrates repository, search service, and projection stores. Every MCP tool delegates here. |
| `MemoryRepository` | SQLite access layer. All record CRUD, revision tracking, outbox management. |
| `SearchService` | Coordinates Qdrant vector search with SQLite filtering. Returns merged, deduplicated results. |
| `QdrantProjectionStore` | Manages the Qdrant collection: upsert, delete, query. Uses Ollama `nomic-embed-text` (768-dim) when `EMBEDDING_STRATEGY=ollama`; falls back to deterministic SHA-256 hash projections (8-dim) when Ollama is unavailable. |
| `ObsidianProjectionStore` | Writes Markdown files to the vault path. |
| `OutboxWorker` | Background thread that processes pending projection events from SQLite outbox table. |

## Data flow

### Write

```
MCP tool call → MemoryTools.write()
  → MemoryRepository.create_memory()   [SQLite]
  → OutboxWorker.process_pending()     [Qdrant async; Obsidian only when queued]
```

The tool returns immediately after the SQLite write. The outbox worker processes Qdrant projection events and any queued Obsidian projection events in a background thread, retrying with exponential backoff on failure. The MCP `memory.journal` path queues Obsidian projection; plain `memory.write` does not expose an Obsidian projection flag.

### Search

```
MCP tool call → MemoryTools.search()
  → SearchService.search()
    → QdrantProjectionStore.query()     [if Qdrant available]
    → MemoryRepository.search_records() [SQLite]
    → merge + deduplicate by id
```

If Qdrant is unavailable, the search falls back to SQLite-only mode and returns `degraded: true`.

## Version history

Every mutation creates a revision row in `memory_revisions`. The current version number is stored on the record. Mutating operations (`update`, `retract`, `delete`) require `expected_version` to prevent silent overwrites.

## Projection state

`memory_projections` tracks sync status for each projection backend (Qdrant, Obsidian). It records the last synced version and any errors encountered during projection.
