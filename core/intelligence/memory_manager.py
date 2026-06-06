"""High-level agent memory helpers for ProjectOS."""

from __future__ import annotations

import json
import uuid
from typing import Any, List, Optional

from core.evaluation.base_evaluator import EvaluationResult
from core.events import AgentResult
from core.intelligence.embedder import BaseEmbedder
from core.intelligence.memory_store import MemoryRecord, MemoryStore, MemoryType
from core.observability.tracer import Tracer, SpanStatus



EXPERIENCE_HEADER = "--- RELEVANT PAST EXPERIENCE ---"
EXPERIENCE_FOOTER = "--- END EXPERIENCE ---"
NEWLINE = "\n"
DEFAULT_DECISION_IMPORTANCE = 0.5
DEFAULT_PATTERN_CONFIDENCE = 0.7
DEFAULT_RECALL_K = 3
MAX_PATTERN_EXAMPLES = 3
MAX_WORKFLOW_NAME_CHARS = 50
HIGH_QUALITY_SCORE = 0.8
FAILURE_IMPORTANCE = 0.2
MEMORY_CONTEXT_DECISION = "decision"
MEMORY_CONTEXT_PATTERN = "pattern"
MEMORY_CONTEXT_WORKFLOW = "workflow"
MEMORY_CONTEXT_EVALUATION = "evaluation"
MEMORY_METADATA_OUTCOME = "outcome"
MEMORY_METADATA_QUALITY_SCORE = "quality_score"
MEMORY_METADATA_SUCCESS_RATE = "success_rate"


class MemoryManager:
    """High-level interface for agents to remember and recall experience."""

    def __init__(
        self,
        memory_store: MemoryStore,
        embedder: BaseEmbedder,
        tracer: Optional[Tracer] = None,
    ) -> None:
        """Initialize the manager with persistent memory storage."""
        self.memory_store = memory_store
        self.embedder = embedder
        self.tracer = tracer

    def remember_decision(
        self,
        agent_name: str,
        decision: str,
        context: str,
        outcome: str,
        quality_score: Optional[float] = None,
    ) -> None:
        """Store an episodic memory for one agent decision."""
        importance = quality_score if quality_score is not None else DEFAULT_DECISION_IMPORTANCE
        self.memory_store.store(
            MemoryRecord(
                memory_id=str(uuid.uuid4()),
                memory_type=MemoryType.EPISODIC,
                agent_name=agent_name,
                content=f"Decision: {decision}. Outcome: {outcome}.",
                context=context,
                importance_score=importance,
                metadata={
                    MEMORY_METADATA_OUTCOME: outcome,
                    MEMORY_METADATA_QUALITY_SCORE: quality_score,
                },
            )
        )

    def remember_pattern(
        self,
        agent_name: str,
        pattern: str,
        examples: List[str],
        confidence: float = DEFAULT_PATTERN_CONFIDENCE,
    ) -> None:
        """Store a semantic memory for a recurring project pattern."""
        rendered_examples = "; ".join(examples[:MAX_PATTERN_EXAMPLES])
        self.memory_store.store(
            MemoryRecord(
                memory_id=str(uuid.uuid4()),
                memory_type=MemoryType.SEMANTIC,
                agent_name=agent_name,
                content=f"Pattern: {pattern}. Examples: {rendered_examples}",
                context=f"{MEMORY_CONTEXT_PATTERN}: {pattern} {rendered_examples}",
                importance_score=confidence,
                metadata={"examples": examples},
            )
        )

    def remember_workflow(
        self,
        agent_name: str,
        workflow_name: str,
        steps: List[str],
        success_rate: float,
    ) -> None:
        """Store a procedural memory for a successful workflow."""
        rendered_steps = " -> ".join(steps)
        self.memory_store.store(
            MemoryRecord(
                memory_id=str(uuid.uuid4()),
                memory_type=MemoryType.PROCEDURAL,
                agent_name=agent_name,
                content=f"Workflow '{workflow_name}': {rendered_steps}",
                context=f"{MEMORY_CONTEXT_WORKFLOW}: {workflow_name} {rendered_steps}",
                importance_score=success_rate,
                metadata={MEMORY_METADATA_SUCCESS_RATE: success_rate},
            )
        )

    def recall(
        self,
        agent_name: str,
        query: str,
        k: int = DEFAULT_RECALL_K,
    ) -> str:
        """Return formatted memories relevant to one agent query."""
        span = self.tracer.start_span("memory.recall", component="memory_manager") if self.tracer else None
        try:
            memories = self.memory_store.retrieve(query, agent_name, k=k)
            if span:
                span.tags.update({
                    "memories_retrieved": len(memories),
                    "agent_name": agent_name
                })
                span.finish(SpanStatus.OK)
            if not memories:
                return ""
            return NEWLINE.join(
                [EXPERIENCE_HEADER]
                + [memory.to_retrieval_text() for memory in memories]
                + [EXPERIENCE_FOOTER]
            )
        except Exception as e:
            if span:
                span.finish(SpanStatus.ERROR, error=str(e))
            raise

    def learn_from_evaluation(
        self,
        agent_result: AgentResult,
        evaluation: EvaluationResult,
    ) -> None:
        """Extract reusable memories from one evaluated agent result."""
        outcome = self._evaluation_outcome(evaluation)
        context = self._evaluation_context(agent_result, evaluation)
        self.remember_decision(
            agent_name=evaluation.agent_name,
            decision=self._decision_summary(agent_result),
            context=context,
            outcome=outcome,
            quality_score=evaluation.weighted_score,
        )
        if evaluation.passed and evaluation.weighted_score > HIGH_QUALITY_SCORE:
            self.remember_pattern(
                agent_name=evaluation.agent_name,
                pattern="High quality agent output pattern",
                examples=[self._output_text(agent_result)],
                confidence=evaluation.weighted_score,
            )
            return
        if not evaluation.passed:
            self.memory_store.store(
                MemoryRecord(
                    memory_id=str(uuid.uuid4()),
                    memory_type=MemoryType.EPISODIC,
                    agent_name=evaluation.agent_name,
                    content=f"Failure: {evaluation.reasoning}",
                    context=context,
                    importance_score=FAILURE_IMPORTANCE,
                    metadata={"event_id": evaluation.event_id},
                )
            )

    def _evaluation_outcome(self, evaluation: EvaluationResult) -> str:
        """Return an outcome sentence for an evaluation."""
        status = "passed" if evaluation.passed else "failed"
        return f"Evaluation {status} with score {evaluation.weighted_score:.2f}"

    def _evaluation_context(
        self,
        agent_result: AgentResult,
        evaluation: EvaluationResult,
    ) -> str:
        """Return retrieval context for an evaluated result."""
        return (
            f"{MEMORY_CONTEXT_EVALUATION}: {evaluation.agent_name} "
            f"{evaluation.event_id} {evaluation.reasoning} "
            f"{self._output_text(agent_result)}"
        )

    def _decision_summary(self, agent_result: AgentResult) -> str:
        """Return a compact decision summary from an agent result."""
        if isinstance(agent_result.output, dict):
            return ", ".join(sorted(str(key) for key in agent_result.output.keys()))
        return self._output_text(agent_result)

    def _output_text(self, agent_result: AgentResult) -> str:
        """Return deterministic text for an agent output."""
        try:
            return json.dumps(agent_result.output, sort_keys=True, default=str)
        except TypeError:
            return str(agent_result.output)


__all__ = ["MemoryManager"]
