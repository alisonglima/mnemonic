# OpenCode — MCP Client Setup

## Prerequisites

- Mnemonic running: `make run` or `docker compose up -d`
- OpenCode installed

## Configuration

Add to your OpenCode MCP config (typically `~/.config/opencode/config.json` or project `.opencode/config.json`):

```json
{
  "mcpServers": {
    "memory": {
      "type": "http",
      "url": "http://localhost:8080"
    }
  }
}
```

## Verify connection

After starting OpenCode in a project, run:

```
memory.health
```

Expected response (healthy):

```json
{
  "sqlite": "up",
  "qdrant": "down",
  "ollama": "down",
  "worker": "up",
  "obsidian_projection": "up",
  "degraded": false,
  "pending_events": 0,
  "oldest_pending_age_seconds": null
}
```

`qdrant: "down"` and `ollama: "down"` are normal if you are running SQLite-only mode.

## Example workflow

```
# Write a memory record
memory.write({
  "content": "The auth module uses JWT with RS256 signing. Private key is in VAULT.",
  "type": "fact",
  "namespace": "project",
  "scope_id": "my-app",
  "source": "agent"
})

# Search for it later
memory.search({
  "query": "auth signing",
  "namespace": "project"
})

# Check system health
memory.health()
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `connection refused` | Server not running | `make run` or `docker compose up -d` |
| `not found` on tool call | Wrong server URL | Confirm `url` points to `http://localhost:8080` (or your `MCP_PORT`) |
| `transport not supported` | Wrong transport type | Use `"type": "http"` not `"sse"` or `"stdio"` |
| `degraded: true` in health | Qdrant or Obsidian vault missing | Normal in SQLite-only mode; start Qdrant if vector search is needed |
| `version_conflict` error | `expected_version` mismatch | Fetch the record with `memory.get` first, use the returned `version` |
