from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


JsonDict = Dict[str, Any]
JsonList = List[Any]


@dataclass
class MemoryRecord:
    id: str
    content: str
    type: str
    namespace: str
    scope_id: str
    source: str
    status: str
    version: int
    content_hash: str
    idempotency_key: Optional[str]
    tags: List[str] = field(default_factory=list)
    notes: List[JsonDict] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)
    obsidian_projection: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MemoryRevision:
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


@dataclass
class OutboxEvent:
    id: str
    memory_id: str
    event_type: str
    target_version: int
    payload: JsonDict
    attempt_count: int
    available_at: str
    processed_at: Optional[str]
    error: Optional[str]


@dataclass
class SearchResult:
    items: List[MemoryRecord]
    search_mode: str
    degraded: bool


@dataclass
class SearchHit:
    id: str
    score: float
    payload: JsonDict


SearchFn = Callable[[str, str, Optional[str], Optional[List[str]], bool, bool, int], SearchResult]
