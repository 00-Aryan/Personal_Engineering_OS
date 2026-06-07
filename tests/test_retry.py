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


def test_no_retry_exceptions() -> None:
    """Verify that exceptions in no_retry_exceptions are raised immediately."""
    calls = 0

    def fn() -> Any:
        nonlocal calls
        calls += 1
        raise ValueError("no retry")

    with pytest.raises(ValueError, match="no retry"):
        with_retry(fn, max_attempts=3, no_retry_exceptions=(ValueError,))

    assert calls == 1


def test_auth_error_401_no_retry() -> None:
    """Verify that a 401 error is raised immediately without retry."""
    calls = 0

    class DummyHTTPError(Exception):
        status_code = 401

    def fn() -> Any:
        nonlocal calls
        calls += 1
        raise DummyHTTPError("unauthorized")

    with patch("core.retry.time.sleep") as sleep_mock, pytest.raises(DummyHTTPError, match="unauthorized"):
        with_retry(fn, max_attempts=3)

    assert calls == 1
    sleep_mock.assert_not_called()


def test_rate_limit_429_retry_with_retry_after() -> None:
    """Verify that a 429 error sleeps for Retry-After value and retries without counting as failure."""
    calls = 0

    class DummyRateLimitError(Exception):
        status_code = 429
        headers = {"Retry-After": "5.0"}

    def fn() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise DummyRateLimitError("rate limit")
        return "ok"

    with patch("core.retry.time.sleep") as sleep_mock:
        assert with_retry(fn, max_attempts=2, backoff_seconds=1.0) == "ok"

    assert calls == 2
    sleep_mock.assert_called_once_with(5.0)


def test_rate_limit_429_retry_default_wait() -> None:
    """Verify that a 429 error sleeps for default 60s if Retry-After is missing and retries without counting as failure."""
    calls = 0

    class DummyRateLimitError(Exception):
        status_code = 429

    def fn() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise DummyRateLimitError("rate limit")
        return "ok"

    with patch("core.retry.time.sleep") as sleep_mock:
        assert with_retry(fn, max_attempts=2, backoff_seconds=1.0) == "ok"

    assert calls == 2
    sleep_mock.assert_called_once_with(60.0)

