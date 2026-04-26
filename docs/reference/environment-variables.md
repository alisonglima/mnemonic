# Environment Variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `MCP_PORT` | `8080` | No | HTTP port the MCP server listens on |
| `SQLITE_PATH` | `./data/memory.db` | No | Path to the SQLite database file |
| `OBSIDIAN_VAULT` | `./obsidian-vault` | No | Path to the Obsidian vault directory |
| `QDRANT_URL` | _(empty)_ | No | Qdrant instance URL (e.g. `http://localhost:6333`). Empty disables vector projections. |
| `QDRANT_COLLECTION` | `memory_records` | No | Name of the Qdrant collection |
| `OLLAMA_URL` | _(empty)_ | No | Ollama instance URL for semantic embeddings. When set, enables Ollama-backed embeddings with hash fallback. |
| `EMBEDDING_STRATEGY` | `hash` | No | Embedding strategy: `hash` (deterministic) or `ollama` (semantic). Default: `hash` |
| `EMBEDDING_MODEL` | `nomic-embed-text` | No | Ollama embedding model (used when `EMBEDDING_STRATEGY=ollama`) |
| `DEFAULT_NAMESPACE` | `default` | No | Default namespace for new records |
| `RETENTION_ACTION` | `delete` | No | Retention action: `delete` or `archive` for expired records |
| `RETENTION_DAYS` | `30` | No | Retention period in days for automatic cleanup |
| `OUTBOX_MAX_WORKERS` | `4` | No | Thread pool size for async Qdrant/Obsidian projections |
| `SEARCH_SCORE_THRESHOLD` | `0.5` | No | Minimum cosine similarity to include Qdrant hit (0.0–1.0) |

## Embedding Strategies

### Hash (default)
`EMBEDDING_STRATEGY=hash` uses a deterministic hash-based embedding. This always works without external dependencies and produces 8-dimensional vectors derived from SHA-256 of the input text.

### Ollama (semantic)
`EMBEDDING_STRATEGY=ollama` uses Ollama for semantic embeddings. Configure `OLLAMA_URL` and `EMBEDDING_MODEL`. When Ollama is unavailable, the system automatically falls back to hash embeddings.

## Defaults and overrides

- Values in `.env` are read on startup. Restart the server after changing `.env`.
- Environment variables set in the shell take precedence over `.env` values.
- For Docker Compose, set variables in the `environment` block or in a `.env` file alongside `docker-compose.yml`.

## Validation

No schema validation is performed at startup. Misconfigured paths may cause errors at runtime when operations are attempted.
