"""LLM-as-judge evaluator implementation for ProjectOS."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Dict, List, Mapping

from core.evaluation.base_evaluator import (
    DEFAULT_PASSING_THRESHOLD,
    BaseEvaluator,
    EvaluationCriteria,
    EvaluationResult,
)
from core.events import AgentResult
from core.model_provider import ModelProvider


EVALUATOR_NAME = "llm_judge"
MODEL_MAX_TOKENS = 2048
CONTEXT_KEY_AGENT_NAME = "agent_name"
CONTEXT_KEY_EVENT_ID = "event_id"
UNKNOWN_VALUE = "unknown"
JSON_KEY_CRITERIA_SCORES = "criteria_scores"
JSON_KEY_REASONING = "reasoning"
JSON_KEY_OVERALL_ASSESSMENT = "overall_assessment"
METADATA_KEY_OVERALL_ASSESSMENT = "overall_assessment"
METADATA_KEY_JUDGE_RAW_OUTPUT = "judge_raw_output"
INVALID_JSON_REASON_TEMPLATE = "Judge returned invalid JSON: {raw_output}"
MODEL_ERROR_REASON_TEMPLATE = "Judge model call failed: {error}"
MODEL_NAME_UNKNOWN = "unknown"


class LLMJudge(BaseEvaluator):
    """
    Evaluates agent output quality using a separate LLM as judge.

    Design principles:
    - Judge model should be different from the judged agent's model
      (avoids self-serving bias). This is enforced by convention, not code.
      Example: CodeWritingAgent uses openrouter-free and the judge uses
      gemini-flash, configured through config/models.yaml.
    - Scoring is done per-criteria, not holistically
      (reduces anchoring bias)
    - Judge is given explicit rubrics, not open-ended instructions
      (reduces inconsistency)
    - Judge output is parsed as structured JSON
      (enables programmatic quality gates)
    """

    JUDGE_SYSTEM_PROMPT = """
You are an expert code and technical writing evaluator.
You evaluate AI agent outputs with precision and consistency.

Rules:
- Score each criterion independently on a 0.0 to 1.0 scale
- 1.0 = perfect, 0.0 = completely fails the criterion
- Provide specific reasoning for each score
- Do not consider factors outside the defined criteria
- Output ONLY valid JSON, no markdown, no preamble

