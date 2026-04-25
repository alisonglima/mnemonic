# Troubleshooting

## Server won't start

**Error: `ModuleNotFoundError: No module named 'mcp_memory'`**

Run `make setup` or `pip install -e mcp-memory` first. The package must be installed in editable mode.

**Error: `Address already in use`**

Another process is using port 8080 (or whatever `MCP_PORT` is set to). Stop the existing process or change the port in `.env`.

**Error: `database is locked`**

SQLite has a write lock issue. Only one writer at a time. Check for concurrent processes or failed transactions holding a lock. Restart the server.

## Search returns no results

1. Check that records exist in SQLite:
   ```python
   # via the MCP tool memory.health to check database status
   ```

2. Check `QDRANT_URL` in `.env`. If Qdrant is unreachable, search falls back to SQLite-only mode and returns `degraded: true`.

3. If using Qdrant: confirm the collection was created. Run `make reindex` to rebuild the collection from SQLite.

4. Verify `namespace` matches the namespace used when records were created.

## Version conflict on update/delete/retract

All three tools require `expected_version`. Fetch the current record with `memory.get` to get its version, then pass that version in the mutation call.

```
VersionConflictError — raised when expected_version != current version.
```

## Qdrant connection failures

- Confirm Qdrant is running: `curl http://localhost:6333/healthz` (if Qdrant port is exposed).
- Check `QDRANT_URL` in `.env` — must be reachable from the MCP server process.
- If Qdrant is down, the server continues to operate in degraded mode (SQLite-only search). Projections are queued in the outbox and retried.
- Run `make reindex` after Qdrant recovers to replay queued projection events.

## Obsidian vault not updating

1. Check `OBSIDIAN_VAULT` path is correct and writable.
2. Check the vault directory exists.
3. Run `make reindex` to rebuild the vault from SQLite.
4. Records must have `obsidian_projection=True`. Only `memory.journal` sets this automatically. Other types require manual projection handling.
5. Deleted records still have `.md` files after reindex (rebuild script skips `deleted` status but does not delete stale files).

## Outbox events not processing

Check `memory.health` for `pending_events` count and `oldest_pending_age_seconds`. If events are stuck:

- The outbox worker background thread may have crashed. Restart the server.
- Events that fail are rescheduled with exponential backoff (up to 300s). Check `memory_projections` table for error messages.
- To force reprocessing, restart the server.

## `make test` fails

Run with verbose output:

```bash
PYTHONPATH=mcp-memory/src python3 -m unittest discover -s mcp-memory/tests -p "test_*.py" -v
```

If the database file is missing, initialize it first:

```bash
PYTHONPATH=mcp-memory/src python3 mcp-memory/scripts/init_db.py
```

## Docker compose fails

- `docker compose up --build` must be run from the repository root.
- If port 8080 is already in use, stop the existing container or change the mapped port in `docker-compose.yml`.
- On Apple Silicon, some base images may need `--platform linux/amd64` added to the Dockerfile.