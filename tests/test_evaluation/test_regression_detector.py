"""Tests for ProjectOS regression detection."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.evaluation.base_evaluator import EvaluationResult
from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.regression_detector import RegressionDetector


AGENT_NAME = "code_review"
MODEL_VERSION = "test-model-v1"
MODEL_VERSION_TWO = "test-model-v2"
EVALUATOR_NAME = "llm_judge"
EVENT_ID = "event"
REASONING = "reasoning"
RAW_SAMPLE = "raw"
BASELINE_KEY = f"{AGENT_NAME}:{MODEL_VERSION}"
BASELINES_FILE = "baselines.json"
RECOMMENDATION_BASELINE_ESTABLISHED = "Baseline established"
RECOMMENDATION_BUILDING_BASELINE = "Building baseline"


def test_first_evaluation_creates_baseline(tmp_path: Path) -> None:
    """Verify first evaluation creates a new baseline."""
    detector = _detector(tmp_path)

    report = detector.check_regression(
        AGENT_NAME,
        _evaluation(0.82),
        MODEL_VERSION,
    )

    assert report.regression_detected is False
    assert report.recommendation == RECOMMENDATION_BASELINE_ESTABLISHED
    assert BASELINE_KEY in detector.get_all_baselines()


def test_below_tolerance_triggers_regression(tmp_path: Path) -> None:
    """Verify a score below tolerance triggers regression."""
    detector = _seeded_detector(tmp_path, [0.85] * 10)

    report = detector.check_regression(
        AGENT_NAME,
        _evaluation(0.65),
        MODEL_VERSION,
    )

    assert report.regression_detected is True
    assert report.delta < 0
    assert "Quality dropped" in report.recommendation


def test_within_tolerance_no_regression(tmp_path: Path) -> None:
    """Verify scores within tolerance do not trigger regression."""
    detector = _seeded_detector(tmp_path, [0.80] * 10)

    report = detector.check_regression(
        AGENT_NAME,
        _evaluation(0.73),
        MODEL_VERSION,
    )

    assert report.regression_detected is False
    assert report.recommendation == "Within tolerance. No action needed."


def test_improvement_reported_correctly(tmp_path: Path) -> None:
    """Verify improvements receive the improvement recommendation."""
    detector = _seeded_detector(tmp_path, [0.70] * 10)

    report = detector.check_regression(
        AGENT_NAME,
        _evaluation(0.90),
        MODEL_VERSION,
    )

    assert report.regression_detected is False
    assert "Quality improved" in report.recommendation


def test_model_change_resets_baseline(tmp_path: Path) -> None:
    """Verify a new model version starts a separate baseline."""
    detector = _seeded_detector(tmp_path, [0.80] * 10)

    report = detector.check_regression(
        AGENT_NAME,
        _evaluation(0.60),
        MODEL_VERSION_TWO,
    )

    assert report.regression_detected is False
    assert report.recommendation == RECOMMENDATION_BASELINE_ESTABLISHED
    assert f"{AGENT_NAME}:{MODEL_VERSION_TWO}" in detector.get_all_baselines()


def test_insufficient_samples_builds_without_triggering(tmp_path: Path) -> None:
    """Verify small baselines build without triggering regression."""
    detector = _seeded_detector(tmp_path, [0.90, 0.90])

    report = detector.check_regression(
        AGENT_NAME,
        _evaluation(0.20),
        MODEL_VERSION,
    )

    assert report.regression_detected is False
    assert report.recommendation == RECOMMENDATION_BUILDING_BASELINE


def test_reset_baseline_removes_entry(tmp_path: Path) -> None:
    """Verify reset removes the selected baseline entry."""
    detector = _seeded_detector(tmp_path, [0.80] * 5)

    detector.reset_baseline(AGENT_NAME, MODEL_VERSION)

    assert BASELINE_KEY not in detector.get_all_baselines()


def test_rolling_window_drops_oldest(tmp_path: Path) -> None:
    """Verify baseline scores keep only the rolling window."""
    detector = _detector(tmp_path)
    scores = [index / 10 for index in range(1, 13)]
    for score in scores:
        detector.check_regression(AGENT_NAME, _evaluation(score), MODEL_VERSION)

    baselines = json.loads((tmp_path / BASELINES_FILE).read_text(encoding="utf-8"))
    stored_scores = baselines[BASELINE_KEY]["scores"]

    assert len(stored_scores) == 10
    assert stored_scores[0] == 0.3
    assert stored_scores[-1] == 1.2


def _seeded_detector(tmp_path: Path, scores: list[float]) -> RegressionDetector:
    """Return a detector after feeding seed scores."""
    detector = _detector(tmp_path)
    for score in scores:
        detector.check_regression(AGENT_NAME, _evaluation(score), MODEL_VERSION)
    return detector


def _detector(tmp_path: Path) -> RegressionDetector:
    """Return a regression detector with temporary state."""
    return RegressionDetector(EvaluationStore(tmp_path), tmp_path)


def _evaluation(score: float) -> EvaluationResult:
    """Return an EvaluationResult with a weighted score."""
    return EvaluationResult(
        evaluator_name=EVALUATOR_NAME,
        agent_name=AGENT_NAME,
        event_id=EVENT_ID,
        timestamp=datetime.now(timezone.utc),
        criteria_scores={"score": score},
        weighted_score=score,
        passed=score >= 0.7,
        reasoning=REASONING,
        raw_output_sample=RAW_SAMPLE,
        evaluation_duration_ms=1,
        evaluator_model=MODEL_VERSION,
        metadata={},
    )
