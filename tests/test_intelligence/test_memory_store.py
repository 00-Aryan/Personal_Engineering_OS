"""Tests for ProjectOS agent memory storage."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.intelligence.embedder import BaseEmbedder
from core.intelligence.memory_store import MemoryRecord, MemoryStore, MemoryType
from core.intelligence.vector_store import NumpyVectorStore


COLLECTION_PREFIX = "memory_test"
AGENT_NAME = "code_review"
OTHER_AGENT_NAME = "planning"
CONTEXT_TEXT = "review auth payment code"
CONTENT_TEXT = "Found repeated SQL injection review pattern."


class ConstantEmbedder(BaseEmbedder):
    """Deterministic embedder for memory tests."""

    def embed(self, text: str) -> list[float]:
        """Return a constant non-zero vector."""
        return [1.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return a constant vector for each input."""
        return [self.embed(text) for text in texts]

    def get_dimension(self) -> int:
        """Return the fixed test dimension."""
        return 1

    def get_embedder_name(self) -> str:
        """Return the test embedder name."""
        return "constant-test"


def test_store_and_retrieve_episodic_memory(tmp_path: Path) -> None:
    """Verify an episodic memory can be stored and retrieved."""
    store = _memory_store(tmp_path)
    record = _record(MemoryType.EPISODIC)

    store.store(record)
    retrieved = store.retrieve(CONTEXT_TEXT, AGENT_NAME)

    assert len(retrieved) == 1
    assert retrieved[0].memory_id == record.memory_id
    assert retrieved[0].to_retrieval_text().startswith("[episodic]")


def test_retrieve_filters_by_agent_name(tmp_path: Path) -> None:
    """Verify retrieval only returns memories for the requested agent."""
    store = _memory_store(tmp_path)
    store.store(_record(MemoryType.EPISODIC, agent_name=OTHER_AGENT_NAME))

    retrieved = store.retrieve(CONTEXT_TEXT, AGENT_NAME)

    assert retrieved == []


def test_retrieve_filters_by_memory_type(tmp_path: Path) -> None:
    """Verify retrieval can filter to specific memory types."""
    store = _memory_store(tmp_path)
    store.store(_record(MemoryType.EPISODIC))
    semantic_record = _record(MemoryType.SEMANTIC, content="Dataclasses are preferred.")
    store.store(semantic_record)

    retrieved = store.retrieve(
        CONTEXT_TEXT,
        AGENT_NAME,
        memory_types=[MemoryType.SEMANTIC],
    )

    assert len(retrieved) == 1
    assert retrieved[0].memory_id == semantic_record.memory_id


def test_access_count_incremented_on_retrieve(tmp_path: Path) -> None:
    """Verify retrieval updates access_count for returned records."""
    store = _memory_store(tmp_path)
    store.store(_record(MemoryType.EPISODIC))

    retrieved = store.retrieve(CONTEXT_TEXT, AGENT_NAME)

    assert retrieved[0].access_count == 1


def test_importance_decay_applied(tmp_path: Path) -> None:
    """Verify old memories decay before access increment is applied."""
    store = _memory_store(tmp_path)
    old_access_time = datetime.now(timezone.utc) - timedelta(days=20)
    store.store(
        _record(
            MemoryType.EPISODIC,
            importance_score=0.5,
            last_accessed=old_access_time,
        )
    )

    retrieved = store.retrieve(CONTEXT_TEXT, AGENT_NAME)

    assert retrieved[0].importance_score < 0.5


def test_pruning_removes_low_importance(tmp_path: Path) -> None:
    """Verify pruning removes memories below the importance threshold."""
    store = _memory_store(tmp_path)
    store.store(_record(MemoryType.EPISODIC, importance_score=0.05))

    pruned_count = store.prune(AGENT_NAME)

    assert pruned_count == 1
    assert store.get_stats(AGENT_NAME)["total_records"] == 0


def test_capacity_limit_triggers_pruning(tmp_path: Path) -> None:
    """Verify per-agent memory capacity removes the lowest importance record."""
    store = _memory_store(tmp_path, max_records_per_agent=1)
    low_record = _record(MemoryType.EPISODIC, importance_score=0.2)
    high_record = _record(MemoryType.EPISODIC, importance_score=0.9)

    store.store(low_record)
    store.store(high_record)
    retrieved = store.retrieve(CONTEXT_TEXT, AGENT_NAME, k=5)

    assert len(retrieved) == 1
    assert retrieved[0].memory_id == high_record.memory_id


def test_stats_accurate_after_operations(tmp_path: Path) -> None:
    """Verify memory stats report counts, type counts, and timestamps."""
    store = _memory_store(tmp_path)
    store.store(_record(MemoryType.EPISODIC, importance_score=0.4))
    store.store(_record(MemoryType.PROCEDURAL, importance_score=0.8))

    stats = store.get_stats(AGENT_NAME)

    assert stats["total_records"] == 2
    assert stats["by_type"]["episodic"] == 1
    assert stats["by_type"]["procedural"] == 1
    assert stats["avg_importance"] == 0.6000000000000001
    assert stats["oldest"] is not None
    assert stats["newest"] is not None


def _memory_store(
    tmp_path: Path,
    max_records_per_agent: int = 1000,
) -> MemoryStore:
    """Return a MemoryStore backed by local vector storage."""
    return MemoryStore(
        lambda collection_name, state_dir, embedder: NumpyVectorStore(
            collection_name,
            state_dir,
        ),
        ConstantEmbedder(),
        tmp_path,
        max_records_per_agent=max_records_per_agent,
    )


def _record(
    memory_type: MemoryType,
    agent_name: str = AGENT_NAME,
    content: str = CONTENT_TEXT,
    importance_score: float = 0.7,
    last_accessed: datetime | None = None,
) -> MemoryRecord:
    """Return a memory record with shared test defaults."""
    now = datetime.now(timezone.utc)
    return MemoryRecord(
        memory_id=str(uuid.uuid4()),
        memory_type=memory_type,
        agent_name=agent_name,
        content=content,
        context=CONTEXT_TEXT,
        importance_score=importance_score,
        created_at=now,
        last_accessed=last_accessed or now,
        metadata={},
    )
