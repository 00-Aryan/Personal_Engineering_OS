"""Tests for ProjectOS queue persistence."""

from __future__ import annotations

import json
from pathlib import Path

from core.events import AgentEvent, EventPriority, EventType
from core.persistence import PersistenceManager


SOURCE_AGENT = "persistence_test"
CORRELATION_ID = "corr-123"
OTHER_CORRELATION_ID = "corr-456"
TASK_ID = "TASK-1"
OTHER_TASK_ID = "TASK-2"
BLOCKER = "permission"
MALFORMED_LINE = "{not-json"
BLOCKED_QUEUE_FILE = "blocked_queue.json"
STATUS_FILE = "last_status.json"
ENCODING = "utf-8"


def test_save_and_load_blocked_task(tmp_path: Path) -> None:
    """Verify blocked events round-trip through persistence."""
    manager = PersistenceManager(tmp_path)
    event = _event(TASK_ID, correlation_id=CORRELATION_ID, blocked_by=BLOCKER)

    manager.save_blocked_task(event)

    loaded_events = manager.load_blocked_tasks()
    assert loaded_events == [event]


def test_clear_blocked_task_removes_only_matching(tmp_path: Path) -> None:
    """Verify blocked clearing preserves non-matching correlations."""
    manager = PersistenceManager(tmp_path)
    matching_event = _event(TASK_ID, correlation_id=CORRELATION_ID, blocked_by=BLOCKER)
    other_event = _event(
        OTHER_TASK_ID,
        correlation_id=OTHER_CORRELATION_ID,
        blocked_by=BLOCKER,
    )
    manager.save_blocked_task(matching_event)
    manager.save_blocked_task(other_event)

    manager.clear_blocked_task(CORRELATION_ID)

    assert manager.load_blocked_tasks() == [other_event]


def test_load_returns_empty_for_missing_file(tmp_path: Path) -> None:
    """Verify missing queue files load as empty lists."""
    manager = PersistenceManager(tmp_path)

    assert manager.load_blocked_tasks() == []
    assert manager.load_pending_events() == []


def test_malformed_line_skipped_not_crashed(tmp_path: Path) -> None:
    """Verify malformed queue lines are skipped without crashing."""
    manager = PersistenceManager(tmp_path)
    event = _event(TASK_ID, correlation_id=CORRELATION_ID)
    manager.save_blocked_task(event)
    blocked_path = tmp_path / BLOCKED_QUEUE_FILE
    blocked_path.write_text(
        f"{MALFORMED_LINE}\n{blocked_path.read_text(encoding=ENCODING)}",
        encoding=ENCODING,
    )

    assert manager.load_blocked_tasks() == [event]


def test_save_and_load_pending_event(tmp_path: Path) -> None:
    """Verify pending events round-trip through persistence."""
    manager = PersistenceManager(tmp_path)
    event = _event(TASK_ID, correlation_id=CORRELATION_ID)

    manager.save_pending_event(event)

    assert manager.load_pending_events() == [event]


def test_snapshot_status_writes_json(tmp_path: Path) -> None:
    """Verify status snapshots include counts and agent statuses."""
    manager = PersistenceManager(tmp_path)
    manager.save_pending_event(_event(TASK_ID, correlation_id=CORRELATION_ID))
    manager.save_blocked_task(
        _event(OTHER_TASK_ID, correlation_id=OTHER_CORRELATION_ID, blocked_by=BLOCKER)
    )

    manager.snapshot_status({"clone": "gemini-flash"})

    status = json.loads((tmp_path / STATUS_FILE).read_text(encoding=ENCODING))
    assert status["agent_statuses"] == {"clone": "gemini-flash"}
    assert status["pending_count"] == 1
    assert status["blocked_count"] == 1
    assert isinstance(status["timestamp"], str)


def test_restart_restores_blocked_tasks(tmp_path: Path) -> None:
    """Verify a new manager can load previously persisted blocked tasks."""
    original_manager = PersistenceManager(tmp_path)
    event = _event(TASK_ID, correlation_id=CORRELATION_ID, blocked_by=BLOCKER)
    original_manager.save_blocked_task(event)

    restarted_manager = PersistenceManager(tmp_path)

    assert restarted_manager.load_blocked_tasks() == [event]


def _event(
    task_id: str,
    correlation_id: str | None = None,
    blocked_by: str | None = None,
) -> AgentEvent:
    """Create a test event with stable fields."""
    return AgentEvent(
        event_type=EventType.CODE_CHANGED,
        source_agent=SOURCE_AGENT,
        payload={"task_id": task_id, "target_agent": "test_agent"},
        correlation_id=correlation_id,
        blocked_by=blocked_by,
        priority=EventPriority.HIGH,
    )
