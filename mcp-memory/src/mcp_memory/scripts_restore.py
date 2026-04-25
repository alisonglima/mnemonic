from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

# Exit codes
EXIT_SUCCESS = 0
EXIT_SOURCE_NOT_FOUND = 1
EXIT_SOURCE_FAILED_VALIDATION = 2
EXIT_PRE_RESTORE_BACKUP_FAILED = 3


def validate_source(path: Path) -> bool:
    """
    Validate the source SQLite database using PRAGMA integrity_check.
    Returns True if valid, False otherwise.
    """
    try:
        conn = sqlite3.connect(str(path))
        try:
            cursor = conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            return result is not None and result[0] == "ok"
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def restore_database(
    backup_path: Path | str,
    target_path: Path | str,
    *,
    dry_run: bool = False,
    no_backup: bool = False,
) -> int:
    """
    Restore the SQLite database from a backup file.

    Args:
        backup_path: Path to the backup file (e.g., memory.backup.db)
        target_path: Path to the target database file (e.g., memory.db)
        dry_run: If True, validate only without copying
        no_backup: If True, skip pre-restore backup of existing target

    Returns:
        EXIT_SUCCESS (0) if restore succeeded,
        EXIT_SOURCE_NOT_FOUND (1) if backup file does not exist,
        EXIT_SOURCE_FAILED_VALIDATION (2) if backup failed validation,
        EXIT_PRE_RESTORE_BACKUP_FAILED (3) if pre-restore backup of target failed.
    """
    backup_path = Path(backup_path)
    target_path = Path(target_path)

    if not backup_path.exists():
        return EXIT_SOURCE_NOT_FOUND

    if not validate_source(backup_path):
        return EXIT_SOURCE_FAILED_VALIDATION

    if dry_run:
        return EXIT_SUCCESS

    # Pre-restore backup of target if it exists and --no-backup not set
    if target_path.exists() and not no_backup:
        pre_restore_backup = target_path.with_suffix(target_path.suffix + ".pre-restore.db")
        try:
            shutil.copy2(target_path, pre_restore_backup)
        except OSError:
            return EXIT_PRE_RESTORE_BACKUP_FAILED

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, target_path)
    return EXIT_SUCCESS