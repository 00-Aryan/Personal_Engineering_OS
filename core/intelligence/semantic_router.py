"""Semantic routing for Clone Agent decisions and dispatch targets."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.intelligence.embedder import BaseEmbedder
from core.intelligence.vector_store import BaseVectorStore, SearchResult, VectorRecord


ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"
ROUTING_EXAMPLES_COLLECTION = "routing_examples"
ROUTING_DECISIONS_FILE_NAME = "routing_decisions.jsonl"
ROUTING_METHOD_SEMANTIC = "semantic"
ROUTING_METHOD_KEYWORD_FALLBACK = "keyword_fallback"
DEFAULT_MIN_CONFIDENCE = 0.60
DEFAULT_TOP_K = 3
METADATA_KEY_CATEGORY = "category"
METADATA_KEY_TEXT = "text"
METADATA_KEY_WEIGHT = "weight"
STATS_KEY_TOTAL_DECISIONS = "total_decisions"
STATS_KEY_SEMANTIC_PCT = "semantic_pct"
STATS_KEY_FALLBACK_PCT = "fallback_pct"
STATS_KEY_AVG_CONFIDENCE = "avg_confidence"
STATS_KEY_DECISIONS_BY_CATEGORY = "decisions_by_category"

CATEGORY_AUTONOMOUS = "AUTONOMOUS"
CATEGORY_ESCALATE = "ESCALATE"
CATEGORY_DEFER_PARALLEL = "DEFER_PARALLEL"
CATEGORY_PLANNING = "planning"
CATEGORY_CODE_WRITING = "code_writing"
CATEGORY_CODE_REVIEW = "code_review"
CATEGORY_ARCHITECTURE = "architecture"
CATEGORY_TEST = "test"
CATEGORY_DOCS = "docs"

KEYWORD_NEW_DEPENDENCY = "new_dependency"
KEYWORD_NEW_DEPENDENCY_TEXT = "new dependency"
KEYWORD_DEPENDENCY = "dependency"
KEYWORD_ADDED = "added"
KEYWORD_BREAKING_CHANGE = "breaking_change"
KEYWORD_DELETE_FILE = "delete_file"
KEYWORD_ARCHITECTURE_CHANGE = "architecture_change"
KEYWORD_ESCALATE = "escalate"
KEYWORD_PERMISSION_BLOCKED = "permission_blocked"
KEYWORD_BLOCKED_BY = "blocked_by"
KEYWORD_PERMISSION = "permission"
KEYWORD_APPROVAL = "approval"
KEYWORD_FORMATTING = "formatting"
KEYWORD_DOCSTRING = "docstring"
KEYWORD_COMMENT = "comment"
KEYWORD_STATUS_UPDATE = "status_update"
KEYWORD_TESTS_DONE = "tests_done"
KEYWORD_REVIEW_DONE = "review_done"
KEYWORD_DOCS_UPDATED = "docs_updated"


@dataclass
class RoutingExample:
    """One labeled example used by the semantic router."""

    text: str
    category: str
    weight: float = 1.0


@dataclass
class RoutingDecision:
    """One semantic or fallback routing decision."""

    category: str
    confidence: float
    nearest_example: str
    routing_method: str
    duration_ms: int


class SemanticRouter:
    """Route event descriptions using embedding similarity and keyword fallback."""

    DEFAULT_ROUTING_EXAMPLES: List[RoutingExample] = [
        RoutingExample("updated function docstring", CATEGORY_AUTONOMOUS),
        RoutingExample("fixed code formatting", CATEGORY_AUTONOMOUS),
        RoutingExample("added type hints to function", CATEGORY_AUTONOMOUS),
        RoutingExample("test file generated for module", CATEGORY_AUTONOMOUS),
        RoutingExample("documentation updated after code change", CATEGORY_AUTONOMOUS),
        RoutingExample("backlog status updated to done", CATEGORY_AUTONOMOUS),
        RoutingExample("comment added to explain logic", CATEGORY_AUTONOMOUS),
        RoutingExample("new external package dependency added", CATEGORY_ESCALATE),
        RoutingExample("breaking change to public API", CATEGORY_ESCALATE),
        RoutingExample("file deleted from repository", CATEGORY_ESCALATE),
        RoutingExample("database schema migration required", CATEGORY_ESCALATE),
        RoutingExample("authentication logic modified", CATEGORY_ESCALATE),
        RoutingExample("changes to more than five core files", CATEGORY_ESCALATE),
        RoutingExample("security vulnerability detected in code", CATEGORY_ESCALATE),
        RoutingExample("waiting for permission to write file", CATEGORY_DEFER_PARALLEL),
        RoutingExample("blocked by sandbox restriction", CATEGORY_DEFER_PARALLEL),
        RoutingExample("requires human approval before proceeding", CATEGORY_DEFER_PARALLEL),
        RoutingExample("dependency on another task not yet complete", CATEGORY_DEFER_PARALLEL),
        RoutingExample("new feature request for the system", CATEGORY_PLANNING),
        RoutingExample("implement a function that does X", CATEGORY_CODE_WRITING),
        RoutingExample("review the quality of this code file", CATEGORY_CODE_REVIEW),
        RoutingExample("should we use pattern A or pattern B", CATEGORY_ARCHITECTURE),
        RoutingExample("write tests for this module", CATEGORY_TEST),
        RoutingExample("update docs to reflect new function", CATEGORY_DOCS),
    ]

    def __init__(
        self,
        embedder: BaseEmbedder,
        vector_store: BaseVectorStore,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        log_path: Optional[Path] = None,
    ) -> None:
        """Initialize router storage, defaults, and decision log path."""
        self.embedder = embedder
        self.vector_store = vector_store
        self.min_confidence = min_confidence
        self.log_path = Path(log_path) if log_path is not None else None
        self._ensure_default_examples()

    def route(self, event_description: str) -> RoutingDecision:
        """Route an event description to a decision category or target agent."""
        started_at = time.perf_counter()
        query_text = event_description or EMPTY_TEXT
        results = self.vector_store.search(
            self.embedder.embed(query_text),
            k=DEFAULT_TOP_K,
        )
        nearest_result = self._nearest_result(results)
        if nearest_result is not None and nearest_result.similarity_score >= self.min_confidence:
            decision = self._semantic_decision(nearest_result, started_at)
        else:
            decision = self._fallback_decision(query_text, nearest_result, started_at)
        self._log_decision(query_text, decision)
        return decision

    def add_example(self, example: RoutingExample) -> None:
        """Embed and persist a new routing example immediately."""
        self._store_example(example)

    def get_routing_stats(self) -> Dict[str, Any]:
        """Return summary statistics from routing_decisions.jsonl."""
        records = self._decision_records()
        total_decisions = len(records)
        decisions_by_category: Dict[str, int] = {}
        semantic_count = 0
        fallback_count = 0
        confidence_total = 0.0
        for record in records:
            category = str(record.get("category", EMPTY_TEXT))
            decisions_by_category[category] = decisions_by_category.get(category, 0) + 1
            method = record.get("routing_method")
            if method == ROUTING_METHOD_SEMANTIC:
                semantic_count += 1
            if method == ROUTING_METHOD_KEYWORD_FALLBACK:
                fallback_count += 1
            confidence_total += float(record.get("confidence", 0.0))
        if total_decisions == 0:
            return {
                STATS_KEY_TOTAL_DECISIONS: 0,
                STATS_KEY_SEMANTIC_PCT: 0.0,
                STATS_KEY_FALLBACK_PCT: 0.0,
                STATS_KEY_AVG_CONFIDENCE: 0.0,
                STATS_KEY_DECISIONS_BY_CATEGORY: {},
            }
        return {
            STATS_KEY_TOTAL_DECISIONS: total_decisions,
            STATS_KEY_SEMANTIC_PCT: semantic_count / total_decisions,
            STATS_KEY_FALLBACK_PCT: fallback_count / total_decisions,
            STATS_KEY_AVG_CONFIDENCE: confidence_total / total_decisions,
            STATS_KEY_DECISIONS_BY_CATEGORY: decisions_by_category,
        }

    def _ensure_default_examples(self) -> None:
        """Seed default routing examples on first run."""
        if self.vector_store.count() > 0:
            return
        texts = [example.text for example in self.DEFAULT_ROUTING_EXAMPLES]
        embeddings = self.embedder.embed_batch(texts)
        for example, embedding in zip(self.DEFAULT_ROUTING_EXAMPLES, embeddings):
            self.vector_store.add(
                VectorRecord(
                    id=str(uuid.uuid4()),
                    text=example.text,
                    embedding=embedding,
                    metadata=_metadata_for_example(example),
                )
            )

    def _store_example(self, example: RoutingExample) -> None:
        """Store one routing example in the vector store."""
        self.vector_store.add(
            VectorRecord(
                id=str(uuid.uuid4()),
                text=example.text,
                embedding=self.embedder.embed(example.text),
                metadata=_metadata_for_example(example),
            )
        )

    def _nearest_result(self, results: List[SearchResult]) -> Optional[SearchResult]:
        """Return the highest weighted search result."""
        if not results:
            return None
        return max(results, key=lambda result: self._weighted_similarity(result))

    def _weighted_similarity(self, result: SearchResult) -> float:
        """Return similarity adjusted by example weight."""
        try:
            weight = float(result.record.metadata.get(METADATA_KEY_WEIGHT, 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        return result.similarity_score * weight

    def _semantic_decision(
        self,
        result: SearchResult,
        started_at: float,
    ) -> RoutingDecision:
        """Build a semantic routing decision from the nearest example."""
        return RoutingDecision(
            category=str(result.record.metadata.get(METADATA_KEY_CATEGORY, EMPTY_TEXT)),
            confidence=result.similarity_score,
            nearest_example=str(result.record.metadata.get(METADATA_KEY_TEXT, result.record.text)),
            routing_method=ROUTING_METHOD_SEMANTIC,
            duration_ms=_duration_ms(started_at),
        )

    def _fallback_decision(
        self,
        event_description: str,
        nearest_result: Optional[SearchResult],
        started_at: float,
    ) -> RoutingDecision:
        """Build a keyword fallback routing decision."""
        return RoutingDecision(
            category=self._keyword_category(event_description),
            confidence=0.0,
            nearest_example=(
                str(nearest_result.record.metadata.get(METADATA_KEY_TEXT, nearest_result.record.text))
                if nearest_result is not None
                else EMPTY_TEXT
            ),
            routing_method=ROUTING_METHOD_KEYWORD_FALLBACK,
            duration_ms=_duration_ms(started_at),
        )

    def _keyword_category(self, event_description: str) -> str:
        """Return a fallback category using legacy keyword semantics."""
        text = event_description.lower()
        if (
            KEYWORD_PERMISSION_BLOCKED in text
            or KEYWORD_BLOCKED_BY in text
            or (KEYWORD_PERMISSION in text and KEYWORD_APPROVAL in text)
        ):
            return CATEGORY_DEFER_PARALLEL
        if any(
            keyword in text
            for keyword in (
                KEYWORD_NEW_DEPENDENCY,
                KEYWORD_NEW_DEPENDENCY_TEXT,
                KEYWORD_BREAKING_CHANGE,
                KEYWORD_DELETE_FILE,
                KEYWORD_ARCHITECTURE_CHANGE,
                KEYWORD_ESCALATE,
            )
        ) or (KEYWORD_DEPENDENCY in text and KEYWORD_ADDED in text):
            return CATEGORY_ESCALATE
        if any(
            keyword in text
            for keyword in (
                KEYWORD_FORMATTING,
                KEYWORD_DOCSTRING,
                KEYWORD_COMMENT,
                KEYWORD_STATUS_UPDATE,
                KEYWORD_TESTS_DONE,
                KEYWORD_REVIEW_DONE,
                KEYWORD_DOCS_UPDATED,
            )
        ):
            return CATEGORY_AUTONOMOUS
        return CATEGORY_AUTONOMOUS

    def _log_decision(self, event_description: str, decision: RoutingDecision) -> None:
        """Append one routing decision to routing_decisions.jsonl."""
        if self.log_path is None:
            return
        payload = {
            "timestamp": _utc_timestamp(),
            "event_description": event_description,
            "category": decision.category,
            "confidence": decision.confidence,
            "nearest_example": decision.nearest_example,
            "routing_method": decision.routing_method,
            "duration_ms": decision.duration_ms,
        }
        _append_atomically(self.log_path, f"{json.dumps(payload, sort_keys=True)}{NEWLINE}")

    def _decision_records(self) -> List[Dict[str, Any]]:
        """Load routing decision records from the JSONL log."""
        if self.log_path is None or not self.log_path.exists():
            return []
        records: List[Dict[str, Any]] = []
        for line in self.log_path.read_text(encoding=ENCODING).splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records


def _metadata_for_example(example: RoutingExample) -> Dict[str, Any]:
    """Return vector metadata for a routing example."""
    return {
        METADATA_KEY_TEXT: example.text,
        METADATA_KEY_CATEGORY: example.category,
        METADATA_KEY_WEIGHT: example.weight,
    }


def _append_atomically(path: Path, content: str) -> None:
    """Append text to a file using atomic replacement."""
    existing_content = path.read_text(encoding=ENCODING) if path.exists() else EMPTY_TEXT
    _write_atomically(path, f"{existing_content}{content}")


def _write_atomically(path: Path, content: str) -> None:
    """Write text to a path using atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{TEMP_PREFIX}{path.name}.",
        suffix=TEMP_SUFFIX,
        dir=str(path.parent),
    )
    try:
        with os.fdopen(file_descriptor, FILE_WRITE_MODE, encoding=ENCODING) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _duration_ms(started_at: float) -> int:
    """Return elapsed milliseconds from a monotonic timestamp."""
    return int((time.perf_counter() - started_at) * 1000)


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


__all__ = ["RoutingDecision", "RoutingExample", "SemanticRouter"]
