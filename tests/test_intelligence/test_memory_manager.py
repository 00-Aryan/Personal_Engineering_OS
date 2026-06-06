"""Tests for ProjectOS memory manager helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.evaluation.base_evaluator import EvaluationResult
from core.events import AgentResult
from core.intelligence.embedder import BaseEmbedder
from core.intelligence.memory_manager import MemoryManager
from core.intelligence.memory_store import MemoryStore, MemoryType
from core.intelligence.vector_store import NumpyVectorStore


AGENT_NAME = "planning"
DECISION_TEXT = "Use dataclass tasks"
CONTEXT_TEXT = "planning backlog decomposition"
OUTCOME_TEXT = "Approved"
PATTERN_TEXT = "Use dataclasses instead of Pydantic"
WORKFLOW_NAME = "Auth feature planning"
EVENT_ID = "event-1"


class ConstantEmbedder(BaseEmbedder):
    """Deterministic embedder for memory manager tests."""

    def embed(self, text: str) -> list[float]:
        """Return a constant non-zero vector."""
        return [1.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return one constant vector per text."""
        return [self.embed(text) for text in texts]

    def get_dimension(self) -> int:
        """Return the fixed test dimension."""
        return 1

    def get_embedder_name(self) -> str:
        """Return the test embedder name."""
        return "constant-test"


def test_remember_decision_creates_episodic_record(tmp_path: Path) -> None:
    """Verify remember_decision stores an episodic memory."""
    manager, store = _manager(tmp_path)

    manager.remember_decision(AGENT_NAME, DECISION_TEXT, CONTEXT_TEXT, OUTCOME_TEXT)

    stats = store.get_stats(AGENT_NAME)
    assert stats["total_records"] == 1
    assert stats["by_type"]["episodic"] == 1


def test_remember_pattern_creates_semantic_record(tmp_path: Path) -> None:
    """Verify remember_pattern stores a semantic memory."""
    manager, store = _manager(tmp_path)

    manager.remember_pattern(AGENT_NAME, PATTERN_TEXT, ["Task uses dataclass"])

    stats = store.get_stats(AGENT_NAME)
    assert stats["total_records"] == 1
    assert stats["by_type"]["semantic"] == 1


def test_recall_returns_formatted_string(tmp_path: Path) -> None:
    """Verify recall returns a prompt-ready experience block."""
    manager, _store = _manager(tmp_path)
    manager.remember_decision(AGENT_NAME, DECISION_TEXT, CONTEXT_TEXT, OUTCOME_TEXT)

    recalled_text = manager.recall(AGENT_NAME, CONTEXT_TEXT)

    assert recalled_text.startswith("--- RELEVANT PAST EXPERIENCE ---")
    assert "[episodic]" in recalled_text
    assert recalled_text.endswith("--- END EXPERIENCE ---")


def test_recall_empty_returns_empty_string(tmp_path: Path) -> None:
    """Verify recall returns empty text when no memories match."""
    manager, _store = _manager(tmp_path)

    assert manager.recall(AGENT_NAME, CONTEXT_TEXT) == ""


def test_learn_from_evaluation_creates_memory_on_pass(tmp_path: Path) -> None:
    """Verify high-scoring passing evaluations create decision and pattern memories."""
    manager, store = _manager(tmp_path)

    manager.learn_from_evaluation(
        AgentResult(success=True, output={"tasks": [{"title": "Schema"}]}),
        _evaluation_result(passed=True, weighted_score=0.9),
    )

    stats = store.get_stats(AGENT_NAME)
    assert stats["total_records"] == 2
    assert stats["by_type"]["episodic"] == 1
    assert stats["by_type"]["semantic"] == 1


def test_learn_from_evaluation_stores_failure_context(tmp_path: Path) -> None:
    """Verify failing evaluations store failure context as episodic memory."""
    manager, store = _manager(tmp_path)

    manager.learn_from_evaluation(
        AgentResult(success=False, output={"error": "invalid json"}),
        _evaluation_result(passed=False, weighted_score=0.3),
    )

    stats = store.get_stats(AGENT_NAME)
    assert stats["total_records"] == 2
    assert stats["by_type"]["episodic"] == 2


def _manager(tmp_path: Path) -> tuple[MemoryManager, MemoryStore]:
    """Return a memory manager and its backing store."""
    embedder = ConstantEmbedder()
    store = MemoryStore(
        lambda collection_name, state_dir, embedder: NumpyVectorStore(
            collection_name,
            state_dir,
        ),
        embedder,
        tmp_path,
    )
    return MemoryManager(store, embedder), store


def _evaluation_result(passed: bool, weighted_score: float) -> EvaluationResult:
    """Return an evaluation result with shared defaults."""
    return EvaluationResult(
        evaluator_name="unit_evaluator",
        agent_name=AGENT_NAME,
        event_id=EVENT_ID,
        timestamp=datetime.now(timezone.utc),
        criteria_scores={"quality": weighted_score},
        weighted_score=weighted_score,
        passed=passed,
        reasoning="evaluation reasoning",
        raw_output_sample="sample",
        evaluation_duration_ms=1,
        evaluator_model="test-model",
        metadata={},
    )
