from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from mcp_memory.embedding import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    OllamaEmbeddingProvider,
    EmbeddingConfig,
)


class TestHashEmbeddingProvider(unittest.TestCase):
    def test_returns_8_dim_vector_by_default(self) -> None:
        provider = HashEmbeddingProvider()
        vec = provider.embed("hello world")
        self.assertEqual(len(vec), 8)

    def test_returns_8_dim_vector_explicit_size(self) -> None:
        provider = HashEmbeddingProvider(size=8)
        vec = provider.embed("hello world")
        self.assertEqual(len(vec), 8)

    def test_deterministic_same_text_same_vector(self) -> None:
        provider = HashEmbeddingProvider()
        vec1 = provider.embed("hello world")
        vec2 = provider.embed("hello world")
        self.assertEqual(vec1, vec2)

    def test_different_text_different_vector(self) -> None:
        provider = HashEmbeddingProvider()
        vec1 = provider.embed("hello world")
        vec2 = provider.embed("goodbye world")
        self.assertNotEqual(vec1, vec2)

    def test_case_insensitive(self) -> None:
        provider = HashEmbeddingProvider()
        vec1 = provider.embed("Hello World")
        vec2 = provider.embed("hello world")
        self.assertEqual(vec1, vec2)

    def test_vector_values_in_range(self) -> None:
        provider = HashEmbeddingProvider()
        vec = provider.embed("test content")
        for val in vec:
            self.assertGreaterEqual(val, -1.0)
            self.assertLessEqual(val, 1.0)


class TestOllamaEmbeddingProvider(unittest.TestCase):
    def test_uses_ollama_url_from_config(self) -> None:
        config = EmbeddingConfig(ollama_url="http://localhost:11434")
        provider = OllamaEmbeddingProvider(config)
        self.assertEqual(provider.config.ollama_url, "http://localhost:11434")

    def test_embed_falls_back_to_hash_when_ollama_unavailable(self) -> None:
        config = EmbeddingConfig(ollama_url="http://localhost:11434")
        provider = OllamaEmbeddingProvider(config)
        # Without a running Ollama, should fall back to hash
        vec = provider.embed("test content")
        self.assertEqual(len(vec), 8)

    def test_embed_uses_hash_when_no_ollama_url(self) -> None:
        config = EmbeddingConfig(ollama_url="")
        provider = OllamaEmbeddingProvider(config)
        vec = provider.embed("test content")
        self.assertEqual(len(vec), 8)

    def test_embed_with_custom_model(self) -> None:
        config = EmbeddingConfig(ollama_url="http://localhost:11434", embedding_model="nomic-embed-text")
        provider = OllamaEmbeddingProvider(config)
        # Even without Ollama running, should try and fall back
        vec = provider.embed("test content")
        self.assertEqual(len(vec), 8)


if __name__ == "__main__":
    unittest.main()
