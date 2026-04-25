from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from mcp_memory.config import Settings


class TestSettings(unittest.TestCase):
    def setUp(self) -> None:
        self.env_to_restore = os.environ.get("SQLITE_PATH")
        # Clear any existing env vars that might interfere
        for key in ["SQLITE_PATH", "OBSIDIAN_VAULT", "MCP_PORT", "QDRANT_URL", "QDRANT_COLLECTION", "OLLAMA_URL", "EMBEDDING_STRATEGY", "EMBEDDING_MODEL", "DEFAULT_NAMESPACE", "RETENTION_ACTION", "RETENTION_DAYS"]:
            if key in os.environ:
                del os.environ[key]

    def tearDown(self) -> None:
        if self.env_to_restore is not None:
            os.environ["SQLITE_PATH"] = self.env_to_restore

    def test_default_values(self) -> None:
        settings = Settings.from_env()
        self.assertEqual(settings.database_path, Path("./memory.db"))
        self.assertEqual(settings.vault_path, Path("./obsidian-vault"))
        self.assertEqual(settings.mcp_port, 8080)
        self.assertEqual(settings.qdrant_url, "")
        self.assertEqual(settings.qdrant_collection, "memory_records")
        self.assertEqual(settings.ollama_url, "")

    def test_embedding_strategy_defaults_to_hash(self) -> None:
        settings = Settings.from_env()
        self.assertEqual(settings.embedding_strategy, "hash")

    def test_embedding_model_defaults(self) -> None:
        settings = Settings.from_env()
        self.assertEqual(settings.embedding_model, "nomic-embed-text")

    def test_default_namespace_defaults(self) -> None:
        settings = Settings.from_env()
        self.assertEqual(settings.default_namespace, "")

    def test_retention_action_defaults_to_archive(self) -> None:
        settings = Settings.from_env()
        self.assertEqual(settings.retention_action, "archive")

    def test_retention_days_defaults_to_30(self) -> None:
        settings = Settings.from_env()
        self.assertEqual(settings.retention_days, 30)

    def test_env_override_embedding_strategy(self) -> None:
        os.environ["EMBEDDING_STRATEGY"] = "ollama"
        settings = Settings.from_env()
        self.assertEqual(settings.embedding_strategy, "ollama")

    def test_env_override_embedding_model(self) -> None:
        os.environ["EMBEDDING_MODEL"] = "mxbai-embed-large"
        settings = Settings.from_env()
        self.assertEqual(settings.embedding_model, "mxbai-embed-large")

    def test_env_override_default_namespace(self) -> None:
        os.environ["DEFAULT_NAMESPACE"] = "my-namespace"
        settings = Settings.from_env()
        self.assertEqual(settings.default_namespace, "my-namespace")

    def test_env_override_retention_action(self) -> None:
        os.environ["RETENTION_ACTION"] = "archive"
        settings = Settings.from_env()
        self.assertEqual(settings.retention_action, "archive")

    def test_env_override_retention_days(self) -> None:
        os.environ["RETENTION_DAYS"] = "90"
        settings = Settings.from_env()
        self.assertEqual(settings.retention_days, 90)

    def test_qdrant_collection_from_env(self) -> None:
        os.environ["QDRANT_COLLECTION"] = "my_collection"
        settings = Settings.from_env()
        self.assertEqual(settings.qdrant_collection, "my_collection")

    def test_ollama_url_from_env(self) -> None:
        os.environ["OLLAMA_URL"] = "http://localhost:11434"
        settings = Settings.from_env()
        self.assertEqual(settings.ollama_url, "http://localhost:11434")


if __name__ == "__main__":
    unittest.main()
