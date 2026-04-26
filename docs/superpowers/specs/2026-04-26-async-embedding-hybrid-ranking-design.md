# Design: Async Embedding + Hybrid Ranking for Mnemonic MCP

**Date:** 2026-04-26
**Status:** Draft
**Goal:** Reduce write latency (async embedding) and improve recall (hybrid ranking)

---

## Context

Mnemonic MCP provides persistent memory for AI agents. Benchmark shows:
- Write latency: ~200ms avg, embedding is 61% of it
- Search latency: ~450ms avg
- Recall: 70% (GOOD), Context Integration: 100% (EXCELLENT)
- Token overhead: 0.74% of 200K window (NEGLIGIBLE)

Target: push recall beyond 70%, reduce write latency by moving embeddings async.

---

## Scope

Two independent improvements that can be implemented in sequence:

1. **Async Embedding** — move Ollama embedding out of synchronous write path
2. **Hybrid Ranking** — implement RRF fusion of FTS5 + vector results

---

## Part 1: Async Embedding

### 1.1 Problem

Current write path:
```
write → repository.create_memory() → qdrant_store.upsert() [BLOCKS on Ollama ~150-300ms] → return
```
Embedding is synchronous and blocking. This is 61% of write latency.

### 1.2 Architecture

```
write() → SQLite commit + FTS5 sync → enqueue outbox event → return immediately (fast)
                                      ↓
                              OutboxWorker (async, background)
                                      ↓
                              process_pending()
                                      ↓
                              For each qdrant-event:
                                - get_memory(id)
                                - check content_hash/fingerprint
                                - embed via Ollama (if needed)
                                - upsert to Qdrant
```

### 1.3 Key Changes

#### A. Repository — no inline Qdrant call

`repository.create_memory()` already enqueues to outbox, does NOT call qdrant directly. This is already correct — the issue is `_project_qdrant()` calls embed + upsert inline.

#### B. QdrantProjectionStore — separate embed from upsert

Add `upsert_with_vector(record, vector)` that upserts pre-computed vector without calling embedder.

```python
def upsert_with_vector(self, record: MemoryRecord, vector: List[float]) -> None:
    # upsert to Qdrant using provided vector, no embedder call
```

#### C. OutboxWorker — embed in worker, not on write path

`_project_qdrant()` generates embedding async:

```python
def _project_qdrant(self, event: OutboxEvent) -> None:
    if not self.qdrant_store.enabled:
        raise RuntimeError("qdrant unavailable")
    record = self.repository.get_memory(event.memory_id)
    if record is None:
        return

    # Handle deleted/retracted
    if record.status not in {"active", "archived"}:
        self.qdrant_store.delete(record.id)
        return

    # Skip if newer event pending
    if self.repository.has_newer_pending_outbox_event(event.memory_id, event.target_version):
        return

    # Content-hash dirty checking
    proj_state = self.repository.get_projection_state(event.memory_id)
    if proj_state.qdrant_content_hash == record.content_hash and \
       proj_state.qdrant_embedding_fingerprint == self._embedding_fingerprint():
        return  # Vector current, skip embedding

    # Embed and upsert
    vector = self._embedder(record.content)
    self.qdrant_store.upsert_with_vector(record, vector)
    self.repository.set_projection_version(event.memory_id, "qdrant", event.target_version)
```

#### D. Embedding fingerprint

Store `qdrant_embedding_fingerprint` in `memory_projections`:
```python
def _embedding_fingerprint(self) -> str:
    return f"{self.vector_strategy}:{self.embedding_model}:{self.vector_size}"
```

If model/size/strategy changes, all vectors are stale — trigger reindex.

#### E. Monotonic version update

`set_projection_version()` must only advance:
```python
current = self.get_projection_version(memory_id, projection)
if current >= version:
    return  # Already at or ahead of target version
```

#### F. Status transitions

Update `memory_projections.qdrant_status` with transitions:
- `pending` — event enqueued, projection not yet attempted
- `ready` — projection succeeded
- `failed` — permanent failure (max retries exceeded)

