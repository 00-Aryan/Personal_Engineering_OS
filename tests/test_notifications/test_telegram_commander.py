"""Unit tests for TelegramCommander and CommandRegistry."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Generator
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.notifications.telegram_commander import TelegramCommander
from core.notifications.command_registry import CommandRegistry
from core.notifications.telegram_notifier import TelegramNotifier, DisabledNotifier
from core.events import AgentEvent, EventType


@pytest.fixture
def mock_get() -> Generator[MagicMock, None, None]:
    """Fixture to mock requests.get."""
    with patch("requests.get") as mock:
        yield mock


def test_poll_ignores_messages_from_other_chats(mock_get: MagicMock) -> None:
    """Verify that commander ignores updates from non-configured chat IDs."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ok": True,
        "result": [
            {
                "update_id": 1001,
                "message": {
                    "chat": {"id": 99999},  # Wrong chat ID
                    "text": "/status",
                },
            }
        ],
    }

    status_handler = MagicMock()
    notifier = MagicMock(spec=TelegramNotifier)

    commander = TelegramCommander(
        bot_token="fake_token",
        chat_id="12345",
        command_handlers={"status": status_handler},
        notifier=notifier,
    )

    def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
        commander.stop()
        return mock_response
    mock_get.side_effect = side_effect

    commander._poll()

    assert not status_handler.called


