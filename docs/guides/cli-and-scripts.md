# CLI and Scripts

This page documents maintenance scripts and Docker health behavior.

## Maintenance Scripts

All scripts live in `mcp-memory/scripts/` and are invoked via `make` or directly with Python.

### backup_sqlite.py

Backs up the SQLite database to a `.backup.db` file.

```bash
# Via make
make backup

# Directly
python -m mcp_memory.scripts.backup_sqlite
```

The script copies `SQLITE_PATH` to `SQLITE_PATH.backup.db`. It is idempotent — running multiple times overwrites the same backup.

### rebuild_qdrant.py

Rebuilds the Qdrant vector index from all records in SQLite.

```bash
make reindex  # also runs rebuild_obsidian.py
```

### rebuild_obsidian.py

Rebuilds the Obsidian vault Markdown files from all records in SQLite.

### init_db.py

Creates the database schema if it does not exist.

## Docker Health Behavior

All services in `docker-compose.yml` have health checks defined. Docker will not mark a container as healthy until its health check passes.

### Health Check Definitions

| Service | Health Check | Healthy When |
|---------|-------------|---------------|
| `qdrant` | Bash TCP probe against `GET /healthz` | HTTP 200 from `/healthz` |
| `ollama` | `ollama list` | Ollama CLI can reach the local server |
| `mcp-memory` | Python `health_check.docker_health()` | SQLite file exists |

### Startup Ordering

`mcp-memory` uses `depends_on` with `condition: service_healthy`, so Docker will not start the MCP server until both `qdrant` and `ollama` are healthy. This means:

1. On first startup, wait for Qdrant and Ollama to become healthy
2. MCP server starts only when both dependencies are ready
3. If a dependency becomes unhealthy after startup, `memory.health` reports degraded state while SQLite-backed memory remains available

### Verifying Health

```bash
# View container health status
docker compose ps

# Inspect health check logs for a specific container
docker inspect --format='{{json .State.Health}}' mnemonic-qdrant-1
```

### Health Check Output

The `mcp-memory` health check script outputs JSON to stdout:

```json
{
  "sqlite": "up",
  "qdrant": "up",
  "ollama": "up",
  "worker": "up",
  "obsidian_projection": "up"
}
```

If `sqlite` is `down`, the health check exits with a non-zero status, signaling Docker to restart the container.
