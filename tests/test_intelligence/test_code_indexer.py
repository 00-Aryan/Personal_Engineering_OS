"""Tests for AST-based ProjectOS code indexing."""

from __future__ import annotations

from pathlib import Path

from core.intelligence.code_indexer import CodeIndexer
from core.intelligence.embedder import BaseEmbedder
from core.intelligence.vector_store import NumpyVectorStore


COLLECTION_NAME = "code_index_test"
ENCODING = "utf-8"


class StaticEmbedder(BaseEmbedder):
    """Small deterministic embedder for indexer tests."""

    def embed(self, text: str) -> list[float]:
        """Return a stable vector based on text length."""
        return [float(len(text)), 1.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed all texts with the single-text implementation."""
        return [self.embed(text) for text in texts]

    def get_dimension(self) -> int:
        """Return the fixed test dimension."""
        return 2

    def get_embedder_name(self) -> str:
        """Return the test embedder name."""
        return "static-test"


def test_index_simple_function_creates_chunk(tmp_path: Path) -> None:
    """Verify indexing a simple function creates a function chunk."""
    file_path = tmp_path / "sample.py"
    file_path.write_text(
        "def greet(name: str) -> str:\n"
        "    \"\"\"Return a greeting.\"\"\"\n"
        "    return f'Hello {name}'\n",
        encoding=ENCODING,
    )
    indexer = _indexer(tmp_path)

    chunks = indexer.index_file(file_path)

    assert any(chunk.chunk_type == "function" and chunk.name == "greet" for chunk in chunks)
    assert indexer.vector_store.count() == len(chunks)


def test_index_class_creates_class_and_method_chunks(tmp_path: Path) -> None:
    """Verify classes and methods are indexed as separate chunks."""
    file_path = tmp_path / "service.py"
    file_path.write_text(
        "class Service:\n"
        "    \"\"\"Example service.\"\"\"\n"
        "    def run(self) -> str:\n"
        "        \"\"\"Run service.\"\"\"\n"
        "        return 'ok'\n",
        encoding=ENCODING,
    )
    indexer = _indexer(tmp_path)

    chunks = indexer.index_file(file_path)

    assert any(chunk.chunk_type == "class" and chunk.name == "Service" for chunk in chunks)
    assert any(
        chunk.chunk_type == "method"
        and chunk.name == "run"
        and chunk.parent_name == "Service"
        for chunk in chunks
    )


def test_syntax_error_creates_raw_chunk_not_crash(tmp_path: Path) -> None:
    """Verify syntax errors create an unparseable chunk instead of raising."""
    file_path = tmp_path / "broken.py"
    file_path.write_text("def broken(:\n", encoding=ENCODING)
    indexer = _indexer(tmp_path)

    chunks = indexer.index_file(file_path)

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "unparseable"
    assert indexer.vector_store.count() == 1


def test_update_file_replaces_old_chunks(tmp_path: Path) -> None:
    """Verify update_file removes old chunks for the file before reindexing."""
    file_path = tmp_path / "replace.py"
    file_path.write_text("def old() -> str:\n    return 'old'\n", encoding=ENCODING)
    indexer = _indexer(tmp_path)
    indexer.index_file(file_path)

    file_path.write_text("def new() -> str:\n    return 'new'\n", encoding=ENCODING)
    indexer.update_file(file_path)

    record_text = "\n".join(record.text for record in indexer.vector_store.records)
    assert "old" not in record_text
    assert "new" in record_text


def test_delete_file_removes_all_chunks(tmp_path: Path) -> None:
    """Verify delete_file removes all chunks associated with one file."""
    file_path = tmp_path / "delete_me.py"
    file_path.write_text("def remove() -> None:\n    return None\n", encoding=ENCODING)
    indexer = _indexer(tmp_path)
    indexer.index_file(file_path)

    indexer.delete_file(file_path)

    assert indexer.vector_store.count() == 0


def test_index_directory_excludes_venv_pattern(tmp_path: Path) -> None:
    """Verify default directory indexing excludes virtual environment paths."""
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("value = 1\n", encoding=ENCODING)
    (tmp_path / "kept.py").write_text("value = 2\n", encoding=ENCODING)
    indexer = _indexer(tmp_path)

    report = indexer.index_directory(tmp_path)

    assert report.files_indexed == 1
    assert all(
        ".venv" not in record.metadata["file_path"]
        for record in indexer.vector_store.records
    )


def test_indexing_report_accurate_counts(tmp_path: Path) -> None:
    """Verify directory indexing reports files, chunks, errors, and line counts."""
    (tmp_path / "one.py").write_text("def one() -> int:\n    return 1\n", encoding=ENCODING)
    (tmp_path / "two.py").write_text("def two() -> int:\n    return 2\n", encoding=ENCODING)
    indexer = _indexer(tmp_path)

    report = indexer.index_directory(tmp_path)

    assert report.files_indexed == 2
    assert report.chunks_created == indexer.vector_store.count()
    assert report.errors == []
    assert report.total_lines_indexed == 4


def _indexer(tmp_path: Path) -> CodeIndexer:
    """Return a CodeIndexer backed by local test storage."""
    return CodeIndexer(
        NumpyVectorStore(COLLECTION_NAME, tmp_path / "state"),
        StaticEmbedder(),
    )
