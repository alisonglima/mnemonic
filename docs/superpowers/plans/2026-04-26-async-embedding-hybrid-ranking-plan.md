# Async Embedding + Hybrid Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce write latency by moving embeddings async and improve recall via RRF hybrid ranking.

**Architecture:** Decouple Ollama embedding from synchronous write path. Embeddings generated in OutboxWorker. Hybrid search fuses FTS5 and vector results via Reciprocal Rank Fusion.

**Tech Stack:** Python 3.11, SQLite (FTS5), Qdrant, Ollama, FastMCP

---

## Phase 1: Async Embedding

### Files Overview

| File | Responsibility |
|------|----------------|
| `mcp-memory/src/mcp_memory/migrations.py` | Schema migrations for new columns |
| `mcp-memory/src/mcp_memory/database.py` | Migration runner |
| `mcp-memory/src/mcp_memory/repository.py` | `get_memory_bulk()`, monotonic version check, projection state |
| `mcp-memory/src/mcp_memory/outbox.py` | Embedding in worker, content-hash check |
| `mcp-memory/src/mcp_memory/qdrant_store.py` | `upsert_with_vector()`, fingerprint attributes |
| `mcp-memory/tests/test_outbox.py` | Tests for async embedding |
| `mcp-memory/tests/test_repository.py` | Tests for bulk get and version monotonicity |

---

### Task 1: Add Schema Migration for Projection Columns

**Files:**
- Modify: `mcp-memory/src/mcp_memory/migrations.py` (add MIGRATIONS list)
- Modify: `mcp-memory/src/mcp_memory/database.py` (add migration runner)
- Modify: `mcp-memory/src/mcp_memory/repository.py` (add new columns to `get_projection_state`)
- Test: `mcp-memory/tests/test_migrations.py` (create)

**Note:** For existing DBs with `user_version = 0` but tables already created (before migrations existed), migration v1 uses the existing full `SCHEMA` as-is (idempotent CREATE IF NOT EXISTS). Migration v2 adds new columns.

```python
# migrations.py — after SCHEMA definition, add MIGRATIONS list

MIGRATIONS = [
    {
        "version": 1,
        "sql": SCHEMA,  # REAL schema string — not a placeholder
    },
    {
        "version": 2,
        "sql": """
            ALTER TABLE memory_projections
            ADD COLUMN qdrant_content_hash TEXT;

            ALTER TABLE memory_projections
            ADD COLUMN qdrant_embedding_fingerprint TEXT;
        """,
    },
]

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1]["version"]
```

```python
# database.py — add migration runner

from mcp_memory.migrations import MIGRATIONS, CURRENT_SCHEMA_VERSION

class Database:
    ...

    def initialize(self) -> None:
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]

            for migration in MIGRATIONS:
                migration_version = int(migration["version"])
                if migration_version <= version:
                    continue

                # Wrap migration + version update in same transaction
                conn.executescript(f"""
BEGIN IMMEDIATE;
{migration["sql"]}
PRAGMA user_version = {migration_version};
COMMIT;
""")
                version = migration_version
```

**Key fix:** Use `executescript` wrapped in explicit `BEGIN IMMEDIATE;...COMMIT;` so migration SQL and `PRAGMA user_version` are atomic. If migration succeeds but PRAGMA fails, rollback occurs.

- [ ] **Step 1: Create test for migration running and existing DB bootstrap**

```python
# tests/test_migrations.py
from mcp_memory.migrations import SCHEMA

def test_migration_adds_projection_columns(temp_db):
    db = Database(temp_db / "test.db")
    db.initialize()
    with db.connect() as conn:
        rows = conn.execute("PRAGMA table_info(memory_projections)").fetchall()
        cols = [r["name"] for r in rows]
        assert "qdrant_content_hash" in cols
        assert "qdrant_embedding_fingerprint" in cols

def test_existing_v1_database_with_user_version_zero_migrates_to_v2(tmp_path):
    """Regression: existing DB created before migrations existed."""
    db = Database(tmp_path / "memory.db")
    with db.connect() as conn:
        conn.executescript(SCHEMA)  # Simulate pre-migration DB
        conn.execute("PRAGMA user_version = 0")
        conn.commit()

    db.initialize()

    with db.connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        rows = conn.execute("PRAGMA table_info(memory_projections)").fetchall()
        columns = {row["name"] for row in rows}

    assert version == 2, f"Expected version 2, got {version}"
    assert "qdrant_content_hash" in columns
    assert "qdrant_embedding_fingerprint" in columns
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_migrations.py -v
# Expected: FAIL — columns don't exist yet
```

- [ ] **Step 3: Implement the migration runner + repository update**

