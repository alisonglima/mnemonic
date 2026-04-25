# Quickstart

Get Mnemonic running and verified.

## Prerequisites

- Python >=3.9

## Step 0 — Clone the repository

```bash
git clone <your-org>/mnemonic.git
cd mnemonic
```

## Step 1 — Install dependencies

```bash
make setup
```

This installs `mcp-memory` in editable mode with its dependencies (`fastmcp`, `qdrant-client`).

## Step 2 — Configure environment

```bash
cp .env.example .env
```

Default values:

| Variable | Default | Purpose |
|---|---|---|
| `MCP_PORT` | `8080` | MCP server port |
| `SQLITE_PATH` | `./data/memory.db` | SQLite database location |
| `OBSIDIAN_VAULT` | `./obsidian-vault` | Obsidian vault path |
| `QDRANT_URL` | _(empty)_ | Qdrant vector store (optional) |
| `QDRANT_COLLECTION` | `memory_records` | Qdrant collection name |

**Qdrant is optional.** By default `QDRANT_URL` is empty and Mnemonic runs in SQLite-only mode. No external services are required.

## Step 3 — Run the MCP server

```bash
make run
```

The server starts on `127.0.0.1:8080`. You should see:

```
Starting MCP server on 127.0.0.1:8080
```

## Step 4 — Verify

```bash
make test
```

Expected output:

```
Ran 22 tests in <time>

OK
```

If all tests pass, your core memory model and MCP tools are wired correctly. This validates the unit test suite — integration with Qdrant and Obsidian requires those services to be configured.

## What you now have

- **SQLite database** at `./data/memory.db` — source of truth for all records.
- **MCP server** on port 8080 — exposes 12 memory tools via HTTP.
- **Obsidian vault** at `./obsidian-vault` — journal entries and queued records are projected as Markdown files.

Qdrant is disabled by default. See [Docker Installation](installation/docker.md) if you want to enable approximate similarity search.

## Next steps

- Read the [docs index](index.md) for available documentation.
- Connect an AI agent (Claude Desktop, Cursor, etc.) to `http://127.0.0.1:8080` as an MCP server.
- Call `memory.health` via the MCP protocol to check system status (SQLite, optional Qdrant reachability, Obsidian vault path).