#### G. Dead-letter state

After N retry attempts (e.g., 5), mark `qdrant_status = 'failed'` and stop retrying. Requires admin intervention or manual requeue.

### 1.4 Error Handling

| Scenario | Behavior |
|----------|----------|
| Ollama unavailable | Mark `failed`, outbox retries with backoff |
| Ollama slow | Worker waits, no impact on write path |
| Embedding fails permanently | `qdrant_status = failed`, stop retrying |
| Qdrant unavailable | Embedding skipped, projection deferred |
| Content unchanged | Skip embedding via content hash check |
| Model/strategy changed | Reindex needed (detected via fingerprint) |

### 1.5 What does NOT change

- FTS5 sync remains synchronous on write (FTS is local, fast)
- `memory.search` still works immediately via FTS5
- Vector search catches up async via outbox

---

## Part 2: Hybrid Ranking

### 2.1 Problem

Current search modes:
- `fts_sqlite` — FTS5 only, used when Qdrant unavailable/stale
- `hybrid` — Qdrant first, then SQLite fallback, simple merge/dedup

No actual score fusion. FTS only used when vector is unavailable.

### 2.2 Architecture

```
search(query) →
  1. Expand query deterministically (singular/plural, synonyms, path tokens)
  2. Run FTS5 search → get top 50 with BM25 ranks
  3. Run Qdrant vector search → get top 50 with cosine scores
  4. Deduplicate by memory_id
  5. Fuse ranks with RRF
  6. Bulk fetch full records from SQLite
  7. Return top N
```

### 2.3 Query Expansion (Deterministic)

```python
def expand_query(query: str) -> List[str]:
    expansions = [query]
    # Singular/plural
    if query.endswith('s'):
        expansions.append(query[:-1])
    else:
        expansions.append(query + 's')
    # Common agent synonyms
    synonyms = {
        'db': ['database', 'postgres', 'postgresql'],
        'embed': ['embedding', 'embedded', 'embeddings'],
        'decision': ['adr', 'architecture decision'],
        'mem': ['memory', 'persistent'],
    }
    for term, syns in synonyms.items():
        if term in query.lower():
            expansions.extend(syns)
    return expansions
```

Use `OR` across expansions for FTS MATCH.

### 2.4 RRF Fusion

```python
def rrf_fusion(fts_results: List[MemoryRecord], vector_results: List[MemoryRecord], k: int = 60) -> List[MemoryRecord]:
    scores = {}
    for rank, record in enumerate(fts_results):
        scores[record.id] = scores.get(record.id, 0) + 1 / (k + rank)
    for rank, record in enumerate(vector_results):
        scores[record.id] = scores.get(record.id, 0) + 1 / (k + rank)
    return sorted(scores.keys(), key=lambda id: scores[id], reverse=True)
```

### 2.5 FTS5 Column Weights

```sql
CREATE VIRTUAL TABLE memory_fts USING fts5(
  memory_id,
  content,
  tags,
  tokenize='unicode61',
  content='memory_records',
  content_rowid='rowid'
);
```

Tags weight is 2x content via `tokenize='unicode61'` and query construction:
```
tags:query OR content:query → tags matches weighted higher via match syntax
```

Actually FTS5 doesn't support per-column weights in MATCH. Instead, search tags separately and boost:
```python
tag_results = search_fts("tags:" + query, ...)
content_results = search_fts(query, ...)
# Tag matches get 2x rank boost
```

### 2.6 FTS5 Filter Parity

`search_fts()` must support same filters as Qdrant:
- `namespace` (already)
- `scope_id` (missing — add)
- `types` (missing — add)
- `status` (filter to active/archived, missing — add)
- `include_archived` (missing — add)

### 2.7 Bulk Hydration

Current design fetches records one-by-one after fusion. For top 50 candidates:
```python
# Bad: N get_memory() calls
for memory_id in fused_ids:
    record = repository.get_memory(memory_id)  # N calls

# Good: bulk fetch
records = repository.get_memory_bulk(fused_ids)  # 1 call
```