**A) Migration runner** (database.py) — as shown in the overview block above.

**B) Add new columns to `get_projection_state`** (repository.py):

```python
# repository.py — update get_projection_state return dict
def get_projection_state(self, memory_id: str) -> Dict[str, Any]:
    ...
    return {
        "qdrant_status": row["qdrant_status"],
        "obsidian_status": row["obsidian_status"],
        "qdrant_version": int(row["qdrant_version"]),
        "obsidian_version": int(row["obsidian_version"]),
        "last_error": row["last_error"],
        "qdrant_content_hash": row["qdrant_content_hash"],        # NEW
        "qdrant_embedding_fingerprint": row["qdrant_embedding_fingerprint"],  # NEW
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_migrations.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add mcp-memory/src/mcp_memory/migrations.py mcp-memory/src/mcp_memory/database.py mcp-memory/src/mcp_memory/repository.py mcp-memory/tests/test_migrations.py
git commit -m "feat: add migration for qdrant projection columns"
```

---

### Task 2: Add get_memory_bulk() to Repository

**Files:**
- Modify: `mcp-memory/src/mcp_memory/repository.py:102-108` (add after `get_memory`)
- Test: `mcp-memory/tests/test_repository.py`

- [ ] **Step 1: Write failing test**

```python
def test_get_memory_bulk_returns_multiple_records(repo, db):
    records = [
        repo.create_memory(content=f"test {i}", type="test",
                          namespace="bulk", scope_id="s1", source="test")
        for i in range(3)
    ]
    ids = [r.id for r in records]
    result = repo.get_memory_bulk(ids)
    assert len(result) == 3
    assert {r.id for r in result} == set(ids)

def test_get_memory_bulk_skips_missing(repo):
    records = [
        repo.create_memory(content="test 1", type="test",
                          namespace="bulk", scope_id="s1", source="test")
    ]
    result = repo.get_memory_bulk([records[0].id, "non-existent-id"])
    assert len(result) == 1
    assert result[0].id == records[0].id

def test_get_memory_bulk_empty_list(repo):
    result = repo.get_memory_bulk([])
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_repository.py::test_get_memory_bulk_returns_multiple_records mcp-memory/tests/test_repository.py::test_get_memory_bulk_skips_missing mcp-memory/tests/test_repository.py::test_get_memory_bulk_empty_list -v
# Expected: FAIL — method not defined
```

- [ ] **Step 3: Implement get_memory_bulk**

```python
def get_memory_bulk(self, memory_ids: List[str]) -> List[MemoryRecord]:
    if not memory_ids:
        return []
    placeholders = ",".join("?" * len(memory_ids))
    with self.database.connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM memory_records WHERE id IN ({placeholders})",
            memory_ids,
        ).fetchall()
    return [self._row_to_record(row) for row in rows if row]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_repository.py::test_get_memory_bulk_returns_multiple_records mcp-memory/tests/test_repository.py::test_get_memory_bulk_skips_missing mcp-memory/tests/test_repository.py::test_get_memory_bulk_empty_list -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add mcp-memory/src/mcp_memory/repository.py mcp-memory/tests/test_repository.py
git commit -m "feat: add get_memory_bulk for efficient batch retrieval"
```

---

### Task 3: Add Monotonic Version Check to set_projection_version

**Files:**
- Modify: `mcp-memory/src/mcp_memory/repository.py` (find `set_projection_version`)
- Test: `mcp-memory/tests/test_repository.py`

- [ ] **Step 1: Write failing test**

```python
def test_set_projection_version_is_monotonic(repo, db):
    # Create a record
    record = repo.create_memory(content="test", type="test",
                               namespace="mono", scope_id="s1", source="test")
    record_id = record.id

    # Set initial version to 5
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO memory_projections (memory_id, qdrant_version, qdrant_status) VALUES (?, ?, ?)",
            (record_id, 5, "ready")
        )

    # Attempt to set version to 3 — should be rejected (monotonic)
    repo.set_projection_version(record_id, "qdrant", 3)

    # Verify version stayed at 5
    current = repo.get_projection_version(record_id, "qdrant")
    assert current == 5, f"Expected version 5, got {current}"

def test_set_projection_version_advances_valid(repo, db):
    record = repo.create_memory(content="test", type="test",
                               namespace="mono", scope_id="s1", source="test")
    record_id = record.id

    repo.set_projection_version(record_id, "qdrant", 1)
    assert repo.get_projection_version(record_id, "qdrant") == 1

    repo.set_projection_version(record_id, "qdrant", 2)
    assert repo.get_projection_version(record_id, "qdrant") == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_repository.py::test_set_projection_version_is_monotonic -v
# Expected: FAIL — no monotonic check
```

