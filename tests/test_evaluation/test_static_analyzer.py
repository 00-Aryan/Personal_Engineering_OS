"""Tests for static analysis and unified quality scoring."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.evaluation.base_evaluator import EvaluationResult
from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.quality_scorer import QualityScorer
from core.evaluation.static_analyzer import (
    ComplexityMetrics,
    SecurityMetrics,
    StaticAnalysisReport,
    StaticAnalyzer,
    StyleMetrics,
)
from core.events import AgentResult


FILE_NAME = "sample.py"
AGENT_NAME = "code_writing"
EVENT_ID = "event-123"
EVALUATOR_NAME = "llm_judge"
MODEL_NAME = "judge-model"
REASONING = "Looks acceptable."
RAW_SAMPLE = "raw output"


def test_analyze_simple_function_passes(tmp_path: Path) -> None:
    """Verify a simple Python file receives a passing static report."""
    source_path = _write_source(
        tmp_path,
        "def greet(name: str) -> str:\n"
        "    \"\"\"Return a greeting.\"\"\"\n"
        "    return f\"hello {name}\"\n",
    )
    analyzer = StaticAnalyzer()

    report = analyzer.analyze(source_path)

    assert report.file_path == str(source_path)
    assert report.passed_quality_gate is True
    assert 0.0 <= report.overall_quality_score <= 1.0
    assert report.summary


def test_overall_score_computed_from_components() -> None:
    """Verify the composite score uses documented component weights."""
    analyzer = StaticAnalyzer(complexity_threshold=10.0)
    complexity = ComplexityMetrics(
        file_path=FILE_NAME,
        avg_cyclomatic_complexity=5.0,
        max_cyclomatic_complexity=5.0,
        maintainability_index=80.0,
        lines_of_code=5,
        comment_ratio=0.0,
        function_count=1,
        class_count=0,
    )
    security = SecurityMetrics(FILE_NAME, 0, 0, 0, [], True)
    style = StyleMetrics(FILE_NAME, 10, [], True)

    score = analyzer._overall_quality_score(complexity, security, style)

    assert score == pytest.approx(0.92)


def test_passed_quality_gate_threshold(tmp_path: Path) -> None:
    """Verify the report pass flag follows the 0.6 quality threshold."""
    analyzer = StaticAnalyzer()
    report = _report(tmp_path / FILE_NAME, 0.59)

    assert report.passed_quality_gate is False
    assert analyzer._complexity_score(10.0) == 1.0


def test_batch_analyze_continues_on_single_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify batch analysis skips one failed file and continues."""
    analyzer = StaticAnalyzer()
    good_path = tmp_path / "good.py"
    bad_path = tmp_path / "bad.py"

    def fake_analyze(file_path: Path) -> StaticAnalysisReport:
        """Return one report and raise for one file."""
        if file_path == bad_path:
            raise RuntimeError("boom")
        return _report(file_path, 0.9)

    monkeypatch.setattr(analyzer, "analyze", fake_analyze)

    reports = analyzer.batch_analyze([bad_path, good_path])

    assert [report.file_path for report in reports] == [str(good_path)]


def test_missing_tool_degrades_gracefully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify missing subprocess tools produce unavailable metrics."""
    source_path = _write_source(tmp_path, "x = 1\n")

    def missing_tool(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Simulate a missing executable."""
        raise FileNotFoundError("missing")

    monkeypatch.setattr(subprocess, "run", missing_tool)
    report = StaticAnalyzer().analyze(source_path)

    assert report.complexity.lines_of_code == 0
    assert report.security.bandit_available is False
    assert report.style.flake8_available is False
    assert report.passed_quality_gate is True


def test_security_score_zero_on_high_severity_issue() -> None:
    """Verify high severity security issues zero the security component."""
    analyzer = StaticAnalyzer()
    complexity = ComplexityMetrics(FILE_NAME, 1.0, 1.0, 100.0, 5, 0.0, 1, 0)
    security = SecurityMetrics(
        FILE_NAME,
        1,
        0,
        0,
        [{"issue_severity": "HIGH"}],
        True,
    )
    style = StyleMetrics(FILE_NAME, 0, [], True)

    score = analyzer._overall_quality_score(complexity, security, style)

    assert score == pytest.approx(0.70)


def test_quality_scorer_combines_llm_and_static(tmp_path: Path) -> None:
    """Verify LLM and static scores combine using configured weights."""
    scorer = QualityScorer(
        static_analyzer=FakeStaticAnalyzer(_report(tmp_path / FILE_NAME, 0.5)),
        evaluation_store=EvaluationStore(tmp_path),
    )

    combined = scorer.score(
        agent_result=AgentResult(success=True, output={"file_path": FILE_NAME}),
        llm_evaluation=_evaluation_result(0.8),
        file_path=tmp_path / FILE_NAME,
    )

    assert combined.agent_name == AGENT_NAME
    assert combined.event_id == EVENT_ID
    assert combined.static_score == 0.5
    assert combined.combined_score == pytest.approx(0.68)
    assert combined.passed is True


class FakeStaticAnalyzer:
    """Static analyzer test double returning a fixed report."""

    def __init__(self, report: StaticAnalysisReport) -> None:
        """Initialize the fake analyzer with a report."""
        self.report = report

    def analyze(self, file_path: Path) -> StaticAnalysisReport:
        """Return the fixed report."""
        return self.report


def _write_source(tmp_path: Path, source: str) -> Path:
    """Write a temporary source file."""
    source_path = tmp_path / FILE_NAME
    source_path.write_text(source, encoding="utf-8")
    return source_path


def _report(file_path: Path, score: float) -> StaticAnalysisReport:
    """Return a static analysis report with a chosen score."""
    return StaticAnalysisReport(
        file_path=str(file_path),
        timestamp=datetime.now(timezone.utc),
        complexity=ComplexityMetrics(
            file_path=str(file_path),
            avg_cyclomatic_complexity=1.0,
            max_cyclomatic_complexity=1.0,
            maintainability_index=90.0,
            lines_of_code=5,
            comment_ratio=0.0,
            function_count=1,
            class_count=0,
        ),
        security=SecurityMetrics(str(file_path), 0, 0, 0, [], True),
        style=StyleMetrics(str(file_path), 0, [], True),
        overall_quality_score=score,
        passed_quality_gate=score >= 0.6,
    )


def _evaluation_result(score: float) -> EvaluationResult:
    """Return an LLM evaluation result with a chosen weighted score."""
    return EvaluationResult(
        evaluator_name=EVALUATOR_NAME,
        agent_name=AGENT_NAME,
        event_id=EVENT_ID,
        timestamp=datetime.now(timezone.utc),
        criteria_scores={"quality": score},
        weighted_score=score,
        passed=score >= 0.7,
        reasoning=REASONING,
        raw_output_sample=RAW_SAMPLE,
        evaluation_duration_ms=1,
        evaluator_model=MODEL_NAME,
        metadata={},
    )
