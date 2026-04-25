# Local Development

This guide covers running Mnemonic outside of Docker on your local machine.

## Prerequisites

- Python >= 3.11
- [`sqlite3`](https://docs.python.org/3/library/sqlite3) (included with Python)

## Install dependencies

```bash
make setup
```

This installs the package in editable mode with all dependencies.

## Configure environment

```bash
cp .env.example .env
```

Default values:

- `MCP_PORT=8080`
- `SQLITE_PATH=./data/memory.db`
- `OBSIDIAN_VAULT=./obsidian-vault`
- `QDRANT_URL=` _(empty — Qdrant is optional; leave empty for SQLite-only mode)_
- `OLLAMA_URL=` _(empty — health-checked when configured; not used for embeddings or projections in current runtime)_

## Initialize the database

```bash
PYTHONPATH=mcp-memory/src python3 mcp-memory/scripts/init_db.py
```

This creates the required SQLite tables. It is safe to run on an existing database.

## Run the MCP server

```bash
make run
```

Or directly:

```bash
PYTHONPATH=mcp-memory/src python3 -m mcp_memory.main --host 127.0.0.1 --port 8080 --serve
```

The server starts on `127.0.0.1:8080`. By default it runs in SQLite-only mode — Qdrant is optional and not required.

## (Optional) Enable Qdrant for approximate similarity search

Qdrant is disabled by default. To enable it:

1. Add a `ports` entry to the `qdrant` service in `docker-compose.yml`:
   ```yaml
   qdrant:
     image: qdrant/qdrant:v1.13.2
     ports:
       - "6333:6333"
   ```
2. Set `QDRANT_URL=http://localhost:6333` in your `.env`.
3. Start Qdrant:
   ```bash
   docker compose up -d qdrant
   ```

## Run tests

```bash
make test
```

This runs the pytest test suite. All tests should pass.

## Available make targets

| Target | Description |
|---|---|
| `make setup` | Install package in editable mode |
| `make test` | Run unit tests |
| `make run` | Start MCP server locally |
| `make reindex` | Rebuild Qdrant and Obsidian indexes (requires Qdrant to be running) |
| `make backup` | Backup SQLite database |
| `make lint` | Syntax-check Python files |
| `make docker-up` | Start all services via docker compose |
| `make docker-down` | Stop docker compose services |