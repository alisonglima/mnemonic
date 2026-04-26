# Reindexing

Reindexing rebuilds the Qdrant vector index and Obsidian vault from the SQLite source of truth. Use this after bulk operations, data corruption, or when setting up a new Qdrant instance.

## When to reindex

- After bulk importing records directly into the SQLite database
- After Qdrant data loss or corruption
- After Obsidian vault deletion
- When deploying to a new environment with existing data

## Run reindex

```bash
make reindex
```

This runs two scripts in sequence:

1. `rebuild_qdrant.py` — reads all active/archived records from SQLite and upserts them into Qdrant, then marks them as synced.
2. `rebuild_obsidian.py` — reads all records with `obsidian_projection=True` and re-materializes their Markdown files in the vault.

## Partial reindex

To rebuild only one projection layer:

```bash
PYTHONPATH=mcp-memory/src python3 mcp-memory/scripts/rebuild_qdrant.py
PYTHONPATH=mcp-memory/src python3 mcp-memory/scripts/rebuild_obsidian.py
```

## What gets projected

### Qdrant (`rebuild_qdrant.py`)

- Records with `status = active` or `status = archived` → upserted into Qdrant
- Records with `status = retracted` or `status = deleted` → deleted from Qdrant

### Obsidian (`rebuild_obsidian.py`)

- Records with `obsidian_projection = True` and `status != deleted` → written as `.md` files
- Records with `status = deleted` are skipped (stale `.md` files from deleted records remain; remove manually if needed)

## Idempotency

Both scripts are idempotent. Running them multiple times is safe. They update the `memory_projections` table so subsequent runs skip already-synced records.

## FTS5 full-text search index

Mnemonic maintains an FTS5 virtual table (`memory_fts`) for keyword search. This is used automatically when Qdrant is unavailable or stale (>10s behind).

```bash
PYTHONPATH=mcp-memory/src python3 mcp-memory/scripts/rebuild_fts.py
```

For Docker:
```bash
docker compose exec mcp-memory python mcp-memory/scripts/rebuild_fts.py
```