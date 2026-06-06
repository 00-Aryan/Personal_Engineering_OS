"""Unified quality scoring across LLM and static analysis results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from core.evaluation.base_evaluator import EvaluationResult
from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.static_analyzer import StaticAnalysisReport, StaticAnalyzer
from core.events import AgentResult


DEFAULT_LLM_WEIGHT = 0.60
DEFAULT_STATIC_WEIGHT = 0.40
WEIGHT_SUM_TARGET = 1.0
WEIGHT_SUM_TOLERANCE = 0.000001
PASSING_THRESHOLD = 0.65
DEFAULT_AGENT_NAME = "unknown"
DEFAULT_EVENT_ID = "unknown"

BREAKDOWN_KEY_LLM = "llm"
BREAKDOWN_KEY_STATIC = "static"
BREAKDOWN_KEY_LLM_WEIGHT = "llm_weight"
BREAKDOWN_KEY_STATIC_WEIGHT = "static_weight"


@dataclass(frozen=True)
class CombinedScore:
    """Combined quality score for one agent result."""

    agent_name: str
    event_id: str
    file_path: Optional[str]
    llm_score: Optional[float]
    static_score: Optional[float]
    combined_score: float
    passed: bool
    breakdown: Dict[str, float]
    timestamp: datetime


class QualityScorer:
    """Combine LLM evaluation scores with static analysis scores."""

    def __init__(
        self,
        static_analyzer: StaticAnalyzer,
        evaluation_store: EvaluationStore,
        llm_weight: float = DEFAULT_LLM_WEIGHT,
        static_weight: float = DEFAULT_STATIC_WEIGHT,
    ) -> None:
        """Initialize scorer dependencies and validate weights."""
        if abs((llm_weight + static_weight) - WEIGHT_SUM_TARGET) > WEIGHT_SUM_TOLERANCE:
            raise ValueError("QualityScorer weights must sum to 1.0.")
        self.static_analyzer = static_analyzer
        self.evaluation_store = evaluation_store
        self.llm_weight = llm_weight
        self.static_weight = static_weight

    def score(
        self,
        agent_result: AgentResult,
        llm_evaluation: Optional[EvaluationResult],
        file_path: Optional[Path],
    ) -> CombinedScore:
        """Return a unified quality score for an agent output."""
        static_report = self._static_report(file_path)
        llm_score = self._llm_score(llm_evaluation)
        static_score = self._static_score(static_report)
        combined_score = self._combined_score(llm_score, static_score)
        return CombinedScore(
            agent_name=self._agent_name(agent_result, llm_evaluation),
            event_id=self._event_id(agent_result, llm_evaluation),
            file_path=str(file_path) if file_path is not None else None,
            llm_score=llm_score,
            static_score=static_score,
            combined_score=combined_score,
            passed=combined_score >= PASSING_THRESHOLD,
            breakdown=self._breakdown(llm_score, static_score),
            timestamp=datetime.now(timezone.utc),
        )

    def _static_report(self, file_path: Optional[Path]) -> Optional[StaticAnalysisReport]:
        """Return a static report or None when static analysis is unavailable."""
        if file_path is None:
            return None
        try:
            report = self.static_analyzer.analyze(file_path)
        except Exception:
            return None
        if not self._has_static_signal(report):
            return None
        return report

    def _has_static_signal(self, report: StaticAnalysisReport) -> bool:
        """Return whether at least one static analyzer provided file signal."""
        return (
            report.security.bandit_available
            or report.style.flake8_available
            or report.complexity.lines_of_code > 0
        )

    def _llm_score(self, llm_evaluation: Optional[EvaluationResult]) -> Optional[float]:
        """Return the LLM score when present."""
        if llm_evaluation is None:
            return None
        return llm_evaluation.weighted_score

    def _static_score(self, report: Optional[StaticAnalysisReport]) -> Optional[float]:
        """Return the static quality score when available."""
        if report is None:
            return None
        return report.overall_quality_score

    def _combined_score(
        self,
        llm_score: Optional[float],
        static_score: Optional[float],
    ) -> float:
        """Return the weighted combined score with graceful degradation."""
        if llm_score is None and static_score is None:
            return 0.0
        if static_score is None:
            return float(llm_score or 0.0)
        if llm_score is None:
            return static_score
        return (llm_score * self.llm_weight) + (static_score * self.static_weight)

    def _breakdown(
        self,
        llm_score: Optional[float],
        static_score: Optional[float],
    ) -> Dict[str, float]:
        """Return component scores and effective weights."""
        if static_score is None:
            return {
                BREAKDOWN_KEY_LLM: float(llm_score or 0.0),
                BREAKDOWN_KEY_LLM_WEIGHT: 1.0,
                BREAKDOWN_KEY_STATIC_WEIGHT: 0.0,
            }
        if llm_score is None:
            return {
                BREAKDOWN_KEY_STATIC: static_score,
                BREAKDOWN_KEY_LLM_WEIGHT: 0.0,
                BREAKDOWN_KEY_STATIC_WEIGHT: 1.0,
            }
        return {
            BREAKDOWN_KEY_LLM: llm_score,
            BREAKDOWN_KEY_STATIC: static_score,
            BREAKDOWN_KEY_LLM_WEIGHT: self.llm_weight,
            BREAKDOWN_KEY_STATIC_WEIGHT: self.static_weight,
        }

    def _agent_name(
        self,
        agent_result: AgentResult,
        llm_evaluation: Optional[EvaluationResult],
    ) -> str:
        """Infer the producing agent name."""
        if llm_evaluation is not None:
            return llm_evaluation.agent_name
        if agent_result.next_events:
            return agent_result.next_events[0].source_agent
        return DEFAULT_AGENT_NAME

    def _event_id(
        self,
        agent_result: AgentResult,
        llm_evaluation: Optional[EvaluationResult],
    ) -> str:
        """Infer the scored event identifier."""
        if llm_evaluation is not None:
            return llm_evaluation.event_id
        if agent_result.next_events:
            next_event = agent_result.next_events[0]
            return next_event.correlation_id or next_event.event_id
        return DEFAULT_EVENT_ID


__all__ = ["CombinedScore", "QualityScorer"]
