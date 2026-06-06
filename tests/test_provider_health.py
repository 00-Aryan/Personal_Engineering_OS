"""Unit tests for provider health checks and monitor state."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import requests

from core.model_provider import OllamaProvider, OpenRouterProvider
from core.provider_health import ProviderHealthMonitor


TEST_ENCODING = "utf-8"


class ResponseStub:
    """Minimal response object for health check tests."""

    def __init__(self, status_code: int) -> None:
        """Store a status code for provider health checks."""
        self.status_code = status_code


class FakeProvider:
    """Provider test double with configurable health."""

    def __init__(self, healthy: bool) -> None:
        """Initialize fake provider health."""
        self.healthy = healthy

    def health_check(self) -> bool:
        """Return configured health."""
        return self.healthy

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Return an unused completion value."""
        return ""

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Return an unused stream."""
        return iter(())

    def get_model_name(self) -> str:
        """Return an unused model name."""
        return "fake"


def test_health_check_returns_true_on_200(tmp_path: Path) -> None:
    """Verify provider health succeeds on HTTP 200."""
    provider = OpenRouterProvider("planning", _config_path(tmp_path))

    with patch("core.model_provider.requests.get") as get_mock:
        get_mock.return_value = ResponseStub(200)

        assert provider.health_check() is True


def test_health_check_returns_false_on_timeout(tmp_path: Path) -> None:
    """Verify provider health returns False on timeout."""
    provider = OllamaProvider("local", _config_path(tmp_path))

    with patch("core.model_provider.requests.get") as get_mock:
        get_mock.side_effect = requests.Timeout("slow")

        assert provider.health_check() is False


def test_health_check_returns_false_on_connection_error(tmp_path: Path) -> None:
    """Verify provider health returns False on connection errors."""
    provider = OllamaProvider("local", _config_path(tmp_path))

    with patch("core.model_provider.requests.get") as get_mock:
        get_mock.side_effect = requests.ConnectionError("down")

        assert provider.health_check() is False


def test_monitor_updates_status_dict() -> None:
    """Verify ProviderHealthMonitor records provider health results."""
    monitor = ProviderHealthMonitor(
        {
            "healthy": FakeProvider(True),
            "unreachable": FakeProvider(False),
        },
        check_interval=1,
    )

    monitor.start()
    try:
        _wait_for_status(monitor)
        assert monitor.get_status() == {"healthy": True, "unreachable": False}
    finally:
        monitor.stop()


def _config_path(tmp_path: Path) -> Path:
    """Write a complete provider config for health checks."""
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        "\n".join(
            [
                "providers:",
                "  openrouter:",
                "    api_key_env: OPENROUTER_API_KEY",
                "    completion_url: https://openrouter.test/chat",
                "    stream_url: https://openrouter.test/chat",
                "    default_model: provider-openrouter-model",
                "  ollama:",
                "    completion_url: http://ollama.test/api/generate",
                "    stream_url: http://ollama.test/api/generate",
                "    default_model: provider-ollama-model",
                "agents:",
                "  planning:",
                "    provider: openrouter",
                "    model: test-openrouter-model",
                "  local:",
                "    provider: ollama",
                "    model: test-ollama-model",
            ]
        )
        + "\n",
        encoding=TEST_ENCODING,
    )
    return config_path


def _wait_for_status(monitor: ProviderHealthMonitor) -> None:
    """Wait briefly until the monitor's first pass completes."""
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        status = monitor.get_status()
        if status.get("healthy") is True:
            return
        time.sleep(0.01)
    raise AssertionError("ProviderHealthMonitor did not update status.")
