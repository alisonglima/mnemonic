from __future__ import annotations

import argparse
import sys

from mcp_memory.config import Settings
from mcp_memory.scripts_restore import (
    EXIT_SUCCESS,
    EXIT_SOURCE_NOT_FOUND,
    EXIT_SOURCE_FAILED_VALIDATION,
    EXIT_PRE_RESTORE_BACKUP_FAILED,
    restore_database,
)


def main() -> int:
    """
    Restore SQLite database from backup.

    Usage:
        python -m mcp_memory.scripts.restore_sqlite [backup_path] [target_path]

    Exit codes:
        0 = success
        1 = source backup not found
        2 = source failed validation (PRAGMA integrity_check)
        3 = pre-restore backup of target failed

    Options:
        --dry-run       Validate source but do not copy
        --no-backup     Skip pre-restore backup of existing target
    """
    parser = argparse.ArgumentParser(description="Restore SQLite database from backup")
    parser.add_argument("backup_path", nargs="?", help="Path to the backup file")
    parser.add_argument("target_path", nargs="?", help="Path to the target database")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate source but do not copy",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip pre-restore backup of existing target",
    )
    args = parser.parse_args()

    if args.backup_path and args.target_path:
        backup_path = args.backup_path
        target_path = args.target_path
    elif args.backup_path or args.target_path:
        print(
            "Error: both backup_path and target_path must be provided, or neither",
            file=sys.stderr,
        )
        return EXIT_SOURCE_NOT_FOUND
    else:
        settings = Settings.from_env()
        db_path = settings.database_path
        backup_path = str(db_path.with_suffix(".backup.db"))
        target_path = str(db_path)

    exit_code = restore_database(
        backup_path,
        target_path,
        dry_run=args.dry_run,
        no_backup=args.no_backup,
    )

    if exit_code == EXIT_SUCCESS:
        print(f"Restored: {target_path}")
    elif exit_code == EXIT_SOURCE_NOT_FOUND:
        print(f"Backup not found: {backup_path}", file=sys.stderr)
    elif exit_code == EXIT_SOURCE_FAILED_VALIDATION:
        print(f"Backup failed validation: {backup_path}", file=sys.stderr)
    elif exit_code == EXIT_PRE_RESTORE_BACKUP_FAILED:
        print(f"Pre-restore backup failed for: {target_path}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())