# MCP Clients

Mnemonic exposes an HTTP MCP server. Any MCP-compatible client can connect using the server address and tool names listed below.

## Client setup guides

- [OpenCode](opencode.md) — primary supported client
- [Claude Code](claude-code.md)
- [Codex](codex.md)
- [Other clients](community-clients.md)

## Server address

```
http://localhost:8080/sse
```

The server uses FastMCP SSE transport. Clients that require a transport type should use `sse`; clients that only require a URL should point at `/sse`.

## Exposed tools

| Tool | Purpose |
|---|---|
| `memory.search` | Hybrid search: SQLite filters + optional Qdrant vector lookup |
| `memory.get` | Retrieve a record by ID |
| `memory.write` | Create a new memory record |
| `memory.update` | Replace a record (requires `expected_version`) |
| `memory.retract` | Soft-delete a record |
| `memory.delete` | Hard-delete a record |
| `memory.journal` | Create a journal entry (projects to Obsidian) |
| `memory.archive` | Archive a record |
| `memory.add_tags` | Attach tags to a record |
| `memory.remove_tags` | Remove tags from a record |
| `memory.append_note` | Append a note to a record |
| `memory.health` | Check SQLite, optional Qdrant, Obsidian vault, worker, and outbox status |
| `memory.batch_write` | Write multiple records in a single call |
| `memory.batch_update_tags` | Update tags on multiple records in a single call |

## `memory.search` parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | string | Yes | Search text (matched against content) |
| `namespace` | string | Yes | Namespace to search within |
| `scope_id` | string | No | Filter by scope |
| `types` | list[string] | No | Filter by record types |
| `limit` | int | No | Max results (default: 5) |
| `include_archived` | bool | No | Include archived records (default: false) |
| `include_retracted` | bool | No | Include retracted records (default: false) |
| `offset` | int | No | Pagination offset (default: 0) |
| `status` | string | No | Filter by status (`active`, `archived`, `retracted`, `deleted`) |
| `created_after` | string | No | ISO 8601 datetime - filter by created_at >= value |
| `created_before` | string | No | ISO 8601 datetime - filter by created_at <= value |
| `updated_after` | string | No | ISO 8601 datetime - filter by updated_at >= value |
| `updated_before` | string | No | ISO 8601 datetime - filter by updated_at <= value |

## `memory.write` parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `content` | string | Yes | Record content |
| `type` | string | Yes | Record type (e. `.g. `note`, `journal`) |
| `namespace` | string | Yes | Namespace |
| `scope_id` | string | Yes | Scope identifier |
| `source` | string | Yes | Source of the write (e.g. `"agent"`) |
| `tags` | list[string] | No | Tags to attach |
| `idempotency_key` | string | No | Key to prevent duplicate writes |
| `metadata` | dict | No | Arbitrary key-value metadata |

## `memory.batch_write` parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `items` | list[dict] | Yes | List of memory item dicts (same structure as `memory.write`) |

Each item in `items` supports all `memory.write` parameters plus `obsidian_projection` (bool, default: false).

Returns: `{results: [], all_created: bool, created_count: int, failed_count: int}`

## `memory.batch_update_tags` parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `updates` | list[dict] | Yes | List of update dicts |

Each update dict supports:
| Parameter | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Memory record ID |
| `add_tags` | list[string] | No | Tags to add |
| `remove_tags` | list[string] | No | Tags to remove |

Returns: `{results: [], all_success: bool, success_count: int, failure_count: int}`

## `memory.update` / `memory.delete` / `memory.retract`

All three require `expected_version` (integer) for optimistic concurrency. The version of the record to be modified must be passed, otherwise the operation fails with a version conflict.

## `memory.health` response keys

| Key | Type | Description |
|---|---|---|
| `sqlite` | string | `"up"` if SQLite database file exists, `"down"` otherwise |
| `qdrant` | string | `"up"` if Qdrant is reachable, `"down"` otherwise |
| `ollama` | string | `"up"` if OLLAMA_URL is configured and /api/tags returns 2xx, `"down"` otherwise |
| `worker` | string | Always `"up"` in the current health response; it does not perform a live thread check |
| `obsidian_projection` | string | `"up"` if the Obsidian vault directory exists, `"down"` otherwise |
| `degraded` | bool | `true` if Qdrant is unavailable or vault is inaccessible |
| `pending_events` | int | Number of outbox events waiting to be processed |
| `oldest_pending_age_seconds` | int | Seconds since the oldest pending event was created |
