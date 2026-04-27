from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from mcp_memory.migrations import MIGRATIONS


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        # Per-connection pragmas — wal_autocheckpoint and synchronous are
        # connection-local (not persisted), so set on every connection.
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.commit()

            version = conn.execute("PRAGMA user_version").fetchone()[0]

            for migration in MIGRATIONS:
                migration_version = int(migration["version"])
                if migration_version <= version:
                    continue

                if "ALTER TABLE" in migration["sql"]:
                    # Idempotent ALTER TABLE: check existing columns first.
                    # Handles the case where migration ran but user_version didn't persist.
                    existing = {row["name"] for row in
                        conn.execute("PRAGMA table_info(memory_projections)").fetchall()}
                    statements = self._filter_alter_statements(migration["sql"], existing)
                    if statements:
                        conn.executescript(f"BEGIN IMMEDIATE;\n{statements}\nCOMMIT;")
                else:
                    conn.executescript(f"BEGIN IMMEDIATE;\n{migration['sql']}\nCOMMIT;")

                # Set user_version separately — executescript + PRAGMA is unreliable
                conn.execute(f"PRAGMA user_version = {migration_version}")
                conn.commit()
                version = migration_version

    def run_wal_checkpoint(self) -> None:
        """Run a passive WAL checkpoint to control WAL file growth."""
        with self.connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

    @staticmethod
    def _filter_alter_statements(sql: str, existing_columns: set) -> str:
        """Remove ALTER TABLE ADD COLUMN statements for columns that already exist."""
        statements = []
        for stmt in sql.strip().rstrip(";").split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            m = re.match(r"ALTER\s+TABLE\s+\w+\s+ADD\s+COLUMN\s+(\w+)", stmt, re.IGNORECASE)
            if m and m.group(1) in existing_columns:
                continue  # Column already exists — skip
            statements.append(stmt)
        return ";\n".join(statements) + ";"
