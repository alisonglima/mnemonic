# Data Flow

## Write path

```
HTTP Request (MCP tool call)
  └── MemoryTools.<operation>()       [serial, blocking]
        └── MemoryRepository.<db_op>()   [SQLite write, transaction]
        └── OutboxWorker.process_pending()  [async, background thread]
              └── for each outbox event:
                    └── QdrantProjectionStore.upsert()   [if event is project_qdrant]
                    └── ObsidianProjectionStore.materialize_journal()  [if event is project_obsidian]
              └── on error: reschedule with backoff (max 300s)

Response returned to MCP client immediately after SQLite commit.
```

The background thread is started by `main.py` when `--serve` is given. It polls the outbox table every second and processes due events.

## Search path

```
HTTP Request (memory.search)
  └── MemoryTools.search()
        └── SearchService.search()
              ├── if include_retracted=True:
              │     └── MemoryRepository.search_records()   [SQLite only, return]
              ├── QdrantProjectionStore.is_available()?
              │     ├── yes, fresh: QdrantProjectionStore.query()  [approximate similarity lookup]
              │     │                     + MemoryRepository.search_records()
              │     │                     → search_mode: "hybrid"
              │     └── yes, stale (>10s) OR unavailable:
              │                     └── MemoryRepository.search_fts()  [FTS5 BM25 keyword search]
              │                     → search_mode: "fts_sqlite", degraded: true
              └── MemoryRepository.search_records()         [SQLite text search, fallback]
              └── merge results by id, respecting limit
              └── return SearchResult(search_mode, degraded, freshness_seconds)
```

### Search modes

| Mode | Condition | Degraded |
|------|-----------|----------|
| `hybrid` | Qdrant available and fresh (<10s staleness) | `false` |
| `fts_sqlite` | Qdrant unavailable or stale (>10s behind) | `true` |
| `fallback_sqlite` | Query has status/date filters or offset > 0 | `false` |

### FTS5 fallback

FTS5 provides BM25-ranked full-text search over record content and tags. It is used automatically when the outbox worker falls behind (>10s). The FTS5 index is synced on every write via `_sync_fts()`. Run `scripts/rebuild_fts.py` to backfill after bulk operations.

## Projection versioning

Every record mutation increments the record's `version`. The same version number is written to the outbox as `target_version`. When the outbox worker processes an event, it checks:

```
if current_projection_version >= event.target_version:
    skip event (already applied)
else:
    apply projection
    set_projection_version(memory_id, projection, event.target_version)
```

This ensures at-least-once delivery and makes reindexing idempotent.

## Outbox event lifecycle

1. **Created** — `_queue_projection_events()` inserts an event with `available_at = now()`, `processed_at = NULL`, `attempt_count = 0`.
2. **Ready** — `list_due_outbox()` selects events where `available_at <= now()`.
3. **Processing** — `apply_projection_event()` applies the projection and marks `processed_at = now()`.
4. **Error** — on exception, `reschedule_outbox_event()` sets `available_at = now + delay`, increments `attempt_count`, and stores the error.
5. **Retry delay** — `min(300, max(5, 5 * (attempt_count + 1)))` seconds.

## Health check path

```
HTTP Request (memory.health tool)
  └── HealthService.status()
        ├── sqlite: check database file exists and is readable
        ├── qdrant: GET {qdrant_url}/healthz (1s timeout; returns "down" if URL not set or unreachable)
        ├── ollama: health-checked via /api/tags when OLLAMA_URL is configured; "down" otherwise
        ├── worker: currently hardcoded "up"
        ├── obsidian_projection: check vault path exists
        ├── degraded: true if qdrant unavailable or vault inaccessible
        ├── pending_events: count of unprocessed outbox events
        └── oldest_pending_age_seconds: seconds since oldest pending event
  └── return { sqlite, qdrant, ollama, worker, obsidian_projection, degraded, pending_events, oldest_pending_age_seconds }
```
