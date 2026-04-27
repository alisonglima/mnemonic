# Performance Reference

Benchmark results for Mnemonic v0.1.1 running on Apple Silicon (M-series), Docker stack with Qdrant and Ollama `nomic-embed-text`.

Run date: 2026-04-27. Reproduce with:

```bash
PYTHONPATH=mcp-memory/src python mcp-memory/scripts/benchmark.py --host 127.0.0.1 --port 8080
```

---

## Write throughput

| Scenario | Count | Ops/sec | Avg latency | Max latency | Stddev |
|----------|-------|---------|------------|------------|--------|
| Sequential | 100 | 78 | 12ms | 146ms | 16ms |
| Sequential | 500 | 34 | 28ms | 499ms | 29ms |
| Concurrent (c=10) | 100 | 112 | 70ms | 886ms | 168ms |
| Concurrent (c=20) | 500 | 107 | 176ms | 3 485ms | 413ms |

**Sequential degradation:** throughput drops 56% from 100 to 500 records. Root cause is Qdrant async indexing pressure and WAL checkpoint accumulation. Workaround: use `memory.batch_write` to reduce round-trips when writing many records at once.

**Concurrent instability:** at c=20 the max latency reaches 3 485ms. SQLite WAL mode allows one concurrent writer; bursts beyond that queue on the write lock. For agent workflows that fire many writes in parallel, reduce concurrency or use `memory.batch_write`.

---

## Search latency

| Scenario | Ops/sec | Avg | Min | Max | Stddev |
|----------|---------|-----|-----|-----|--------|
| Hybrid RRF (5 queries × 5 runs) | 22 | 45ms | 14ms | 140ms | 35ms |

Search corpus size during benchmark: ~100 records. Behaviour at 1 000+ records is untested. See [roadmap](../../ROADMAP.md).

---

## Base overhead

Every MCP call via Docker incurs a fixed ~38ms overhead regardless of payload size. This is MCP SSE transport + Docker bridge network latency and is not related to content size or embedding computation.

| Deployment mode | Per-call base overhead |
|----------------|----------------------|
| Docker (`docker compose up`) | ~38ms |
| Native (`make run`) | ~5–10ms (estimated) |

For CLI tools and agent loops where MCP calls are on the critical path, `make run` is the lower-latency option. Docker is preferable when you need Qdrant and Ollama with minimal setup effort.

---

## Qualitative results

| Assessment | Score | Notes |
|------------|-------|-------|
| Recall & Precision | 100% | Unique token found at rank 1 among 20 distractors |
| Context Integration | 100% | Decision record retrieved across simulated multi-phase workflow |
| Namespace Isolation | 100% | Zero cross-namespace leakage |
| Reliability Under Load | 100% | 0 errors across 50 concurrent ops |
| Bottleneck Analysis | 50% | Latency flat across payload sizes → overhead-dominant, not embedding-dominant |
| Token Overhead (measured) | 100% | 0.26% of 200K context window (5 results) |
| Token Overhead (theoretical) | 100% | 0.74% of 200K window (full session estimate) |

**Overall qualitative score: 93% (EXCELLENT)**

---

## Embedding overhead

Embedding computation (Ollama `nomic-embed-text`) does not appear in per-call latency because it runs asynchronously in the outbox worker after the SQLite write returns. The estimated embedding contribution to call latency is ~0%.

In degraded mode (hash fallback), the embedding is synchronous but negligible (<1ms for SHA-256 hashing).

---

## Known limitations

- Sequential throughput at scale (500+ writes/session) degrades significantly. Tracked in [roadmap](../../ROADMAP.md).
- Concurrent write instability (c=20+) produces high tail latency. Tracked in [roadmap](../../ROADMAP.md).
- Search quality at 1 000+ records is untested.
- Docker adds an unavoidable ~38ms base overhead that native mode does not have.