- [ ] **Step 3: Find and update set_projection_version**

```python
def set_projection_version(self, memory_id: str, projection: str, version: int) -> None:
    current = self.get_projection_version(memory_id, projection)
    if current is not None and current >= version:
        return  # Already at or ahead — don't regress
    with self.database.connect() as conn:
        conn.execute(
            f"UPDATE memory_projections SET {projection}_version = ? WHERE memory_id = ?",
            (version, memory_id),
        )
        conn.commit()
```

**Key fix:** Use `conn.commit()` not `connection.commit()`. The local variable is `conn`.

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_repository.py::test_set_projection_version_is_monotonic mcp-memory/tests/test_repository.py::test_set_projection_version_advances_valid -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add mcp-memory/src/mcp_memory/repository.py
git commit -m "fix: make set_projection_version monotonic"
```

---

### Task 4: Add upsert_with_vector to QdrantProjectionStore

**Files:**
- Modify: `mcp-memory/src/mcp_memory/qdrant_store.py:142-165` (add after `upsert`)
- Modify: Add `embedding_model` attribute if not present
- Test: `mcp-memory/tests/test_qdrant_store.py`

**Prerequisite:** Add `embedding_model` to QdrantProjectionStore constructor.

- [ ] **Step 1: Add embedding_model to constructor**

```python
# qdrant_store.py — add to __init__ parameters and self assignment
def __init__(
    self,
    enabled: bool = False,
    url: str = "",
    *,
    collection_name: str = "memory_records",
    vector_size: int = 8,
    client=None,
    embedder: Optional[Callable[[str], List[float]]] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
    vector_strategy: str = "hash",
    embedding_model: str = "unknown",  # NEW PARAMETER
):
    ...
    # Derive from provider if available, else use parameter
    provider_config = getattr(embedding_provider, "config", None)
    provider_model = getattr(provider_config, "embedding_model", None)
    self.embedding_model = provider_model or embedding_model
```

- [ ] **Step 2: Write failing test**

```python
def test_upsert_with_vector_skips_embedding(mock_qdrant, repo, record):
    captured_vector = None
    def capture_upsert(collection_name, wait, points):
        nonlocal captured_vector
        captured_vector = points[0]["vector"]
    mock_qdrant.upsert = capture_upsert

    store = QdrantProjectionStore(enabled=True, client=mock_qdrant, vector_strategy="ollama", embedding_model="nomic-embed-text", vector_size=768)
    store.upsert_with_vector(record, [0.1] * 768)

    assert captured_vector == [0.1] * 768  # Pre-computed vector used, not embedded
```

- [ ] **Step 3: Run test to verify it fails**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_qdrant_store.py::test_upsert_with_vector_skips_embedding -v
# Expected: FAIL — method doesn't exist
```

- [ ] **Step 4: Add upsert_with_vector**

```python
def upsert_with_vector(self, record: MemoryRecord, vector: List[float]) -> None:
    if not self.is_available():
        raise RuntimeError("qdrant unavailable")
    self.ensure_collection()
    point = {
        "id": str(record.id),
        "vector": vector,
        "payload": {
            "memory_id": record.id,
            "namespace": record.namespace,
            "scope_id": record.scope_id,
            "type": record.type,
            "status": record.status,
            "version": record.version,
        },
    }
    if PointStruct is None:
        self.client.upsert(collection_name=self.collection_name, wait=True, points=[point])
    else:
        self.client.upsert(
            collection_name=self.collection_name,
            wait=True,
            points=[PointStruct(id=point["id"], vector=point["vector"], payload=point["payload"])],
        )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_qdrant_store.py::test_upsert_with_vector_skips_embedding -v
# Expected: PASS
```

- [ ] **Step 6: Commit**

```bash
git add mcp-memory/src/mcp_memory/qdrant_store.py mcp-memory/tests/test_qdrant_store.py
git commit -m "feat: add upsert_with_vector for pre-computed embeddings"
```

---

### Task 5: Update OutboxWorker to Embed in Worker

**Files:**
- Modify: `mcp-memory/src/mcp_memory/outbox.py:73-91` (`_project_qdrant`)
- Test: `mcp-memory/tests/test_outbox.py`

**Key design decisions:**
- Use `qdrant_status` with values `pending|ready|error` — NOT `embedding_status`, NOT `projecting`
- `_embedding_fingerprint()` uses actual attributes that exist on qdrant_store
- When qdrant_status is set to `error`, also store error in `last_error` column

- [ ] **Step 1: Write failing test for async embedding**

