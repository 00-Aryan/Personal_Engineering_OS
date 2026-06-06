"""Unit tests for the RateLimiter observability component."""

from __future__ import annotations

import time
import threading
from core.observability.rate_limiter import RateLimiter


def test_acquire_succeeds_when_tokens_available():
    """Verify that acquiring tokens succeeds instantly if bucket has capacity."""
    limiter = RateLimiter(capacity=5, tokens_per_second=1.0, provider_name="test")
    assert limiter.acquire(3) is True
    assert abs(limiter.tokens - 2.0) < 0.1


def test_acquire_blocks_until_tokens_refill():
    """Verify that acquire blocks and waits for refills if capacity is exceeded."""
    limiter = RateLimiter(capacity=1, tokens_per_second=5.0, provider_name="test")
    assert limiter.acquire(1) is True

    start = time.time()
    # Bucket is empty, needs to wait 0.2s for 1 token at 5.0/sec
    assert limiter.acquire(1, timeout=1.0) is True
    duration = time.time() - start
    assert 0.1 <= duration <= 0.4


def test_try_acquire_returns_false_immediately():
    """Verify that try_acquire returns False immediately if not enough tokens."""
    limiter = RateLimiter(capacity=1, tokens_per_second=1.0, provider_name="test")
    assert limiter.try_acquire(1) is True

    start = time.time()
    assert limiter.try_acquire(1) is False
    assert time.time() - start < 0.05


def test_get_wait_time_accurate():
    """Verify that get_wait_time estimates the wait time correctly."""
    limiter = RateLimiter(capacity=2, tokens_per_second=2.0, provider_name="test")
    assert limiter.acquire(2) is True
    # Wait for 1 token at 2.0 tokens/second should be 0.5s
    wait = limiter.get_wait_time(1)
    assert abs(wait - 0.5) < 0.05


def test_thread_safety_concurrent_acquires():
    """Verify that concurrent acquires from multiple threads are thread-safe."""
    limiter = RateLimiter(capacity=10, tokens_per_second=100.0, provider_name="test")

    num_threads = 5
    def worker():
        for _ in range(5):
            assert limiter.acquire(1) is True

    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
