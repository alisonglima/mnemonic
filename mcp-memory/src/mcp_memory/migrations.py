from __future__ import annotations

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_records (
  id TEXT PRIMARY KEY,
  namespace TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  type TEXT NOT NULL,
  obsidian_projection INTEGER NOT NULL DEFAULT 0,
  content TEXT NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  version INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  idempotency_key TEXT,
  tags_json TEXT NOT NULL,
  notes_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_revisions (
  id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  content TEXT NOT NULL,
  type TEXT NOT NULL,
  status TEXT NOT NULL,
  tags_snapshot TEXT NOT NULL,
  notes_snapshot TEXT NOT NULL,
  metadata_snapshot TEXT NOT NULL,
  changed_by TEXT NOT NULL,
  changed_at TEXT NOT NULL,
  change_reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_projections (
  memory_id TEXT PRIMARY KEY,
  qdrant_version INTEGER NOT NULL DEFAULT 0,
  obsidian_version INTEGER NOT NULL DEFAULT 0,
  qdrant_status TEXT NOT NULL DEFAULT 'pending',
  obsidian_status TEXT NOT NULL DEFAULT 'pending',
  last_qdrant_sync_at TEXT,
  last_obsidian_sync_at TEXT,
  last_error TEXT
);

CREATE TABLE IF NOT EXISTS memory_outbox (
  id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  target_version INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  available_at TEXT NOT NULL,
  processed_at TEXT,
  error TEXT
);

-- FTS5 for full-text search over memory content and tags
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  memory_id,
  content,
  tags,
  tokenize='unicode61'
);
"""

MIGRATIONS = [
    {
        "version": 1,
        "sql": SCHEMA,
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
