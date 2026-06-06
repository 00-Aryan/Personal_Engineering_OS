"""Circuit breaker implementation for ProjectOS model provider calls."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


class CircuitState(Enum):
    """Enumeration of possible circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerStats:
    """Statistics and current state of a circuit breaker."""

    provider_name: str
    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_at: Optional[datetime]
    last_success_at: Optional[datetime]
    opened_at: Optional[datetime]
    total_requests: int
    blocked_requests: int


class CircuitOpenError(Exception):
    """Raised when the circuit is OPEN and request is blocked."""

    def __init__(
        self,
        message: str,
        provider_name: str,
        recovery_timeout: float,
    ) -> None:
        """Initialize the error with provider and recovery timeout details."""
        super().__init__(message)
        self.provider_name = provider_name
        self.recovery_timeout = recovery_timeout


class CircuitBreaker:
    """Monitors failures for a provider and blocks calls if failure threshold is reached."""

    def __init__(
        self,
        provider_name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        state_dir: Optional[Path] = None,
    ) -> None:
        """Initialize the circuit breaker and load persisted state if any."""
        self.provider_name = provider_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state_dir = Path(state_dir) if state_dir else Path.cwd() / ".projectos_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / f"circuit_state_{provider_name}.json"
        self.log_path = self.state_dir / "circuit_breaker.jsonl"
        self._lock = threading.Lock()
        self._probe_in_progress = False

        with self._lock:
            self._load_state_locked()

    def _save_state_locked(self) -> None:
        """Save current circuit breaker state atomically. Lock must be held by caller."""
        data = {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_at": self.last_failure_at.isoformat() if self.last_failure_at else None,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "total_requests": self.total_requests,
            "blocked_requests": self.blocked_requests,
        }
        temp_fd, temp_path = tempfile.mkstemp(dir=str(self.state_path.parent))
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(temp_path, self.state_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def _load_state_locked(self) -> None:
        """Load circuit breaker state from file. Lock must be held by caller."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_at = None
        self.last_success_at = None
        self.opened_at = None
        self.total_requests = 0
        self.blocked_requests = 0

        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.state = CircuitState(data.get("state", "closed"))
                self.failure_count = int(data.get("failure_count", 0))
                self.success_count = int(data.get("success_count", 0))
                lf = data.get("last_failure_at")
                self.last_failure_at = datetime.fromisoformat(lf) if lf else None
                ls = data.get("last_success_at")
                self.last_success_at = datetime.fromisoformat(ls) if ls else None
                op = data.get("opened_at")
                self.opened_at = datetime.fromisoformat(op) if op else None
                self.total_requests = int(data.get("total_requests", 0))
                self.blocked_requests = int(data.get("blocked_requests", 0))
            except Exception:
                pass

    def _log_transition_locked(
        self,
        old_state: CircuitState,
        new_state: CircuitState,
        reason: str,
    ) -> None:
        """Append transition history log atomically. Lock must be held by caller."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider_name": self.provider_name,
            "old_state": old_state.value,
            "new_state": new_state.value,
            "reason": reason,
        }
        encoded = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        try:
            fd = os.open(
                self.log_path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )
            try:
                os.write(fd, encoded)
            finally:
                os.close(fd)
        except Exception:
            pass

    def call(self, fn: Callable, *args, **kwargs) -> Any:
        """Route call through the circuit breaker, checking for open/blocked states."""
        with self._lock:
            self.total_requests += 1
            now = datetime.now(timezone.utc)

            if self.state == CircuitState.OPEN:
                if self.opened_at and (now - self.opened_at).total_seconds() >= self.recovery_timeout:
                    old_state = self.state
                    self.state = CircuitState.HALF_OPEN
                    self._log_transition_locked(old_state, self.state, "recovery timeout elapsed")
                    self._save_state_locked()
                else:
                    self.blocked_requests += 1
                    self._save_state_locked()
                    raise CircuitOpenError(
                        f"Circuit is OPEN for provider {self.provider_name}",
                        provider_name=self.provider_name,
                        recovery_timeout=self.recovery_timeout,
                    )

            if self.state == CircuitState.HALF_OPEN:
                if self._probe_in_progress:
                    self.blocked_requests += 1
                    self._save_state_locked()
                    raise CircuitOpenError(
                        f"Circuit is HALF_OPEN and probe in progress for provider {self.provider_name}",
                        provider_name=self.provider_name,
                        recovery_timeout=self.recovery_timeout,
                    )
                self._probe_in_progress = True

        try:
            result = fn(*args, **kwargs)
            success = True
            error = None
        except Exception as e:
            success = False
            error = e

        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._probe_in_progress = False

            if success:
                self._record_success_locked(now)
            else:
                self._record_failure_locked(now)

        if not success and error:
            raise error
        return result

    def record_success(self) -> None:
        """Record manual or external call success."""
        with self._lock:
            self._record_success_locked(datetime.now(timezone.utc))

    def record_failure(self) -> None:
        """Record manual or external call failure."""
        with self._lock:
            self._record_failure_locked(datetime.now(timezone.utc))

    def _record_success_locked(self, timestamp: datetime) -> None:
        """Update stats and state for success. Lock must be held by caller."""
        self.success_count += 1
        self.last_success_at = timestamp
        self.failure_count = 0

        if self.state == CircuitState.HALF_OPEN:
            old_state = self.state
            self.state = CircuitState.CLOSED
            self._log_transition_locked(old_state, self.state, "probe call succeeded")

        self._save_state_locked()

    def _record_failure_locked(self, timestamp: datetime) -> None:
        """Update stats and state for failure. Lock must be held by caller."""
        self.failure_count += 1
        self.last_failure_at = timestamp

        if self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
            if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
                old_state = self.state
                self.state = CircuitState.OPEN
                self.opened_at = timestamp
                reason = (
                    "probe call failed"
                    if old_state == CircuitState.HALF_OPEN
                    else f"{self.failure_count} consecutive failures"
                )
                self._log_transition_locked(old_state, self.state, reason)

        self._save_state_locked()

    def get_stats(self) -> CircuitBreakerStats:
        """Return snapshot stats of the circuit breaker."""
        with self._lock:
            return CircuitBreakerStats(
                provider_name=self.provider_name,
                state=self.state,
                failure_count=self.failure_count,
                success_count=self.success_count,
                last_failure_at=self.last_failure_at,
                last_success_at=self.last_success_at,
                opened_at=self.opened_at,
                total_requests=self.total_requests,
                blocked_requests=self.blocked_requests,
            )

    def reset(self) -> None:
        """Force the circuit breaker to CLOSED state."""
        with self._lock:
            old_state = self.state
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_at = None
            self.last_success_at = None
            self.opened_at = None
            self._log_transition_locked(old_state, self.state, "manual reset")
            self._save_state_locked()
