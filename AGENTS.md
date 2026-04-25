# AGENTS.md — Mnemonic Agent Context

This file provides context for AI agents (OpenCode, Claude Code, Codex, and others) working on this codebase.

## Project Structure

```
mcp-memory/
  src/mcp_memory/     # Python package — all runtime code lives here
    config.py         # Settings (pydantic, reads from env vars)
    database.py       # SQLite connection + migration runner
    errors.py         # Domain exceptions: NotFoundError, VersionConflictError, InvalidRequestError
    health.py         # HealthService — status check
    logging.py        # Logging configuration
    migrations.py     # Schema version history
    models.py         # Pydantic models: MemoryRecord, SearchResult, etc.
    repository.py     # CRUD + search on SQLite
    search.py         # SearchService — hybrid SQLite+Qdrant search
    qdrant_store.py   # QdrantProjectionStore — vector projection (optional)
    obsidian_store.py # ObsidianProjectionStore — Markdown projection (optional)
    outbox.py         # OutboxWorker — async projection pipeline
    tools.py          # MemoryTools — business logic called by MCP handlers
    main.py           # FastMCP server, tool registration, CLI entry point
  scripts/            # Maintenance scripts (backup, reindex, rebuild, init_db)
  tests/              # Unit tests
docs/                 # User-facing documentation
```

## Source of Truth Hierarchy

1. **SQLite** — every record, revision, tag, and note lives here. Always authoritative.
2. **Qdrant** — vector projection of SQLite records. Optional. Rebuilt with `make reindex`.
3. **Obsidian vault** — Markdown projection. Optional. Rebuilt with `make reindex`.

Never treat Qdrant or Obsidian files as source of truth. If in doubt, read SQLite.

## How to Run Tests

```bash
make test
# equivalent: PYTHONPATH=mcp-memory/src python3 -m pytest mcp-memory/tests/ -q
```

## make Targets

| Target | What it does |
|---|---|
| `make setup` | Install package in editable mode with dev dependencies |
| `make test` | Run pytest against `mcp-memory/tests/` |
| `make run` | Start MCP server on `127.0.0.1:8080` (reads `.env`) |
| `make docker-up` | `docker compose up -d` |
| `make docker-down` | `docker compose down` |
| `make reindex` | Rebuild Qdrant + Obsidian projections from SQLite |
| `make backup` | Copy SQLite DB to `.backup.db` |
| `make lint` | Python syntax check (py_compile) |
| `make format` | Fix trailing whitespace and missing final newlines |

## Invariants — Never Violate

- **MCP tool names are frozen.** Tools in `main.py` (`memory.search`, `memory.write`, `memory.get`, `memory.update`, `memory.retract`, `memory.delete`, `memory.journal`, `memory.archive`, `memory.add_tags`, `memory.remove_tags`, `memory.append_note`, `memory.health`, `memory.batch_write`, `memory.batch_update_tags`) must not be renamed or have required parameters removed.
- **Env var names are frozen.** `SQLITE_PATH`, `OBSIDIAN_VAULT`, `MCP_PORT`, `QDRANT_URL`, `QDRANT_COLLECTION`, `OLLAMA_URL` must keep their current behavior.
- **`expected_version` is required for mutations.** `memory.update`, `memory.retract`, `memory.delete` all require `expected_version: int` for optimistic concurrency. Do not make this optional.
- **SQLite schema is append-only.** Add new columns in a new migration in `migrations.py`. Never drop or rename columns.
- **Qdrant and Obsidian are projections.** Never make the server fail to start because Qdrant or Obsidian is unavailable. Both must degrade gracefully.

## Internal Patterns

### Settings
All config comes from `Settings.from_env()` in `config.py`. Pass `Settings` through constructors; do not call `os.getenv` directly in business logic.

### Tool registration
Tools are registered in `main.py:build_mcp_server()` using `@mcp.tool(name="memory.<name>")`. Each tool calls `safe_call(tools.<method>, ...)` which converts domain exceptions to structured error dicts.

### Testing fixtures
Tests use `tempfile.TemporaryDirectory` for SQLite and vault paths. See `test_tools.py:_tools()` for the standard fixture pattern.

### Outbox pattern
Writes to Qdrant and Obsidian are async via `OutboxWorker`. After a write, call `worker.process_pending()` to flush in tests. The worker is a background thread in production.
