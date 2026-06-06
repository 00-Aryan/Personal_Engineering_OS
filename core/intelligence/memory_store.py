"""Persistent agent memory storage for ProjectOS intelligence."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from core.intelligence.embedder import BaseEmbedder
from core.intelligence.vector_store import BaseVectorStore, SearchResult, VectorRecord


ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"
MEMORY_RECORDS_FILE_NAME = "memory_records.jsonl"
MEMORY_COLLECTION_TEMPLATE = "memory_{memory_type}"
DEFAULT_IMPORTANCE_SCORE = 0.5
IMPORTANCE_ACCESS_INCREMENT = 0.05
IMPORTANCE_DAILY_DECAY = 0.01
MAX_IMPORTANCE_SCORE = 1.0
MIN_IMPORTANCE_SCORE = 0.0
DEFAULT_MIN_IMPORTANCE = 0.1
DEFAULT_MAX_RECORDS_PER_AGENT = 1000
DEFAULT_RETRIEVAL_K = 5
SECONDS_PER_DAY = 86400.0
METADATA_KEY_MEMORY_ID = "memory_id"
METADATA_KEY_MEMORY_TYPE = "memory_type"
METADATA_KEY_AGENT_NAME = "agent_name"
METADATA_KEY_IMPORTANCE_SCORE = "importance_score"
METADATA_KEY_CREATED_AT = "created_at"
METADATA_KEY_METADATA = "metadata"
STATS_KEY_TOTAL_RECORDS = "total_records"
STATS_KEY_BY_TYPE = "by_type"
STATS_KEY_AVG_IMPORTANCE = "avg_importance"
STATS_KEY_OLDEST = "oldest"
STATS_KEY_NEWEST = "newest"
LOGGER_NAME = "projectos.memory_store"

VectorStoreFactoryFn = Callable[[str, Path, BaseEmbedder], BaseVectorStore]
logger = logging.getLogger(LOGGER_NAME)


class MemoryType(Enum):
    """Supported ProjectOS agent memory categories."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass
