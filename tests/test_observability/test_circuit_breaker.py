"""Unit tests for the CircuitBreaker observability component."""

from __future__ import annotations

import time
import tempfile
from pathlib import Path
import pytest

from core.observability.circuit_breaker import CircuitBreaker, CircuitState, CircuitOpenError


@pytest.fixture
def temp_state_dir():
    """Fixture that provides a temporary directory for circuit state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_closed_state_allows_requests(temp_state_dir):
    """Verify that closed circuit breaker forwards requests and tracks success."""
    cb = CircuitBreaker(
        provider_name="test-provider",
        failure_threshold=2,
        recovery_timeout=1.0,
        state_dir=temp_state_dir,
    )
    assert cb.state == CircuitState.CLOSED

    res = cb.call(lambda: "ok")
    assert res == "ok"
    assert cb.get_stats().success_count == 1
    assert cb.get_stats().failure_count == 0


def test_opens_after_threshold_failures(temp_state_dir):
    """Verify that the circuit opens after consecutive failure threshold is reached."""
    cb = CircuitBreaker(
        provider_name="test-provider",
        failure_threshold=2,
        recovery_timeout=1.0,
        state_dir=temp_state_dir,
    )

    # 1st failure
    with pytest.raises(ValueError):
        cb.call(lambda: exec("raise ValueError('fail')") or None)
    assert cb.state == CircuitState.CLOSED

    # 2nd failure => opens
    with pytest.raises(ValueError):
        cb.call(lambda: exec("raise ValueError('fail')") or None)
    assert cb.state == CircuitState.OPEN
    assert cb.get_stats().failure_count == 2


def test_open_state_raises_circuit_open_error(temp_state_dir):
    """Verify that an open circuit immediately raises CircuitOpenError without calling fn."""
    cb = CircuitBreaker(
        provider_name="test-provider",
        failure_threshold=2,
        recovery_timeout=1.0,
        state_dir=temp_state_dir,
    )

    # Force open
    for _ in range(2):
        try:
            cb.call(lambda: exec("raise ValueError()") or None)
        except ValueError:
            pass

    assert cb.state == CircuitState.OPEN

    # Call should raise CircuitOpenError immediately
    called = False
    def fn():
        nonlocal called
        called = True
        return "ok"

    with pytest.raises(CircuitOpenError) as excinfo:
        cb.call(fn)

    assert called is False
    assert excinfo.value.provider_name == "test-provider"
    assert excinfo.value.recovery_timeout == 1.0


def test_transitions_to_half_open_after_timeout(temp_state_dir):
    """Verify that open circuit transitions to half-open after recovery timeout."""
    cb = CircuitBreaker(
        provider_name="test-provider",
        failure_threshold=1,
        recovery_timeout=0.1,
        state_dir=temp_state_dir,
    )

    # Force open
    try:
        cb.call(lambda: exec("raise ValueError()") or None)
    except ValueError:
        pass
    assert cb.state == CircuitState.OPEN

    time.sleep(0.15)

    # Next call should transition to HALF_OPEN and close on success
    res = cb.call(lambda: "probe-ok")
    assert res == "probe-ok"
    assert cb.state == CircuitState.CLOSED


def test_half_open_closes_on_success(temp_state_dir):
    """Verify that probe success in half-open state closes the circuit."""
    cb = CircuitBreaker(
        provider_name="test-provider",
        failure_threshold=1,
        recovery_timeout=0.1,
        state_dir=temp_state_dir,
    )

    # Open it
    try:
        cb.call(lambda: exec("raise ValueError()") or None)
    except ValueError:
        pass

    time.sleep(0.15)
    cb.call(lambda: "probe-ok")
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


def test_half_open_reopens_on_failure(temp_state_dir):
    """Verify that probe failure in half-open state reopens the circuit."""
    cb = CircuitBreaker(
        provider_name="test-provider",
        failure_threshold=1,
        recovery_timeout=0.1,
        state_dir=temp_state_dir,
    )

    # Open it
    try:
        cb.call(lambda: exec("raise ValueError()") or None)
    except ValueError:
        pass

    time.sleep(0.15)
    with pytest.raises(ValueError):
        cb.call(lambda: exec("raise ValueError()") or None)
    assert cb.state == CircuitState.OPEN


def test_reset_returns_to_closed(temp_state_dir):
    """Verify that manual reset forces circuit back to closed state."""
    cb = CircuitBreaker(
        provider_name="test-provider",
        failure_threshold=1,
        recovery_timeout=1.0,
        state_dir=temp_state_dir,
    )

    try:
        cb.call(lambda: exec("raise ValueError()") or None)
    except ValueError:
        pass
    assert cb.state == CircuitState.OPEN

    cb.reset()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


def test_stats_accurate_throughout_lifecycle(temp_state_dir):
    """Verify that request counts and failures are tracked accurately."""
    cb = CircuitBreaker(
        provider_name="test-provider",
        failure_threshold=2,
        recovery_timeout=1.0,
        state_dir=temp_state_dir,
    )
    cb.call(lambda: "ok")
    stats = cb.get_stats()
    assert stats.total_requests == 1
    assert stats.success_count == 1
    assert stats.blocked_requests == 0
