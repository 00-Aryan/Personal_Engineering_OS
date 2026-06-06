"""AST-based Python code indexing for ProjectOS codebase awareness."""

from __future__ import annotations

import ast
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core.intelligence.embedder import BaseEmbedder
from core.intelligence.vector_store import BaseVectorStore, VectorRecord


ENCODING = "utf-8"
CHUNK_TYPE_MODULE = "module"
CHUNK_TYPE_CLASS = "class"
CHUNK_TYPE_FUNCTION = "function"
CHUNK_TYPE_METHOD = "method"
CHUNK_TYPE_UNPARSEABLE = "unparseable"
DEFAULT_MAX_CHUNK_LINES = 100
DEFAULT_INCLUDE_PATTERNS = ["*.py"]
DEFAULT_EXCLUDE_PATTERNS = ["__pycache__", ".venv", "test_*", ".git", "migrations"]
METADATA_KEY_CHUNK_ID = "chunk_id"
METADATA_KEY_FILE_PATH = "file_path"
METADATA_KEY_CHUNK_TYPE = "chunk_type"
METADATA_KEY_NAME = "name"
METADATA_KEY_START_LINE = "start_line"
METADATA_KEY_END_LINE = "end_line"
METADATA_KEY_PARENT_NAME = "parent_name"
METADATA_KEY_IMPORTS = "imports"
METADATA_KEY_CALLED_BY = "called_by"
METADATA_KEY_DOCSTRING = "docstring"
METADATA_KEY_COMPLEXITY_SCORE = "complexity_score"
LOGGER_NAME = "projectos.code_indexer"

logger = logging.getLogger(LOGGER_NAME)


@dataclass
class CodeChunk:
    """One indexed Python code chunk and retrieval metadata."""

    chunk_id: str
    file_path: str
    chunk_type: str
    name: str
    content: str
    start_line: int
    end_line: int
    parent_name: Optional[str] = None
    imports: List[str] = field(default_factory=list)
    called_by: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    complexity_score: Optional[float] = None


@dataclass
class IndexingReport:
    """Summary returned after indexing a directory."""

    files_indexed: int
    chunks_created: int
    errors: List[str]
    duration_ms: int
    total_lines_indexed: int