def test_poll_calls_correct_handler_for_command(mock_get: MagicMock) -> None:
    """Verify that commander routes commands to the correct handlers."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ok": True,
        "result": [
            {
                "update_id": 1002,
                "message": {
                    "chat": {"id": 12345},  # Configured chat ID
                    "text": "/approve test-id-123",
                },
            }
        ],
    }

    approve_handler = MagicMock()
    notifier = MagicMock(spec=TelegramNotifier)

    commander = TelegramCommander(
        bot_token="fake_token",
        chat_id="12345",
        command_handlers={"approve": approve_handler},
        notifier=notifier,
    )

    def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
        commander.stop()
        return mock_response
    mock_get.side_effect = side_effect

    commander._poll()

    approve_handler.assert_called_once_with(["test-id-123"])


def test_approve_marks_escalation_approved(tmp_path: Path) -> None:
    """Verify handle_approve updates the status in escalation_queue.md and dispatches PERMISSION_GRANTED."""
    escalation_path = tmp_path / "escalation_queue.md"
    decisions_path = tmp_path / "decisions.log"

    # Write initial queue with a pending item
    escalation_path.write_text(
        "# Escalation Queue\n"
        "Format: | timestamp | event_id | reason | status |\n"
        "| 2026-06-11T03:00:00Z | test-id-123 | test reason | PENDING |\n",
        encoding="utf-8",
    )

    mock_clone = MagicMock()
    mock_clone._escalation_queue_path = escalation_path
    mock_clone._decisions_log_path = decisions_path
    mock_clone.project_root = tmp_path

    notifier = MagicMock(spec=TelegramNotifier)

    registry = CommandRegistry(
        clone_agent=mock_clone,
        phase_manager=None,
        notifier=notifier,
        state_dir=tmp_path,
    )

    registry.handle_approve(["test-id-123"])

    # Check that status was updated
    content = escalation_path.read_text(encoding="utf-8")
    assert "| test-id-123 | test reason | APPROVED |" in content

    # Check decision log
    decisions_content = decisions_path.read_text(encoding="utf-8")
    assert "Telegram approval: test-id-123" in decisions_content

    # Check notification sent
    notifier.send.assert_any_call("✅ Approved: test-id-123")

    # Check that PERMISSION_GRANTED event was handled by clone_agent
    assert mock_clone.handle.called
    called_event = mock_clone.handle.call_args[0][0]
    assert isinstance(called_event, AgentEvent)
    assert called_event.event_type == EventType.PERMISSION_GRANTED
    assert called_event.correlation_id == "test-id-123"


def test_reject_stores_reason(tmp_path: Path) -> None:
    """Verify handle_reject updates the status in escalation_queue.md and logs the rejection reason."""
    escalation_path = tmp_path / "escalation_queue.md"
    decisions_path = tmp_path / "decisions.log"

    escalation_path.write_text(
        "# Escalation Queue\n"
        "Format: | timestamp | event_id | reason | status |\n"
        "| 2026-06-11T03:00:00Z | test-id-123 | test reason | PENDING |\n",
        encoding="utf-8",
    )

    mock_clone = MagicMock()
    mock_clone._escalation_queue_path = escalation_path
    mock_clone._decisions_log_path = decisions_path
    mock_clone.project_root = tmp_path

    notifier = MagicMock(spec=TelegramNotifier)

    registry = CommandRegistry(
        clone_agent=mock_clone,
        phase_manager=None,
        notifier=notifier,
        state_dir=tmp_path,
    )

    registry.handle_reject(["test-id-123", "Too", "risky"])

    # Check status and reason column update
    content = escalation_path.read_text(encoding="utf-8")
    assert "| test-id-123 | test reason (Too risky) | REJECTED |" in content

    # Check decision log
    decisions_content = decisions_path.read_text(encoding="utf-8")
    assert "Telegram rejection: test-id-123 - Reason: Too risky" in decisions_content

    # Check notification sent
    notifier.send.assert_any_call("❌ Rejected: test-id-123\nReason: Too risky")


def test_pause_creates_flag_file(tmp_path: Path) -> None:
    """Verify handle_pause touches the paused flag file and logs the decision."""
    decisions_path = tmp_path / "decisions.log"

    mock_clone = MagicMock()
    mock_clone._decisions_log_path = decisions_path

    notifier = MagicMock(spec=TelegramNotifier)

    registry = CommandRegistry(
        clone_agent=mock_clone,
        phase_manager=None,
        notifier=notifier,
        state_dir=tmp_path,
    )

    registry.handle_pause([])

    paused_file = tmp_path / "paused"
    assert paused_file.exists()

    decisions_content = decisions_path.read_text(encoding="utf-8")
    assert "ProjectOS paused" in decisions_content
    notifier.send.assert_any_call("⏸ ProjectOS paused. All agent work suspended.")


def test_resume_removes_flag_file(tmp_path: Path) -> None:
    """Verify handle_resume deletes the paused flag file and logs the decision."""
    paused_file = tmp_path / "paused"
    paused_file.touch()

    decisions_path = tmp_path / "decisions.log"

    mock_clone = MagicMock()
    mock_clone._decisions_log_path = decisions_path

    notifier = MagicMock(spec=TelegramNotifier)

    registry = CommandRegistry(
        clone_agent=mock_clone,
        phase_manager=None,
        notifier=notifier,
        state_dir=tmp_path,
    )

    registry.handle_resume([])

    assert not paused_file.exists()

    decisions_content = decisions_path.read_text(encoding="utf-8")
    assert "ProjectOS resumed" in decisions_content
    notifier.send.assert_any_call("▶️ ProjectOS resumed.")


def test_unknown_command_sends_help(mock_get: MagicMock) -> None:
    """Verify that unknown commands trigger the help command handler."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "ok": True,
        "result": [
            {
                "update_id": 1003,
                "message": {
                    "chat": {"id": 12345},
                    "text": "/foobar",
                },
            }
        ],
    }

    help_handler = MagicMock()
    notifier = MagicMock(spec=TelegramNotifier)

    commander = TelegramCommander(
        bot_token="fake_token",
        chat_id="12345",
        command_handlers={
            "help": help_handler,
        },
        notifier=notifier,
    )

    def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
        commander.stop()
        return mock_response
    mock_get.side_effect = side_effect

    commander._poll()

    assert help_handler.called


def test_stop_exits_polling_loop_cleanly(mock_get: MagicMock) -> None:
    """Verify stop event flag shuts down commander polling loop."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True, "result": []}
    mock_get.return_value = mock_response

    notifier = MagicMock(spec=TelegramNotifier)

    commander = TelegramCommander(
        bot_token="fake_token",
        chat_id="12345",
        command_handlers={},
        notifier=notifier,
    )

    # Verify start spawns a running thread
    commander.start()
    assert commander._thread is not None
    assert commander._thread.is_alive()

    # Call stop
    commander.stop()
    # The loop should terminate cleanly and thread should join
    commander._thread.join(timeout=2.0)
    assert not commander._thread.is_alive()