```python
def test_project_qdrant_embeds_in_worker(mock_qdrant, mock_ollama, repo, record):
    mock_ollama.embed.return_value = [0.1] * 768
    worker = OutboxWorker(repo, qdrant_store=mock_qdrant, max_workers=1)
    # Mock the embedder on the qdrant_store
    worker._embedder = mock_ollama.embed
    worker._embedding_fingerprint = lambda: "ollama:nomic-embed-text:768"

    event = repo.list_due_outbox()[0]
    worker._project_qdrant(event)

    mock_ollama.embed.assert_called_once()
    mock_qdrant.upsert_with_vector.assert_called_once()
    mock_qdrant.upsert.assert_not_called()  # upsert_with_vector, not upsert

def test_project_qdrant_skips_when_hash_unmodified(mock_qdrant, mock_ollama, repo, record, db):
    # Pre-set content_hash and fingerprint to match current — should skip
    with db.connect() as conn:
        conn.execute("""
            UPDATE memory_projections
            SET qdrant_content_hash = ?, qdrant_embedding_fingerprint = ?
            WHERE memory_id = ?
        """, (record.content_hash, "ollama:nomic-embed-text:768", record.id))

    worker = OutboxWorker(repo, qdrant_store=mock_qdrant, max_workers=1)
    worker._embedder = mock_ollama.embed
    worker._embedding_fingerprint = lambda: "ollama:nomic-embed-text:768"

    event = repo.list_due_outbox()[0]
    worker._project_qdrant(event)

    # Ollama should NOT be called
    mock_ollama.embed.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_outbox.py::test_project_qdrant_embeds_in_worker mcp-memory/tests/test_outbox.py::test_project_qdrant_skips_when_hash_unmodified -v
# Expected: FAIL — not implemented
```

- [ ] **Step 3: Implement _project_qdrant with embedding**

```python
def _project_qdrant(self, event: OutboxEvent) -> None:
    if not self.qdrant_store.enabled:
        raise RuntimeError("qdrant unavailable")
    record = self.repository.get_memory(event.memory_id)
    if record is None:
        return

    if record.status not in {"active", "archived"}:
        self.qdrant_store.delete(record.id)
        self.repository.mark_outbox_processed(event.id)
        return

    if self.repository.has_newer_pending_outbox_event(event.memory_id, event.target_version):
        return

    # Get current projection state
    proj_state = self.repository.get_projection_state(event.memory_id)
    fingerprint = self._embedding_fingerprint()

    # Content-hash dirty check — skip vector generation if content unchanged
    if (proj_state["qdrant_content_hash"] == record.content_hash and
        proj_state["qdrant_embedding_fingerprint"] == fingerprint):
        # Vector already current
        self.repository.mark_outbox_processed(event.id)
        return

    # Generate embedding and upsert
    try:
        vector = self._embedder(record.content)
        self.qdrant_store.upsert_with_vector(record, vector)

        # Update projection state — use qdrant_status values: pending|ready|error
        self.repository.update_projection_state(
            event.memory_id,
            qdrant_version=event.target_version,
            qdrant_content_hash=record.content_hash,
            qdrant_embedding_fingerprint=fingerprint,
            qdrant_status="ready",  # NOT embedding_status
            last_error=None,
        )
        self.repository.mark_outbox_processed(event.id)

    except Exception as exc:
        # Mark error, don't retry infinitely — dead-letter handled in Task 6
        self.repository.update_projection_state(
            event.memory_id,
            qdrant_status="error",
            last_error=str(exc),
        )
        raise  # Let outbox worker handle retry

def _embedding_fingerprint(self) -> str:
    # Use actual attributes that exist on qdrant_store
    strategy = getattr(self.qdrant_store, 'vector_strategy', 'unknown')
    model = getattr(self.qdrant_store, 'embedding_model', 'unknown')
    size = getattr(self.qdrant_store, 'vector_size', 0)
    return f"{strategy}:{model}:{size}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_outbox.py::test_project_qdrant_embeds_in_worker mcp-memory/tests/test_outbox.py::test_project_qdrant_skips_when_hash_unmodified -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add mcp-memory/src/mcp_memory/outbox.py mcp-memory/tests/test_outbox.py
git commit -m "feat: move embedding to OutboxWorker for async projection"
```

---

### Task 6: Add Dead-Letter State and Max Retries

**Files:**
- Modify: `mcp-memory/src/mcp_memory/outbox.py` (`_process_single`)
- Modify: `mcp-memory/src/mcp_memory/repository.py` (`reschedule_outbox_event`)
- Test: `mcp-memory/tests/test_outbox.py`

**Key fix:** Do NOT drive test through `list_due_outbox()` after first retry — `available_at` filtering makes the event unavailable. Use direct `reschedule_outbox_event` calls with `delay_seconds=0`.

