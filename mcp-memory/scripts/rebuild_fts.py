#!/usr/bin/env python3
"""Rebuild FTS5 index from SQLite source of truth."""
from pathlib import Path

from mcp_memory.database import Database
from mcp_memory.repository import MemoryRepository


def rebuild_fts(db_path: Path) -> int:
    db = Database(db_path)
    db.initialize()
    repo = MemoryRepository(db)

    # Clear FTS table
    with db.connect() as conn:
        conn.execute("DELETE FROM memory_fts")

    # Reindex all records
    count = 0
    for record in repo.list_records():
        if record.status in {"active", "archived"}:
            with db.connect() as conn:
                tags_str = " ".join(record.tags)
                conn.execute(
                    "INSERT OR REPLACE INTO memory_fts (memory_id, content, tags) VALUES (?, ?, ?)",
                    (record.id, record.content, tags_str),
                )
                count += 1

    with db.connect() as conn:
        conn.commit()
    return count


if __name__ == "__main__":
    import sys

    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./data/memory.db")
    count = rebuild_fts(db_path)
    print(f"Indexed {count} records into FTS5")
