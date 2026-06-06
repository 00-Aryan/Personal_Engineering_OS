"""Rate limiter implementation for ProjectOS agents."""

from __future__ import annotations

import time
import threading
from enum import Enum
from typing import Dict


class RateLimitStrategy(Enum):
    """Supported rate limiting algorithms."""

    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"


class RateLimiter:
    """Token bucket rate limiter that smooths out bursts of requests."""

    def __init__(
        self,
        capacity: int,
        tokens_per_second: float,
        provider_name: str,
    ) -> None:
        """Initialize the rate limiter with capacity and refill rate."""
        self.capacity = capacity
        self.tokens_per_second = tokens_per_second
        self.provider_name = provider_name
        self.tokens = float(capacity)
        self.last_updated = time.time()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    def _update_tokens(self) -> None:
        """Refill tokens based on elapsed time. Must be called with lock held."""
        now = time.time()
        elapsed = now - self.last_updated
        if elapsed > 0:
            new_tokens = elapsed * self.tokens_per_second
            self.tokens = min(float(self.capacity), self.tokens + new_tokens)
            self.last_updated = now

    def acquire(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        """Block until tokens are available or timeout is reached."""
        start_time = time.time()
        with self._cond:
            while True:
                self._update_tokens()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

                elapsed = time.time() - start_time
                remaining_timeout = timeout - elapsed
                if remaining_timeout <= 0:
                    return False

                needed = tokens - self.tokens
                wait_time = needed / self.tokens_per_second
                sleep_time = min(wait_time, remaining_timeout)
                self._cond.wait(timeout=sleep_time)

    def try_acquire(self, tokens: int = 1) -> bool:
        """Attempt to acquire tokens without blocking."""
        with self._lock:
            self._update_tokens()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def get_wait_time(self, tokens: int) -> float:
        """Return estimated seconds until requested tokens are available."""
        with self._lock:
            self._update_tokens()
            if self.tokens >= tokens:
                return 0.0
            needed = tokens - self.tokens
            return needed / self.tokens_per_second


class ProviderRateLimits:
    """Pre-configured rate limits per provider."""

    LIMITS: Dict[str, RateLimiter] = {
        "gemini": RateLimiter(
            capacity=1500,
            tokens_per_second=25.0,
            provider_name="gemini",
        ),
        "openrouter": RateLimiter(
            capacity=200,
            tokens_per_second=3.3,
            provider_name="openrouter",
        ),
        "ollama": RateLimiter(
            capacity=10000,
            tokens_per_second=100.0,
            provider_name="ollama",
        ),
        "default": RateLimiter(
            capacity=100,
            tokens_per_second=2.0,
            provider_name="default",
        ),
    }

    @classmethod
    def get(cls, provider_name: str) -> RateLimiter:
        """Return limiter for the given provider, falling back to default."""
        return cls.LIMITS.get(provider_name, cls.LIMITS["default"])
