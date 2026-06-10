"""Tests for BriefGenerator."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from datetime import datetime
import pytest
from core.notifications.brief_generator import BriefGenerator


@pytest.fixture
def temp_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_brief_handles_no_activity(temp_dir: Path) -> None:
    notifier = MagicMock()
    generator = BriefGenerator(notifier, temp_dir, [])
    
    brief = generator.generate_morning_brief()
    assert "No active projects registered" in brief
    
    notifier.send.assert_called_once()
    assert "No active projects registered" in notifier.send.call_args[0][0]


def test_morning_brief_sent_via_notifier(temp_dir: Path) -> None:
    notifier = MagicMock()
    project_root = temp_dir / "my_project"
    project_root.mkdir()
    
    (project_root / "decisions.log").touch()
    
    generator = BriefGenerator(notifier, temp_dir, [project_root])
    brief = generator.generate_morning_brief()
    
    notifier.send_morning_brief.assert_called_once()
    
    args, kwargs = notifier.send_morning_brief.call_args
    summaries = kwargs.get("project_summaries") or args[0]
    assert len(summaries) == 1
    assert summaries[0]["project_name"] == "my_project"
    assert summaries[0]["task_count"] == 0


def test_evening_digest_sent_via_notifier(temp_dir: Path) -> None:
    notifier = MagicMock()
    project_root = temp_dir / "my_project"
    project_root.mkdir()
    
    generator = BriefGenerator(notifier, temp_dir, [project_root])
    digest = generator.generate_evening_digest()
    
    notifier.send_evening_digest.assert_called_once()


def test_brief_written_to_file(temp_dir: Path) -> None:
    notifier = MagicMock()
    project_root = temp_dir / "my_project"
    project_root.mkdir()
    
    generator = BriefGenerator(notifier, temp_dir, [project_root])
    generator.generate_morning_brief()
    
    morning_brief_file = project_root / "morning_brief.md"
    assert morning_brief_file.exists()
    assert "Morning Brief" in morning_brief_file.read_text(encoding="utf-8")
    
    generator.generate_evening_digest()
    evening_digest_file = project_root / "evening_digest.md"
    assert evening_digest_file.exists()
    assert "Evening Digest" in evening_digest_file.read_text(encoding="utf-8")


def test_last_brief_timestamp_updated(temp_dir: Path) -> None:
    notifier = MagicMock()
    generator = BriefGenerator(notifier, temp_dir, [])
    
    assert not generator.last_brief_file.exists()
    
    generator.generate_morning_brief()
    
    assert generator.last_brief_file.exists()
    timestamp_str = generator.last_brief_file.read_text(encoding="utf-8").strip()
    dt = datetime.fromisoformat(timestamp_str)
    assert dt is not None
