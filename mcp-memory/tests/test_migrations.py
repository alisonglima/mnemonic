from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mcp_memory.database import Database
from mcp_memory.migrations import SCHEMA


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


def test_existing_v1_database_with_user_version_zero_migrates_to_v2(tmp_path):
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

    assert version == 2, f"Expected version 2, got {version}"
    assert "qdrant_content_hash" in columns
    assert "qdrant_embedding_fingerprint" in columns