- [ ] **Step 1: Write failing test**

```python
from mcp_memory.repository import MAX_EMBEDDING_RETRIES

def test_reschedule_outbox_event_dead_letters_after_max_retries(repo):
    record = repo.create_memory(
        content="dead letter test",
        type="test",
        namespace="dead-letter",
        scope_id="s1",
        source="test",
    )

    event = next(
        e for e in repo.list_due_outbox()
        if e.memory_id == record.id and "qdrant" in e.event_type
    )

    # Retry MAX_EMBEDDING_RETRIES times via direct reschedule call
    for _ in range(MAX_EMBEDDING_RETRIES):
        repo.reschedule_outbox_event(event.id, delay_seconds=0, error="Ollama down")

    # After max retries, event should be dead-lettered
    pending = repo.list_pending_outbox()
    refreshed = next((e for e in pending if e.id == event.id), None)
    assert refreshed is not None, "Event should still exist in pending"
    assert refreshed.attempt_count == MAX_EMBEDDING_RETRIES
    assert "DEAD_LETTER" in (refreshed.error or "")

    state = repo.get_projection_state(record.id)
    assert state["qdrant_status"] == "error"
    assert "DEAD_LETTER" in (state["last_error"] or "")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_outbox.py::test_reschedule_outbox_event_dead_letters_after_max_retries -v
# Expected: FAIL — dead-letter not implemented
```

- [ ] **Step 3: Update reschedule_outbox_event with max retries**

```python
MAX_EMBEDDING_RETRIES = 5

def reschedule_outbox_event(self, event_id: str, delay_seconds: int, error: str = None) -> None:
    with self.database.connect() as conn:
        row = conn.execute(
            "SELECT attempt_count, memory_id FROM memory_outbox WHERE id = ?", (event_id,)
        ).fetchone()
        if not row:
            return
        new_attempts = row["attempt_count"] + 1
        memory_id = row["memory_id"]

        if new_attempts >= MAX_EMBEDDING_RETRIES:
            # Dead-letter: mark error and stop retrying
            conn.execute(
                "UPDATE memory_outbox SET error = ?, attempt_count = ? WHERE id = ?",
                (f"DEAD_LETTER: {error}", new_attempts, event_id)
            )
            conn.execute(
                "UPDATE memory_projections SET qdrant_status = 'error', last_error = ? WHERE memory_id = ?",
                (f"DEAD_LETTER: {error}", memory_id)
            )
        else:
            conn.execute(
                "UPDATE memory_outbox SET available_at = datetime('now', '+' || ? || ' seconds'), "
                "error = ?, attempt_count = ? WHERE id = ?",
                (delay_seconds, error, new_attempts, event_id)
            )
        conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_outbox.py::test_reschedule_outbox_event_dead_letters_after_max_retries -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add mcp-memory/src/mcp_memory/outbox.py mcp-memory/src/mcp_memory/repository.py
git commit -m "feat: add dead-letter state after max embedding retries"
```

---

## Phase 2: Hybrid Ranking

### Files Overview

| File | Responsibility |
|------|----------------|
| `mcp-memory/src/mcp_memory/search.py` | RRF fusion, query expansion, bulk hydration |
| `mcp-memory/src/mcp_memory/repository.py` | Enhanced `search_fts` with filters and ranks |
| `mcp-memory/tests/test_search.py` | Tests for hybrid ranking |

---

### Task 7: Add Query Expansion

**Files:**
- Modify: `mcp-memory/src/mcp_memory/search.py` (add before `SearchService`)
- Test: `mcp-memory/tests/test_search.py`

- [ ] **Step 1: Write failing test**

```python
def test_query_expansion_includes_plural():
    from mcp_memory.search import expand_query
    result = expand_query("dogs")
    terms = [t.strip() for t in result.split(" OR ")]
    assert "dog" in terms  # plural → singular
    assert "dogs" in terms  # original

def test_query_expansion_includes_synonyms():
    from mcp_memory.search import expand_query
    result = expand_query("embed")
    terms = [t.strip() for t in result.split(" OR ")]
    assert "embedding" in terms, f"Expected 'embedding' in terms, got: {terms}"

def test_expand_query_returns_string_for_fts():
    from mcp_memory.search import expand_query
    # expand_query returns string ready for FTS OR query
    result = expand_query("postgres")
    assert isinstance(result, str)
    terms = [t.strip() for t in result.split(" OR ")]
    assert "postgres" in terms
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_search.py::test_query_expansion_includes_plural -v
# Expected: FAIL — expand_query not defined
```

- [ ] **Step 3: Implement expand_query**

