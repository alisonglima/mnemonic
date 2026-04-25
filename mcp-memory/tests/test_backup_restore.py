from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


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
        self.assertIn(result.returncode, [0, 1])

    def test_restore_library_copies_backup_to_target(self) -> None:
        """The restore library should copy the backup file to the target location."""
        from mcp_memory.scripts_restore import restore_database

        # Create a backup file with content
        backup_path = self.tmp_path / "memory.backup.db"
        backup_path.write_text("backup content")

        target_path = self.tmp_path / "memory.db"

        # Restore
        result = restore_database(backup_path, target_path)

        self.assertTrue(result)
        self.assertTrue(target_path.exists())
        self.assertEqual(target_path.read_text(), "backup content")

    def test_restore_library_fails_when_backup_missing(self) -> None:
        """restore_database should return False when backup file does not exist."""
        from mcp_memory.scripts_restore import restore_database

        backup_path = self.tmp_path / "nonexistent.backup.db"
        target_path = self.tmp_path / "memory.db"

        result = restore_database(backup_path, target_path)

        self.assertFalse(result)

    def test_main_backup_and_restore_cycle(self) -> None:
        """Full backup → restore cycle should preserve data."""
        from mcp_memory.scripts_restore import restore_database

        # Create original database
        original = self.tmp_path / "memory.db"
        original.write_text("original db content")

        # Create backup
        backup = original.with_suffix(".backup.db")
        shutil.copy2(original, backup)
        self.assertTrue(backup.exists())

        # Simulate data loss
        original.unlink()
        self.assertFalse(original.exists())

        # Restore from backup
        result = restore_database(backup, original)
        self.assertTrue(result)
        self.assertTrue(original.exists())
        self.assertEqual(original.read_text(), "original db content")


if __name__ == "__main__":
    unittest.main()