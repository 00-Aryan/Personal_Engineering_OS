"""Unit tests for the Ollama model provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional
from unittest.mock import patch

from core.model_provider import OllamaProvider


class ResponseStub:
    """Small requests response stub for Ollama tests."""

    def __init__(
        self,
        payload: Optional[Mapping[str, Any]] = None,
        status_code: int = 200,
    ) -> None:
        """Store mocked response payload and status."""
        self._payload = payload or {}
        self.status_code = status_code
        self.raise_for_status_called = False

    def json(self) -> Mapping[str, Any]:
        """Return mocked JSON payload."""
        return self._payload

    def raise_for_status(self) -> None:
        """Record status validation."""
        self.raise_for_status_called = True


def _write_config(config_path: Path) -> None:
    """Write a minimal Ollama provider config for tests."""
    config_path.write_text(
        "\n".join(
            [
                "providers:",
                "  ollama:",
                "    completion_url: http://localhost:11434/api/generate",
                "    stream_url: http://localhost:11434/api/generate",
                "    default_model: ollama-default",
                "agents:",
                "  local:",
                "    provider: ollama",
                "    model: ollama-llama3",
            ]
        ),
        encoding="utf-8",
    )


@patch("core.model_provider.requests.post")
def test_complete_sends_correct_payload(post_mock: Any, tmp_path: Path, monkeypatch: Any) -> None:
    """Verify Ollama complete sends model, prompt, stream, and token options."""
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    config_path = tmp_path / "models.yaml"
    _write_config(config_path)
    post_mock.return_value = ResponseStub(payload={"response": "ok"})

    provider = OllamaProvider("local", config_path)
    result = provider.complete("hello", "system", 64)

    assert result == "ok"
    post_mock.assert_called_once()
    args, kwargs = post_mock.call_args
    assert args[0] == "http://localhost:11434/api/generate"
    assert kwargs["json"]["model"] == "ollama-llama3"
    assert kwargs["json"]["prompt"] == "hello"
    assert kwargs["json"]["stream"] is False
    assert kwargs["json"]["options"]["num_predict"] == 64


@patch("core.model_provider.requests.post")
def test_complete_returns_response_field(post_mock: Any, tmp_path: Path, monkeypatch: Any) -> None:
    """Verify Ollama complete returns the response field."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test")
    config_path = tmp_path / "models.yaml"
    _write_config(config_path)
    post_mock.return_value = ResponseStub(payload={"response": "local output"})

    provider = OllamaProvider("local", config_path)
    result = provider.complete("prompt", "system", 32)

    assert result == "local output"
    args, _ = post_mock.call_args
    assert args[0] == "http://ollama.test/api/generate"


@patch("core.model_provider.requests.get")
def test_health_check_true_on_200(get_mock: Any, tmp_path: Path, monkeypatch: Any) -> None:
    """Verify Ollama health check returns true on HTTP 200."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test")
    config_path = tmp_path / "models.yaml"
    _write_config(config_path)
    get_mock.return_value = ResponseStub(status_code=200)

    provider = OllamaProvider("local", config_path)

    assert provider.health_check() is True
    args, kwargs = get_mock.call_args
    assert args[0] == "http://ollama.test/api/tags"
    assert kwargs["timeout"] == 5


@patch("core.model_provider.requests.get")
def test_health_check_false_on_connection_error(
    get_mock: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Verify Ollama health check never raises on connection errors."""
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    config_path = tmp_path / "models.yaml"
    _write_config(config_path)
    get_mock.side_effect = ConnectionError("down")

    provider = OllamaProvider("local", config_path)

    assert provider.health_check() is False
