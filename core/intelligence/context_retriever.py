"""Retrieve indexed code context for ProjectOS agent prompts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, TYPE_CHECKING

from core.intelligence.code_indexer import (
    CodeChunk,
    code_chunk_from_record,
)
from core.intelligence.embedder import BaseEmbedder
from core.intelligence.vector_store import BaseVectorStore, SearchResult, VectorRecord
from core.observability.tracer import Tracer, SpanStatus

if TYPE_CHECKING:
    from core.observability.token_budget import TokenBudget


CONTEXT_HEADER = "--- RELEVANT CODEBASE CONTEXT ---"
CONTEXT_SEPARATOR = "---"
PYTHON_FENCE_START = "```python"
PYTHON_FENCE_END = "```"
NEWLINE = "\n"
DEFAULT_MAX_CONTEXT_TOKENS = 2000
DEFAULT_TOP_K = 5
TOKEN_ESTIMATE_DIVISOR = 4
FILE_PATH_METADATA_KEY = "file_path"
IMPORTS_METADATA_KEY = "imports"
CALLED_BY_METADATA_KEY = "called_by"
SIMILARITY_TEMPLATE = "{score:.2f}"


@dataclass
class RetrievalContext:
    """Assembled context ready to inject into an agent prompt."""

    query: str
    retrieved_chunks: List[CodeChunk]
    similarity_scores: List[float]
    retrieval_duration_ms: int
    total_tokens_estimate: int = field(init=False)
    _formatted_context: Optional[str] = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Compute a rough token estimate after construction."""
        self.total_tokens_estimate = len(self.formatted_context) // TOKEN_ESTIMATE_DIVISOR

    @property
    def formatted_context(self) -> str:
        """Return retrieved chunks formatted for prompt injection."""
        if self._formatted_context is not None:
            return self._formatted_context
        if not self.retrieved_chunks:
            return CONTEXT_HEADER
        sections = [CONTEXT_HEADER]
        for chunk, score in zip(self.retrieved_chunks, self.similarity_scores):
            sections.extend(
                [
                    (
                        f"[{chunk.file_path}:{chunk.start_line}-{chunk.end_line}] "
                        f"(similarity: {SIMILARITY_TEMPLATE.format(score=score)})"
                    ),
                    PYTHON_FENCE_START,
                    chunk.content,
                    PYTHON_FENCE_END,
                    CONTEXT_SEPARATOR,
                ]
            )
        return NEWLINE.join(sections).rstrip()