class CodeIndexer:
    """Parse Python files with AST and index code chunks into a vector store."""

    def __init__(
        self,
        vector_store: BaseVectorStore,
        embedder: BaseEmbedder,
        max_chunk_lines: int = DEFAULT_MAX_CHUNK_LINES,
    ) -> None:
        """Initialize the indexer with storage, embeddings, and chunk limits."""
        self.vector_store = vector_store
        self.embedder = embedder
        self.max_chunk_lines = max_chunk_lines

    def index_file(self, file_path: Path) -> List[CodeChunk]:
        """Parse, embed, and store chunks for one Python file."""
        chunks = self._chunks_for_file(Path(file_path))
        self._store_chunks(chunks)
        return chunks

    def index_directory(
        self,
        root_path: Path,
        include_patterns: List[str] = DEFAULT_INCLUDE_PATTERNS,
        exclude_patterns: List[str] = DEFAULT_EXCLUDE_PATTERNS,
    ) -> IndexingReport:
        """Index matching Python files below a root directory."""
        started_at = time.perf_counter()
        files_indexed = 0
        chunks_created = 0
        total_lines_indexed = 0
        errors: List[str] = []
        pending_chunks: List[CodeChunk] = []

        for file_path in self._iter_files(root_path, include_patterns, exclude_patterns):
            try:
                chunks = self._chunks_for_file(file_path)
                pending_chunks.extend(chunks)
                files_indexed += 1
                chunks_created += len(chunks)
                total_lines_indexed += self._line_count(file_path)
            except Exception as error:
                errors.append(f"{file_path}: {error}")

        self._populate_called_by(pending_chunks)
        self._store_chunks(pending_chunks)
        return IndexingReport(
            files_indexed=files_indexed,
            chunks_created=chunks_created,
            errors=errors,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            total_lines_indexed=total_lines_indexed,
        )

    def update_file(self, file_path: Path) -> None:
        """Replace all stored chunks for one file with a fresh index."""
        self.delete_file(file_path)
        self.index_file(file_path)

    def delete_file(self, file_path: Path) -> None:
        """Remove all vector records for one indexed file path."""
        file_path_text = str(Path(file_path))
        for record_id in self._record_ids_for_file(file_path_text):
            self.vector_store.delete(record_id)

    def clear(self) -> None:
        """Remove all records from this code index collection."""
        for record_id in self._all_record_ids():
            self.vector_store.delete(record_id)

    def _chunks_for_file(self, file_path: Path) -> List[CodeChunk]:
        """Return code chunks extracted from one file without storing them."""
        content = file_path.read_text(encoding=ENCODING)
        lines = content.splitlines()
        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            return [
                CodeChunk(
                    chunk_id=str(uuid.uuid4()),
                    file_path=str(file_path),
                    chunk_type=CHUNK_TYPE_UNPARSEABLE,
                    name=file_path.name,
                    content=content,
                    start_line=1,
                    end_line=max(len(lines), 1),
                    imports=[],
                )
            ]

        module_imports = _imports_for_node(tree)
        module_docstring = ast.get_docstring(tree)
        chunks = [
            CodeChunk(
                chunk_id=str(uuid.uuid4()),
                file_path=str(file_path),
                chunk_type=CHUNK_TYPE_MODULE,
                name=file_path.name,
                content=self._module_content(tree, lines),
                start_line=1,
                end_line=self._module_end_line(tree),
                imports=module_imports,
                docstring=module_docstring,
            )
        ]
        for node, parent_name in self._structural_nodes(tree):
            chunks.extend(
                self._chunks_for_node(
                    file_path=file_path,
                    lines=lines,
                    node=node,
                    parent_name=parent_name,
                )
            )
        return chunks

    def _chunks_for_node(
        self,
        file_path: Path,
        lines: Sequence[str],
        node: ast.AST,
        parent_name: Optional[str],
    ) -> List[CodeChunk]:
        """Return one or more chunks for a class, function, or method node."""
        start_line = int(getattr(node, "lineno", 1))
        end_line = int(getattr(node, "end_lineno", start_line))
        name = str(getattr(node, "name", file_path.name))
        if isinstance(node, ast.ClassDef):
            chunk_type = CHUNK_TYPE_CLASS
            parent = None
        elif parent_name:
            chunk_type = CHUNK_TYPE_METHOD
            parent = parent_name
        else:
            chunk_type = CHUNK_TYPE_FUNCTION
            parent = None

        base_chunk = CodeChunk(
            chunk_id=str(uuid.uuid4()),
            file_path=str(file_path),
            chunk_type=chunk_type,
            name=name,
            content=self._content_slice(lines, start_line, end_line),
            start_line=start_line,
            end_line=end_line,
            parent_name=parent,
            imports=_imports_for_node(node),
            docstring=ast.get_docstring(node),
            complexity_score=_complexity_score(node),
        )
        return self._split_if_needed(base_chunk)

    def _structural_nodes(
        self,
        tree: ast.AST,
    ) -> List[tuple[ast.AST, Optional[str]]]:
        """Return class/function nodes with class parents for methods."""
        nodes: List[tuple[ast.AST, Optional[str]]] = []

        def visit(node: ast.AST, class_parent: Optional[str]) -> None:
            """Visit AST nodes while tracking the nearest class parent."""
            if isinstance(node, ast.ClassDef):
                nodes.append((node, None))
                for child in node.body:
                    visit(child, node.name)
                return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nodes.append((node, class_parent))
                for child in node.body:
                    visit(child, class_parent)
                return
            for child in ast.iter_child_nodes(node):
                visit(child, class_parent)

        visit(tree, None)
        return nodes

    def _split_if_needed(self, chunk: CodeChunk) -> List[CodeChunk]:
        """Split oversized chunks into max-line segments."""
        line_count = chunk.end_line - chunk.start_line + 1
        if line_count <= self.max_chunk_lines:
            return [chunk]

        lines = chunk.content.splitlines()
        split_chunks: List[CodeChunk] = []
        for offset in range(0, len(lines), self.max_chunk_lines):
            part_lines = lines[offset : offset + self.max_chunk_lines]
            part_start = chunk.start_line + offset
            part_end = part_start + len(part_lines) - 1
            split_chunks.append(
                CodeChunk(
                    chunk_id=str(uuid.uuid4()),
                    file_path=chunk.file_path,
                    chunk_type=chunk.chunk_type,
                    name=chunk.name,
                    content="\n".join(part_lines),
                    start_line=part_start,
                    end_line=part_end,
                    parent_name=chunk.parent_name,
                    imports=chunk.imports,
                    called_by=chunk.called_by,
                    docstring=chunk.docstring,
                    complexity_score=chunk.complexity_score,
                )
            )
        return split_chunks

    def _store_chunks(self, chunks: Sequence[CodeChunk]) -> None:
        """Embed and store chunks as vector records."""
        if not chunks:
            return
        embeddings = self.embedder.embed_batch([chunk.content for chunk in chunks])
        for chunk, embedding in zip(chunks, embeddings):
            self.vector_store.add(
                VectorRecord(
                    id=chunk.chunk_id,
                    text=chunk.content,
                    embedding=embedding,
                    metadata=_metadata_for_chunk(chunk),
                )
            )

    def _populate_called_by(self, chunks: Sequence[CodeChunk]) -> None:
        """Populate file-level reverse import references on chunks."""
        module_by_file = {
            chunk.file_path: Path(chunk.file_path).stem
            for chunk in chunks
            if chunk.chunk_type == CHUNK_TYPE_MODULE
        }
        imports_by_file = {
            chunk.file_path: set(chunk.imports)
            for chunk in chunks
            if chunk.chunk_type == CHUNK_TYPE_MODULE
        }
        called_by_by_file: Dict[str, List[str]] = {file_path: [] for file_path in module_by_file}
        for importer_file, imported_names in imports_by_file.items():
            for target_file, module_name in module_by_file.items():
                if importer_file == target_file:
                    continue
                if module_name in imported_names:
                    called_by_by_file[target_file].append(importer_file)
        for chunk in chunks:
            chunk.called_by = sorted(called_by_by_file.get(chunk.file_path, []))

    def _iter_files(
        self,
        root_path: Path,
        include_patterns: Iterable[str],
        exclude_patterns: Iterable[str],
    ) -> Iterable[Path]:
        """Yield files included by glob patterns and not excluded by pattern."""
        root = Path(root_path)
        for pattern in include_patterns:
            for file_path in root.rglob(pattern):
                if file_path.is_file() and not self._is_excluded(file_path, exclude_patterns):
                    yield file_path

    def _is_excluded(self, file_path: Path, exclude_patterns: Iterable[str]) -> bool:
        """Return whether a path matches any configured exclusion."""
        path_parts = file_path.parts
        for pattern in exclude_patterns:
            if any(part == pattern for part in path_parts):
                return True
            if file_path.match(pattern) or file_path.name == pattern:
                return True
        return False

    def _module_content(self, tree: ast.Module, lines: Sequence[str]) -> str:
        """Return module-level imports and docstring content."""
        selected_lines: List[str] = []
        docstring = ast.get_docstring(tree)
        if docstring:
            selected_lines.append(docstring)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                selected_lines.append(
                    self._content_slice(
                        lines,
                        int(getattr(node, "lineno", 1)),
                        int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                    )
                )
        return "\n".join(selected_lines).strip()

    def _module_end_line(self, tree: ast.Module) -> int:
        """Return the last line covered by module metadata."""
        end_line = 1
        for node in tree.body:
            if isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom)):
                end_line = max(end_line, int(getattr(node, "end_lineno", end_line)))
        return end_line

    def _content_slice(
        self,
        lines: Sequence[str],
        start_line: int,
        end_line: int,
    ) -> str:
        """Return source lines using one-based inclusive line numbers."""
        return "\n".join(lines[start_line - 1 : end_line])

    def _line_count(self, file_path: Path) -> int:
        """Return the number of text lines in a file."""
        return len(file_path.read_text(encoding=ENCODING).splitlines())

    def _record_ids_for_file(self, file_path: str) -> List[str]:
        """Return stored vector record IDs for one file path."""
        return [
            record.id
            for record in self._iter_records()
            if record.metadata.get(METADATA_KEY_FILE_PATH) == file_path
        ]

    def _all_record_ids(self) -> List[str]:
        """Return all record IDs available from the backing store."""
        return [record.id for record in self._iter_records()]

    def _iter_records(self) -> Iterable[VectorRecord]:
        """Yield records from vector stores that expose local record access."""
        records = getattr(self.vector_store, "records", None)
        if isinstance(records, list):
            return list(records)
        collection = getattr(self.vector_store, "collection", None)
        if collection is not None:
            try:
                response = collection.get(include=["documents", "metadatas"])
                return [
                    VectorRecord(
                        id=str(record_id),
                        text=str(document or ""),
                        embedding=[],
                        metadata=dict(metadata or {}),
                    )
                    for record_id, document, metadata in zip(
                        response.get("ids", []),
                        response.get("documents", []),
                        response.get("metadatas", []),
                    )
                ]
            except Exception as error:
                logger.warning("Could not enumerate vector records: %s", error)
        return []


