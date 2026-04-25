from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp_memory.database import Database
from mcp_memory.qdrant_store import QdrantProjectionStore
from mcp_memory.repository import MemoryRepository
from mcp_memory.search import SearchService


def _repo(tmp_path: Path) -> MemoryRepository:
    db = Database(tmp_path / "memory.db")
    db.initialize()
    return MemoryRepository(db)


class _FakeQdrantClient:
    def __init__(self) -> None:
        self.points = {}
        self.last_filter = None

    def get_collections(self):
        return {"collections": []}

    def collection_exists(self, _name: str) -> bool:
        return True

    def create_collection(self, **_kwargs) -> None:
        return None

    def upsert(self, *, collection_name: str, wait: bool, points):
        for point in points:
            # Accept both dict points and qdrant-client PointStruct-like objects
            if hasattr(point, "id"):
                self.points[str(point.id)] = {"id": point.id, "vector": point.vector, "payload": point.payload}
            else:
                self.points[str(point["id"])] = point

    def delete(self, *, collection_name: str, points_selector, wait: bool):
        for point_id in points_selector["points"]:
            self.points.pop(str(point_id), None)

    def query_points(self, *, collection_name: str, query, limit: int, query_filter=None, with_payload=True, with_vectors=False):
        hits = []
        self.last_filter = query_filter
        allowed_statuses = None
        allowed_namespace = None
        allowed_scope = None
        allowed_types = None
        if query_filter:
            allowed_statuses = {condition["match"] for condition in query_filter if condition["key"] == "status"}
            namespaces = {condition["match"] for condition in query_filter if condition["key"] == "namespace"}
            scopes = {condition["match"] for condition in query_filter if condition["key"] == "scope_id"}
            types = {condition["match"] for condition in query_filter if condition["key"] == "type"}
            allowed_namespace = next(iter(namespaces)) if namespaces else None
            allowed_scope = next(iter(scopes)) if scopes else None
            allowed_types = types or None
        for point in self.points.values():
            payload = point["payload"]
            if allowed_statuses and payload.get("status") not in allowed_statuses:
                continue
            if allowed_namespace and payload.get("namespace") != allowed_namespace:
                continue
            if allowed_scope and payload.get("scope_id") != allowed_scope:
                continue
            if allowed_types and payload.get("type") not in allowed_types:
                continue
            score = sum(a * b for a, b in zip(query, point["vector"]))
            hits.append(type("Hit", (), {"id": point["id"], "score": score, "payload": payload}))
        hits.sort(key=lambda item: item.score, reverse=True)
        return type("QueryResult", (), {"points": hits[:limit]})


class SearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.repo = _repo(self.tmp_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_search_defaults_to_active_records(self) -> None:
        active = self.repo.create_memory(
            content="Active guidance for the memory stack.",
            type="decision",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )
        archived = self.repo.create_memory(
            content="Archived guidance for the memory stack.",
            type="decision",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )
        self.repo.archive_memory(archived.id)

        service = SearchService(self.repo)
        result = service.search(query="guidance", namespace="project", scope_id="mnemonic")

        ids = [item.id for item in result.items]
        self.assertIn(active.id, ids)
        self.assertNotIn(archived.id, ids)
        self.assertEqual(result.search_mode, "fallback_sqlite")

    def test_include_retracted_uses_sqlite_only(self) -> None:
        record = self.repo.create_memory(
            content="Retracted memory",
            type="mistake",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )
        self.repo.retract_memory(record.id, expected_version=1, reason="superseded")

        service = SearchService(self.repo)
        result = service.search(
            query="Retracted",
            namespace="project",
            scope_id="mnemonic",
            include_retracted=True,
        )

        self.assertEqual(result.search_mode, "fallback_sqlite")
        self.assertEqual(result.items[0].status, "retracted")

    def test_hybrid_search_prefers_qdrant_when_available(self) -> None:
        record = self.repo.create_memory(
            content="Semantic retrieval target",
            type="decision",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )
        fake_client = _FakeQdrantClient()
        store = QdrantProjectionStore(enabled=True, url="http://fake", client=fake_client)
        store.upsert(record)

        service = SearchService(self.repo, store)
        result = service.search(query="Semantic retrieval target", namespace="project", scope_id="mnemonic")

        self.assertEqual(result.search_mode, "hybrid")
        self.assertFalse(result.degraded)
        self.assertEqual(result.items[0].id, record.id)

    def test_qdrant_query_applies_namespace_scope_type_filters(self) -> None:
        matching = self.repo.create_memory(
            content="Matching record",
            type="decision",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )
        other_scope = self.repo.create_memory(
            content="Other scope",
            type="decision",
            namespace="project",
            scope_id="other-scope",
            source="human",
        )
        other_type = self.repo.create_memory(
            content="Other type",
            type="mistake",
            namespace="project",
            scope_id="mnemonic",
            source="human",
        )
        fake_client = _FakeQdrantClient()
        store = QdrantProjectionStore(enabled=True, url="http://fake", client=fake_client)
        store.upsert(matching)
        store.upsert(other_scope)
        store.upsert(other_type)

        service = SearchService(self.repo, store)
        result = service.search(
            query="Matching",
            namespace="project",
            scope_id="mnemonic",
            types=["decision"],
        )

        ids = [item.id for item in result.items]
        self.assertIn(matching.id, ids)
        self.assertNotIn(other_scope.id, ids)
        self.assertNotIn(other_type.id, ids)


if __name__ == "__main__":
    unittest.main()
