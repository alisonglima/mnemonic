from __future__ import annotations

import sys

from mcp_memory.config import Settings
from mcp_memory.scripts_restore import restore_database


def main() -> int:
    """
    Restore SQLite database from backup.

    Usage:
        python restore_sqlite.py [backup_path] [target_path]

    If no arguments are given, uses Settings.from_env() to determine paths.
    Backup is expected at SQLITE_PATH.backup.db and restores to SQLITE_PATH.
    """
    if len(sys.argv) >= 3:
        backup_path = sys.argv[1]
        target_path = sys.argv[2]
    else:
        settings = Settings.from_env()
        db_path = settings.database_path
        backup_path = str(db_path.with_suffix(".backup.db"))
        target_path = str(db_path)

    success = restore_database(backup_path, target_path)
    if success:
        print(f"Restored: {target_path}")
        return 0
    else:
        print(f"Backup not found: {backup_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())