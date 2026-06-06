"""Regression detection for ProjectOS evaluation scores."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping

from core.evaluation.base_evaluator import EvaluationResult
from core.evaluation.evaluation_store import EvaluationStore


ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"
BASELINES_FILE_NAME = "baselines.json"
LOGGER_NAME = "projectos.regression_detector"

DEFAULT_REGRESSION_TOLERANCE = 0.10
DEFAULT_MIN_BASELINE_SAMPLES = 5
DEFAULT_BASELINE_WINDOW = 10
PERCENT_MULTIPLIER = 100.0
ZERO_SCORE = 0.0

KEY_AGENT_NAME = "agent_name"
KEY_MODEL_VERSION = "model_version"
KEY_SCORES = "scores"
KEY_BASELINE_SCORE = "baseline_score"
KEY_SAMPLE_SIZE = "sample_size"
KEY_UPDATED_AT = "updated_at"

RECOMMENDATION_BASELINE_ESTABLISHED = "Baseline established"
RECOMMENDATION_BUILDING_BASELINE = "Building baseline"
RECOMMENDATION_STABLE = "Within tolerance. No action needed."
RECOMMENDATION_REGRESSION_TEMPLATE = (
    "Quality dropped {delta_pct:.1f}%. Review model/prompt changes."
)
RECOMMENDATION_IMPROVEMENT_TEMPLATE = (
    "Quality improved {delta_pct:.1f}%. Consider updating baseline."
)
LOG_CORRUPT_BASELINE = "Corrupt baselines.json ignored: %s"


def _write_atomically(path: Path, content: str) -> None:
    """Write content to a path by replacing it with a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{TEMP_PREFIX}{path.name}.",
        suffix=TEMP_SUFFIX,
        dir=str(path.parent),
    )
    try:
        with os.fdopen(
            file_descriptor,
            FILE_WRITE_MODE,
            encoding=ENCODING,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


@dataclass
class RegressionReport:
    """Report describing a regression check result."""

    agent_name: str
    current_score: float
    baseline_score: float
    delta: float
    delta_pct: float
    regression_detected: bool
    model_version: str
    sample_size: int
    recommendation: str
    timestamp: datetime


class RegressionDetector:
    """
    Detects quality regression in agent outputs by comparing current
    performance against versioned rolling baselines.

    Baseline strategy:
    - Baseline is the rolling average of recent evaluation scores
    - Rolling window defaults to 10 scores
    - At least five samples are required before regression can trigger
    - Regression threshold is current < baseline * (1 - tolerance)

    Version tracking:
    - Baseline is versioned by model name from config
    - Changing models resets baseline automatically
    - Baseline file: .projectos_state/baselines.json
    """

    def __init__(
        self,
        evaluation_store: EvaluationStore,
        state_dir: Path,
        regression_tolerance: float = DEFAULT_REGRESSION_TOLERANCE,
        min_baseline_samples: int = DEFAULT_MIN_BASELINE_SAMPLES,
        baseline_window: int = DEFAULT_BASELINE_WINDOW,
    ) -> None:
        """Initialize regression detector state and thresholds."""
        self.evaluation_store = evaluation_store
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.regression_tolerance = regression_tolerance
        self.min_baseline_samples = min_baseline_samples
        self.baseline_window = baseline_window
        self.baselines_path = self.state_dir / BASELINES_FILE_NAME
        self._logger = logging.getLogger(LOGGER_NAME)

    def check_regression(
        self,
        agent_name: str,
        current_evaluation: EvaluationResult,
        model_version: str,
    ) -> RegressionReport:
        """Check current score against the agent/model rolling baseline."""
        baselines = self._load_baselines()
        baseline_key = self._baseline_key(agent_name, model_version)
        current_score = current_evaluation.weighted_score
        baseline = self._baseline_record(baselines.get(baseline_key))
        if baseline is None:
            baseline_score = current_score
            baselines[baseline_key] = self._new_record(
                agent_name,
                model_version,
                [current_score],
            )
            self._save_baselines(baselines)
            return self._report(
                agent_name,
                current_score,
                baseline_score,
                False,
                model_version,
                1,
                RECOMMENDATION_BASELINE_ESTABLISHED,
            )

        scores = self._scores(baseline)
        baseline_score = self._average(scores)
        if len(scores) < self.min_baseline_samples:
            updated_scores = self._updated_scores(scores, current_score)
            baselines[baseline_key] = self._new_record(
                agent_name,
                model_version,
                updated_scores,
            )
            self._save_baselines(baselines)
            return self._report(
                agent_name,
                current_score,
                baseline_score,
                False,
                model_version,
                len(updated_scores),
                RECOMMENDATION_BUILDING_BASELINE,
            )

        regression_detected = current_score < baseline_score * (
            1.0 - self.regression_tolerance
        )
        recommendation = self._recommendation(
            current_score,
            baseline_score,
            regression_detected,
        )
        updated_scores = self._updated_scores(scores, current_score)
        baselines[baseline_key] = self._new_record(
            agent_name,
            model_version,
            updated_scores,
        )
        self._save_baselines(baselines)
        return self._report(
            agent_name,
            current_score,
            baseline_score,
            regression_detected,
            model_version,
            len(updated_scores),
            recommendation,
        )

    def get_all_baselines(self) -> Dict[str, Dict[str, Any]]:
        """Return all stored baselines with sample sizes."""
        return {
            baseline_key: self._summary_record(record)
            for baseline_key, record in self._load_baselines().items()
            if isinstance(record, Mapping)
        }

    def reset_baseline(self, agent_name: str, model_version: str) -> None:
        """Remove one baseline entry so the next evaluation recreates it."""
        baselines = self._load_baselines()
        baselines.pop(self._baseline_key(agent_name, model_version), None)
        self._save_baselines(baselines)

    def _load_baselines(self) -> Dict[str, Any]:
        """Load baselines JSON, treating corrupt files as empty."""
        if not self.baselines_path.exists():
            return {}
        try:
            payload = json.loads(self.baselines_path.read_text(encoding=ENCODING))
        except json.JSONDecodeError as error:
            self._logger.warning(LOG_CORRUPT_BASELINE, error)
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_baselines(self, baselines: Mapping[str, Any]) -> None:
        """Write baselines JSON atomically."""
        rendered = json.dumps(baselines, sort_keys=True, indent=2)
        _write_atomically(self.baselines_path, f"{rendered}{NEWLINE}")

    def _baseline_record(self, value: Any) -> Mapping[str, Any] | None:
        """Return a baseline mapping or None."""
        if isinstance(value, Mapping):
            return value
        return None

    def _new_record(
        self,
        agent_name: str,
        model_version: str,
        scores: List[float],
    ) -> Dict[str, Any]:
        """Return a normalized baseline record."""
        return {
            KEY_AGENT_NAME: agent_name,
            KEY_MODEL_VERSION: model_version,
            KEY_SCORES: list(scores[-self.baseline_window :]),
            KEY_BASELINE_SCORE: self._average(scores[-self.baseline_window :]),
            KEY_SAMPLE_SIZE: len(scores[-self.baseline_window :]),
            KEY_UPDATED_AT: datetime.now(timezone.utc).isoformat(),
        }

    def _summary_record(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        """Return a public baseline summary mapping."""
        scores = self._scores(record)
        return {
            KEY_AGENT_NAME: str(record.get(KEY_AGENT_NAME, EMPTY_TEXT)),
            KEY_MODEL_VERSION: str(record.get(KEY_MODEL_VERSION, EMPTY_TEXT)),
            KEY_BASELINE_SCORE: self._average(scores),
            KEY_SAMPLE_SIZE: len(scores),
            KEY_UPDATED_AT: str(record.get(KEY_UPDATED_AT, EMPTY_TEXT)),
        }

    def _scores(self, record: Mapping[str, Any]) -> List[float]:
        """Return numeric baseline scores from a record."""
        scores = record.get(KEY_SCORES)
        if not isinstance(scores, list):
            return []
        normalized_scores: List[float] = []
        for score in scores:
            try:
                normalized_scores.append(float(score))
            except (TypeError, ValueError):
                continue
        return normalized_scores

    def _updated_scores(self, scores: List[float], current_score: float) -> List[float]:
        """Return scores after appending current score and trimming window."""
        return [*scores, current_score][-self.baseline_window :]

    def _average(self, scores: List[float]) -> float:
        """Return average score or zero when no scores exist."""
        if not scores:
            return ZERO_SCORE
        return sum(scores) / len(scores)

    def _recommendation(
        self,
        current_score: float,
        baseline_score: float,
        regression_detected: bool,
    ) -> str:
        """Return a human-readable regression recommendation."""
        delta_pct = self._delta_pct(current_score, baseline_score)
        if regression_detected:
            return RECOMMENDATION_REGRESSION_TEMPLATE.format(
                delta_pct=abs(delta_pct)
            )
        if current_score > baseline_score:
            return RECOMMENDATION_IMPROVEMENT_TEMPLATE.format(delta_pct=delta_pct)
        return RECOMMENDATION_STABLE

    def _report(
        self,
        agent_name: str,
        current_score: float,
        baseline_score: float,
        regression_detected: bool,
        model_version: str,
        sample_size: int,
        recommendation: str,
    ) -> RegressionReport:
        """Build a regression report with computed delta fields."""
        delta = current_score - baseline_score
        return RegressionReport(
            agent_name=agent_name,
            current_score=current_score,
            baseline_score=baseline_score,
            delta=delta,
            delta_pct=self._delta_pct(current_score, baseline_score),
            regression_detected=regression_detected,
            model_version=model_version,
            sample_size=sample_size,
            recommendation=recommendation,
            timestamp=datetime.now(timezone.utc),
        )

    def _delta_pct(self, current_score: float, baseline_score: float) -> float:
        """Return percentage delta relative to baseline."""
        if baseline_score == ZERO_SCORE:
            return ZERO_SCORE
        return ((current_score - baseline_score) / baseline_score) * PERCENT_MULTIPLIER

    def _baseline_key(self, agent_name: str, model_version: str) -> str:
        """Return a stable key for an agent/model baseline."""
        return f"{agent_name}:{model_version}"


__all__ = ["RegressionDetector", "RegressionReport"]
