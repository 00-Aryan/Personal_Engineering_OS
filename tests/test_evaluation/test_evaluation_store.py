"""Tests for ProjectOS EvaluationStore."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.evaluation.base_evaluator import EvaluationResult
from core.evaluation.evaluation_store import EvaluationStore


AGENT_NAME = "code_review"
OTHER_AGENT_NAME = "planning"
EVALUATOR_NAME = "llm_judge"
OTHER_EVALUATOR_NAME = "static"
EVENT_ID_ONE = "event-1"
EVENT_ID_TWO = "event-2"
MODEL_NAME = "judge-test-model"
REASONING = "Reasoning text"
RAW_SAMPLE = "raw output"
EVALUATIONS_JSONL_NAME = "evaluations.jsonl"
ENCODING = "utf-8"


def test_save_and_load_recent(tmp_path: Path) -> None:
    """Verify saved evaluations can be loaded by agent and evaluator."""
    store = EvaluationStore(tmp_path)
    store.save(_result(EVENT_ID_ONE, AGENT_NAME, EVALUATOR_NAME, 0.8))
    store.save(_result(EVENT_ID_TWO, OTHER_AGENT_NAME, EVALUATOR_NAME, 0.3))

    results = store.load_recent(AGENT_NAME, EVALUATOR_NAME)

    assert [result.event_id for result in results] == [EVENT_ID_ONE]


def test_load_for_event_returns_correct_results(tmp_path: Path) -> None:
    """Verify event lookup returns all evaluations for one event."""
    store = EvaluationStore(tmp_path)
    store.save(_result(EVENT_ID_ONE, AGENT_NAME, EVALUATOR_NAME, 0.8))
    store.save(_result(EVENT_ID_ONE, AGENT_NAME, OTHER_EVALUATOR_NAME, 0.7))
    store.save(_result(EVENT_ID_TWO, AGENT_NAME, EVALUATOR_NAME, 0.6))

    results = store.load_for_event(EVENT_ID_ONE)

    assert len(results) == 2
    assert {result.evaluator_name for result in results} == {
        EVALUATOR_NAME,
        OTHER_EVALUATOR_NAME,
    }


def test_get_agent_average_score_correct(tmp_path: Path) -> None:
    """Verify average score is computed over recent results."""
    store = EvaluationStore(tmp_path)
    for index, score in enumerate([0.6, 0.7, 0.8, 0.9, 1.0]):
        store.save(_result(f"event-{index}", AGENT_NAME, EVALUATOR_NAME, score))

    average = store.get_agent_average_score(AGENT_NAME, EVALUATOR_NAME)

    assert average == 0.8


def test_returns_none_when_insufficient_data(tmp_path: Path) -> None:
    """Verify fewer than five results is insufficient for an average."""
    store = EvaluationStore(tmp_path)
    for index in range(4):
        store.save(_result(f"event-{index}", AGENT_NAME, EVALUATOR_NAME, 0.8))

    average = store.get_agent_average_score(AGENT_NAME, EVALUATOR_NAME)

    assert average is None


def test_append_only_never_overwrites(tmp_path: Path) -> None:
    """Verify saving preserves existing JSONL records."""
    store = EvaluationStore(tmp_path)
    existing_record = {
        "evaluator_name": EVALUATOR_NAME,
        "agent_name": AGENT_NAME,
        "event_id": EVENT_ID_ONE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "criteria_scores": {"first": 0.8},
        "weighted_score": 0.8,
        "passed": True,
        "reasoning": REASONING,
        "raw_output_sample": RAW_SAMPLE,
        "evaluation_duration_ms": 1,
        "evaluator_model": MODEL_NAME,
        "metadata": {},
    }
    log_path = tmp_path / EVALUATIONS_JSONL_NAME
    log_path.write_text(f"{json.dumps(existing_record)}\n", encoding=ENCODING)

    store.save(_result(EVENT_ID_TWO, AGENT_NAME, EVALUATOR_NAME, 0.9))

    event_ids = [
        json.loads(line)["event_id"]
        for line in log_path.read_text(encoding=ENCODING).splitlines()
    ]
    assert event_ids == [EVENT_ID_ONE, EVENT_ID_TWO]


def _result(
    event_id: str,
    agent_name: str,
    evaluator_name: str,
    weighted_score: float,
) -> EvaluationResult:
    """Return a sample evaluation result."""
    return EvaluationResult(
        evaluator_name=evaluator_name,
        agent_name=agent_name,
        event_id=event_id,
        timestamp=datetime.now(timezone.utc),
        criteria_scores={"first": weighted_score},
        weighted_score=weighted_score,
        passed=weighted_score >= 0.7,
        reasoning=REASONING,
        raw_output_sample=RAW_SAMPLE,
        evaluation_duration_ms=1,
        evaluator_model=MODEL_NAME,
        metadata={},
    )
