"""Unit tests for TelegramNotifier."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.notifications.telegram_notifier import (
    TelegramNotifier,
    DisabledNotifier,
    _escape_md,
    REDACTED_BOT_TOKEN,
)

def _join_notifier_threads() -> None:
    """Join all active TelegramNotifier threads to ensure async requests complete."""
    threads = [t for t in threading.enumerate() if t.name == "TelegramNotifierThread"]
    for t in threads:
        t.join(timeout=1.0)


@pytest.fixture
def mock_post() -> Generator[MagicMock, None, None]:
    """Fixture to mock requests.post."""
    with patch("requests.post") as mock:
        yield mock


def test_send_fires_in_background_thread(mock_post: MagicMock) -> None:
    """Verify send fires requests in a background thread and does not block."""
    notifier = TelegramNotifier("fake_token", "fake_chat_id")

    # Set up mock_post to block/sleep slightly
    block_event = threading.Event()

    def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
        block_event.wait()
        return MagicMock()

    mock_post.side_effect = side_effect

    start_time = time.perf_counter()
    notifier.send("Hello world")
    duration = time.perf_counter() - start_time

    # Must return control quickly (non-blocking)
    assert duration < 0.05

    # Release background thread
    block_event.set()

    # Join active non-main threads to ensure completion before asserting
    _join_notifier_threads()

    assert mock_post.called


def test_send_never_raises_on_http_error(mock_post: MagicMock, tmp_path: Path) -> None:
    """Verify HTTP exceptions in requests.post are handled silently without raising."""
    # Write to a temporary decisions.log path
    notifier = TelegramNotifier("fake_token", "fake_chat_id", project_root=tmp_path)

    # Set requests.post to raise an HTTPError
    mock_post.side_effect = requests.exceptions.HTTPError("Bad Request")

    # Call send. It should not raise an exception
    notifier.send("Hello")

    # Join background threads
    _join_notifier_threads()

    # Check that error was logged
    log_path = tmp_path / "decisions.log"
    assert log_path.exists()
    log_content = log_path.read_text(encoding="utf-8")
    assert "[telegram_notifier] Error sending message:" in log_content
    assert "Bad Request" in log_content


def test_send_escapes_plain_text_for_markdown_v2(mock_post: MagicMock) -> None:
    """Verify plain send input is escaped before Telegram receives it."""
    notifier = TelegramNotifier("fake_token", "fake_chat_id")

    notifier.send("ProjectOS Telegram test — if you see this, it works!")

    _join_notifier_threads()

    assert mock_post.called
    payload = mock_post.call_args[1]["json"]
    assert payload["text"] == "ProjectOS Telegram test — if you see this, it works\\!"


def test_http_error_log_redacts_telegram_bot_token(mock_post: MagicMock, tmp_path: Path) -> None:
    """Verify Telegram bot tokens are not written to decisions.log on HTTP errors."""
    token = "123456:secret-token"
    notifier = TelegramNotifier(token, "fake_chat_id", project_root=tmp_path)
    response = requests.Response()
    response.status_code = 400
    response.url = f"https://api.telegram.org/bot{token}/sendMessage"
    error = requests.exceptions.HTTPError(
        f"400 Client Error: Bad Request for url: {response.url}",
        response=response,
    )
    mock_post.return_value = response
    response.raise_for_status = MagicMock(side_effect=error)  # type: ignore[method-assign]

    notifier.send("Hello")

    _join_notifier_threads()

    log_content = (tmp_path / "decisions.log").read_text(encoding="utf-8")
    assert token not in log_content
    assert REDACTED_BOT_TOKEN in log_content
    assert "Bad Request" in log_content


def test_disabled_notifier_is_noop(mock_post: MagicMock) -> None:
    """Verify DisabledNotifier methods return immediately without network requests."""
    notifier = DisabledNotifier()

    notifier.send("Hello")
    notifier.send_phase_complete("Proj", 1, "Setup", 1, 1, "Next", "id")
    notifier.send_escalation("Title", "Reason", "event_id", "Details")
    notifier.send_morning_brief([], 0, 0)
    notifier.send_evening_digest(0, [], [], [])
    notifier.send_alert("info", "msg", "comp")
    notifier.send_project_started("Proj", [], "id")

    assert not mock_post.called


def test_from_env_returns_disabled_when_no_token() -> None:
    """Verify from_env returns a DisabledNotifier if env keys are missing."""
    with patch.dict(os.environ, {}, clear=True):
        notifier = TelegramNotifier.from_env()
        assert isinstance(notifier, DisabledNotifier)


def test_phase_complete_message_format(mock_post: MagicMock) -> None:
    """Verify send_phase_complete constructs the message with correct formatting."""
    notifier = TelegramNotifier("fake_token", "fake_chat_id")
    notifier.send_phase_complete(
        project_name="Test-Project",
        phase_number=2,
        phase_name="Core",
        files_changed=5,
        tests_passing=20,
        next_phase_summary="Build.Database",
        approval_id="phase-2-id"
    )

    _join_notifier_threads()

    assert mock_post.called
    kwargs = mock_post.call_args[1]
    payload = kwargs["json"]
    text = payload["text"]

    # Verify MarkdownV2 styling elements
    assert "✅ *Phase 2 Complete — Test\\-Project*" in text
    assert "📁 Files changed: 5" in text
    assert "🧪 Tests passing: 20" in text
    assert "*Next: Build\\.Database*" in text
    assert "`/approve phase-2-id`" in text


def test_escalation_message_format(mock_post: MagicMock) -> None:
    """Verify send_escalation formats message details correctly."""
    notifier = TelegramNotifier("fake_token", "fake_chat_id")
    notifier.send_escalation(
        title="Breaking Change!",
        reason="Removed API method.",
        event_id="evt-123",
        details="Deprecated in v1.0."
    )

    _join_notifier_threads()

    assert mock_post.called
    payload = mock_post.call_args[1]["json"]
    text = payload["text"]

    assert "⚠️ *Decision Required*" in text
    assert "*Breaking Change\\!*" in text
    assert "Removed API method\\." in text
    assert "Deprecated in v1\\.0\\." in text
    assert "`/approve evt-123`" in text


def test_morning_brief_format(mock_post: MagicMock) -> None:
    """Verify send_morning_brief formats the status summary of projects correctly."""
    notifier = TelegramNotifier("fake_token", "fake_chat_id")
    notifier.send_morning_brief(
        project_summaries=[
            {
                "project_name": "Project-A",
                "task_count": 10,
                "file_count": 4,
                "phase_status": "Active.Development"
            }
        ],
        pending_approvals=3,
        blocked_tasks=1,
        token_alert="Warning: Token limit approaching!"
    )

    _join_notifier_threads()

    assert mock_post.called
    payload = mock_post.call_args[1]["json"]
    text = payload["text"]

    assert "🌅 *ProjectOS Morning Brief*" in text
    assert "Warning: Token limit approaching\\!" in text
    assert "📦 *Project\\-A*" in text
    assert "• Completed overnight: 10 tasks" in text
    assert "• Changed: 4 files" in text
    assert "• Status: Active\\.Development" in text
    assert "📋 Pending your approval: 3" in text
    assert "🔒 Blocked tasks: 1" in text
    assert "Use `/status` for full details\\." in text


def test_alert_message_uses_correct_emoji(mock_post: MagicMock) -> None:
    """Verify send_alert maps severities to correct emoji labels."""
    notifier = TelegramNotifier("fake_token", "fake_chat_id")

    # 1. Critical
    notifier.send_alert("CRITICAL", "Database offline!", "db_pool")
    # 2. Warning
    notifier.send_alert("warning", "Latency high.", "api")
    # 3. Info
    notifier.send_alert("Info", "Backup started.", "cron")

    _join_notifier_threads()

    assert mock_post.call_count == 3

    # Check emoji maps
    critical_text = mock_post.call_args_list[0][1]["json"]["text"]
    assert "🔴 *CRITICAL Alert — db\\_pool*" in critical_text
    assert "Database offline\\!" in critical_text

    warning_text = mock_post.call_args_list[1][1]["json"]["text"]
    assert "🟡 *WARNING Alert — api*" in warning_text
    assert "Latency high\\." in warning_text

    info_text = mock_post.call_args_list[2][1]["json"]["text"]
    assert "🟢 *INFO Alert — cron*" in info_text
    assert "Backup started\\." in info_text