Output format:
{
  "criteria_scores": {"criterion_name": score_float, ...},
  "reasoning": "specific explanation for each score",
  "overall_assessment": "one sentence summary"
}
""".strip()

    def __init__(
        self,
        judge_model_provider: ModelProvider,
        criteria: List[EvaluationCriteria],
        passing_threshold: float = DEFAULT_PASSING_THRESHOLD,
    ) -> None:
        """Initialize the judge provider, criteria, and pass threshold."""
        self.name = EVALUATOR_NAME
        self.judge_model_provider = judge_model_provider
        self.criteria = list(criteria)
        self.passing_threshold = passing_threshold

    def evaluate(
        self,
        agent_result: AgentResult,
        context: Dict[str, Any],
    ) -> EvaluationResult:
        """Evaluate agent output using the configured judge model."""
        started_at = perf_counter()
        prompt = self.format_evaluation_prompt(agent_result, context)
        try:
            raw_output = self.judge_model_provider.complete(
                prompt,
                self.JUDGE_SYSTEM_PROMPT,
                MODEL_MAX_TOKENS,
            )
        except Exception as error:
            return self._failed_result(
                agent_result,
                context,
                started_at,
                MODEL_ERROR_REASON_TEMPLATE.format(error=error),
                EMPTY_CRITERIA_SCORES,
                EMPTY_METADATA,
            )

        try:
            parsed_output = json.loads(raw_output)
        except json.JSONDecodeError:
            return self._failed_result(
                agent_result,
                context,
                started_at,
                INVALID_JSON_REASON_TEMPLATE.format(raw_output=raw_output),
                EMPTY_CRITERIA_SCORES,
                {METADATA_KEY_JUDGE_RAW_OUTPUT: raw_output},
            )

        criteria_scores = self._criteria_scores(parsed_output)
        reasoning = self._reasoning(parsed_output)
        weighted_score = self.compute_weighted_score(criteria_scores)
        return EvaluationResult(
            evaluator_name=self.name,
            agent_name=self.context_string(context, CONTEXT_KEY_AGENT_NAME),
            event_id=self.context_string(context, CONTEXT_KEY_EVENT_ID),
            timestamp=datetime.now(timezone.utc),
            criteria_scores=criteria_scores,
            weighted_score=weighted_score,
            passed=weighted_score >= self.passing_threshold,
            reasoning=reasoning,
            raw_output_sample=self.raw_output_sample(agent_result),
            evaluation_duration_ms=self._duration_ms(started_at),
            evaluator_model=self._evaluator_model(),
            metadata={
                METADATA_KEY_OVERALL_ASSESSMENT: self._overall_assessment(
                    parsed_output
                ),
                METADATA_KEY_JUDGE_RAW_OUTPUT: raw_output,
            },
        )

    def _criteria_scores(self, parsed_output: Any) -> Dict[str, float]:
        """Return parsed per-criterion scores from judge JSON."""
        if not isinstance(parsed_output, Mapping):
            return {}
        scores = parsed_output.get(JSON_KEY_CRITERIA_SCORES)
        if not isinstance(scores, Mapping):
            return {}
        return {
            str(criterion_name): self._bounded_score(score)
            for criterion_name, score in scores.items()
        }

    def _reasoning(self, parsed_output: Any) -> str:
        """Return judge reasoning text from parsed output."""
        if not isinstance(parsed_output, Mapping):
            return UNKNOWN_VALUE
        reasoning = parsed_output.get(JSON_KEY_REASONING)
        if isinstance(reasoning, str) and reasoning:
            return reasoning
        return UNKNOWN_VALUE

    def _overall_assessment(self, parsed_output: Any) -> str:
        """Return the judge's one-sentence overall assessment."""
        if not isinstance(parsed_output, Mapping):
            return UNKNOWN_VALUE
        assessment = parsed_output.get(JSON_KEY_OVERALL_ASSESSMENT)
        if isinstance(assessment, str) and assessment:
            return assessment
        return UNKNOWN_VALUE

    def _failed_result(
        self,
        agent_result: AgentResult,
        context: Dict[str, Any],
        started_at: float,
        reasoning: str,
        criteria_scores: Dict[str, float],
        metadata: Dict[str, Any],
    ) -> EvaluationResult:
        """Return a non-crashing failed evaluation result."""
        return EvaluationResult(
            evaluator_name=self.name,
            agent_name=self.context_string(context, CONTEXT_KEY_AGENT_NAME),
            event_id=self.context_string(context, CONTEXT_KEY_EVENT_ID),
            timestamp=datetime.now(timezone.utc),
            criteria_scores=criteria_scores,
            weighted_score=0.0,
            passed=False,
            reasoning=reasoning,
            raw_output_sample=self.raw_output_sample(agent_result),
            evaluation_duration_ms=self._duration_ms(started_at),
            evaluator_model=self._evaluator_model(),
            metadata=dict(metadata),
        )

    def _evaluator_model(self) -> str:
        """Return the configured judge model name without raising."""
        try:
            model_name = self.judge_model_provider.get_model_name()
        except Exception:
            return MODEL_NAME_UNKNOWN
        if isinstance(model_name, str) and model_name:
            return model_name
        return MODEL_NAME_UNKNOWN

    def _duration_ms(self, started_at: float) -> int:
        """Return elapsed milliseconds from a monotonic start time."""
        return int((perf_counter() - started_at) * 1000)


EMPTY_CRITERIA_SCORES: Dict[str, float] = {}
EMPTY_METADATA: Dict[str, Any] = {}


__all__ = ["LLMJudge"]