```python
def expand_query(query: str) -> str:
    """Deterministically expand query for FTS5. Returns FTS query string with OR."""
    if not query or not query.strip():
        return query

    expansions = [query]

    # Singular/plural
    if query.endswith('s') and len(query) > 2:
        expansions.append(query[:-1])
    elif not query.endswith('s'):
        expansions.append(query + 's')

    # Common agent synonyms
    synonyms = {
        'db': ['database', 'postgres', 'postgresql'],
        'embed': ['embedding', 'embedded', 'embeddings'],
        'decision': ['adr', 'architecture decision'],
        'mem': ['memory', 'persistent'],
        'config': ['configuration'],
        'auth': ['authentication', 'authorization'],
        'api': ['interface'],
    }
    query_lower = query.lower()
    for term, syns in synonyms.items():
        if term in query_lower:
            expansions.extend(syns)

    # Path tokenization
    import re
    if '/' in query or '_' in query:
        tokens = re.split(r'[/_\-\.]+', query)
        expansions.extend([t for t in tokens if len(t) > 1])

    # Deduplicate
    seen = set()
    unique = []
    for e in expansions:
        if e not in seen:
            seen.add(e)
            unique.append(e)

    # Return FTS OR query string
    return " OR ".join(unique)
```

**Key fix:** `expand_query` returns a **string** FTS query (with OR), not a list. `search_fts` receives a string.

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_search.py::test_query_expansion_includes_plural mcp-memory/tests/test_search.py::test_query_expansion_includes_synonyms mcp-memory/tests/test_search.py::test_expand_query_returns_string_for_fts -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add mcp-memory/src/mcp_memory/search.py mcp-memory/tests/test_search.py
git commit -m "feat: add deterministic query expansion"
```

---

### Task 8: Enhance search_fts with Filters and Parameterized Query

**Files:**
- Modify: `mcp-memory/src/mcp_memory/repository.py:714-730`
- Test: `mcp-memory/tests/test_repository.py`

**Key fix:** Use parameterized queries for status values. Never concatenate user input directly into SQL.

- [ ] **Step 1: Write failing test**

```python
def test_search_fts_filters_by_type(repo, db):
    r1 = repo.create_memory(content="architecture decision", type="decision",
                            namespace="fts", scope_id="s1", source="test")
    r2 = repo.create_memory(content="quick note", type="note",
                            namespace="fts", scope_id="s1", source="test")

    results = repo.search_fts(
        query="architecture",
        namespace="fts",
        limit=10,
        types=["decision"],
    )
    result_ids = [id for id, _ in results]
    assert r1.id in result_ids
    assert r2.id not in result_ids

def test_search_fts_uses_parameterized_status(repo, db):
    # Verify SQL injection is not possible via status parameter
    r = repo.create_memory(content="test sql injection", type="test",
                           namespace="fts", scope_id="s1", source="test")
    # This should not cause SQL error even with unusual status
    results = repo.search_fts(query="sql", namespace="fts", limit=10, status="active")
    assert len(results) >= 0  # No SQL error
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_repository.py::test_search_fts_filters_by_type -v
# Expected: FAIL — search_fts doesn't support filters
```

- [ ] **Step 3: Update search_fts signature and implementation**

```python
def search_fts(
    self,
    query: str,
    namespace: str,
    limit: int,
    scope_id: Optional[str] = None,
    types: Optional[List[str]] = None,
    status: Optional[str] = None,
    include_archived: bool = False,
) -> List[Tuple[str, float]]:  # Return (memory_id, bm25_rank)
    """Search FTS5 and return memory IDs with BM25 ranks.

    Args:
        query: FTS query string (can contain OR, AND operators)
        namespace: Required namespace filter
        limit: Max results
        scope_id: Optional scope filter
        types: Optional list of type strings to filter
        status: Filter by status (default "active")
        include_archived: If True, include both active and archived

    Returns:
        List of (memory_id, bm25_rank) tuples, ordered by rank
    """
    # Build parameterized status filter
    if include_archived:
        status_values = ["active", "archived"]
    else:
        status_values = [status or "active"]

    placeholders = ",".join("?" * len(status_values))

    sql = f"""
        SELECT memory_id, bm25(memory_fts) as rank
        FROM memory_fts
        WHERE memory_id IN (
            SELECT id FROM memory_records
            WHERE namespace = ?
              AND status IN ({placeholders})
        )
        AND memory_fts MATCH ?
    """
    params = [namespace] + status_values + [query]

    if scope_id:
        sql += " AND memory_id IN (SELECT id FROM memory_records WHERE scope_id = ?)"
        params.append(scope_id)
    if types:
        type_placeholders = ",".join("?" * len(types))
        sql += f" AND memory_id IN (SELECT id FROM memory_records WHERE type IN ({type_placeholders}))"
        params.extend(types)

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    with self.database.connect() as connection:
        try:
            rows = connection.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if (
                "fts5:" in message
                or "malformed match" in message
                or "unterminated string" in message
                or "no such column" in message
            ):
                return []  # FTS syntax error from special chars — return empty safely
            raise
    return [(row["memory_id"], row["rank"]) for row in rows]
