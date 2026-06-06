"""Persistence for ProjectOS evaluation results."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from core.evaluation.base_evaluator import EvaluationResult


ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"
EVALUATIONS_JSONL_NAME = "evaluations.jsonl"
LOGGER_NAME = "projectos.evaluation_store"
MIN_AVERAGE_SCORE_RESULTS = 5

FIELD_EVALUATOR_NAME = "evaluator_name"
FIELD_AGENT_NAME = "agent_name"
FIELD_EVENT_ID = "event_id"
FIELD_TIMESTAMP = "timestamp"
FIELD_CRITERIA_SCORES = "criteria_scores"
FIELD_WEIGHTED_SCORE = "weighted_score"
FIELD_PASSED = "passed"
FIELD_REASONING = "reasoning"
FIELD_RAW_OUTPUT_SAMPLE = "raw_output_sample"
FIELD_EVALUATION_DURATION_MS = "evaluation_duration_ms"
FIELD_EVALUATOR_MODEL = "evaluator_model"
FIELD_METADATA = "metadata"


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


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file through atomic replacement."""
    existing_content = path.read_text(encoding=ENCODING) if path.exists() else EMPTY_TEXT
    _write_atomically(path, f"{existing_content}{content}")


class EvaluationStore:
    """Persists all evaluation results for regression detection in TASK_22."""

    def __init__(self, store_dir: Path) -> None:
        """Initialize the store directory and evaluations JSONL path."""
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.evaluations_path = self.store_dir / EVALUATIONS_JSONL_NAME
        self._logger = logging.getLogger(LOGGER_NAME)

    def save(self, result: EvaluationResult) -> None:
        """Append one evaluation result to evaluations.jsonl atomically."""
        _append_atomically(
            self.evaluations_path,
            f"{json.dumps(self._serialize(result), sort_keys=True)}{NEWLINE}",
        )

    def load_recent(
        self,
        agent_name: str,
        evaluator_name: str,
        limit: int = 50,
    ) -> List[EvaluationResult]:
        """Return recent evaluation results for an agent and evaluator."""
        if limit <= 0:
            return []
        matches = [
            result
            for result in self._records()
            if result.agent_name == agent_name
            and result.evaluator_name == evaluator_name
        ]
        return matches[-limit:]

    def load_for_event(self, event_id: str) -> List[EvaluationResult]:
        """Return all evaluation results for a specific event."""
        return [result for result in self._records() if result.event_id == event_id]

    def get_agent_average_score(
        self,
        agent_name: str,
        evaluator_name: str,
        window: int = 20,
    ) -> Optional[float]:
        """Return average weighted score over the latest evaluation window."""
        recent_results = self.load_recent(agent_name, evaluator_name, window)
        if len(recent_results) < MIN_AVERAGE_SCORE_RESULTS:
            return None
        total_score = sum(result.weighted_score for result in recent_results)
        return total_score / len(recent_results)

    def _records(self) -> List[EvaluationResult]:
        """Read valid evaluation JSONL records, skipping malformed lines."""
        if not self.evaluations_path.exists():
            return []
        results: List[EvaluationResult] = []
        for line in self.evaluations_path.read_text(encoding=ENCODING).splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                results.append(self._deserialize(record))
            except Exception as error:
                self._logger.warning("Skipped malformed evaluation line: %s", error)
        return results

    def _serialize(self, result: EvaluationResult) -> Dict[str, Any]:
        """Serialize one evaluation result to a JSON-safe mapping."""
        return {
            FIELD_EVALUATOR_NAME: result.evaluator_name,
            FIELD_AGENT_NAME: result.agent_name,
            FIELD_EVENT_ID: result.event_id,
            FIELD_TIMESTAMP: result.timestamp.isoformat(),
            FIELD_CRITERIA_SCORES: dict(result.criteria_scores),
            FIELD_WEIGHTED_SCORE: result.weighted_score,
            FIELD_PASSED: result.passed,
            FIELD_REASONING: result.reasoning,
            FIELD_RAW_OUTPUT_SAMPLE: result.raw_output_sample,
            FIELD_EVALUATION_DURATION_MS: result.evaluation_duration_ms,
            FIELD_EVALUATOR_MODEL: result.evaluator_model,
            FIELD_METADATA: result.metadata,
        }

    def _deserialize(self, record: Mapping[str, Any]) -> EvaluationResult:
        """Deserialize one JSON mapping into an EvaluationResult."""
        criteria_scores = record.get(FIELD_CRITERIA_SCORES)
        metadata = record.get(FIELD_METADATA)
        if not isinstance(criteria_scores, Mapping):
            criteria_scores = {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        return EvaluationResult(
            evaluator_name=str(record[FIELD_EVALUATOR_NAME]),
            agent_name=str(record[FIELD_AGENT_NAME]),
            event_id=str(record[FIELD_EVENT_ID]),
            timestamp=datetime.fromisoformat(str(record[FIELD_TIMESTAMP])),
            criteria_scores={
                str(key): float(value) for key, value in criteria_scores.items()
            },
            weighted_score=float(record[FIELD_WEIGHTED_SCORE]),
            passed=bool(record[FIELD_PASSED]),
            reasoning=str(record[FIELD_REASONING]),
            raw_output_sample=str(record[FIELD_RAW_OUTPUT_SAMPLE]),
            evaluation_duration_ms=int(record[FIELD_EVALUATION_DURATION_MS]),
            evaluator_model=str(record[FIELD_EVALUATOR_MODEL]),
            metadata=dict(metadata),
        )


__all__ = ["EvaluationStore"]
