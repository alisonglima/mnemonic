# Community Client Setup Template

Mnemonic uses standard HTTP MCP transport (FastMCP). Any client that supports `type: http` MCP servers can connect.

## Minimum configuration

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

Replace `http://localhost:8080` with your `MCP_PORT` if customized.

## Verifying connectivity

Any MCP client should be able to call `memory.health`. A successful response looks like:

```json
{
  "sqlite": "up",
  "worker": "up",
  "degraded": false
}
```

## Known working clients

- OpenCode — see [opencode.md](opencode.md)
- Claude Code — see [claude-code.md](claude-code.md)
- Codex — see [codex.md](codex.md)

## Adding a new client guide

Open a PR adding `docs/guides/mcp-clients/<client-name>.md` following the structure of an existing guide (prerequisites, config snippet, health verification, example workflow, troubleshooting table).
