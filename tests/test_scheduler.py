"""Tests for project scheduler."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from core.project_scheduler import ProjectScheduler
from core.phase_manager import Phase, PhaseStatus


@pytest.fixture
def temp_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_get_next_returns_none_when_nothing_active(temp_dir: Path) -> None:
    phase_manager = MagicMock()
    notifier = MagicMock()
    scheduler = ProjectScheduler(phase_manager, notifier, temp_dir)
    assert scheduler.get_next_project() is None


def test_round_robin_rotation(temp_dir: Path) -> None:
    phase_manager = MagicMock()
    notifier = MagicMock()
    
    phase_a = Phase(
        phase_id="phase_1",
        project_name="A",
        phase_number=1,
        phase_name="P1",
        goal="",
        tasks=[],
        status=PhaseStatus.IN_PROGRESS,
        approval_id=None,
        created_at=None,
        started_at=None,
        completed_at=None,
        rejection_reason=None,
    )
    phase_b = Phase(
        phase_id="phase_1",
        project_name="B",
        phase_number=1,
        phase_name="P1",
        goal="",
        tasks=[],
        status=PhaseStatus.IN_PROGRESS,
        approval_id=None,
        created_at=None,
        started_at=None,
        completed_at=None,
        rejection_reason=None,
    )
    
    def load_state_mock(proj_name: str):
        if proj_name == "A":
            return [phase_a]
        if proj_name == "B":
            return [phase_b]
        return []

    phase_manager._load_state.side_effect = load_state_mock
    
    scheduler = ProjectScheduler(phase_manager, notifier, temp_dir)
    scheduler.register_project("A", temp_dir / "A")
    scheduler.register_project("B", temp_dir / "B")
    
    first = scheduler.get_next_project()
    assert first == "A"
    
    scheduler.record_work_done("A")
    
    second = scheduler.get_next_project()
    assert second == "B"
    
    scheduler.record_work_done("B")
    
    third = scheduler.get_next_project()
    assert third == "A"


def test_priority_affects_frequency(temp_dir: Path) -> None:
    phase_manager = MagicMock()
    notifier = MagicMock()
    
    phase_a = Phase(
        phase_id="phase_1",
        project_name="A",
        phase_number=1,
        phase_name="P1",
        goal="",
        tasks=[],
        status=PhaseStatus.IN_PROGRESS,
        approval_id=None,
        created_at=None,
        started_at=None,
        completed_at=None,
        rejection_reason=None,
    )
    phase_b = Phase(
        phase_id="phase_1",
        project_name="B",
        phase_number=1,
        phase_name="P1",
        goal="",
        tasks=[],
        status=PhaseStatus.IN_PROGRESS,
        approval_id=None,
        created_at=None,
        started_at=None,
        completed_at=None,
        rejection_reason=None,
    )
    
    phase_manager._load_state.side_effect = lambda name: [phase_a] if name == "A" else [phase_b]
    
    scheduler = ProjectScheduler(phase_manager, notifier, temp_dir)
    scheduler.register_project("A", temp_dir / "A", priority=2)
    scheduler.register_project("B", temp_dir / "B", priority=1)
    
    from datetime import datetime, timezone, timedelta
    
    assert scheduler.get_next_project() == "A"
    scheduler.record_work_done("A")
    
    assert scheduler.get_next_project() == "B"
    scheduler.record_work_done("B")
    
    now = datetime.now(timezone.utc)
    scheduler.projects["A"]["last_worked_at"] = (now - timedelta(seconds=2)).isoformat()
    scheduler.projects["B"]["last_worked_at"] = (now - timedelta(seconds=1)).isoformat()
    
    assert scheduler.get_next_project() == "A"


def test_blocked_project_skipped(temp_dir: Path) -> None:
    phase_manager = MagicMock()
    notifier = MagicMock()
    
    phase_a = Phase(
        phase_id="phase_1",
        project_name="A",
        phase_number=1,
        phase_name="P1",
        goal="",
        tasks=[],
        status=PhaseStatus.IN_PROGRESS,
        approval_id=None,
        created_at=None,
        started_at=None,
        completed_at=None,
        rejection_reason=None,
    )
    phase_b = Phase(
        phase_id="phase_1",
        project_name="B",
        phase_number=1,
        phase_name="P1",
        goal="",
        tasks=[],
        status=PhaseStatus.IN_PROGRESS,
        approval_id=None,
        created_at=None,
        started_at=None,
        completed_at=None,
        rejection_reason=None,
    )
    
    phase_manager._load_state.side_effect = lambda name: [phase_a] if name == "A" else [phase_b]
    
    scheduler = ProjectScheduler(phase_manager, notifier, temp_dir)
    
    root_a = temp_dir / "A"
    root_b = temp_dir / "B"
    root_a.mkdir()
    root_b.mkdir()
    
    scheduler.register_project("A", root_a)
    scheduler.register_project("B", root_b)
    
    blocked_file = root_a / "blocked_tasks.md"
    blocked_file.write_text(
        "# Blocked Tasks\n"
        "| task_id | blocked_by | correlation_id | reconnect_plan |\n"
        "|---|---|---|---|\n"
        "| PLAN-01 | dependency | 123 | none |\n",
        encoding="utf-8"
    )
    
    assert scheduler.get_next_project() == "B"
