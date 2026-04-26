from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import List, Optional
from urllib.request import urlopen
from urllib.error import URLError

from pydantic import BaseModel


class EmbeddingConfig(BaseModel):
    ollama_url: str = ""
    embedding_model: str = "nomic-embed-text"
    embedding_strategy: str = "hash"
    embedding_size: int = 768


class EmbeddingProvider(ABC):
    """Protocol for embedding providers."""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Return a fixed-size vector for the given text."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider is available for embeddings."""
        ...


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic hash-based embedding (fallback when Ollama unavailable)."""

    def __init__(self, size: int = 8):
        self.size = size

    def embed(self, text: str) -> List[float]:
        import random
        seed = int.from_bytes(hashlib.sha256(text.lower().encode("utf-8")).digest(), "big")
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(self.size)]

    def is_available(self) -> bool:
        return True

    def strategy_name(self) -> str:
        return "hash"

    def vector_size(self) -> int:
        return self.size


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama-backed embedding provider with hash fallback."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self._fallback = HashEmbeddingProvider(size=config.embedding_size)

    def embed(self, text: str) -> List[float]:
        if not self.config.ollama_url:
            return self._fallback.embed(text)

        try:
            return self._embed_from_ollama(text)
        except Exception:  # noqa: BLE001
            return self._fallback.embed(text)

    def _embed_from_ollama(self, text: str) -> List[float]:
        import json
        import urllib.request

        if not self.config.ollama_url:
            raise RuntimeError("Ollama URL not configured")

        # /api/embed is the stable endpoint since Ollama 0.6.x
        # (/api/embeddings was removed in 0.6.x)
        url = f"{self.config.ollama_url.rstrip('/')}/api/embed"
        payload = json.dumps({"model": self.config.embedding_model, "input": text}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            embeddings = data.get("embeddings", [])
            return embeddings[0] if embeddings else []

    def is_available(self) -> bool:
        if not self.config.ollama_url:
            return False
        try:
            with urlopen(f"{self.config.ollama_url}/api/tags", timeout=1) as resp:
                return 200 <= resp.status < 300
        except (URLError, TimeoutError, ValueError):
            return False

    def strategy_name(self) -> str:
        return "ollama"

    def vector_size(self) -> int:
        return self.config.embedding_size


def create_embedding_provider(config: EmbeddingConfig) -> EmbeddingProvider:
    """Factory function to create the appropriate embedding provider."""
    if config.embedding_strategy == "ollama" and config.ollama_url:
        return OllamaEmbeddingProvider(config)
    return HashEmbeddingProvider(size=config.embedding_size)
