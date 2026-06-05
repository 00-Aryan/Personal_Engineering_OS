"""Unit tests for JSONL decision logging."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.decision_log import DecisionLogger


EVENT_ID_ONE = "event-1"
EVENT_ID_TWO = "event-2"
EVENT_ID_THREE = "event-3"
CORRELATION_ID = "corr-1"
AGENT_CLONE = "clone"
AGENT_PLANNING = "planning"
CATEGORY_AUTONOMOUS = "AUTONOMOUS"
CATEGORY_ESCALATE = "ESCALATE"
CATEGORY_DEFER_PARALLEL = "DEFER_PARALLEL"
REASONING = "test reasoning"
OUTCOME = "test outcome"
DECISIONS_JSONL = "decisions.jsonl"
ENCODING = "utf-8"


def test_log_writes_valid_jsonl(tmp_path: Path) -> None:
    """Verify log writes one JSONL record with expected fields."""
    logger = DecisionLogger(tmp_path)

    logger.log(
        event_id=EVENT_ID_ONE,
        correlation_id=CORRELATION_ID,
        agent_name=AGENT_CLONE,
        decision_category=CATEGORY_AUTONOMOUS,
        reasoning=REASONING,
        outcome=OUTCOME,
        duration_ms=42,
    )

    records = _json_lines(tmp_path)
    assert len(records) == 1
    assert records[0]["event_id"] == EVENT_ID_ONE
    assert records[0]["correlation_id"] == CORRELATION_ID
    assert records[0]["agent_name"] == AGENT_CLONE
    assert records[0]["decision_category"] == CATEGORY_AUTONOMOUS
    assert records[0]["duration_ms"] == 42


def test_each_line_is_valid_json(tmp_path: Path) -> None:
    """Verify every emitted decision line is valid JSON."""
    logger = DecisionLogger(tmp_path)

    logger.log(EVENT_ID_ONE, None, AGENT_CLONE, CATEGORY_AUTONOMOUS, REASONING, OUTCOME)
    logger.log(EVENT_ID_TWO, None, AGENT_CLONE, CATEGORY_ESCALATE, REASONING, OUTCOME)

    for line in (tmp_path / DECISIONS_JSONL).read_text(encoding=ENCODING).splitlines():
        assert isinstance(json.loads(line), dict)


def test_append_only_never_overwrites(tmp_path: Path) -> None:
    """Verify new decisions preserve existing log lines."""
    logger = DecisionLogger(tmp_path)
    existing_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": EVENT_ID_ONE,
        "correlation_id": None,
        "agent_name": AGENT_CLONE,
        "decision_category": CATEGORY_AUTONOMOUS,
        "reasoning": REASONING,
        "outcome": OUTCOME,
        "escalated": False,
        "duration_ms": None,
    }
    (tmp_path / DECISIONS_JSONL).write_text(
        f"{json.dumps(existing_record)}\n",
        encoding=ENCODING,
    )

    logger.log(EVENT_ID_TWO, None, AGENT_CLONE, CATEGORY_ESCALATE, REASONING, OUTCOME)

    records = _json_lines(tmp_path)
    assert [record["event_id"] for record in records] == [EVENT_ID_ONE, EVENT_ID_TWO]


def test_query_filters_by_agent(tmp_path: Path) -> None:
    """Verify query filters decisions by agent name."""
    logger = DecisionLogger(tmp_path)
    logger.log(EVENT_ID_ONE, None, AGENT_CLONE, CATEGORY_AUTONOMOUS, REASONING, OUTCOME)
    logger.log(EVENT_ID_TWO, None, AGENT_PLANNING, CATEGORY_AUTONOMOUS, REASONING, OUTCOME)

    records = logger.query(agent_name=AGENT_PLANNING)

    assert [record["event_id"] for record in records] == [EVENT_ID_TWO]


def test_query_filters_by_category(tmp_path: Path) -> None:
    """Verify query filters decisions by decision category."""
    logger = DecisionLogger(tmp_path)
    logger.log(EVENT_ID_ONE, None, AGENT_CLONE, CATEGORY_AUTONOMOUS, REASONING, OUTCOME)
    logger.log(EVENT_ID_TWO, None, AGENT_CLONE, CATEGORY_ESCALATE, REASONING, OUTCOME)

    records = logger.query(decision_category=CATEGORY_ESCALATE)

    assert [record["event_id"] for record in records] == [EVENT_ID_TWO]


def test_query_respects_limit(tmp_path: Path) -> None:
    """Verify query returns only the last N matching decisions."""
    logger = DecisionLogger(tmp_path)
    logger.log(EVENT_ID_ONE, None, AGENT_CLONE, CATEGORY_AUTONOMOUS, REASONING, OUTCOME)
    logger.log(EVENT_ID_TWO, None, AGENT_CLONE, CATEGORY_AUTONOMOUS, REASONING, OUTCOME)
    logger.log(EVENT_ID_THREE, None, AGENT_CLONE, CATEGORY_AUTONOMOUS, REASONING, OUTCOME)

    records = logger.query(limit=2)

    assert [record["event_id"] for record in records] == [EVENT_ID_TWO, EVENT_ID_THREE]


def test_summary_counts_correctly(tmp_path: Path) -> None:
    """Verify summary aggregates by category, agent, and escalation rate."""
    logger = DecisionLogger(tmp_path)
    logger.log(EVENT_ID_ONE, None, AGENT_CLONE, CATEGORY_AUTONOMOUS, REASONING, OUTCOME)
    logger.log(
        EVENT_ID_TWO,
        None,
        AGENT_CLONE,
        CATEGORY_ESCALATE,
        REASONING,
        OUTCOME,
        escalated=True,
    )
    logger.log(
        EVENT_ID_THREE,
        None,
        AGENT_PLANNING,
        CATEGORY_DEFER_PARALLEL,
        REASONING,
        OUTCOME,
    )

    summary = logger.summary()

    assert summary["total_decisions"] == 3
    assert summary["by_category"]["AUTONOMOUS"] == 1
    assert summary["by_category"]["ESCALATE"] == 1
    assert summary["by_category"]["DEFER"] == 1
    assert summary["by_agent"] == {AGENT_CLONE: 2, AGENT_PLANNING: 1}
    assert summary["escalation_rate"] == 1 / 3


def test_malformed_line_skipped_in_query(tmp_path: Path) -> None:
    """Verify malformed JSONL lines do not break query."""
    logger = DecisionLogger(tmp_path)
    logger.log(EVENT_ID_ONE, None, AGENT_CLONE, CATEGORY_AUTONOMOUS, REASONING, OUTCOME)
    log_path = tmp_path / DECISIONS_JSONL
    log_path.write_text(
        f"{{not-json\n{log_path.read_text(encoding=ENCODING)}",
        encoding=ENCODING,
    )

    records = logger.query(since=datetime.now(timezone.utc) - timedelta(days=1))

    assert [record["event_id"] for record in records] == [EVENT_ID_ONE]


def _json_lines(tmp_path: Path) -> list[dict[str, object]]:
    """Return parsed decision log records."""
    return [
        json.loads(line)
        for line in (tmp_path / DECISIONS_JSONL).read_text(encoding=ENCODING).splitlines()
    ]
