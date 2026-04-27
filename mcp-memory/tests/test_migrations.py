from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mcp_memory.database import Database
from mcp_memory.migrations import CURRENT_SCHEMA_VERSION, SCHEMA


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def test_migration_adds_projection_columns(temp_db):
    db = Database(temp_db / "test.db")
    db.initialize()
    with db.connect() as conn:
        rows = conn.execute("PRAGMA table_info(memory_projections)").fetchall()
        cols = [r["name"] for r in rows]
    assert "qdrant_content_hash" in cols
    assert "qdrant_embedding_fingerprint" in cols


def test_existing_v1_database_with_user_version_zero_migrates_to_v3(tmp_path):
    """Regression: existing DB created before migrations existed."""
    db = Database(tmp_path / "memory.db")
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA user_version = 0")
        conn.commit()

    db.initialize()

    with db.connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        rows = conn.execute("PRAGMA table_info(memory_projections)").fetchall()
        columns = {row["name"] for row in rows}
        # Check v3 indexes exist
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_memory_records%'"
        ).fetchall()
        index_names = {idx["name"] for idx in indexes}

    assert version == 3, f"Expected version 3, got {version}"
    assert "qdrant_content_hash" in columns
    assert "qdrant_embedding_fingerprint" in columns
    assert "idx_memory_records_namespace_status" in index_names
    assert "idx_memory_records_scope_id" in index_names


def test_migration_runner_sets_user_version_correctly(tmp_path):
    """Regression: PRAGMA user_version must persist after migration."""
    db = Database(tmp_path / "memory.db")
    db.initialize()

    with db.connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == CURRENT_SCHEMA_VERSION, f"user_version should be {CURRENT_SCHEMA_VERSION}, got {version}"


def test_initialize_is_idempotent(tmp_path):
    """initialize() called twice must not crash (duplicate column names)."""
    db = Database(tmp_path / "memory.db")
    db.initialize()
    db.initialize()
    with db.connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == CURRENT_SCHEMA_VERSION


def test_initialize_recovers_from_stale_user_version(tmp_path):
    """Simulate the P0 bug: v2 columns exist but user_version is 0."""
    db = Database(tmp_path / "memory.db")
    # Create schema with v2 columns but user_version = 0 (broken state)
    with db.connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memory_records (
              id TEXT PRIMARY KEY, namespace TEXT NOT NULL, scope_id TEXT NOT NULL,
              type TEXT NOT NULL, obsidian_projection INTEGER NOT NULL DEFAULT 0,
              content TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
              version INTEGER NOT NULL, content_hash TEXT NOT NULL, idempotency_key TEXT,
              tags_json TEXT NOT NULL, notes_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_revisions (
              id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, version INTEGER NOT NULL,
              content TEXT NOT NULL, type TEXT NOT NULL, status TEXT NOT NULL,
              tags_snapshot TEXT NOT NULL, notes_snapshot TEXT NOT NULL,
              metadata_snapshot TEXT NOT NULL, changed_by TEXT NOT NULL,
              changed_at TEXT NOT NULL, change_reason TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_projections (
              memory_id TEXT PRIMARY KEY, qdrant_version INTEGER NOT NULL DEFAULT 0,
              obsidian_version INTEGER NOT NULL DEFAULT 0, qdrant_status TEXT NOT NULL DEFAULT 'pending',
              obsidian_status TEXT NOT NULL DEFAULT 'pending', last_qdrant_sync_at TEXT,
              last_obsidian_sync_at TEXT, last_error TEXT,
              qdrant_content_hash TEXT, qdrant_embedding_fingerprint TEXT
            );
            CREATE TABLE IF NOT EXISTS memory_outbox (
              id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, event_type TEXT NOT NULL,
              target_version INTEGER NOT NULL, payload_json TEXT NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL,
              processed_at TEXT, error TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
              memory_id, content, tags, tokenize='unicode61'
            );
        """)
        conn.execute("PRAGMA user_version = 0")
        conn.commit()

    # initialize() must not crash — columns already exist
    db.initialize()

    with db.connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        rows = conn.execute("PRAGMA table_info(memory_projections)").fetchall()
        columns = {row["name"] for row in rows}

    assert version == CURRENT_SCHEMA_VERSION
    assert "qdrant_content_hash" in columns
    assert "qdrant_embedding_fingerprint" in columns
