"""Tests for the ProjectOS LLM-as-judge evaluator."""

from __future__ import annotations

import json
from typing import Any, Iterator

import pytest

from core.evaluation.base_evaluator import EvaluationCriteria, EvaluationResult
from core.evaluation.llm_judge import LLMJudge
from core.events import AgentResult
from core.model_provider import ModelProvider


AGENT_NAME = "code_review"
EVENT_ID = "event-123"
MODEL_NAME = "judge-test-model"
REASONING = "Specific reasoning for each score."
OVERALL = "The output is acceptable."
OUTPUT_KEY_VALUE = "value"
LONG_OUTPUT = "x" * 700


class MockModelProvider(ModelProvider):
    """Model provider test double returning configured completion text."""

    provider_key = "mock"

    def __init__(self, response: str) -> None:
        """Initialize the mock without reading model configuration files."""
        self.response = response
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        agent_name: str | None = None,
        token_budget: Any = None,
        *args,
        **kwargs,
    ) -> str:
        """Capture prompt inputs and return the configured response."""
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)
        return self.response

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield no streamed chunks for this test double."""
        return iter(())

    def get_model_name(self) -> str:
        """Return the configured test model name."""
        return MODEL_NAME


def test_evaluate_returns_evaluation_result() -> None:
    """Verify evaluate returns a populated EvaluationResult."""
    judge = LLMJudge(_provider(_valid_response()), _criteria())

    result = judge.evaluate(_agent_result(), _context())

    assert isinstance(result, EvaluationResult)
    assert result.evaluator_name == "llm_judge"
    assert result.agent_name == AGENT_NAME
    assert result.event_id == EVENT_ID


def test_weighted_score_computed_correctly() -> None:
    """Verify weighted score uses criterion weights."""
    judge = LLMJudge(_provider(_valid_response(first=0.8, second=0.4)), _criteria())

    result = judge.evaluate(_agent_result(), _context())

    assert result.weighted_score == pytest.approx(0.68)


def test_passed_true_when_above_threshold() -> None:
    """Verify passed is true when weighted score meets the threshold."""
    judge = LLMJudge(
        _provider(_valid_response(first=0.9, second=0.8)),
        _criteria(),
        passing_threshold=0.7,
    )

    result = judge.evaluate(_agent_result(), _context())

    assert result.passed is True


def test_passed_false_when_below_threshold() -> None:
    """Verify passed is false when weighted score misses the threshold."""
    judge = LLMJudge(
        _provider(_valid_response(first=0.2, second=0.3)),
        _criteria(),
        passing_threshold=0.7,
    )

    result = judge.evaluate(_agent_result(), _context())

    assert result.passed is False


def test_invalid_json_returns_failed_result_not_crash() -> None:
    """Verify invalid judge JSON returns a failed result instead of raising."""
    judge = LLMJudge(_provider("{not valid json"), _criteria())

    result = judge.evaluate(_agent_result(), _context())

    assert result.weighted_score == 0.0
    assert result.passed is False
    assert result.reasoning.startswith("Judge returned invalid JSON:")


def test_criteria_weights_must_sum_to_one() -> None:
    """Verify invalid criterion weights raise a ValueError."""
    judge = LLMJudge(
        _provider(_valid_response()),
        [
            EvaluationCriteria("first", "First criterion", 0.5, 0.7),
            EvaluationCriteria("second", "Second criterion", 0.4, 0.7),
        ],
    )

    with pytest.raises(ValueError):
        judge.evaluate(_agent_result(), _context())


def test_evaluation_duration_ms_populated() -> None:
    """Verify evaluation duration is populated as milliseconds."""
    judge = LLMJudge(_provider(_valid_response()), _criteria())

    result = judge.evaluate(_agent_result(), _context())

    assert isinstance(result.evaluation_duration_ms, int)
    assert result.evaluation_duration_ms >= 0


def test_raw_output_sample_truncated_to_500_chars() -> None:
    """Verify raw output sample is capped at 500 characters."""
    judge = LLMJudge(_provider(_valid_response()), _criteria())
    result = judge.evaluate(AgentResult(success=True, output=LONG_OUTPUT), _context())

    assert len(result.raw_output_sample) == 500


def _criteria() -> list[EvaluationCriteria]:
    """Return two weighted criteria for tests."""
    return [
        EvaluationCriteria("first", "First criterion", 0.7, 0.7),
        EvaluationCriteria("second", "Second criterion", 0.3, 0.7),
    ]


def _valid_response(first: float = 0.9, second: float = 0.8) -> str:
    """Return a valid judge JSON response."""
    return json.dumps(
        {
            "criteria_scores": {
                "first": first,
                "second": second,
            },
            "reasoning": REASONING,
            "overall_assessment": OVERALL,
        }
    )


def _provider(response: str) -> MockModelProvider:
    """Return a mock model provider."""
    return MockModelProvider(response)


def _agent_result() -> AgentResult:
    """Return a sample agent result."""
    return AgentResult(success=True, output={OUTPUT_KEY_VALUE: "ok"})


def _context() -> dict[str, str]:
    """Return a sample evaluation context."""
    return {"agent_name": AGENT_NAME, "event_id": EVENT_ID}
