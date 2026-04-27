# Frequently Asked Questions

## The repository is named `mnemonic` but the product is Mnemonic — why?

The directory `mnemonic` is the official public name. The product is called **Mnemonic** and the Python package is `mcp-memory` because PyPI naming conventions and MCP tooling require it.

## What does "local-first" mean?

Local-first means all your data stays on your machine. Mnemonic writes to a local SQLite database and projects journal entries and queued records to a local Obsidian vault. No cloud account is required. You can run it entirely offline. Qdrant and Ollama are optional and run locally via Docker Compose when enabled, so your memory and embeddings never leave your environment.

## Why Qdrant and Ollama?

- **Qdrant** provides approximate similarity search over memory projections. It runs locally in the Docker Compose stack. It is optional — the system degrades gracefully to SQLite FTS-only if unavailable.
- **Ollama** runs local embedding models. When `EMBEDDING_STRATEGY=ollama` is set, Mnemonic uses `nomic-embed-text` (768-dim) to generate real semantic vectors for Qdrant. If Ollama is unavailable, the system falls back to deterministic SHA-256 hash projections (8-dim) — these provide rough grouping, not true semantic understanding.

Both are optional. In SQLite-only mode (no Qdrant, no Ollama), search falls back to SQLite FTS5 full-text search.

## Does Mnemonic require authentication?

No, and this is intentional for the primary use case.

The MCP endpoint (`http://localhost:8080/sse`) has no authentication. This is safe for:

- **Local deployments** — only processes on your machine can reach port 8080. OS-level isolation is the security boundary.
- **Private VPN access** (e.g. MikroTik Back to Home) — only devices you have authenticated to your VPN can reach the service. The VPN is the security perimeter.

Authentication would require configuring Bearer tokens or custom headers on every agent (Claude Code, OpenCode, Codex, etc.) and not all MCP clients support this easily. The added friction is not justified for single-user local or VPN setups.

For shared or semi-public deployments, add a reverse proxy (Caddy, nginx) with IP allowlist or basicauth in front of port 8080. This is transparent to MCP clients and requires no changes to the server.

## What performance should I expect?

Measured on Apple Silicon, Docker stack (Qdrant + Ollama nomic-embed-text), v0.1.1:

| Operation | Throughput | Avg latency |
|-----------|-----------|------------|
| Sequential writes (100 records) | 78 ops/sec | 12ms |
| Sequential writes (500 records) | 34 ops/sec | 28ms |
| Concurrent writes (c=10) | 112 ops/sec | 70ms |
| Search (hybrid RRF) | 22 ops/sec | 45ms |

**Base overhead per call via Docker:** ~38ms (MCP SSE transport + Docker networking). This is constant regardless of payload size.

For latency-sensitive workflows, run natively with `make run` instead of Docker. Native mode removes the networking overhead and reduces per-call latency to ~5–10ms.

**Token overhead:** measured at 0.26% of a 200K context window (5 search results). Negligible.

## Can I access Mnemonic remotely?

Yes, via a private VPN. The recommended approach is MikroTik Back to Home or any WireGuard-based VPN that tunnels to your home network. No changes to the server are needed — point the MCP client URL at your home machine's LAN IP instead of `localhost`.

Do not expose port 8080 directly to the public internet without a reverse proxy with authentication.

## Why does Mnemonic also write to Obsidian?

Obsidian is a widely-used, open Markdown-based note-taking tool. Mnemonic projects journal entries and queued records to your local Obsidian vault so you can read, search, and link those entries as plain Markdown files. This gives you a human-readable view of what your agents are storing without requiring any special software.

## Who owns my data?

You do. Mnemonic stores everything in SQLite and Qdrant on your own machine. The project does not collect, transmit, or aggregate any usage data. There is no hosted service, no account required, and no telemetry.

## What is the current project status?

Mnemonic is in **alpha**. The core memory model, MCP tools, SQLite source of truth, optional Qdrant vector projections, Ollama embedding integration, and Obsidian vault sync are functional. The API surface may change as the project matures. See the [changelog](./CHANGELOG.md) for recent changes and the [roadmap](./ROADMAP.md) for known limitations and planned improvements.