class ContextRetriever:
    """Retrieve relevant code chunks for a given agent task."""

    def __init__(
        self,
        vector_store: BaseVectorStore,
        embedder: BaseEmbedder,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        top_k: int = DEFAULT_TOP_K,
        tracer: Optional[Tracer] = None,
        token_budget: Optional[TokenBudget] = None,
    ) -> None:
        """Initialize retrieval dependencies and limits."""
        self.vector_store = vector_store
        self.embedder = embedder
        self.max_context_tokens = max_context_tokens
        self.top_k = top_k
        self.tracer = tracer
        self.token_budget = token_budget

    def retrieve_for_task(
        self,
        task_description: str,
        file_path: Optional[str] = None,
        agent_name: Optional[str] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        token_budget: Optional[TokenBudget] = None,
    ) -> RetrievalContext:
        """Retrieve and format relevant chunks for one agent task."""
        span = self.tracer.start_span("context_retrieval", component="context_retriever") if self.tracer else None
        try:
            started_at = time.perf_counter()
            query = self._query_text(task_description, file_path, agent_name)
            results = self.vector_store.search(
                self.embedder.embed(query),
                k=self.top_k,
                filter_metadata=metadata_filter,
            )
            combined_results = list(results)
            if file_path:
                combined_results.extend(self._file_results(file_path))
            deduplicated_results = self._deduplicated_results(combined_results)
            trimmed_results = self._trimmed_results(deduplicated_results)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            context = RetrievalContext(
                query=query,
                retrieved_chunks=[
                    code_chunk_from_record(result.record) for result in trimmed_results
                ],
                similarity_scores=[
                    result.similarity_score for result in trimmed_results
                ],
                retrieval_duration_ms=duration_ms,
            )

            tb = token_budget or getattr(self, "token_budget", None)
            if tb:
                budgets_dict = getattr(tb, "budgets", tb.DEFAULT_BUDGETS)
                agent_budget = budgets_dict.get(agent_name or "default", budgets_dict["default"])
                budget_for_context = agent_budget["hard_limit_per_call"] // 3
                trimmed_context = tb.trim_context_to_budget(
                    context.formatted_context, budget_for_context
                )
                context._formatted_context = trimmed_context
                context.total_tokens_estimate = len(trimmed_context) // TOKEN_ESTIMATE_DIVISOR

            if span:
                span.tags.update({
                    "chunks_retrieved": len(context.retrieved_chunks),
                    "query_tokens": len(query) // 4
                })
                span.finish(SpanStatus.OK)
            return context
        except Exception as e:
            if span:
                span.finish(SpanStatus.ERROR, error=str(e))
            raise

    def retrieve_related_files(self, file_path: str) -> List[str]:
        """Return files that import or are imported by the given file path."""
        target_path = str(Path(file_path))
        target_module = Path(target_path).stem
        related_files = set()
        for record in self._iter_records():
            record_file_path = str(record.metadata.get(FILE_PATH_METADATA_KEY, ""))
            if not record_file_path or record_file_path == target_path:
                continue
            imports_text = str(record.metadata.get(IMPORTS_METADATA_KEY, ""))
            called_by_text = str(record.metadata.get(CALLED_BY_METADATA_KEY, ""))
            if target_module in imports_text or target_path in called_by_text:
                related_files.add(record_file_path)
        return sorted(related_files)

    def _query_text(
        self,
        task_description: str,
        file_path: Optional[str],
        agent_name: Optional[str],
    ) -> str:
        """Build a retrieval query from task, file, and agent metadata."""
        parts = [task_description.strip()]
        if file_path:
            parts.append(str(file_path))
        if agent_name:
            parts.append(str(agent_name))
        return NEWLINE.join(part for part in parts if part)

    def _file_results(self, file_path: str) -> List[SearchResult]:
        """Return chunks from a file with a forced perfect score."""
        file_path_text = str(Path(file_path))
        results: List[SearchResult] = []
        for record in self._iter_records():
            if record.metadata.get(FILE_PATH_METADATA_KEY) == file_path_text:
                results.append(
                    SearchResult(
                        record=record,
                        similarity_score=1.0,
                        rank=0,
                    )
                )
        return results

    def _deduplicated_results(self, results: Iterable[SearchResult]) -> List[SearchResult]:
        """Deduplicate search results by chunk ID, keeping the best score."""
        best_by_id: Dict[str, SearchResult] = {}
        for result in results:
            record_id = result.record.id
            existing_result = best_by_id.get(record_id)
            if existing_result is None or result.similarity_score > existing_result.similarity_score:
                best_by_id[record_id] = result
        return sorted(
            best_by_id.values(),
            key=lambda result: result.similarity_score,
            reverse=True,
        )

    def _trimmed_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """Drop lowest-score chunks until the context fits the token budget."""
        kept_results: List[SearchResult] = []
        for result in results:
            candidate_results = kept_results + [result]
            context = RetrievalContext(
                query="",
                retrieved_chunks=[
                    code_chunk_from_record(candidate.record)
                    for candidate in candidate_results
                ],
                similarity_scores=[
                    candidate.similarity_score for candidate in candidate_results
                ],
                retrieval_duration_ms=0,
            )
            if context.total_tokens_estimate <= self.max_context_tokens:
                kept_results.append(result)
        return kept_results

    def _iter_records(self) -> Iterable[VectorRecord]:
        """Yield records from vector stores that expose local record access."""
        records = getattr(self.vector_store, "records", None)
        if isinstance(records, list):
            return list(records)
        collection = getattr(self.vector_store, "collection", None)
        if collection is not None:
            try:
                response = collection.get(include=["documents", "metadatas", "embeddings"])
                return [
                    VectorRecord(
                        id=str(record_id),
                        text=str(document or ""),
                        embedding=list(embedding or []),
                        metadata=dict(metadata or {}),
                    )
                    for record_id, document, metadata, embedding in zip(
                        response.get("ids", []),
                        response.get("documents", []),
                        response.get("metadatas", []),
                        response.get("embeddings", []),
                    )
                ]
            except Exception:
                return []
        return []


__all__ = ["ContextRetriever", "RetrievalContext"]
