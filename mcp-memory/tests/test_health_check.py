from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_memory.config import Settings
from mcp_memory.database import Database
from mcp_memory.repository import MemoryRepository
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.search import SearchService


class TestHealthCheck(unittest.TestCase):
    """Tests for the health_check module."""

    def setUp(self) -> None:
        self.tmpdir = MagicMock()
        self.tmp_path = Path("/tmp/healthcheck_test")
        self.tmp_path.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        pass

    def test_docker_health_returns_expected_keys(self) -> None:
        """Verify docker_health returns sqlite, qdrant, ollama, worker keys."""
        from mcp_memory.health_check import docker_health
        result = docker_health(sqlite_path=self.tmp_path / "memory.db")
        self.assertIn("sqlite", result)
        self.assertIn("qdrant", result)
        self.assertIn("ollama", result)
        self.assertIn("worker", result)

    def test_sqlite_check_returns_up_when_file_exists(self) -> None:
        """SQLite check should return 'up' when db file exists."""
        from mcp_memory.health_check import docker_health
        db_path = self.tmp_path / "memory.db"
        db_path.touch()
        result = docker_health(sqlite_path=db_path)
        self.assertEqual(result["sqlite"], "up")

    def test_sqlite_check_returns_down_when_file_missing(self) -> None:
        """SQLite check should return 'down' when db file does not exist."""
        from mcp_memory.health_check import docker_health
        db_path = self.tmp_path / "nonexistent.db"
        result = docker_health(sqlite_path=db_path)
        self.assertEqual(result["sqlite"], "down")

    def test_qdrant_check_uses_healthz_endpoint(self) -> None:
        """Qdrant Docker health should use the endpoint exposed by the image."""
        from mcp_memory.health_check import _qdrant_check

        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch("mcp_memory.health_check.urlopen", return_value=_Response()) as urlopen:
            result = _qdrant_check("http://qdrant:6333")

        self.assertEqual(result, "up")
        urlopen.assert_called_once_with("http://qdrant:6333/healthz", timeout=2)


if __name__ == "__main__":
    unittest.main()
