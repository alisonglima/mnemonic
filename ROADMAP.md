# Roadmap

## Completed

### Phase 1 — Public repository readiness
- Complete docs tree (installation, guides, architecture, reference).
- CI pipeline and contribution templates.
- Public issue and PR hygiene.
- Stable README, license, and governance files.

### Phase 2 — Docker & operational reliability
- Docker Compose health checks for all services.
- Verified backup and restore tooling (PRAGMA integrity_check).

### Phase 3 — Richer MCP surface
- `memory.batch_write` and `memory.batch_update_tags`.
- Extended `memory.search` filters (date range, status, offset/pagination).

### Phase 4 — Vector & configuration
- Ollama embedding integration (`nomic-embed-text`, 768-dim) with hash fallback.
- Enhanced Obsidian vault projection (rich frontmatter, status subdirectories).
- Expanded configuration: `EMBEDDING_STRATEGY`, `RETENTION_DAYS`, `DEFAULT_NAMESPACE`, `OUTBOX_MAX_WORKERS`.

---

## Next — Performance & reliability

Findings from benchmark run (2026-04-27, v0.1.1, Docker stack with Ollama):

### Write throughput degradation at scale
Sequential write throughput drops from 78 ops/sec (100 records) to 34 ops/sec (500 records) — a 56% reduction driven by Qdrant async indexing overhead and WAL checkpoint accumulation.

- Investigate deferred Qdrant sync (batch flush instead of per-write outbox events).
- Profile WAL checkpoint behaviour under sustained sequential load.
- Add throughput-at-scale test (1 000+ records) to CI benchmark.

### Concurrent write instability
At concurrency=20 over 500 writes: max latency 3 485ms, stddev 413ms. SQLite WAL single-writer contention under high parallelism.

- Add application-level write serialisation queue to smooth concurrent bursts.
- Evaluate connection pool and `busy_timeout` tuning.
- Add concurrency stress test to benchmark suite.

### Search scalability (untested)
Current benchmarks cover ~100 records in the vector index. Recall quality and latency at 1 000+ records are unknown.

- Benchmark `memory.search` at 1 K and 10 K record corpus sizes.
- Measure Qdrant RRF ranking quality degradation at scale.

### Native mode vs Docker latency
Docker networking adds a fixed ~38ms overhead per MCP call regardless of payload size. For latency-sensitive workflows (CLI tools, fast agent loops), native mode (`make run`) reduces this to ~5–10ms.

- Document native mode as the recommended path for single-user developer setups.
- Add latency comparison table to performance reference.

---

## Later — Security & deployment options

### Optional authentication
The MCP endpoint has no authentication. This is intentional and acceptable for:
- Single-user local deployments (firewall enforces isolation).
- Remote access via a private VPN (e.g. MikroTik Back to Home) where the network boundary is the security perimeter.

For shared or semi-public deployments:
- Evaluate Bearer token support in FastMCP.
- Document a Caddy/nginx reverse proxy pattern as the least-friction auth layer (transparent to MCP clients, no client-side changes needed).

### Embedding quality improvements
Current hash fallback (8-dim SHA-256) provides rough similarity grouping only. Ollama `nomic-embed-text` (768-dim) is the recommended path and is active in the Docker stack. Future work:

- Support additional embedding models and providers.
- Allow per-namespace embedding strategy configuration.
- Benchmark recall quality improvement at scale when using true semantic embeddings vs hash fallback.

### Long-running memory management
- Automatic retention enforcement (archive/delete records older than `RETENTION_DAYS`).
- Namespace-level record counts and storage size reporting in `memory.health`.
- Pruning strategy for outbox events after successful projection.

---

## Status Matrix

| Feature | Status | Notes |
|---|---|---|
| Complete docs tree (installation, guides, architecture, reference) | ✅ Implemented | `docs/` tree |
| CI pipeline and contribution templates | ✅ Implemented | `.github/workflows/ci.yml` |
| Public issue and PR hygiene | ✅ Implemented | Issue + PR templates |
| Stable README, license, and governance files | ✅ Implemented | README, LICENSE, CODE_OF_CONDUCT, SECURITY, CONTRIBUTING |
| Improved MCP client integration guides | ✅ Implemented | Per-client guides in `docs/guides/mcp-clients/` |
| Reliable Docker Compose with health checks | ✅ Implemented | Health checks for all 3 services |
| Verified backup and restore tooling | ✅ Implemented | Scripts with PRAGMA integrity_check |
| Batch MCP operations and advanced search | ✅ Implemented | batch_write, batch_update_tags, date/status filters |
| Ollama embedding integration | ✅ Implemented | nomic-embed-text (768-dim) with hash fallback |
| Enhanced Obsidian vault projection | ✅ Implemented | Rich frontmatter, status subdirs |
| Expanded configuration options | ✅ Implemented | embedding_strategy, retention, namespace config |
| Write throughput degradation at scale | 🔲 Planned | 56% drop from 100→500 sequential writes |
| Concurrent write instability | 🔲 Planned | Max 3 485ms at c=20, stddev 413ms |
| Search scalability benchmarks | 🔲 Planned | Untested beyond ~100 records in vector index |
| Native mode latency documentation | 🔲 Planned | Docker adds ~38ms fixed overhead per call |
| Optional authentication (proxy pattern) | 🔲 Planned | Not required for local/VPN use; needed for shared deployments |
| Long-running memory management | 🔲 Planned | Retention enforcement, storage reporting |
