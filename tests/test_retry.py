"""Unit tests for retry helper behavior."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from core.retry import with_retry


def test_succeeds_on_first_attempt() -> None:
    """Verify retry returns immediately when the callable succeeds."""
    calls = 0

    def fn() -> str:
        """Return a successful value."""
        nonlocal calls
        calls += 1
        return "ok"

    assert with_retry(fn) == "ok"
    assert calls == 1


def test_retries_on_failure_then_succeeds() -> None:
    """Verify retry retries transient failures before returning success."""
    calls = 0

    def fn() -> str:
        """Fail once, then succeed."""
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        return "ok"

    with patch("core.retry.time.sleep") as sleep_mock:
        assert with_retry(fn, max_attempts=3, backoff_seconds=1.0) == "ok"

    assert calls == 2
    sleep_mock.assert_called_once_with(1.0)


def test_raises_after_max_attempts() -> None:
    """Verify retry raises the final exception after all attempts fail."""

    def fn() -> Any:
        """Always fail."""
        raise RuntimeError("permanent")

    with patch("core.retry.time.sleep"), pytest.raises(RuntimeError, match="permanent"):
        with_retry(fn, max_attempts=3, backoff_seconds=1.0)


def test_exponential_backoff_timing() -> None:
    """Verify retry sleeps with increasing backoff between failures."""
    calls = 0

    def fn() -> str:
        """Fail twice, then succeed."""
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("temporary")
        return "ok"

    with patch("core.retry.time.sleep") as sleep_mock:
        assert with_retry(fn, max_attempts=3, backoff_seconds=2.0) == "ok"

    assert [call.args[0] for call in sleep_mock.call_args_list] == [2.0, 4.0]