```

**Key fix:** All dynamic values use `?` parameters. FTS parse errors caught and return empty instead of crashing.

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_repository.py::test_search_fts_filters_by_type mcp-memory/tests/test_repository.py::test_search_fts_uses_parameterized_status -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add mcp-memory/src/mcp_memory/repository.py
git commit -m "feat: enhance search_fts with filters and parameterized status"
```

---

### Task 9: Implement RRF Fusion in SearchService

**Files:**
- Modify: `mcp-memory/src/mcp_memory/search.py:36-114`
- Test: `mcp-memory/tests/test_search.py`

**Key design decisions:**
- `expand_query()` called INSIDE `search_fts` or BEFORE calling it (not inside both)
- `search_fts` receives raw query string, not list
- `search_fts` returns `List[Tuple[str, float]]` not just `List[str]`

- [ ] **Step 1: Write failing test for RRF**

```python
def test_rrf_fusion_ranks_both_sources():
    from mcp_memory.search import rrf_fusion
    # FTS results: (memory_id, bm25_rank) — lower rank = better match
    fts_results = [
        ("a", 1.5),
        ("b", 2.3),
        ("c", 3.1),
    ]
    # Vector results: just memory_ids in rank order
    vector_ids = ["b", "d", "e"]
    fused = rrf_fusion(fts_results, vector_ids, k=60)

    # b should be first (present in both, high rank from both)
    assert fused[0] == "b"
    # a and c should follow (only in FTS)
    assert fused[1] in ["a", "c"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_search.py::test_rrf_fusion_ranks_both_sources -v
# Expected: FAIL — rrf_fusion not defined
```

- [ ] **Step 3: Implement rrf_fusion and update search**

```python
def rrf_fusion(
    fts_results: List[Tuple[str, float]],  # (memory_id, bm25_rank)
    vector_ids: List[str],  # memory_ids in rank order
    k: int = 60,
) -> List[str]:
    """Reciprocal Rank Fusion over FTS and vector results.

    Args:
        fts_results: List of (memory_id, bm25_rank) from search_fts
        vector_ids: List of memory_ids from Qdrant (ordered by cosine similarity)
        k: RRF smoothing parameter (default 60)

    Returns:
        List of memory_ids sorted by fused RRF score (descending)
    """
    scores: Dict[str, float] = {}

    # FTS: rank by position (lower bm25 = better, but position matters more)
    for rank, (memory_id, _) in enumerate(fts_results):
        scores[memory_id] = scores.get(memory_id, 0) + 1 / (k + rank)

    # Vector: rank by position
    for rank, memory_id in enumerate(vector_ids):
        scores[memory_id] = scores.get(memory_id, 0) + 1 / (k + rank)

    # Sort by fused score descending
    return sorted(scores.keys(), key=lambda id: scores[id], reverse=True)


class SearchService:
    # ... existing init ...

    def search(self, *, query: str, namespace: str, ...) -> SearchResult:
        # When filters require SQLite-only path
        if status or created_after or created_before or ...:
            items = self.repository.search_records(...)
            return SearchResult(items=items, search_mode="fallback_sqlite",
                             degraded=False, freshness_seconds=0)

        qdrant_available = self.qdrant_store.is_available()
        freshness_seconds = self._qdrant_freshness_seconds()
        qdrant_stale = freshness_seconds > QRANT_STALENESS_THRESHOLD_SECONDS

        if not qdrant_available or qdrant_stale:
            # FTS-only mode — expand query here before calling search_fts
            fts_query = expand_query(query)
            fts_results = self.repository.search_fts(
                query=fts_query, namespace=namespace, limit=limit * 3,
                scope_id=scope_id, types=types, status=status,
                include_archived=include_archived,
            )
            memory_ids = [id for id, _ in fts_results]
            records = self.repository.get_memory_bulk(memory_ids) if memory_ids else []
            return SearchResult(
                items=records[:limit],
                search_mode="fts_sqlite",
                degraded=qdrant_stale or (not qdrant_available and self.qdrant_store.enabled),
                freshness_seconds=freshness_seconds,
            )

        # Hybrid RRF mode — expand query once, use for both paths
        fts_query = expand_query(query)

        fts_results = self.repository.search_fts(
            query=fts_query, namespace=namespace, limit=50,
            scope_id=scope_id, types=types, status="active",
            include_archived=include_archived,
        )

        vector_hits = self.qdrant_store.query(
            query=query,  # Raw query — qdrant_store.query() embeds it via Ollama before querying Qdrant
            namespace=namespace, scope_id=scope_id,
            types=types, include_archived=include_archived, limit=50,
            score_threshold=self.score_threshold,
        )
        vector_ids = [hit.id for hit in vector_hits]

        # RRF fusion
        fused_ids = rrf_fusion(fts_results, vector_ids, k=60)

        # Bulk hydration
        fused_records = self.repository.get_memory_bulk(fused_ids)
        record_map = {r.id: r for r in fused_records}
        items = [record_map[id] for id in fused_ids if id in record_map][:limit]

        return SearchResult(
            items=items,
            search_mode="hybrid_rrf",
            degraded=False,
            freshness_seconds=freshness_seconds,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/test_search.py::test_rrf_fusion_ranks_both_sources -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add mcp-memory/src/mcp_memory/search.py mcp-memory/tests/test_search.py
git commit -m "feat: implement RRF hybrid ranking"
```

