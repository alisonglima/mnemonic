# Environment Variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `MCP_PORT` | `8080` | No | HTTP port the MCP server listens on |
| `SQLITE_PATH` | `./data/memory.db` | No | Path to the SQLite database file |
| `OBSIDIAN_VAULT` | `./obsidian-vault` | No | Path to the Obsidian vault directory |
| `QDRANT_URL` | _(empty)_ | No | Qdrant instance URL (e.g. `http://localhost:6333`). Empty disables vector projections. |
| `QDRANT_COLLECTION` | `memory_records` | No | Name of the Qdrant collection |
| `OLLAMA_URL` | _(empty)_ | No | Ollama instance URL. Reserved for future local-model workflows. Not used by current projection logic. |

## `OLLAMA_URL` — reserved / not active

`OLLAMA_URL` is accepted in the environment and stored in `Settings.ollama_url`, but the current runtime does not call Ollama. It exists to support future local-model vector workflows. Do not expect embedding behavior to activate by configuring this variable today.

## Defaults and overrides

- Values in `.env` are read on startup. Restart the server after changing `.env`.
- Environment variables set in the shell take precedence over `.env` values.
- For Docker Compose, set variables in the `environment` block or in a `.env` file alongside `docker-compose.yml`.

## Validation

No schema validation is performed at startup. Misconfigured paths may cause errors at runtime when operations are attempted.
