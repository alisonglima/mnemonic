from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from mcp_memory.database import Database
from mcp_memory.errors import InvalidRequestError, NotFoundError, VersionConflictError
from mcp_memory.models import MemoryRecord, MemoryRevision, OutboxEvent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _loads(value: str) -> Any:
    return json.loads(value) if value else None


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


MAX_EMBEDDING_RETRIES = 5


class MemoryRepository:
    def __init__(self, database: Database):
        self.database = database

    def create_memory(
        self,
        *,
        content: str,
        type: str,
        namespace: str,
        scope_id: str,
        source: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        obsidian_projection: bool = False,
    ) -> MemoryRecord:
        memory_id = str(uuid.uuid4())
        created_at = _now()
        record = MemoryRecord(
            id=memory_id,
            content=content,
            type=type,
            namespace=namespace,
            scope_id=scope_id,
            source=source,
            status="active",
            version=1,
            content_hash=_hash_content(content),
            idempotency_key=idempotency_key,
            tags=sorted(set(tags or [])),
            notes=[],
            metadata=metadata or {},
            obsidian_projection=obsidian_projection,
            created_at=created_at,
            updated_at=created_at,
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_records (
                  id, namespace, scope_id, type, obsidian_projection, content, source, status,
                  version, content_hash, idempotency_key, tags_json, notes_json, metadata_json,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.namespace,
                    record.scope_id,
                    record.type,
                    int(record.obsidian_projection),
                    record.content,
                    record.source,
                    record.status,
                    record.version,
                    record.content_hash,
                    record.idempotency_key,
                    _json(record.tags),
                    _json(record.notes),
                    _json(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
            self._insert_revision(connection, record, source, "create")
            self._ensure_projection_row(connection, record.id)
            self._queue_projection_events(connection, record.id, record.version, record.obsidian_projection)
            self._sync_fts(connection, record)
            connection.commit()
        return record

    def get_memory(self, memory_id: str) -> Optional[MemoryRecord]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_records WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def get_memory_bulk(self, memory_ids: List[str]) -> List[Optional[MemoryRecord]]:
        """Fetch multiple memories by ID. Missing IDs produce None in result list."""
        if not memory_ids:
            return []
        placeholders = ",".join("?" * len(memory_ids))
        query = f"SELECT * FROM memory_records WHERE id IN ({placeholders}) AND status IN ('active', 'archived')"
        with self.database.connect() as connection:
            rows = connection.execute(query, memory_ids).fetchall()
        id_to_row = {row["id"]: row for row in rows}
        return [id_to_row.get(mid) and self._row_to_record(id_to_row[mid]) for mid in memory_ids]

    def list_revisions(self, memory_id: str) -> List[MemoryRevision]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_revisions WHERE memory_id = ? ORDER BY version ASC",
                (memory_id,),
            ).fetchall()
        return [self._row_to_revision(row) for row in rows]

    def update_memory(
        self,
        *,
        memory_id: str,
        expected_version: int,
        content: Optional[str],
        type: Optional[str],
        metadata: Optional[Dict[str, Any]],
        change_reason: str,
    ) -> MemoryRecord:
        record = self._require_record(memory_id)
        if record.version != expected_version:
            raise VersionConflictError("VersionConflictError")
        updated = MemoryRecord(
            **{
                **record.__dict__,
                "content": content if content is not None else record.content,
                "type": type if type is not None else record.type,
                "metadata": metadata if metadata is not None else record.metadata,
                "content_hash": _hash_content(content if content is not None else record.content),
                "version": record.version + 1,
                "updated_at": _now(),
            }
        )
        with self.database.connect() as connection:
            changed = self._persist_record(connection, updated, expected_version=expected_version)
            if changed == 0:
                raise VersionConflictError("VersionConflictError")
            self._insert_revision(connection, updated, record.source, change_reason)
            self._queue_projection_events(connection, updated.id, updated.version, updated.obsidian_projection)
            connection.commit()
        return updated

    def archive_memory(self, memory_id: str, reason: Optional[str] = None) -> MemoryRecord:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM memory_records WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                raise NotFoundError("not_found")
            record = self._row_to_record(row)
            if record.status == "archived":
                return record
            if record.status in {"deleted", "retracted"}:
                raise InvalidRequestError("invalid_request")
            return self._mutate_record_in_connection(
                connection,
                record,
                new_status="archived",
                change_reason=reason or "archive",
                expected_version=record.version,
            )

    def retract_memory(self, memory_id: str, *, expected_version: int, reason: str) -> MemoryRecord:
        record = self._require_record(memory_id)
        if record.version != expected_version:
            raise VersionConflictError("VersionConflictError")
        if record.status not in {"active", "archived"}:
            raise InvalidRequestError("invalid_request")
        return self._mutate_record(record, new_status="retracted", change_reason=reason, expected_version=expected_version)

    def delete_memory(self, memory_id: str, *, expected_version: int, reason: str) -> MemoryRecord:
        record = self._require_record(memory_id)
        if record.version != expected_version:
            raise VersionConflictError("VersionConflictError")
        if record.status == "deleted":
            raise InvalidRequestError("invalid_request")
        return self._mutate_record(record, new_status="deleted", change_reason=reason, expected_version=expected_version)

    def add_tags(self, memory_id: str, tags: List[str]) -> MemoryRecord:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM memory_records WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                raise NotFoundError("not_found")
            record = self._row_to_record(row)
            merged = sorted(set(record.tags).union(tags))
            if merged == record.tags:
                return record
            return self._mutate_record_in_connection(
                connection,
                record,
                new_tags=merged,
                change_reason="add_tags",
                expected_version=record.version,
            )

    def remove_tags(self, memory_id: str, tags: List[str]) -> MemoryRecord:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM memory_records WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                raise NotFoundError("not_found")
            record = self._row_to_record(row)
            remaining = [tag for tag in record.tags if tag not in set(tags)]
            if remaining == record.tags:
                return record
            return self._mutate_record_in_connection(
                connection,
                record,
                new_tags=remaining,
                change_reason="remove_tags",
                expected_version=record.version,
            )

    def append_note(self, memory_id: str, *, note: str, source: str) -> MemoryRecord:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM memory_records WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                raise NotFoundError("not_found")
            record = self._row_to_record(row)
            notes = list(record.notes)
            notes.append({"note": note, "source": source, "created_at": _now()})
            return self._mutate_record_in_connection(
                connection,
                record,
                new_notes=notes,
                change_reason="append_note",
                expected_version=record.version,
            )

    def search_records(
        self,
        *,
        query: str,
        namespace: str,
        scope_id: Optional[str],
        types: Optional[List[str]],
        include_archived: bool,
        include_retracted: bool,
        limit: int,
        offset: int = 0,
        status: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        updated_after: Optional[str] = None,
        updated_before: Optional[str] = None,
    ) -> List[MemoryRecord]:
        if status:
            statuses = [status]
        else:
            statuses = ["active"]
            if include_archived:
                statuses.append("archived")
            if include_retracted:
                statuses.append("retracted")
        params: List[Any] = [namespace]
        where = ["namespace = ?", "status IN ({})".format(",".join("?" for _ in statuses))]
        params.extend(statuses)
        if scope_id:
            where.append("scope_id = ?")
            params.append(scope_id)
        if types:
            where.append("type IN ({})".format(",".join("?" for _ in types)))
            params.extend(types)
        if query:
            where.append("LOWER(content) LIKE ?")
            params.append(f"%{query.lower()}%")
        if created_after:
            where.append("created_at >= ?")
            params.append(created_after)
        if created_before:
            where.append("created_at <= ?")
            params.append(created_before)
        if updated_after:
            where.append("updated_at >= ?")
            params.append(updated_after)
        if updated_before:
            where.append("updated_at <= ?")
            params.append(updated_before)
        params.extend([limit, offset])
        sql = f"SELECT * FROM memory_records WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        with self.database.connect() as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_records(self) -> List[MemoryRecord]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM memory_records ORDER BY created_at ASC").fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_by_tag(self, tag: str, namespace: Optional[str] = None) -> int:
        """Delete all records containing a specific tag. Returns count of deleted records."""
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if namespace:
                rows = connection.execute(
                    "SELECT * FROM memory_records WHERE namespace = ? AND status != 'deleted'",
                    (namespace,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM memory_records WHERE status != 'deleted'"
                ).fetchall()

            deleted = 0
            for row in rows:
                record = self._row_to_record(row)
                if tag in record.tags:
                    self._mutate_record_in_connection(
                        connection,
                        record,
                        new_status="deleted",
                        change_reason=f"cleanup_tag:{tag}",
                        expected_version=record.version,
                    )
                    deleted += 1
            return deleted

    def list_pending_outbox(self) -> List[OutboxEvent]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_outbox WHERE processed_at IS NULL ORDER BY available_at ASC"
            ).fetchall()
        return [self._row_to_outbox(row) for row in rows]

    def list_due_outbox(self) -> List[OutboxEvent]:
        now = _now()
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_outbox WHERE processed_at IS NULL AND available_at <= ? ORDER BY available_at ASC",
                (now,),
            ).fetchall()
        return [self._row_to_outbox(row) for row in rows]

    def has_newer_pending_outbox_event(self, memory_id: str, current_target_version: int) -> bool:
        """Return True if a newer unprocessed outbox event exists for this record.

        Used by the OutboxWorker to skip embeddings for records that will be
        superseded — avoids wasting Ollama CPU on data that will change again soon.
        """
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM memory_outbox WHERE memory_id = ? AND target_version > ? AND processed_at IS NULL LIMIT 1",
                (memory_id, current_target_version),
            ).fetchone()
        return row is not None

    def pending_outbox_count(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM memory_outbox WHERE processed_at IS NULL"
            ).fetchone()
        return int(row["count"]) if row else 0

    def oldest_pending_age_seconds(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT available_at FROM memory_outbox WHERE processed_at IS NULL ORDER BY available_at ASC LIMIT 1"
            ).fetchone()
        if not row:
            return 0
        oldest = datetime.fromisoformat(row["available_at"])
        return max(0, int((datetime.now(timezone.utc) - oldest).total_seconds()))

    def qdrant_coverage_ratio(self, namespace: Optional[str] = None, scope_id: Optional[str] = None) -> float:
        """Return fraction of active records with current Qdrant projection (0.0–1.0).

        Args:
            namespace: If provided, scope coverage calculation to this namespace.
            scope_id: If provided, further scope to this scope_id within the namespace.
        """
        with self.database.connect() as conn:
            params: list = []
            where = ["mr.status = 'active'"]
            if namespace:
                where.append("mr.namespace = ?")
                params.append(namespace)
            if scope_id:
                where.append("mr.scope_id = ?")
                params.append(scope_id)

            where_clause = " AND ".join(where)

            total = conn.execute(
                f"SELECT COUNT(*) FROM memory_records mr WHERE {where_clause}",
                params,
            ).fetchone()[0]
            if total == 0:
                return 1.0

            ready = conn.execute(
                f"""SELECT COUNT(*) FROM memory_projections mp
                   JOIN memory_records mr ON mr.id = mp.memory_id
                   WHERE {where_clause}
                   AND mp.qdrant_status = 'ready'
                   AND mp.qdrant_version >= mr.version""",
                params,
            ).fetchone()[0]
        return ready / total

    def get_projection_state(self, memory_id: str) -> Dict[str, Any]:
        with self.database.connect() as connection:
            self._ensure_projection_row(connection, memory_id)
            row = connection.execute(
                "SELECT * FROM memory_projections WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return {
            "qdrant_status": row["qdrant_status"],
            "obsidian_status": row["obsidian_status"],
            "qdrant_version": int(row["qdrant_version"]),
            "obsidian_version": int(row["obsidian_version"]),
            "last_error": row["last_error"],
            "qdrant_content_hash": row["qdrant_content_hash"],
            "qdrant_embedding_fingerprint": row["qdrant_embedding_fingerprint"],
        }

    def update_projection_state(self, memory_id: str, **kwargs) -> None:
        """Update projection state columns. kwargs keys must match column names."""
        allowed = {
            "qdrant_version", "qdrant_status", "qdrant_content_hash",
            "qdrant_embedding_fingerprint", "last_error",
            "obsidian_version", "obsidian_status",
        }
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [memory_id]
        with self.database.connect() as conn:
            conn.execute(
                f"UPDATE memory_projections SET {set_clause} WHERE memory_id = ?",
                values,
            )
            conn.commit()

    def enqueue_projection_event(self, memory_id: str, event_type: str, *, target_version: int) -> OutboxEvent:
        event = OutboxEvent(
            id=str(uuid.uuid4()),
            memory_id=memory_id,
            event_type=event_type,
            target_version=target_version,
            payload={"memory_id": memory_id, "target_version": target_version},
            attempt_count=0,
            available_at=_now(),
            processed_at=None,
            error=None,
        )
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO memory_outbox (id, memory_id, event_type, target_version, payload_json, attempt_count, available_at, processed_at, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.memory_id,
                    event.event_type,
                    event.target_version,
                    _json(event.payload),
                    event.attempt_count,
                    event.available_at,
                    event.processed_at,
                    event.error,
                ),
            )
            connection.commit()
        return event

    def mark_outbox_processed(self, event_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_outbox SET processed_at = ?, attempt_count = attempt_count + 1, error = NULL WHERE id = ?",
                (_now(), event_id),
            )
            connection.commit()

    def reschedule_outbox_event(self, event_id: str, *, delay_seconds: int, error: str) -> None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT attempt_count, memory_id, event_type FROM memory_outbox WHERE id = ?", (event_id,)
            ).fetchone()
            if not row:
                return
            new_attempts = row["attempt_count"] + 1
            memory_id = row["memory_id"]
            event_type = row["event_type"]

            if new_attempts >= MAX_EMBEDDING_RETRIES:
                # Dead-letter: mark error and stop retrying
                # Set processed_at so worker doesn't re-poll this event indefinitely
                conn.execute(
                    "UPDATE memory_outbox SET processed_at = ?, error = ?, attempt_count = ? WHERE id = ?",
                    (_now(), f"DEAD_LETTER: {error}", new_attempts, event_id),
                )
                if "qdrant" in event_type:
                    conn.execute(
                        "UPDATE memory_projections SET qdrant_status = 'error', last_error = ? WHERE memory_id = ?",
                        (f"DEAD_LETTER: {error}", memory_id),
                    )
                elif "obsidian" in event_type:
                    conn.execute(
                        "UPDATE memory_projections SET obsidian_status = 'error', last_error = ? WHERE memory_id = ?",
                        (f"DEAD_LETTER: {error}", memory_id),
                    )
            else:
                available_at = datetime.now(timezone.utc).timestamp() + delay_seconds
                available_at_iso = datetime.fromtimestamp(available_at, tz=timezone.utc).isoformat()
                conn.execute(
                    "UPDATE memory_outbox SET available_at = ?, error = ?, attempt_count = ? WHERE id = ?",
                    (available_at_iso, error, new_attempts, event_id),
                )
            conn.commit()

    def set_projection_version(self, memory_id: str, projection: str, version: int) -> None:
        current = self.get_projection_version(memory_id, projection)
        if current is not None and current >= version:
            return  # Already at or ahead — don't regress
        column = f"{projection}_version"
        status_column = f"{projection}_status"
        sync_column = f"last_{projection}_sync_at"
        with self.database.connect() as conn:
            self._ensure_projection_row(conn, memory_id)
            conn.execute(
                f"UPDATE memory_projections SET {column} = ?, {status_column} = 'ready', {sync_column} = ? WHERE memory_id = ?",
                (version, _now(), memory_id),
            )
            conn.commit()

    def set_projection_error(self, memory_id: str, projection: str, error: str) -> None:
        status_column = f"{projection}_status"
        with self.database.connect() as connection:
            self._ensure_projection_row(connection, memory_id)
            connection.execute(
                f"UPDATE memory_projections SET {status_column} = 'error', last_error = ? WHERE memory_id = ?",
                (error, memory_id),
            )
            connection.commit()

    def get_projection_version(self, memory_id: str, projection: str) -> int:
        column = f"{projection}_version"
        with self.database.connect() as connection:
            self._ensure_projection_row(connection, memory_id)
            row = connection.execute(
                f"SELECT {column} AS version FROM memory_projections WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return int(row["version"]) if row else 0

    def find_idempotency_match(
        self,
        *,
        namespace: str,
        scope_id: str,
        source: str,
        idempotency_key: Optional[str],
    ) -> Optional[MemoryRecord]:
        if not idempotency_key:
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_records WHERE namespace = ? AND scope_id = ? AND source = ? AND idempotency_key = ?",
                (namespace, scope_id, source, idempotency_key),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def find_exact_duplicate(
        self,
        *,
        namespace: str,
        scope_id: str,
        content_hash: str,
    ) -> Optional[MemoryRecord]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_records WHERE namespace = ? AND scope_id = ? AND content_hash = ? ORDER BY created_at DESC LIMIT 1",
                (namespace, scope_id, content_hash),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def _mutate_record(
        self,
        record: MemoryRecord,
        *,
        new_status: Optional[str] = None,
        new_tags: Optional[List[str]] = None,
        new_notes: Optional[List[Dict[str, Any]]] = None,
        new_metadata: Optional[Dict[str, Any]] = None,
        change_reason: str,
        expected_version: Optional[int] = None,
    ) -> MemoryRecord:
        updated = MemoryRecord(
            **{
                **record.__dict__,
                "status": new_status if new_status is not None else record.status,
                "tags": new_tags if new_tags is not None else record.tags,
                "notes": new_notes if new_notes is not None else record.notes,
                "metadata": new_metadata if new_metadata is not None else record.metadata,
                "version": record.version + 1,
                "updated_at": _now(),
            }
        )
        with self.database.connect() as connection:
            return self._mutate_record_in_connection(
                connection,
                record,
                new_status=new_status,
                new_tags=new_tags,
                new_notes=new_notes,
                new_metadata=new_metadata,
                change_reason=change_reason,
                expected_version=expected_version,
            )

    def _mutate_record_in_connection(
        self,
        connection,
        record: MemoryRecord,
        *,
        new_status: Optional[str] = None,
        new_tags: Optional[List[str]] = None,
        new_notes: Optional[List[Dict[str, Any]]] = None,
        new_metadata: Optional[Dict[str, Any]] = None,
        change_reason: str,
        expected_version: Optional[int] = None,
    ) -> MemoryRecord:
        updated = MemoryRecord(
            **{
                **record.__dict__,
                "status": new_status if new_status is not None else record.status,
                "tags": new_tags if new_tags is not None else record.tags,
                "notes": new_notes if new_notes is not None else record.notes,
                "metadata": new_metadata if new_metadata is not None else record.metadata,
                "version": record.version + 1,
                "updated_at": _now(),
            }
        )
        changed = self._persist_record(connection, updated, expected_version=expected_version)
        if expected_version is not None and changed == 0:
            raise VersionConflictError("VersionConflictError")
        self._insert_revision(connection, updated, record.source, change_reason)
        self._queue_projection_events(connection, updated.id, updated.version, updated.obsidian_projection)
        connection.commit()
        return updated

    def _persist_record(self, connection, record: MemoryRecord, expected_version: Optional[int] = None) -> int:
        if expected_version is None:
            cursor = connection.execute(
                """
                UPDATE memory_records
                SET type = ?, content = ?, status = ?, version = ?, content_hash = ?, tags_json = ?,
                    notes_json = ?, metadata_json = ?, updated_at = ?, obsidian_projection = ?
                WHERE id = ?
                """,
                (
                    record.type,
                    record.content,
                    record.status,
                    record.version,
                    record.content_hash,
                    _json(record.tags),
                    _json(record.notes),
                    _json(record.metadata),
                    record.updated_at,
                    int(record.obsidian_projection),
                    record.id,
                ),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE memory_records
                SET type = ?, content = ?, status = ?, version = ?, content_hash = ?, tags_json = ?,
                    notes_json = ?, metadata_json = ?, updated_at = ?, obsidian_projection = ?
                WHERE id = ? AND version = ?
                """,
                (
                    record.type,
                    record.content,
                    record.status,
                    record.version,
                    record.content_hash,
                    _json(record.tags),
                    _json(record.notes),
                    _json(record.metadata),
                    record.updated_at,
                    int(record.obsidian_projection),
                    record.id,
                    expected_version,
                ),
            )
        self._sync_fts(connection, record)
        return cursor.rowcount

    def _insert_revision(self, connection, record: MemoryRecord, changed_by: str, change_reason: str) -> None:
        connection.execute(
            "INSERT INTO memory_revisions (id, memory_id, version, content, type, status, tags_snapshot, notes_snapshot, metadata_snapshot, changed_by, changed_at, change_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                record.id,
                record.version,
                record.content,
                record.type,
                record.status,
                _json(record.tags),
                _json(record.notes),
                _json(record.metadata),
                changed_by,
                record.updated_at,
                change_reason,
            ),
        )

    def _ensure_projection_row(self, connection, memory_id: str) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO memory_projections (memory_id) VALUES (?)",
            (memory_id,),
        )

    def _queue_projection_events(self, connection, memory_id: str, version: int, obsidian_projection: bool) -> None:
        for event_type in ["project_qdrant"] + (["project_obsidian"] if obsidian_projection else []):
            connection.execute(
                "INSERT INTO memory_outbox (id, memory_id, event_type, target_version, payload_json, attempt_count, available_at, processed_at, error) VALUES (?, ?, ?, ?, ?, 0, ?, NULL, NULL)",
                (
                    str(uuid.uuid4()),
                    memory_id,
                    event_type,
                    version,
                    _json({"memory_id": memory_id, "target_version": version}),
                    _now(),
                ),
            )

    def _require_record(self, memory_id: str) -> MemoryRecord:
        record = self.get_memory(memory_id)
        if record is None:
            raise NotFoundError("not_found")
        return record

    def _row_to_record(self, row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            content=row["content"],
            type=row["type"],
            namespace=row["namespace"],
            scope_id=row["scope_id"],
            source=row["source"],
            status=row["status"],
            version=int(row["version"]),
            content_hash=row["content_hash"],
            idempotency_key=row["idempotency_key"],
            tags=_loads(row["tags_json"]) or [],
            notes=_loads(row["notes_json"]) or [],
            metadata=_loads(row["metadata_json"]) or {},
            obsidian_projection=bool(row["obsidian_projection"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_revision(self, row) -> MemoryRevision:
        return MemoryRevision(
            id=row["id"],
            memory_id=row["memory_id"],
            version=int(row["version"]),
            content=row["content"],
            type=row["type"],
            status=row["status"],
            tags_snapshot=_loads(row["tags_snapshot"]) or [],
            notes_snapshot=_loads(row["notes_snapshot"]) or [],
            metadata_snapshot=_loads(row["metadata_snapshot"]) or {},
            changed_by=row["changed_by"],
            changed_at=row["changed_at"],
            change_reason=row["change_reason"],
        )

    def _row_to_outbox(self, row) -> OutboxEvent:
        return OutboxEvent(
            id=row["id"],
            memory_id=row["memory_id"],
            event_type=row["event_type"],
            target_version=int(row["target_version"]),
            payload=_loads(row["payload_json"]) or {},
            attempt_count=int(row["attempt_count"]),
            available_at=row["available_at"],
            processed_at=row["processed_at"],
            error=row["error"],
        )

    def _sync_fts(self, connection, record: MemoryRecord) -> None:
        tags_str = " ".join(record.tags)
        connection.execute(
            "INSERT OR REPLACE INTO memory_fts (memory_id, content, tags) VALUES (?, ?, ?)",
            (record.id, record.content, tags_str),
        )

    def search_fts(
        self,
        query: str,
        namespace: str,
        limit: int,
        scope_id: Optional[str] = None,
        types: Optional[List[str]] = None,
        status: Optional[str] = None,
        include_archived: bool = False,
        expand: bool = True,
    ) -> List[Tuple[str, float]]:  # Return (memory_id, bm25_rank)
        """Search FTS5 and return memory IDs with BM25 ranks.

        Args:
            query: FTS query string (can contain OR, AND operators)
            namespace: Required namespace filter
            limit: Max results
            scope_id: Optional scope filter
            types: Optional list of type strings to filter
            status: Filter by status (default "active")
            include_archived: If True, include both active and archived
            expand: If True, expand query using expand_query before searching

        Returns:
            List of (memory_id, bm25_rank) tuples, ordered by rank
        """
        if expand:
            from mcp_memory.search import expand_query
            query = expand_query(query)
        # Build parameterized status filter
        if include_archived:
            status_values = ["active", "archived"]
        else:
            status_values = [status or "active"]

        placeholders = ",".join("?" * len(status_values))

        sql = f"""
            SELECT memory_id, bm25(memory_fts) as rank
            FROM memory_fts
            WHERE memory_id IN (
                SELECT id FROM memory_records
                WHERE namespace = ?
                  AND status IN ({placeholders})
            )
            AND memory_fts MATCH ?
        """
        params: List[Any] = [namespace] + status_values + [query]

        if scope_id:
            sql += " AND memory_id IN (SELECT id FROM memory_records WHERE scope_id = ?)"
            params.append(scope_id)
        if types:
            type_placeholders = ",".join("?" * len(types))
            sql += f" AND memory_id IN (SELECT id FROM memory_records WHERE type IN ({type_placeholders}))"
            params.extend(types)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        with self.database.connect() as connection:
            try:
                rows = connection.execute(sql, params).fetchall()
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if (
                    "fts5:" in message
                    or "malformed match" in message
                    or "unterminated string" in message
                    or "no such column" in message
                ):
                    return []  # FTS syntax error from special chars — return empty safely
                raise
        return [(row["memory_id"], row["rank"]) for row in rows]