def code_chunk_from_record(record: VectorRecord) -> CodeChunk:
    """Rebuild a CodeChunk from a vector record and stored metadata."""
    metadata = record.metadata
    return CodeChunk(
        chunk_id=str(metadata.get(METADATA_KEY_CHUNK_ID, record.id)),
        file_path=str(metadata.get(METADATA_KEY_FILE_PATH, "")),
        chunk_type=str(metadata.get(METADATA_KEY_CHUNK_TYPE, "")),
        name=str(metadata.get(METADATA_KEY_NAME, "")),
        content=record.text,
        start_line=int(metadata.get(METADATA_KEY_START_LINE, 1)),
        end_line=int(metadata.get(METADATA_KEY_END_LINE, 1)),
        parent_name=_optional_metadata_text(metadata.get(METADATA_KEY_PARENT_NAME)),
        imports=_json_list(metadata.get(METADATA_KEY_IMPORTS)),
        called_by=_json_list(metadata.get(METADATA_KEY_CALLED_BY)),
        docstring=_optional_metadata_text(metadata.get(METADATA_KEY_DOCSTRING)),
        complexity_score=_optional_float(metadata.get(METADATA_KEY_COMPLEXITY_SCORE)),
    )


def _metadata_for_chunk(chunk: CodeChunk) -> Dict[str, Any]:
    """Return vector-store metadata for one code chunk."""
    return {
        METADATA_KEY_CHUNK_ID: chunk.chunk_id,
        METADATA_KEY_FILE_PATH: chunk.file_path,
        METADATA_KEY_CHUNK_TYPE: chunk.chunk_type,
        METADATA_KEY_NAME: chunk.name,
        METADATA_KEY_START_LINE: chunk.start_line,
        METADATA_KEY_END_LINE: chunk.end_line,
        METADATA_KEY_PARENT_NAME: chunk.parent_name,
        METADATA_KEY_IMPORTS: json.dumps(chunk.imports),
        METADATA_KEY_CALLED_BY: json.dumps(chunk.called_by),
        METADATA_KEY_DOCSTRING: chunk.docstring,
        METADATA_KEY_COMPLEXITY_SCORE: chunk.complexity_score,
    }


def _imports_for_node(node: ast.AST) -> List[str]:
    """Return imported top-level names found inside an AST node."""
    imports: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            imports.extend(alias.name.split(".")[0] for alias in child.names)
        elif isinstance(child, ast.ImportFrom) and child.module:
            imports.append(child.module.split(".")[0])
    return sorted(set(imports))


def _complexity_score(node: ast.AST) -> Optional[float]:
    """Return optional cyclomatic complexity from radon when installed."""
    try:
        from radon.complexity import cc_visit_ast
    except ImportError:
        return None
    try:
        scores = cc_visit_ast(node)
    except Exception:
        return None
    if not scores:
        return None
    return float(scores[0].complexity)


def _json_list(value: Any) -> List[str]:
    """Decode a JSON metadata list into strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def _optional_metadata_text(value: Any) -> Optional[str]:
    """Return metadata text or None for empty values."""
    if isinstance(value, str) and value:
        return value
    return None


def _optional_float(value: Any) -> Optional[float]:
    """Return a float metadata value when available."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["CodeChunk", "CodeIndexer", "IndexingReport", "code_chunk_from_record"]
