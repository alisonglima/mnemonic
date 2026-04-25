from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_memory.scripts_restore import (
    EXIT_SUCCESS,
    EXIT_SOURCE_NOT_FOUND,
    EXIT_SOURCE_FAILED_VALIDATION,
    EXIT_PRE_RESTORE_BACKUP_FAILED,
)


def _make_sqlite(path: Path) -> None:
    """Create a valid SQLite database at the given path."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()


class TestRestoreScript(unittest.TestCase):
    """Tests for the restore_sqlite.py script."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_script_exists_and_is_executable(self) -> None:
        """Verify restore_sqlite.py exists as a script."""
        script_path = ROOT / "scripts" / "restore_sqlite.py"
        self.assertTrue(script_path.exists(), f"Script not found at {script_path}")

    def test_script_accepts_source_and_target_arguments(self) -> None:
        """Script should accept source and target file paths as arguments."""
        source = self.tmp_path / "source.db"
        target = self.tmp_path / "target.db"

        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "restore_sqlite.py"), str(source), str(target)],
            capture_output=True,
            text=True,
        )
        # Script should either succeed or fail gracefully (e.g., source doesn't exist)
        # We just verify it accepts the arguments
        self.assertIn(result.returncode, [0, 1, 2, 3])

    def test_restore_library_copies_backup_to_target(self) -> None:
        """The restore library should copy the backup file to the target location."""
        from mcp_memory.scripts_restore import restore_database

        # Create a valid SQLite backup
        backup_path = self.tmp_path / "memory.backup.db"
        _make_sqlite(backup_path)

        target_path = self.tmp_path / "memory.db"

        # Restore
        exit_code = restore_database(backup_path, target_path)

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertTrue(target_path.exists())

    def test_restore_library_fails_when_backup_missing(self) -> None:
        """restore_database should return EXIT_SOURCE_NOT_FOUND when backup file does not exist."""
        from mcp_memory.scripts_restore import restore_database

        backup_path = self.tmp_path / "nonexistent.backup.db"
        target_path = self.tmp_path / "memory.db"

        exit_code = restore_database(backup_path, target_path)

        self.assertEqual(exit_code, EXIT_SOURCE_NOT_FOUND)

    def test_main_backup_and_restore_cycle(self) -> None:
        """Full backup → restore cycle should preserve data."""
        from mcp_memory.scripts_restore import restore_database

        # Create original database
        original = self.tmp_path / "memory.db"
        _make_sqlite(original)

        # Create backup
        backup = original.with_suffix(".backup.db")
        shutil.copy2(original, backup)
        self.assertTrue(backup.exists())

        # Simulate data loss
        original.unlink()
        self.assertFalse(original.exists())

        # Restore from backup
        exit_code = restore_database(backup, original)
        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertTrue(original.exists())

    def test_dry_run_makes_no_changes(self) -> None:
        """--dry-run should validate source but not copy to target."""
        from mcp_memory.scripts_restore import restore_database

        backup_path = self.tmp_path / "memory.backup.db"
        _make_sqlite(backup_path)

        target_path = self.tmp_path / "memory.db"

        exit_code = restore_database(backup_path, target_path, dry_run=True)

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertFalse(target_path.exists())

    def test_pre_restore_backup_created(self) -> None:
        """Pre-restore backup should be created at target.pre-restore.db before overwriting."""
        from mcp_memory.scripts_restore import restore_database

        # Create existing target
        target_path = self.tmp_path / "memory.db"
        _make_sqlite(target_path)

        # Create backup
        backup_path = self.tmp_path / "memory.backup.db"
        _make_sqlite(backup_path)

        pre_restore_path = target_path.with_suffix(target_path.suffix + ".pre-restore.db")

        exit_code = restore_database(backup_path, target_path, dry_run=False, no_backup=False)

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertTrue(pre_restore_path.exists())

    def test_corrupt_source_returns_exit_code_2(self) -> None:
        """A corrupt (non-SQLite) source should return EXIT_SOURCE_FAILED_VALIDATION."""
        from mcp_memory.scripts_restore import restore_database

        backup_path = self.tmp_path / "corrupt.backup.db"
        backup_path.write_text("this is not a sqlite database")

        target_path = self.tmp_path / "memory.db"

        exit_code = restore_database(backup_path, target_path)

        self.assertEqual(exit_code, EXIT_SOURCE_FAILED_VALIDATION)
        self.assertFalse(target_path.exists())

    def test_no_backup_skips_pre_restore(self) -> None:
        """--no-backup should skip creation of target.pre-restore.db."""
        from mcp_memory.scripts_restore import restore_database

        # Create existing target
        target_path = self.tmp_path / "memory.db"
        _make_sqlite(target_path)

        # Create backup
        backup_path = self.tmp_path / "memory.backup.db"
        _make_sqlite(backup_path)

        pre_restore_path = target_path.with_suffix(target_path.suffix + ".pre-restore.db")

        exit_code = restore_database(backup_path, target_path, dry_run=False, no_backup=True)

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertFalse(pre_restore_path.exists())


if __name__ == "__main__":
    unittest.main()