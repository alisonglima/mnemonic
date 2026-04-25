# Configuration

Mnemonic is configured entirely through environment variables. Copy `.env.example` to `.env` and adjust as needed.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MCP_PORT` | `8080` | HTTP port the MCP server listens on |
| `SQLITE_PATH` | `./data/memory.db` | Path to the SQLite database file (source of truth) |
| `OBSIDIAN_VAULT` | `./obsidian-vault` | Path to the Obsidian vault directory for Markdown projections |
| `QDRANT_URL` | _(empty)_ | URL of the Qdrant instance (e.g. `http://localhost:6333`). Empty means vector projections are disabled. |
| `QDRANT_COLLECTION` | `memory_records` | Name of the Qdrant collection used for memory records |
| `OLLAMA_URL` | _(empty)_ | URL of an Ollama instance. Reserved for future local-model workflows. Currently not used by the projection logic. |

## Path expectations

- `SQLITE_PATH` must be writable. The parent directory is created automatically when running `make run`.
- `OBSIDIAN_VAULT` must be writable. It is created automatically if it does not exist.

## Qdrant vector projections

Vector projections are **deterministic SHA-256 hash projections** (8-dim). They are lightweight approximations, not true semantic embeddings. No external model is required.

When `QDRANT_URL` is empty or Qdrant is unreachable, the MCP server degrades gracefully to SQLite-only search.

## Ollama health check

`OLLAMA_URL` is configured in the environment but is **not currently used by the runtime logic**. It exists to support future local-model vector workflows. No embedding behavior activates based on this variable today.

## Applying changes

Restart the MCP server after changing environment variables. For docker-compose, run:

```bash
docker compose down && docker compose up --build
```

For local development, stop the server with Ctrl+C and restart with `make run`.
