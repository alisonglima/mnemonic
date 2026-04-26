from __future__ import annotations

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
        return connection

    def initialize(self) -> None:
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]

            for migration in MIGRATIONS:
                migration_version = int(migration["version"])
                if migration_version <= version:
                    continue

                conn.executescript(f"""
BEGIN IMMEDIATE;
{migration["sql"]}
PRAGMA user_version = {migration_version};
COMMIT;
""")
                version = migration_version
