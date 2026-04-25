from __future__ import annotations

import shutil
from pathlib import Path


def restore_database(backup_path: Path | str, target_path: Path | str) -> bool:
    """
    Restore the SQLite database from a backup file.

    Args:
        backup_path: Path to the backup file (e.g., memory.backup.db)
        target_path: Path to the target database file (e.g., memory.db)

    Returns:
        True if restore succeeded, False if backup file does not exist.
    """
    backup_path = Path(backup_path)
    target_path = Path(target_path)

    if not backup_path.exists():
        return False

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, target_path)
    return True