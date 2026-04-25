# CLI and Scripts

## MCP server

### Start the server

```bash
python -m mcp_memory.main --host 0.0.0.0 --port 8080 --serve
```

With `make run` (respects `MCP_PORT` from environment):

```bash
make run
```

### CLI arguments

| Argument | Default | Description |
|---|---|---|
| `--host` | `0.0.0.0` | Interface to bind to |
| `--port` | `8080` | TCP port |
| `--serve` | _(required)_ | Must be present to start the HTTP server |

## Maintenance scripts

All scripts are in `mcp-memory/scripts/` and are run with `PYTHONPATH=mcp-memory/src`.

### Rebuild Qdrant index

```bash
make reindex
# or directly:
PYTHONPATH=mcp-memory/src python3 mcp-memory/scripts/rebuild_qdrant.py
```

Reads all active and archived records from SQLite and upserts them into Qdrant. Skips retracted/deleted records.

### Rebuild Obsidian vault

```bash
PYTHONPATH=mcp-memory/src python3 mcp-memory/scripts/rebuild_obsidian.py
```

Re-materializes all records with `obsidian_projection=True` as Markdown files in the vault directory.

### Backup SQLite

```bash
make backup
# or directly:
PYTHONPATH=mcp-memory/src python3 mcp-memory/scripts/backup_sqlite.py
```

Copies `SQLITE_PATH` to the same path with its suffix replaced by `.backup.db` (`./data/memory.db` → `./data/memory.backup.db`).

### Initialize database

```bash
PYTHONPATH=mcp-memory/src python3 mcp-memory/scripts/init_db.py
```

Creates required SQLite tables. Safe to run on existing databases (uses `CREATE TABLE IF NOT EXISTS`).

## Make targets

| Target | Description |
|---|---|
| `make setup` | Install package in editable mode |
| `make test` | Run unit test suite |
| `make run` | Start MCP server locally |
| `make docker-up` | Start all services via docker compose |
| `make docker-down` | Stop docker compose services |
| `make reindex` | Rebuild Qdrant and Obsidian indexes |
| `make backup` | Backup SQLite database |
| `make lint` | Syntax-check Python files with `py_compile` |
| `make format` | Strip trailing whitespace and ensure final newline |
