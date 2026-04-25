from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Callable, Dict, List, Optional


JsonDict = Dict[str, Any]
JsonList = List[Any]


class MemoryRecord(BaseModel):
    id: str
    content: str
    type: str
    namespace: str
    scope_id: str
    source: str
    status: str
    version: int
    content_hash: str
    idempotency_key: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    notes: List[JsonDict] = Field(default_factory=list)
    metadata: JsonDict = Field(default_factory=dict)
    obsidian_projection: bool = False
    created_at: str = ""
    updated_at: str = ""


class MemoryRevision(BaseModel):
    id: str
    memory_id: str
    version: int
    content: str
    type: str
    status: str
    tags_snapshot: List[str]
    notes_snapshot: List[JsonDict]
    metadata_snapshot: JsonDict
    changed_by: str
    changed_at: str
    change_reason: str


class OutboxEvent(BaseModel):
    id: str
    memory_id: str
    event_type: str
    target_version: int
    payload: JsonDict
    attempt_count: int
    available_at: str
    processed_at: Optional[str] = None
    error: Optional[str] = None


class SearchResult(BaseModel):
    items: List[MemoryRecord]
    search_mode: str
    degraded: bool


class SearchHit(BaseModel):
    id: str
    score: float
    payload: JsonDict


SearchFn = Callable[[str, str, Optional[str], Optional[List[str]], bool, bool, int], SearchResult]