Add `get_memory_bulk(memory_ids: List[str]) -> List[MemoryRecord]`.

### 2.8 Query Embedding Decision

Semantic vector search requires embedding the query. Options:

| Option | Pro | Con |
|--------|-----|-----|
| **Accept per-query Ollama** | Simple, works, semantic quality | 150-300ms latency per search |
| **Cache query embeddings** | Reuse within session | Session-scoped, not cross-session |
| **Skip vector, FTS only** | Fast, no Ollama | Lower semantic recall |

**Recommendation:** Accept per-query Ollama (Option A). Search latency ~450ms is already acceptable for agents. Ollama call is ~150-300ms of that. Acceptable.

Document that hybrid search latency = FTS time + Ollama embed + Qdrant query.

### 2.9 Search Mode Reporting

After fusion, report actual mode used:
- `hybrid_rrf` — used both FTS and vector, fused with RRF
- `fts_sqlite` — vector unavailable or Qdrant stale
- `fallback_sqlite` — filters used that bypass vector

---

## Part 3: Schema Migrations

### 3.1 New Columns for `memory_projections`

```sql
ALTER TABLE memory_projections ADD COLUMN qdrant_content_hash TEXT;
ALTER TABLE memory_projections ADD COLUMN qdrant_embedding_fingerprint TEXT;
ALTER TABLE memory_projections ADD COLUMN embedding_status TEXT DEFAULT 'pending';
```

`qdrant_status` already exists — `embedding_status` extends it or we repurpose `qdrant_status`:
- `pending` — enqueued, not yet attempted
- `projecting` — worker currently processing
- `ready` — projection complete
- `failed` — permanent failure

### 3.2 Migration Strategy

Add to `migrations.py` — NOT `CREATE IF NOT EXISTS` in `initialize()`.

```python
MIGRATIONS = [
    # v1: initial schema
    {"version": 1, "sql": "CREATE TABLE ..."},
    # v2: add projections columns
    {"version": 2, "sql": "ALTER TABLE memory_projections ADD COLUMN ..."},
]
```

Run migrations in order, track current version in DB.

### 3.3 Reindex When Fingerprint Changes

If `embedding_fingerprint` changes (model/size/strategy changed), all Qdrant vectors are stale. Run `rebuild_qdrant.py` after such changes.

---

## Part 4: Implementation Order

### Phase 1: Async Embedding (P0)
1. Add migration for new projection columns
2. Add `set_projection_version` monotonic check
3. Add `get_memory_bulk()`
4. Modify `_project_qdrant()` to embed in worker
5. Add `upsert_with_vector()` to QdrantProjectionStore
6. Add embedding fingerprint tracking
7. Add dead-letter state (max retries)
8. Test: write latency drops, vector search catches up async

### Phase 2: Hybrid Ranking (P1)
1. Add query expansion function
2. Add `search_fts()` with filter parity (scope_id, types, status, include_archived)
3. Implement RRF fusion in `SearchService`
4. Add bulk hydration
5. Update search mode reporting
6. Test: recall improves, latency stays under 1s

### Phase 3: Validation (P2)
1. Run benchmark, measure recall@N
2. If below 80%, iterate on expansion/fusion params
3. Document recall target

---

## Part 5: What We Skip (YAGNI)

- LLM-based query expansion (too slow, too complex)
- Title/summary fields (schema change, not minimum viable)
- Separate EmbeddingWorker (OutboxWorker handles both)
- Weighted score normalization (RRF is simpler and sufficient)
- GPU embedding support (future)
- Cross-worker coordination/locks (single instance for now)

---

## Open Questions

1. **Max retry attempts before dead-letter?** Recommend 5.
2. **FTS weight for tags?** Start with 2x, tune if needed.
3. **RRF k parameter?** Start with 60, tune if needed.
4. **Accept per-query Ollama for vector search?** Yes unless latency proves unacceptable.

---

## Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Write latency (avg) | < 50ms | Benchmark |
| Recall | > 80% | Recall benchmark |
| Search latency (p95) | < 1000ms | Benchmark |
| Context Integration | 100% | Already 100% |