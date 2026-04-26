from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp_memory.qdrant_store import QdrantProjectionStore


@pytest.fixture
def mock_qdrant():
    store = QdrantProjectionStore(enabled=True, url="http://localhost:6333")
    store.client = MagicMock()
    store.client.collection_exists.return_value = True
    store.client.get_collections.return_value = MagicMock()
    return store


def test_upsert_with_vector_skips_embedding(mock_qdrant):
    """Verify upsert_with_vector passes pre-computed vector instead of calling embed()."""
    mock_qdrant.is_available = lambda: True
    record = MagicMock()
    record.id = "test-id"
    record.namespace = "ns"
    record.scope_id = "s1"
    record.type = "note"
    record.status = "active"
    record.version = 1
    record.content = "test content"

    vector = [0.1] * 768
    mock_qdrant.upsert_with_vector(record, vector)

    # Verify upsert was called with the pre-computed vector
    mock_qdrant.client.upsert.assert_called_once()
    call_kwargs = mock_qdrant.client.upsert.call_args[1]
    assert call_kwargs["collection_name"] == "memory_records"
    points = call_kwargs["points"]
    assert len(points) == 1
    # points[0] may be a dict (when PointStruct is None) or a PointStruct
    actual_vector = points[0].vector if hasattr(points[0], "vector") else points[0]["vector"]
    assert actual_vector == vector