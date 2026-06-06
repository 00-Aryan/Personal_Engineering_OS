"""Tests for ProjectOS quality gate enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.evaluation.base_evaluator import EvaluationResult
from core.evaluation.quality_gate import (
    DEFAULT_POLICIES,
    GATE_LOG_NAME,
    GateDecision,
    QualityGate,
)
from core.evaluation.quality_scorer import CombinedScore
from core.evaluation.regression_detector import RegressionReport
from core.evaluation.static_analyzer import (
    ComplexityMetrics,
    SecurityMetrics,
    StaticAnalysisReport,
    StyleMetrics,
)
from core.events import AgentResult


AGENT_NAME = "code_writing"
UNKNOWN_AGENT = "unknown_agent"
EVENT_ID = "event-123"
FILE_NAME = "sample.py"
MODEL_VERSION = "model-v1"
EVALUATOR_NAME = "llm_judge"
REASONING = "reasoning"
RAW_SAMPLE = "raw"


def test_pass_decision_on_high_score(tmp_path: Path) -> None:
    """Verify high combined scores pass the gate."""
    gate = _gate(tmp_path, score=0.9)

    result = gate.evaluate(_agent_result(), AGENT_NAME, _evaluation(0.9), tmp_path / FILE_NAME, MODEL_VERSION)

    assert result.decision is GateDecision.PASS
    assert result.blocking_reasons == []


def test_block_decision_on_low_score(tmp_path: Path) -> None:
    """Verify low combined scores block the gate."""
    gate = _gate(tmp_path, score=0.2)

    result = gate.evaluate(_agent_result(), AGENT_NAME, _evaluation(0.2), tmp_path / FILE_NAME, MODEL_VERSION)

    assert result.decision is GateDecision.BLOCK
    assert result.blocking_reasons


def test_block_on_security_high_severity(tmp_path: Path) -> None:
    """Verify high severity static security issues block."""
    static_report = _static_report(tmp_path / FILE_NAME, 0.9, high_security=1)
    gate = _gate(tmp_path, score=0.9, static_report=static_report)

    result = gate.evaluate(_agent_result(), AGENT_NAME, _evaluation(0.9), tmp_path / FILE_NAME, MODEL_VERSION)

    assert result.decision is GateDecision.BLOCK
    assert "high severity security issues" in result.blocking_reasons[0]


def test_escalate_on_regression_detected(tmp_path: Path) -> None:
    """Verify regression reports escalate when policy requires it."""
    gate = _gate(tmp_path, score=0.9, regression_detected=True)

    result = gate.evaluate(_agent_result(), AGENT_NAME, _evaluation(0.9), tmp_path / FILE_NAME, MODEL_VERSION)

    assert result.decision is GateDecision.ESCALATE
    assert "regression detected" in result.blocking_reasons[0]


def test_override_changes_decision_to_bypass(tmp_path: Path) -> None:
    """Verify override appends a BYPASS decision."""
    gate = _gate(tmp_path, score=0.2)
    gate.evaluate(_agent_result(), AGENT_NAME, _evaluation(0.2), tmp_path / FILE_NAME, MODEL_VERSION)

    result = gate.override(EVENT_ID, "manual review passed")

    assert result.decision is GateDecision.BYPASS
    assert result.human_override is True
    assert result.override_reason == "manual review passed"


def test_override_requires_nonempty_reason(tmp_path: Path) -> None:
    """Verify override rejects an empty reason."""
    gate = _gate(tmp_path, score=0.2)

    with pytest.raises(ValueError):
        gate.override(EVENT_ID, " ")


def test_gate_result_logged_to_jsonl(tmp_path: Path) -> None:
    """Verify gate evaluations are appended to gate_decisions.jsonl."""
    gate = _gate(tmp_path, score=0.9)

    gate.evaluate(_agent_result(), AGENT_NAME, _evaluation(0.9), tmp_path / FILE_NAME, MODEL_VERSION)

    log_path = tmp_path / GATE_LOG_NAME
    assert log_path.exists()
    assert EVENT_ID in log_path.read_text(encoding="utf-8")


def test_block_rate_computed_correctly(tmp_path: Path) -> None:
    """Verify block rate counts BLOCK and ESCALATE decisions."""
    gate = _gate(tmp_path, score=0.9)
    gate.evaluate(_agent_result("pass-1"), AGENT_NAME, _evaluation(0.9, "pass-1"), tmp_path / FILE_NAME, MODEL_VERSION)
    gate.quality_scorer.score_value = 0.1
    gate.evaluate(_agent_result("block-1"), AGENT_NAME, _evaluation(0.1, "block-1"), tmp_path / FILE_NAME, MODEL_VERSION)

    assert gate.get_block_rate(AGENT_NAME) == pytest.approx(0.5)


def test_default_policy_used_for_unknown_agent(tmp_path: Path) -> None:
    """Verify unknown agents use the default gate policy."""
    gate = _gate(tmp_path, score=0.4)

    result = gate.evaluate(_agent_result(), UNKNOWN_AGENT)

    assert result.gate_policy == "default"
    assert result.decision is GateDecision.PASS


def test_pass_without_llm_eval_if_not_required(tmp_path: Path) -> None:
    """Verify policies without required LLM evaluation can pass without it."""
    gate = _gate(tmp_path, score=0.6)

    result = gate.evaluate(_agent_result(), UNKNOWN_AGENT)

    assert result.decision is GateDecision.PASS
    assert "llm evaluation required" not in result.warnings


class FakeQualityScorer:
    """QualityScorer test double returning controlled combined scores."""

    def __init__(self, score: float, static_report: StaticAnalysisReport) -> None:
        """Initialize score and static analyzer fake."""
        self.score_value = score
        self.static_analyzer = FakeStaticAnalyzer(static_report)

    def score(
        self,
        agent_result: AgentResult,
        llm_evaluation: EvaluationResult | None,
        file_path: Path | None,
    ) -> CombinedScore:
        """Return a controlled combined score."""
        event_id = EVENT_ID
        if llm_evaluation is not None:
            event_id = llm_evaluation.event_id
        return CombinedScore(
            agent_name=AGENT_NAME,
            event_id=event_id,
            file_path=str(file_path) if file_path is not None else None,
            llm_score=self.score_value if llm_evaluation is not None else None,
            static_score=None,
            combined_score=self.score_value,
            passed=self.score_value >= 0.65,
            breakdown={},
            timestamp=datetime.now(timezone.utc),
        )


class FakeStaticAnalyzer:
    """Static analyzer fake returning one report."""

    def __init__(self, report: StaticAnalysisReport) -> None:
        """Initialize fake report."""
        self.report = report

    def analyze(self, file_path: Path) -> StaticAnalysisReport:
        """Return the configured report."""
        return self.report


@dataclass
class FakeRegressionDetector:
    """Regression detector fake."""

    regression_detected: bool = False

    def check_regression(
        self,
        agent_name: str,
        current_evaluation: EvaluationResult,
        model_version: str,
    ) -> RegressionReport:
        """Return a controlled regression report."""
        return RegressionReport(
            agent_name=agent_name,
            current_score=current_evaluation.weighted_score,
            baseline_score=1.0,
            delta=current_evaluation.weighted_score - 1.0,
            delta_pct=-20.0,
            regression_detected=self.regression_detected,
            model_version=model_version,
            sample_size=5,
            recommendation="Review model/prompt changes.",
            timestamp=datetime.now(timezone.utc),
        )


def _gate(
    tmp_path: Path,
    score: float,
    static_report: StaticAnalysisReport | None = None,
    regression_detected: bool = False,
) -> QualityGate:
    """Return a quality gate with fake dependencies."""
    report = static_report or _static_report(tmp_path / FILE_NAME, score)
    return QualityGate(
        DEFAULT_POLICIES,
        FakeQualityScorer(score, report),
        FakeRegressionDetector(regression_detected),
        tmp_path / GATE_LOG_NAME,
    )


def _agent_result(event_id: str = EVENT_ID) -> AgentResult:
    """Return a sample agent result."""
    return AgentResult(
        success=True,
        output={"file_path": FILE_NAME},
        metadata={"model_version": MODEL_VERSION, "event_id": event_id},
    )


def _evaluation(score: float, event_id: str = EVENT_ID) -> EvaluationResult:
    """Return an evaluation result with a chosen score."""
    return EvaluationResult(
        evaluator_name=EVALUATOR_NAME,
        agent_name=AGENT_NAME,
        event_id=event_id,
        timestamp=datetime.now(timezone.utc),
        criteria_scores={"quality": score},
        weighted_score=score,
        passed=score >= 0.7,
        reasoning=REASONING,
        raw_output_sample=RAW_SAMPLE,
        evaluation_duration_ms=1,
        evaluator_model=MODEL_VERSION,
        metadata={},
    )


def _static_report(
    file_path: Path,
    score: float,
    high_security: int = 0,
) -> StaticAnalysisReport:
    """Return a static analysis report."""
    return StaticAnalysisReport(
        file_path=str(file_path),
        timestamp=datetime.now(timezone.utc),
        complexity=ComplexityMetrics(str(file_path), 1.0, 1.0, 90.0, 5, 0.0, 1, 0),
        security=SecurityMetrics(str(file_path), high_security, 0, 0, [], True),
        style=StyleMetrics(str(file_path), 0, [], True),
        overall_quality_score=score,
        passed_quality_gate=score >= 0.6,
    )
