"""Tests for ProjectOS code context retrieval."""

from __future__ import annotations

from pathlib import Path

from core.intelligence.code_indexer import CodeIndexer
from core.intelligence.context_retriever import ContextRetriever
from core.intelligence.embedder import BaseEmbedder
from core.intelligence.vector_store import NumpyVectorStore


COLLECTION_NAME = "context_retriever_test"
ENCODING = "utf-8"


class KeywordEmbedder(BaseEmbedder):
    """Deterministic keyword embedder for retrieval tests."""

    keywords = ("payment", "user", "target", "alpha")

    def embed(self, text: str) -> list[float]:
        """Return keyword-count vectors for the supplied text."""
        lowered_text = text.lower()
        return [float(lowered_text.count(keyword)) for keyword in self.keywords]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch by calling embed for each text."""
        return [self.embed(text) for text in texts]

    def get_dimension(self) -> int:
        """Return the fixed keyword vector dimension."""
        return len(self.keywords)

    def get_embedder_name(self) -> str:
        """Return the test embedder name."""
        return "keyword-test"


def test_retrieve_returns_relevant_chunks(tmp_path: Path) -> None:
    """Verify retrieval returns chunks matching the task query."""
    retriever = _indexed_retriever(tmp_path)

    context = retriever.retrieve_for_task("review payment flow")

    assert context.retrieved_chunks
    assert "payment" in context.retrieved_chunks[0].content.lower()


def test_file_path_chunks_always_included(tmp_path: Path) -> None:
    """Verify file_path chunks are included even for an unrelated query."""
    retriever = _indexed_retriever(tmp_path)
    target_path = tmp_path / "target.py"

    context = retriever.retrieve_for_task("unrelated query", file_path=str(target_path))

    assert any(chunk.file_path == str(target_path) for chunk in context.retrieved_chunks)


def test_token_budget_respected(tmp_path: Path) -> None:
    """Verify retrieval does not exceed the configured context token budget."""
    retriever = _indexed_retriever(tmp_path, max_context_tokens=40)

    context = retriever.retrieve_for_task("payment user target alpha")

    assert context.total_tokens_estimate <= 40


def test_deduplication_works(tmp_path: Path) -> None:
    """Verify the same chunk returned by search and file lookup appears once."""
    retriever = _indexed_retriever(tmp_path)
    target_path = tmp_path / "payment.py"

    context = retriever.retrieve_for_task("payment", file_path=str(target_path))

    chunk_ids = [chunk.chunk_id for chunk in context.retrieved_chunks]
    assert len(chunk_ids) == len(set(chunk_ids))


def test_formatted_context_contains_file_path_and_lines(tmp_path: Path) -> None:
    """Verify formatted context includes source locations and code fences."""
    retriever = _indexed_retriever(tmp_path)
    target_path = tmp_path / "payment.py"

    context = retriever.retrieve_for_task("payment", file_path=str(target_path))

    assert f"{target_path}:1-" in context.formatted_context
    assert "```python" in context.formatted_context


def test_empty_store_returns_empty_context(tmp_path: Path) -> None:
    """Verify retrieval from an empty store returns no chunks."""
    embedder = KeywordEmbedder()
    store = NumpyVectorStore(COLLECTION_NAME, tmp_path / "empty")
    retriever = ContextRetriever(store, embedder)

    context = retriever.retrieve_for_task("payment")

    assert context.retrieved_chunks == []
    assert context.similarity_scores == []


def _indexed_retriever(
    tmp_path: Path,
    max_context_tokens: int = 2000,
) -> ContextRetriever:
    """Return a retriever with a small indexed Python project."""
    embedder = KeywordEmbedder()
    store = NumpyVectorStore(COLLECTION_NAME, tmp_path / "state")
    indexer = CodeIndexer(store, embedder)
    (tmp_path / "payment.py").write_text(
        "def payment_total() -> int:\n"
        "    \"\"\"Return payment total.\"\"\"\n"
        "    return 10\n",
        encoding=ENCODING,
    )
    (tmp_path / "target.py").write_text(
        "def target_user() -> str:\n"
        "    \"\"\"Return target user.\"\"\"\n"
        "    return 'user'\n",
        encoding=ENCODING,
    )
    indexer.index_directory(tmp_path)
    return ContextRetriever(
        store,
        embedder,
        max_context_tokens=max_context_tokens,
        top_k=4,
    )
