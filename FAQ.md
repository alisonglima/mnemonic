# Frequently Asked Questions

## The repository is named `mnemonic` but the product is Mnemonic — why?

The directory `mnemonic` is the official public name. The product is called **Mnemonic** and the Python package is `mcp-memory` because PyPI naming conventions and MCP tooling require it.

## What does "local-first" mean?

Local-first means all your data stays on your machine. Mnemonic writes to a local SQLite database and projects journal entries and queued records to a local Obsidian vault. No cloud account is required. You can run it entirely offline. Qdrant is optional and runs locally via Docker Compose when enabled, so your approximate similarity search never leaves your environment.

## Why Qdrant and Ollama?

- **Qdrant** provides approximate similarity search over memory projections. It runs locally in the Docker Compose stack when enabled. It is optional — the system degrades gracefully to SQLite-only if it is unavailable.
- **Ollama** is included and reserved for future local-model workflows (e.g. generating summaries or embeddings without sending data to an external API). It is not used by current projection logic.
- Both are optional in the sense that the system degrades gracefully if they are unavailable.

## Why does Mnemonic also write to Obsidian?

Obsidian is a widely-used, open Markdown-based note-taking tool. Mnemonic projects journal entries and queued records to your local Obsidian vault so you can read, search, and link those entries as plain Markdown files. This gives you a human-readable view of what your agents are storing without requiring any special software.

## Who owns my data?

You do. Mnemonic stores everything in SQLite and Qdrant on your own machine. The project does not collect, transmit, or aggregate any usage data. There is no hosted service, no account required, and no telemetry.

## What is the current project status?

Mnemonic is in **alpha**. The core memory model, MCP tools, SQLite source of truth, optional Qdrant projections, and Obsidian vault sync are functional. The API surface may change as the project matures. See the [changelog](./CHANGELOG.md) for what has been added recently.