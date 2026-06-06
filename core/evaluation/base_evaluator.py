"""Base evaluation abstractions for ProjectOS agent outputs."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping

from core.events import AgentResult


DEFAULT_PASSING_THRESHOLD = 0.7
MAX_RAW_OUTPUT_SAMPLE_CHARS = 500
WEIGHT_SUM_TARGET = 1.0
WEIGHT_SUM_TOLERANCE = 0.000001
MIN_SCORE = 0.0
MAX_SCORE = 1.0

PROMPT_OUTPUT_HEADING = "Output to evaluate"
PROMPT_CONTEXT_HEADING = "Evaluation context"
PROMPT_CRITERIA_HEADING = "Criteria definitions"
PROMPT_SCORING_HEADING = "Scoring instructions"
PROMPT_FORMAT_HEADING = "Output format specification"
PROMPT_SCORE_INSTRUCTION = (
    "Score each criterion independently from 0.0 to 1.0. "
    "Use only the listed criteria and return valid JSON only."
)
PROMPT_OUTPUT_FORMAT = (
    '{"criteria_scores":{"criterion_name":0.0},'
    '"reasoning":"specific explanation",'
    '"overall_assessment":"one sentence summary"}'
)
UNKNOWN_VALUE = "unknown"


@dataclass
class EvaluationCriteria:
    """One weighted quality criterion used by an evaluator."""

    name: str
    description: str
    weight: float
    passing_threshold: float


@dataclass
class EvaluationResult:
    """Structured result produced by an evaluator for one agent output."""

    evaluator_name: str
    agent_name: str
    event_id: str
    timestamp: datetime
    criteria_scores: Dict[str, float]
    weighted_score: float
    passed: bool
    reasoning: str
    raw_output_sample: str
    evaluation_duration_ms: int
    evaluator_model: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseEvaluator(ABC):
    """Abstract evaluator interface for ProjectOS quality checks."""

    name: str
    criteria: List[EvaluationCriteria]
    passing_threshold: float = DEFAULT_PASSING_THRESHOLD

    @abstractmethod
    def evaluate(
        self,
        agent_result: AgentResult,
        context: Dict[str, Any],
    ) -> EvaluationResult:
        """Evaluate an agent result and return a structured score."""

    def compute_weighted_score(self, criteria_scores: Dict[str, float]) -> float:
        """Return the weighted score after validating criterion weights."""
        self._validate_weight_sum()
        weighted_score = 0.0
        for criterion in self.criteria:
            score = self._bounded_score(criteria_scores.get(criterion.name, MIN_SCORE))
            weighted_score += score * criterion.weight
        return weighted_score

    def format_evaluation_prompt(
        self,
        agent_result: AgentResult,
        context: Dict[str, Any],
    ) -> str:
        """Build a structured prompt for a judge model."""
        prompt_sections = [
            self._prompt_section(
                PROMPT_OUTPUT_HEADING,
                self._json_text(agent_result.output),
            ),
            self._prompt_section(PROMPT_CONTEXT_HEADING, self._json_text(context)),
            self._prompt_section(
                PROMPT_CRITERIA_HEADING,
                self._json_text([self._criteria_payload(item) for item in self.criteria]),
            ),
            self._prompt_section(PROMPT_SCORING_HEADING, PROMPT_SCORE_INSTRUCTION),
            self._prompt_section(PROMPT_FORMAT_HEADING, PROMPT_OUTPUT_FORMAT),
        ]
        return "\n\n".join(prompt_sections)

    def raw_output_sample(self, agent_result: AgentResult) -> str:
        """Return the first 500 characters of serialized agent output."""
        return self._json_text(agent_result.output)[:MAX_RAW_OUTPUT_SAMPLE_CHARS]

    def context_string(
        self,
        context: Mapping[str, Any],
        key: str,
        default: str = UNKNOWN_VALUE,
    ) -> str:
        """Return one context value as a non-empty string."""
        value = context.get(key)
        if isinstance(value, str) and value:
            return value
        return default

    def _validate_weight_sum(self) -> None:
        """Raise ValueError when configured criterion weights do not sum to 1.0."""
        total_weight = sum(criterion.weight for criterion in self.criteria)
        if abs(total_weight - WEIGHT_SUM_TARGET) > WEIGHT_SUM_TOLERANCE:
            raise ValueError("Evaluation criteria weights must sum to 1.0.")

    def _bounded_score(self, value: Any) -> float:
        """Return a score clamped to the valid 0.0 to 1.0 range."""
        try:
            score = float(value)
        except (TypeError, ValueError):
            return MIN_SCORE
        return min(max(score, MIN_SCORE), MAX_SCORE)

    def _criteria_payload(self, criterion: EvaluationCriteria) -> Dict[str, Any]:
        """Return a JSON-safe criterion payload for judge prompts."""
        return {
            "name": criterion.name,
            "description": criterion.description,
            "weight": criterion.weight,
            "passing_threshold": criterion.passing_threshold,
        }

    def _json_text(self, value: Any) -> str:
        """Serialize a value to deterministic JSON text when possible."""
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except TypeError:
            return str(value)

    def _prompt_section(self, heading: str, body: str) -> str:
        """Format one structured prompt section."""
        return f"## {heading}\n{body}"