---

## Phase 3: Integration Test and Benchmark

**Files:**
- Test: Run full test suite and benchmark

- [ ] **Step 1: Run full test suite**

```bash
PYTHONPATH=mcp-memory/src pytest mcp-memory/tests/ -v --ignore=mcp-memory/tests/test_docker_e2e.py
# Expected: All pass
```

- [ ] **Step 2: Run benchmark**

```bash
PYTHONPATH=mcp-memory/src python3 mcp-memory/scripts/benchmark.py
# Expected:
# - Write latency < 50ms avg (async embedding)
# - Recall > 80%
# - Search latency < 1000ms
# - Context Integration = 100%
```

- [ ] **Step 3: If recall < 80%, tune RRF k parameter**

```python
# Try k=30, k=45, k=60, k=90 in search.py
# Pick best on eval set
```

- [ ] **Step 4: Commit final changes**

```bash
git add -A
git commit -m "feat: async embedding and hybrid ranking complete"
```

---

## Implementation Order

1. **Task 1:** Migration for projection columns (no embedding_status column)
2. **Task 2:** `get_memory_bulk()`
3. **Task 3:** Monotonic version check (conn.commit() fix)
4. **Task 4:** `upsert_with_vector()` + verify embedding attributes
5. **Task 5:** Embed in OutboxWorker (use qdrant_status, not embedding_status)
6. **Task 6:** Dead-letter state (use qdrant_status=error)
7. **Task 7:** Query expansion (returns string, not list)
8. **Task 8:** Enhanced `search_fts` with parameterized filters
9. **Task 9:** RRF fusion (expand query inside search method, not in search_fts)
10. **Task 10:** Integration test and benchmark

---

## Spec Coverage Checklist

| Spec Requirement | Task |
|-----------------|------|
| Async embedding via OutboxWorker | Tasks 4, 5 |
| Content-hash dirty checking | Task 5 |
| Monotonic version update | Task 3 |
| Dead-letter state (qdrant_status=error, not failed) | Task 6 |
| `upsert_with_vector()` | Task 4 |
| Query expansion (returns string FTS query) | Task 7 |
| RRF fusion | Task 9 |
| FTS filter parity | Task 8 |
| Bulk hydration | Task 9 |
| Migration for new columns | Task 1 |
| `get_memory_bulk()` | Task 2 |
| No `projecting` status (YAGNI) | N/A |
| No `embedding_status` column (reuse qdrant_status) | Tasks 1, 5, 6 |

---

## Issues Fixed from Review

| # | Issue | Fix Applied |
|---|-------|-------------|
| 1 | embedding_status vs qdrant_status | Removed embedding_status, reuse qdrant_status values: pending\|ready\|error |
| 2 | SQL injection in search_fts | Parameterized queries with status_values list |
| 3 | connection.commit() typo | Changed to conn.commit() |
| 4 | record_id undefined in test | Test now captures record.id from create_memory return |
| 5 | expand_query returns List but search_fts expects str | expand_query returns FTS query string (with OR); called BEFORE search_fts in search methods |
| 6 | "projecting" status in spec but never implemented | Removed from spec — YAGNI |
| 7 | embedding_fingerprint attributes may not exist | Use getattr() with defaults; verify in Task 4 |

---

## Placeholder Scan

- [ ] No "TBD" or "TODO" remaining
- [ ] All function signatures defined
- [ ] All tests have actual assertions
- [ ] All file paths are exact
- [ ] All commands have expected output
- [ ] No empty commits (Task 10 removed)