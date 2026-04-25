# Claude Code — MCP Client Setup

## Prerequisites

- Mnemonic running: `make run` or `docker compose up -d`
- Claude Code CLI installed

## Configuration

Add to your project `.claude/settings.json` or global `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "http://localhost:8080/sse"
    }
  }
}
```

Alternatively, add via the CLI:

```bash
claude mcp add memory --transport sse http://localhost:8080/sse
```

## Verify connection

In Claude Code, call:

```
memory.health
```

Expected: `sqlite: "up"`, `worker: "up"`. Qdrant and Ollama will show `"down"` in SQLite-only mode — this is expected.

## Example workflow

```
# Store a decision record
memory.write({
  "content": "Decided to use Drizzle ORM over Prisma for lighter runtime footprint.",
  "type": "decision",
  "namespace": "project",
  "scope_id": "my-project",
  "source": "agent",
  "tags": ["orm", "architecture"]
})

# Retrieve by search
memory.search({
  "query": "ORM decision",
  "namespace": "project"
})
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Tool not available | MCP server not configured | Check `claude mcp list` and verify `memory` appears |
| `connection refused` | Server not running | `make run` |
| `version_conflict` | Stale `expected_version` | Call `memory.get` first and use the current `version` |
