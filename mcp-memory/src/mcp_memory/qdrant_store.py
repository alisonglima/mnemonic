from __future__ import annotations

import hashlib
from urllib.error import URLError
from urllib.request import urlopen
from typing import Callable, List, Optional

from mcp_memory.embedding import EmbeddingProvider, HashEmbeddingProvider
from mcp_memory.models import MemoryRecord, SearchHit

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, Filter, MatchValue, PointIdsList, PointStruct, VectorParams, FieldCondition
except Exception:  # noqa: BLE001
    QdrantClient = None
    Distance = Filter = MatchValue = PointIdsList = PointStruct = VectorParams = FieldCondition = None


def simple_embed(text: str, size: int = 8) -> List[float]:
    digest = hashlib.sha256(text.lower().encode("utf-8")).digest()
    values = []
    for index in range(size):
        values.append((digest[index] / 255.0) * 2 - 1)
    return values


class QdrantProjectionStore:
    def __init__(
        self,
        enabled: bool = False,
        url: str = "",
        *,
        collection_name: str = "memory_records",
        vector_size: int = 8,
        client=None,
        embedder: Optional[Callable[[str], List[float]]] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        vector_strategy: str = "hash",
    ):
        self.enabled = enabled
        self.url = url.rstrip("/")
        self.supported = client is not None or QdrantClient is not None
        self.collection_name = collection_name
        self.vector_strategy = vector_strategy

        # Embedding provider takes precedence over simple embedder callable
        # Derive vector_size from provider when available
        if embedding_provider is not None:
            self._embedding_provider = embedding_provider
            self._embedder = embedding_provider.embed
            self.vector_size = embedding_provider.vector_size()
        elif embedder is not None:
            self._embedder = embedder
            self._embedding_provider = None
            self.vector_size = vector_size
        else:
            self._embedding_provider = HashEmbeddingProvider(size=vector_size)
            self._embedder = self._embedding_provider.embed
            self.vector_size = vector_size

        if client is not None:
            self.client = client
        elif self.enabled and self.url and QdrantClient is not None:
            self.client = QdrantClient(self.url)
        else:
            self.client = None

    def is_available(self) -> bool:
        if not self.enabled or not self.url or not self.supported or self.client is None:
            return False
        if hasattr(self.client, "get_collections"):
            try:
                self.client.get_collections()
                return True
            except Exception:  # noqa: BLE001
                return False
        try:
            with urlopen(f"{self.url}/healthz", timeout=1) as response:  # noqa: S310
                return 200 <= getattr(response, "status", 0) < 300
        except (URLError, TimeoutError, ValueError):
            return False

    def health(self) -> str:
        return "up" if self.is_available() else "down"

    def search(self, *_args, **_kwargs) -> List[MemoryRecord]:
        raise NotImplementedError

    def ensure_collection(self) -> None:
        if self.client is None:
            raise RuntimeError("qdrant unavailable")
        if hasattr(self.client, "collection_exists") and self.client.collection_exists(self.collection_name):
            return
        if hasattr(self.client, "create_collection"):
            if VectorParams is None:
                self.client.create_collection(collection_name=self.collection_name, vectors_config={"size": self.vector_size, "distance": "Cosine"})
            else:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
                )

    def query(
        self,
        *,
        query: str,
        namespace: str,
        scope_id: Optional[str],
        types: Optional[List[str]],
        include_archived: bool,
        limit: int,
    ) -> List[SearchHit]:
        if not self.is_available():
            return []
        self.ensure_collection()
        statuses = ["active"] + (["archived"] if include_archived else [])
        conditions = [{"key": "status", "match": status} for status in statuses]
        conditions.append({"key": "namespace", "match": namespace})
        if scope_id:
            conditions.append({"key": "scope_id", "match": scope_id})
        if types:
            for item in types:
                conditions.append({"key": "type", "match": item})
        hits = self.client.query_points(
            collection_name=self.collection_name,
            query=self._embedder(query),
            limit=limit,
            query_filter=conditions,
            with_payload=True,
            with_vectors=False,
        )
        return [SearchHit(id=str(hit.id), score=float(hit.score), payload=dict(hit.payload)) for hit in hits.points]

    def upsert(self, _record: MemoryRecord) -> None:
        if not self.is_available():
            raise RuntimeError("qdrant unavailable")
        self.ensure_collection()
        point = {
            "id": str(_record.id),
            "vector": self._embedder(_record.content),
            "payload": {
                "memory_id": _record.id,
                "namespace": _record.namespace,
                "scope_id": _record.scope_id,
                "type": _record.type,
                "status": _record.status,
                "version": _record.version,
            },
        }
        if PointStruct is None:
            self.client.upsert(collection_name=self.collection_name, wait=True, points=[point])
        else:
            self.client.upsert(
                collection_name=self.collection_name,
                wait=True,
                points=[PointStruct(id=point["id"], vector=point["vector"], payload=point["payload"])],
            )

    def delete(self, _memory_id: str) -> None:
        if not self.is_available():
            raise RuntimeError("qdrant unavailable")
        self.ensure_collection()
        if PointIdsList is None:
            self.client.delete(collection_name=self.collection_name, points_selector={"points": [str(_memory_id)]}, wait=True)
        else:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=[str(_memory_id)]),
                wait=True,
            )
