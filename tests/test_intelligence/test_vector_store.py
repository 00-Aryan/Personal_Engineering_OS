"""Tests for ProjectOS vector store abstractions."""

from __future__ import annotations

from pathlib import Path

from core.intelligence.vector_store import NumpyVectorStore, VectorRecord


COLLECTION_NAME = "test_collection"


def test_add_and_search_returns_correct_record(tmp_path: Path) -> None:
    """Verify a stored vector can be retrieved by similarity."""
    store = NumpyVectorStore(COLLECTION_NAME, tmp_path)
    record = _record("alpha", [1.0, 0.0])
    store.add(record)

    results = store.search([1.0, 0.0])

    assert results[0].record.id == record.id


def test_search_returns_k_results(tmp_path: Path) -> None:
    """Verify search respects the requested result count."""
    store = NumpyVectorStore(COLLECTION_NAME, tmp_path)
    for index in range(5):
        store.add(_record(f"record-{index}", [1.0, float(index)]))

    results = store.search([1.0, 0.0], k=3)

    assert len(results) == 3


def test_cosine_similarity_identical_vectors_score_one(tmp_path: Path) -> None:
    """Verify identical vectors score 1.0."""
    store = NumpyVectorStore(COLLECTION_NAME, tmp_path)
    store.add(_record("alpha", [1.0, 2.0, 3.0]))

    results = store.search([1.0, 2.0, 3.0])

    assert results[0].similarity_score == 1.0


def test_cosine_similarity_orthogonal_vectors_score_zero(tmp_path: Path) -> None:
    """Verify orthogonal vectors score 0.0."""
    store = NumpyVectorStore(COLLECTION_NAME, tmp_path)
    store.add(_record("alpha", [1.0, 0.0]))

    results = store.search([0.0, 1.0])

    assert results[0].similarity_score == 0.0


def test_metadata_filter_applied_before_similarity(tmp_path: Path) -> None:
    """Verify metadata filtering excludes higher-similarity non-matches."""
    store = NumpyVectorStore(COLLECTION_NAME, tmp_path)
    store.add(_record("wrong agent", [1.0, 0.0], {"agent_name": "planning"}))
    expected = _record("right agent", [0.0, 1.0], {"agent_name": "code_review"})
    store.add(expected)

    results = store.search([1.0, 0.0], filter_metadata={"agent_name": "code_review"})

    assert len(results) == 1
    assert results[0].record.id == expected.id


def test_persistence_survives_reload(tmp_path: Path) -> None:
    """Verify records are loaded after constructing a new store."""
    first_store = NumpyVectorStore(COLLECTION_NAME, tmp_path)
    record = _record("persisted", [1.0, 0.0])
    first_store.add(record)

    second_store = NumpyVectorStore(COLLECTION_NAME, tmp_path)
    results = second_store.search([1.0, 0.0])

    assert second_store.count() == 1
    assert results[0].record.id == record.id


def test_delete_removes_record(tmp_path: Path) -> None:
    """Verify delete removes an existing record."""
    store = NumpyVectorStore(COLLECTION_NAME, tmp_path)
    record = _record("alpha", [1.0, 0.0])
    store.add(record)

    deleted = store.delete(record.id)

    assert deleted is True
    assert store.search([1.0, 0.0]) == []


def test_count_accurate_after_adds_and_deletes(tmp_path: Path) -> None:
    """Verify count tracks adds and deletes."""
    store = NumpyVectorStore(COLLECTION_NAME, tmp_path)
    first = _record("first", [1.0, 0.0])
    second = _record("second", [0.0, 1.0])
    store.add(first)
    store.add(second)
    store.delete(first.id)

    assert store.count() == 1


def test_search_empty_store_returns_empty_list(tmp_path: Path) -> None:
    """Verify search on an empty store is safe."""
    store = NumpyVectorStore(COLLECTION_NAME, tmp_path)

    assert store.search([1.0, 0.0]) == []


def _record(
    text: str,
    embedding: list[float],
    metadata: dict[str, str] | None = None,
) -> VectorRecord:
    """Return a vector record for tests."""
    return VectorRecord(text=text, embedding=embedding, metadata=metadata or {})
