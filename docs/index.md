# Mnemonic — Documentation

## Getting started

- [Quickstart](quickstart.md) — Install, configure, and verify Mnemonic in 5 steps.

## Concepts at a glance

- **Local-first design** — SQLite as source of truth, Qdrant for vector projections, Obsidian for human-readable Markdown.
- **Dual-write pipeline** — Async outbox pattern projects records to your Obsidian vault without blocking MCP operations.
- **Deterministic vector projections** — SHA-256 hash projections (8-dim) provide approximate similarity lookup without external models. Not true semantic embeddings.

## MCP Tools

Mnemonic exposes MCP tools over FastMCP SSE:

| Tool | Purpose |
|---|---|
| `memory.search` | Hybrid search: SQLite filters + optional Qdrant vector lookup |
| `memory.write` | Create a new memory record |
| `memory.get` | Retrieve a record by ID |
| `memory.update` | Replace a record (optimistic concurrency) |
| `memory.retract` | Soft-delete a record |
| `memory.delete` | Hard-delete a record |
| `memory.journal` | Append a timestamped journal entry |
| `memory.archive` | Move a record to archived state |
| `memory.add_tags` | Attach tags to existing records |
| `memory.remove_tags` | Detach tags from existing records |
| `memory.append_note` | Add a note to an existing record |
| `memory.health` | Check system status: SQLite DB file exists, Qdrant reachable, Obsidian vault path exists |
| `memory.batch_write` | Write multiple records in one call |
| `memory.batch_update_tags` | Update tags on multiple records in one call |

## Operations

| Command | Description |
|---|---|
| `make setup` | Install dependencies (editable mode) |
| `make test` | Run unit test suite |
| `make run` | Start MCP server on `127.0.0.1:8080` |
| `make docker-up` | Start all services via docker compose |
| `make docker-down` | Stop docker compose services |
| `make reindex` | Rebuild Qdrant vector + Obsidian Markdown indexes |
| `make backup` | Backup SQLite database |
| `make lint` | Syntax check Python files |
| `make format` | Fix whitespace in Python files |

## Data model

- **Records** — Core memory units with type, namespace, content, tags, and metadata.
- **Versions** — Every mutation creates a new version; optimistic concurrency prevents silent overwrites.
- **Tags** — Many-to-many labels for organizing and filtering records.
- **Idempotency keys** — Optional keys on writes to prevent duplicate operations.

## Installation

- [Docker](installation/docker.md) — Run Mnemonic with Docker Compose
- [Local development](installation/local-dev.md) — Run directly on your machine
- [Configuration](installation/configuration.md) — Environment variable reference

## Guides

- [Obsidian integration](guides/obsidian.md) — Project journal entries to a local vault
- [MCP clients](guides/mcp-clients/index.md) — Connect any MCP-compatible client
- [Backups](guides/backups.md) — Back up the SQLite source of truth
- [Reindexing](guides/reindexing.md) — Rebuild Qdrant and Obsidian indexes

## Architecture

- [Overview](architecture/overview.md) — System design and principles
- [Data flow](architecture/data-flow.md) — Write, search, and projection paths
- [Components](architecture/components.md) — Key modules and their responsibilities

## Reference

- [Environment variables](reference/environment-variables.md) — Full variable reference
- [CLI and scripts](reference/cli-and-scripts.md) — Server CLI and maintenance scripts
- [Troubleshooting](reference/troubleshooting.md) — Common issues and solutions

## Project status

**Alpha.** The core memory model, MCP tools, and dual-write pipeline are functional. API surface may change.
