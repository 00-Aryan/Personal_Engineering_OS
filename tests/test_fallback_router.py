"""Unit tests for fallback model routing."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator

import pytest

from core.fallback_router import FallbackRouter
from core.model_provider import ModelProvider


class FakeProvider(ModelProvider):
    """Minimal provider fake for fallback router tests."""

    provider_key = "fake"

    def __init__(self, name: str, response: str = "ok", should_fail: bool = False) -> None:
        """Initialize fake provider behavior without loading model config."""
        self.name = name
        self.response = response
        self.should_fail = should_fail
        self.calls = 0

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        agent_name: str | None = None,
        token_budget: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Return fake response or raise a configured failure."""
        self.calls += 1
        if self.should_fail:
            raise RuntimeError(f"{self.name} failed")
        return self.response

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield fake stream chunks."""
        yield self.complete(prompt, system_prompt, 0)

    def get_model_name(self) -> str:
        """Return fake model name."""
        return f"{self.name}-model"

    def health_check(self) -> bool:
        """Return fake provider health."""
        return not self.should_fail


class FakeHealthMonitor:
    """Health monitor fake exposing a status dictionary."""

    def __init__(self, status: Dict[str, bool]) -> None:
        """Store provider health status."""
        self.status = status

    def get_status(self) -> Dict[str, bool]:
        """Return configured provider health status."""
        return dict(self.status)


def test_uses_primary_when_healthy() -> None:
    """Verify the primary provider is used when healthy."""
    primary = FakeProvider("primary", response="primary-output")
    fallback = FakeProvider("fallback", response="fallback-output")
    router = FallbackRouter(
        primary,
        [fallback],
        FakeHealthMonitor({"primary": True, "fallback": True}),
    )

    result = router.complete("prompt", "system", 128)

    assert result == "primary-output"
    assert primary.calls == 1
    assert fallback.calls == 0


def test_falls_back_to_first_fallback_on_primary_failure() -> None:
    """Verify the first fallback is used when primary raises."""
    primary = FakeProvider("primary", should_fail=True)
    fallback = FakeProvider("fallback", response="fallback-output")
    router = FallbackRouter(
        primary,
        [fallback],
        FakeHealthMonitor({"primary": True, "fallback": True}),
    )

    result = router.complete("prompt", "system", 128)

    assert result == "fallback-output"
    assert primary.calls == 1
    assert fallback.calls == 1


def test_falls_back_to_second_if_first_also_fails() -> None:
    """Verify the second fallback is used after two failures."""
    primary = FakeProvider("primary", should_fail=True)
    first = FakeProvider("first", should_fail=True)
    second = FakeProvider("second", response="second-output")
    router = FallbackRouter(
        primary,
        [first, second],
        FakeHealthMonitor({"primary": True, "first": True, "second": True}),
    )

    result = router.complete("prompt", "system", 128)

    assert result == "second-output"
    assert primary.calls == 1
    assert first.calls == 1
    assert second.calls == 1


def test_raises_if_all_providers_fail() -> None:
    """Verify a clear error is raised when no providers can complete."""
    primary = FakeProvider("primary", should_fail=True)
    fallback = FakeProvider("fallback", should_fail=True)
    router = FallbackRouter(
        primary,
        [fallback],
        FakeHealthMonitor({"primary": True, "fallback": True}),
    )

    with pytest.raises(RuntimeError, match="All providers failed; attempted"):
        router.complete("prompt", "system", 128)


def test_logs_which_provider_was_used(caplog: pytest.LogCaptureFixture) -> None:
    """Verify successful provider selection is logged."""
    primary = FakeProvider("primary", should_fail=True)
    fallback = FakeProvider("fallback", response="fallback-output")
    router = FallbackRouter(
        primary,
        [fallback],
        FakeHealthMonitor({"primary": True, "fallback": True}),
    )

    with caplog.at_level(logging.INFO, logger="projectos.fallback_router"):
        result = router.complete("prompt", "system", 128)

    assert result == "fallback-output"
    assert "FallbackRouter used provider fallback" in caplog.text
