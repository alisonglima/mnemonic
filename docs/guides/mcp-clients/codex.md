# Codex — MCP Client Setup

## Prerequisites

- Mnemonic running: `make run` or `docker compose up -d`
- Codex CLI installed

## Configuration

Add to your Codex MCP configuration:

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

Call `memory.health` from a Codex session. Expected: `sqlite: "up"`, `worker: "up"`.

## Example workflow

```
# Write context that persists across sessions
memory.write({
  "content": "This repo uses pnpm workspaces. Always run pnpm install from root.",
  "type": "fact",
  "namespace": "project",
  "scope_id": "my-repo",
  "source": "agent"
})

# Recall it in a new session
memory.search({
  "query": "pnpm install",
  "namespace": "project"
})
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `connection refused` | Server not running | `make run` |
| `degraded: true` | Qdrant unavailable | Expected in SQLite-only mode |
| Tool call returns `error.code: not_found` | Wrong record ID | Use `memory.search` to find the correct ID first |
