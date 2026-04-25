from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_memory.database import Database
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository


class PlanAlignmentTests(unittest.TestCase):
    @unittest.skipIf(sys.version_info < (3, 11), "plan requires Python 3.11+")
    def test_project_metadata_matches_v2_plan(self) -> None:
        import tomllib

        pyproject = Path(__file__).parents[1] / "pyproject.toml"
        metadata = tomllib.loads(pyproject.read_text())

        project = metadata["project"]
        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertIn("pydantic>=2", project["dependencies"])
        self.assertIn("pytest", metadata["project"]["optional-dependencies"]["dev"])

    @unittest.skipIf(sys.version_info < (3, 11), "plan requires Python 3.11+")
    def test_models_and_settings_are_pydantic_models(self) -> None:
        from pydantic import BaseModel

        from mcp_memory.config import Settings
        from mcp_memory.models import MemoryRecord

        self.assertTrue(issubclass(MemoryRecord, BaseModel))
        self.assertTrue(issubclass(Settings, BaseModel))

    @unittest.skipIf(sys.version_info < (3, 11), "plan requires Python 3.11+")
    def test_fastmcp_is_a_required_runtime_dependency(self) -> None:
        sys.modules.pop("mcp_memory.main", None)
        with patch.dict(sys.modules, {"fastmcp": None}):
            with self.assertRaises(ModuleNotFoundError):
                __import__("mcp_memory.main")
        sys.modules.pop("mcp_memory.main", None)

    @unittest.skipIf(sys.version_info < (3, 11), "plan requires Python 3.11+")
    def test_health_checks_ollama_when_configured(self) -> None:
        from mcp_memory.config import Settings
        from mcp_memory.health import HealthService

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db = Database(tmp_path / "memory.db")
            db.initialize()
            repository = MemoryRepository(db)
            settings = Settings(
                database_path=tmp_path / "memory.db",
                vault_path=tmp_path,
                ollama_url="http://ollama:11434",
            )
            health = HealthService(settings, repository, QdrantProjectionStore())

            class _Response:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            with patch("mcp_memory.health.urlopen", return_value=_Response()) as urlopen:
                status = health.status()

            self.assertEqual(status["ollama"], "up")
            urlopen.assert_called_once_with("http://ollama:11434/api/tags", timeout=1)


if __name__ == "__main__":
    unittest.main()