class MemoryRecord:
    """One persistent memory record for an agent."""

    memory_id: str
    memory_type: MemoryType
    agent_name: str
    content: str
    context: str
    importance_score: float = DEFAULT_IMPORTANCE_SCORE
    access_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize IDs, enum values, timestamps, and importance bounds."""
        self.memory_id = _uuid_text(self.memory_id)
        if not isinstance(self.memory_type, MemoryType):
            self.memory_type = MemoryType(str(self.memory_type))
        self.importance_score = _bounded_importance(self.importance_score)

    def to_retrieval_text(self) -> str:
        """Format memory for injection into agent prompts."""
        return f"[{self.memory_type.value}] {self.content}"


class MemoryStore:
    """Manage episodic, semantic, and procedural memories with vector search."""

    def __init__(
        self,
        vector_store_factory_fn: VectorStoreFactoryFn,
        embedder: BaseEmbedder,
        state_dir: Path,
        max_records_per_agent: int = DEFAULT_MAX_RECORDS_PER_AGENT,
    ) -> None:
        """Initialize memory JSONL persistence and type-specific vector stores."""
        self.vector_store_factory_fn = vector_store_factory_fn
        self.embedder = embedder
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.max_records_per_agent = max_records_per_agent
        self.records_path = self.state_dir / MEMORY_RECORDS_FILE_NAME
        self.vector_stores = {
            memory_type: vector_store_factory_fn(
                MEMORY_COLLECTION_TEMPLATE.format(memory_type=memory_type.value),
                self.state_dir,
                embedder,
            )
            for memory_type in MemoryType
        }

    def store(self, record: MemoryRecord) -> None:
        """Store a memory in JSONL and vector search, then enforce capacity."""
        records = self._records_by_id()
        records[record.memory_id] = record
        self._save_records(records.values())
        self._replace_vector_record(record)
        self._enforce_capacity(record.agent_name, record.memory_type)

    def retrieve(
        self,
        query: str,
        agent_name: str,
        memory_types: Optional[List[MemoryType]] = None,
        k: int = DEFAULT_RETRIEVAL_K,
        min_importance: float = DEFAULT_MIN_IMPORTANCE,
    ) -> List[MemoryRecord]:
        """Retrieve relevant memories and update access metadata."""
        if k <= 0:
            return []
        records_by_id = self._records_by_id()
        query_embedding = self.embedder.embed(query)
        candidate_results = self._candidate_results(
            query_embedding,
            agent_name,
            memory_types,
            k,
        )
        ranked_records = self._ranked_records(
            candidate_results,
            records_by_id,
            min_importance,
        )
        retrieved_records = [record for record, _score in ranked_records[:k]]
        if retrieved_records:
            self._mark_accessed(records_by_id, retrieved_records)
        return retrieved_records

    def prune(
        self,
        agent_name: str,
        memory_type: Optional[MemoryType] = None,
    ) -> int:
        """Remove low-importance memories for an agent and return prune count."""
        records = self._records_by_id()
        pruned_ids = []
        now = _utc_now()
        for record in records.values():
            if record.agent_name != agent_name:
                continue
            if memory_type is not None and record.memory_type is not memory_type:
                continue
            decayed_score = self._decayed_importance(record, now)
            if decayed_score < DEFAULT_MIN_IMPORTANCE:
                pruned_ids.append(record.memory_id)
        self._delete_records(records, pruned_ids)
        return len(pruned_ids)

    def get_stats(self, agent_name: str) -> Dict[str, Any]:
        """Return memory counts and importance summary for one agent."""
        records = [
            record
            for record in self._records_by_id().values()
            if record.agent_name == agent_name
        ]
        by_type = {memory_type.value: 0 for memory_type in MemoryType}
        for record in records:
            by_type[record.memory_type.value] += 1
        if not records:
            return {
                STATS_KEY_TOTAL_RECORDS: 0,
                STATS_KEY_BY_TYPE: by_type,
                STATS_KEY_AVG_IMPORTANCE: 0.0,
                STATS_KEY_OLDEST: None,
                STATS_KEY_NEWEST: None,
            }
        return {
            STATS_KEY_TOTAL_RECORDS: len(records),
            STATS_KEY_BY_TYPE: by_type,
            STATS_KEY_AVG_IMPORTANCE: (
                sum(record.importance_score for record in records) / len(records)
            ),
            STATS_KEY_OLDEST: min(record.created_at for record in records).isoformat(),
            STATS_KEY_NEWEST: max(record.created_at for record in records).isoformat(),
        }

    def _candidate_results(
        self,
        query_embedding: List[float],
        agent_name: str,
        memory_types: Optional[List[MemoryType]],
        k: int,
    ) -> List[SearchResult]:
        """Return vector search candidates across requested memory types."""
        selected_types = memory_types or list(MemoryType)
        results: List[SearchResult] = []
        for memory_type in selected_types:
            results.extend(
                self.vector_stores[memory_type].search(
                    query_embedding,
                    k=k,
                    filter_metadata={METADATA_KEY_AGENT_NAME: agent_name},
                )
            )
        return results

    def _ranked_records(
        self,
        results: Iterable[SearchResult],
        records_by_id: Mapping[str, MemoryRecord],
        min_importance: float,
    ) -> List[tuple[MemoryRecord, float]]:
        """Return unique memory records sorted by importance times similarity."""
        best_by_id: Dict[str, tuple[MemoryRecord, float]] = {}
        now = _utc_now()
        for result in results:
            memory_id = str(result.record.metadata.get(METADATA_KEY_MEMORY_ID, result.record.id))
            record = records_by_id.get(memory_id)
            if record is None:
                continue
            decayed_score = self._decayed_importance(record, now)
            if decayed_score < min_importance:
                continue
            combined_score = decayed_score * result.similarity_score
            existing_item = best_by_id.get(memory_id)
            if existing_item is None or combined_score > existing_item[1]:
                best_by_id[memory_id] = (record, combined_score)
        return sorted(best_by_id.values(), key=lambda item: item[1], reverse=True)

    def _mark_accessed(
        self,
        records_by_id: Dict[str, MemoryRecord],
        retrieved_records: Iterable[MemoryRecord],
    ) -> None:
        """Update access count, last_accessed, and importance for retrieved records."""
        now = _utc_now()
        for record in retrieved_records:
            updated_record = records_by_id[record.memory_id]
            decayed_score = self._decayed_importance(updated_record, now)
            updated_record.importance_score = _bounded_importance(
                decayed_score + IMPORTANCE_ACCESS_INCREMENT
            )
            updated_record.access_count += 1
            updated_record.last_accessed = now
            record.importance_score = updated_record.importance_score
            record.access_count = updated_record.access_count
            record.last_accessed = updated_record.last_accessed
        self._save_records(records_by_id.values())
        for record in retrieved_records:
            self._replace_vector_record(record)

    def _enforce_capacity(self, agent_name: str, memory_type: MemoryType) -> None:
        """Prune lowest-importance records when agent/type capacity is exceeded."""
        records = self._records_by_id()
        matching_records = [
            record
            for record in records.values()
            if record.agent_name == agent_name and record.memory_type is memory_type
        ]
        overflow_count = len(matching_records) - self.max_records_per_agent
        if overflow_count <= 0:
            return
        sorted_records = sorted(
            matching_records,
            key=lambda record: record.importance_score,
        )
        self._delete_records(
            records,
            [record.memory_id for record in sorted_records[:overflow_count]],
        )

    def _delete_records(
        self,
        records: Dict[str, MemoryRecord],
        memory_ids: Iterable[str],
    ) -> None:
        """Delete memory IDs from JSONL and vector stores."""
        deleted_ids = list(memory_ids)
        if not deleted_ids:
            return
        for memory_id in deleted_ids:
            record = records.pop(memory_id, None)
            if record is not None:
                self.vector_stores[record.memory_type].delete(memory_id)
        self._save_records(records.values())

    def _replace_vector_record(self, record: MemoryRecord) -> None:
        """Replace the vector-store entry for one memory record."""
        self.vector_stores[record.memory_type].delete(record.memory_id)
        self.vector_stores[record.memory_type].add(
            VectorRecord(
                id=record.memory_id,
                text=record.context,
                embedding=self.embedder.embed(record.context),
                metadata=_metadata_for_record(record),
            )
        )

    def _decayed_importance(self, record: MemoryRecord, now: datetime) -> float:
        """Return importance after time decay from last access."""
        days_since_access = max(
            (now - record.last_accessed).total_seconds() / SECONDS_PER_DAY,
            0.0,
        )
        return _bounded_importance(
            record.importance_score - (days_since_access * IMPORTANCE_DAILY_DECAY)
        )

    def _records_by_id(self) -> Dict[str, MemoryRecord]:
        """Load all memory records from JSONL keyed by memory ID."""
        if not self.records_path.exists():
            return {}
        records: Dict[str, MemoryRecord] = {}
        for line in self.records_path.read_text(encoding=ENCODING).splitlines():
            if not line.strip():
                continue
            try:
                record = _record_from_payload(json.loads(line))
                records[record.memory_id] = record
            except Exception as error:
                logger.warning("Skipped malformed memory record: %s", error)
        return records

    def _save_records(self, records: Iterable[MemoryRecord]) -> None:
        """Persist memory records to JSONL with atomic replacement."""
        rendered_records = [
            json.dumps(_record_payload(record), sort_keys=True)
            for record in sorted(records, key=lambda item: item.created_at)
        ]
        content = NEWLINE.join(rendered_records)
        if content:
            content = f"{content}{NEWLINE}"
        _write_atomically(self.records_path, content)


def _record_payload(record: MemoryRecord) -> Dict[str, Any]:
    """Serialize one memory record to JSON-safe data."""
    return {
        "memory_id": record.memory_id,
        "memory_type": record.memory_type.value,
        "agent_name": record.agent_name,
        "content": record.content,
        "context": record.context,
        "importance_score": record.importance_score,
        "access_count": record.access_count,
        "created_at": record.created_at.isoformat(),
        "last_accessed": record.last_accessed.isoformat(),
        "metadata": record.metadata,
    }


def _record_from_payload(payload: Mapping[str, Any]) -> MemoryRecord:
    """Deserialize a JSON mapping into a MemoryRecord."""
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    return MemoryRecord(
        memory_id=str(payload["memory_id"]),
        memory_type=MemoryType(str(payload["memory_type"])),
        agent_name=str(payload["agent_name"]),
        content=str(payload["content"]),
        context=str(payload["context"]),
        importance_score=float(payload.get("importance_score", DEFAULT_IMPORTANCE_SCORE)),
        access_count=int(payload.get("access_count", 0)),
        created_at=_datetime_from_value(payload.get("created_at")),
        last_accessed=_datetime_from_value(payload.get("last_accessed")),
        metadata=dict(metadata),
    )


def _metadata_for_record(record: MemoryRecord) -> Dict[str, Any]:
    """Return vector-store metadata for one memory record."""
    return {
        METADATA_KEY_MEMORY_ID: record.memory_id,
        METADATA_KEY_MEMORY_TYPE: record.memory_type.value,
        METADATA_KEY_AGENT_NAME: record.agent_name,
        METADATA_KEY_IMPORTANCE_SCORE: record.importance_score,
        METADATA_KEY_CREATED_AT: record.created_at.isoformat(),
        METADATA_KEY_METADATA: json.dumps(record.metadata, sort_keys=True, default=str),
    }


def _write_atomically(path: Path, content: str) -> None:
    """Write text to a path using atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{TEMP_PREFIX}{path.name}.",
        suffix=TEMP_SUFFIX,
        dir=str(path.parent),
    )
    try:
        with os.fdopen(
            file_descriptor,
            FILE_WRITE_MODE,
            encoding=ENCODING,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _datetime_from_value(value: Any) -> datetime:
    """Return a timezone-aware datetime parsed from a value."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            parsed_value = datetime.fromisoformat(value)
            if parsed_value.tzinfo is None:
                return parsed_value.replace(tzinfo=timezone.utc)
            return parsed_value
        except ValueError:
            pass
    return _utc_now()


def _utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


def _bounded_importance(value: Any) -> float:
    """Clamp a value into the valid memory importance range."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = DEFAULT_IMPORTANCE_SCORE
    return min(max(score, MIN_IMPORTANCE_SCORE), MAX_IMPORTANCE_SCORE)


def _uuid_text(value: str) -> str:
    """Return a UUID4 text value, replacing invalid IDs."""
    try:
        parsed_uuid = uuid.UUID(str(value))
        if parsed_uuid.version == 4:
            return str(parsed_uuid)
    except (TypeError, ValueError, AttributeError):
        pass
    return str(uuid.uuid4())


__all__ = ["MemoryRecord", "MemoryStore", "MemoryType"]
