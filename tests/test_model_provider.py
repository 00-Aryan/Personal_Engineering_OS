"""Unit tests for model provider implementations."""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from unittest.mock import patch

from core.events import AgentEvent, EventType
from core.model_provider import GeminiProvider, OllamaProvider, OpenRouterProvider


class ResponseStub:
    """Minimal requests response stub for provider unit tests."""

    def __init__(
        self,
        payload: Optional[Mapping[str, Any]] = None,
        lines: Optional[Iterable[str]] = None,
    ) -> None:
        """Store mocked JSON payloads and streamed response lines."""
        self._payload = payload or {}
        self._lines = list(lines or [])
        self.raise_for_status_called = False

    def json(self) -> Mapping[str, Any]:
        """Return the mocked JSON response payload."""
        return self._payload

    def raise_for_status(self) -> None:
        """Record that the provider checked HTTP status."""
        self.raise_for_status_called = True

    def iter_lines(self, decode_unicode: bool = False) -> Iterable[str]:
        """Yield mocked streamed response lines."""
        return iter(self._lines)


class ModelProviderTestCase(unittest.TestCase):
    """Tests model provider behavior with mocked HTTP calls."""

    def setUp(self) -> None:
        """Create a temporary model configuration for each test."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self._temp_dir.name) / "models.yaml"
        self.config_path.write_text(
            "\n".join(
                [
                    "providers:",
                    "  openrouter:",
                    "    api_key_env: OPENROUTER_API_KEY",
                    "    completion_url: https://openrouter.test/chat",
                    "    stream_url: https://openrouter.test/chat",
                    "    default_model: provider-openrouter-model",
                    "  gemini:",
                    "    api_key_env: GEMINI_API_KEY",
                    "    completion_url_template: https://gemini.test/models/{model}:generate?key={api_key}",
                    "    stream_url_template: https://gemini.test/models/{model}:stream?key={api_key}",
                    "    default_model: provider-gemini-model",
                    "  ollama:",
                    "    completion_url: http://ollama.test/api/generate",
                    "    stream_url: http://ollama.test/api/generate",
                    "    default_model: provider-ollama-model",
                    "agents:",
                    "  planning:",
                    "    provider: openrouter",
                    "    model: test-openrouter-model",
                    "  clone:",
                    "    provider: gemini",
                    "    model: test-gemini-model",
                    "  local:",
                    "    provider: ollama",
                    "    model: test-ollama-model",
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        """Remove the temporary model configuration."""
        self._temp_dir.cleanup()

    def test_agent_event_has_unique_ids(self) -> None:
        """Verify AgentEvent instances receive unique UUID event IDs."""
        first_event = AgentEvent(
            event_type=EventType.MANUAL_TRIGGER,
            source_agent="test",
            payload={},
        )
        second_event = AgentEvent(
            event_type=EventType.MANUAL_TRIGGER,
            source_agent="test",
            payload={},
        )

        self.assertNotEqual(first_event.event_id, second_event.event_id)
        uuid.UUID(first_event.event_id)
        uuid.UUID(second_event.event_id)

    def test_correlation_id_propagation(self) -> None:
        """Verify child events can link back to a parent event ID."""
        parent_event = AgentEvent(
            event_type=EventType.MANUAL_TRIGGER,
            source_agent="parent",
            payload={},
        )
        child_event = AgentEvent(
            event_type=EventType.BACKLOG_CHANGED,
            source_agent="child",
            payload={},
            correlation_id=parent_event.event_id,
        )

        self.assertEqual(child_event.correlation_id, parent_event.event_id)

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "fake-openrouter-key"},
        clear=True,
    )
    @patch("core.model_provider.requests.post")
    def test_openrouter_complete_uses_config_model(self, post_mock: Any) -> None:
        """Verify OpenRouter complete calls use config and mocked HTTP."""
        post_mock.return_value = ResponseStub(
            payload={"choices": [{"message": {"content": "openrouter output"}}]}
        )

        provider = OpenRouterProvider("planning", self.config_path)
        result = provider.complete("prompt", "system", 64)

        self.assertEqual(result, "openrouter output")
        self.assertEqual(provider.get_model_name(), "test-openrouter-model")
        post_mock.assert_called_once()
        _, kwargs = post_mock.call_args
        self.assertEqual(kwargs["json"]["model"], "test-openrouter-model")
        self.assertEqual(kwargs["json"]["max_tokens"], 64)
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer fake-openrouter-key",
        )
        self.assertFalse(kwargs["stream"])

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "fake-openrouter-key"},
        clear=True,
    )
    @patch("core.model_provider.requests.post")
    def test_openrouter_stream_uses_mocked_http(self, post_mock: Any) -> None:
        """Verify OpenRouter stream yields mocked response fragments."""
        post_mock.return_value = ResponseStub(
            lines=[
                'data: {"choices": [{"delta": {"content": "a"}}]}',
                'data: {"choices": [{"delta": {"content": "b"}}]}',
                "data: [DONE]",
            ]
        )

        provider = OpenRouterProvider("planning", self.config_path)
        result = list(provider.stream("prompt", "system"))

        self.assertEqual(result, ["a", "b"])
        _, kwargs = post_mock.call_args
        self.assertTrue(kwargs["json"]["stream"])
        self.assertTrue(kwargs["stream"])

    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-gemini-key"}, clear=True)
    @patch("core.model_provider.requests.post")
    def test_gemini_complete_uses_config_model(self, post_mock: Any) -> None:
        """Verify Gemini complete calls use config and mocked HTTP."""
        post_mock.return_value = ResponseStub(
            payload={
                "candidates": [
                    {"content": {"parts": [{"text": "gemini output"}]}}
                ]
            }
        )

        provider = GeminiProvider("clone", self.config_path)
        result = provider.complete("prompt", "system", 128)

        self.assertEqual(result, "gemini output")
        self.assertEqual(provider.get_model_name(), "test-gemini-model")
        post_mock.assert_called_once()
        args, kwargs = post_mock.call_args
        self.assertIn("test-gemini-model", args[0])
        self.assertIn("fake-gemini-key", args[0])
        self.assertEqual(
            kwargs["json"]["generationConfig"]["maxOutputTokens"],
            128,
        )
        self.assertFalse(kwargs["stream"])

    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-gemini-key"}, clear=True)
    @patch("core.model_provider.requests.post")
    def test_gemini_stream_uses_mocked_http(self, post_mock: Any) -> None:
        """Verify Gemini stream yields mocked response fragments."""
        post_mock.return_value = ResponseStub(
            lines=[
                '{"candidates": [{"content": {"parts": [{"text": "x"}]}}]}',
                '{"candidates": [{"content": {"parts": [{"text": "y"}]}}]}',
            ]
        )

        provider = GeminiProvider("clone", self.config_path)
        result = list(provider.stream("prompt", "system"))

        self.assertEqual(result, ["x", "y"])
        _, kwargs = post_mock.call_args
        self.assertTrue(kwargs["stream"])

    @patch("core.model_provider.requests.post")
    def test_ollama_complete_uses_config_model(self, post_mock: Any) -> None:
        """Verify Ollama complete calls use config and mocked HTTP."""
        post_mock.return_value = ResponseStub(payload={"response": "ollama output"})

        provider = OllamaProvider("local", self.config_path)
        result = provider.complete("prompt", "system", 32)

        self.assertEqual(result, "ollama output")
        self.assertEqual(provider.get_model_name(), "test-ollama-model")
        post_mock.assert_called_once()
        _, kwargs = post_mock.call_args
        self.assertEqual(kwargs["json"]["model"], "test-ollama-model")
        self.assertEqual(kwargs["json"]["options"]["num_predict"], 32)
        self.assertFalse(kwargs["json"]["stream"])

    @patch("core.model_provider.requests.post")
    def test_ollama_stream_uses_mocked_http(self, post_mock: Any) -> None:
        """Verify Ollama stream yields mocked response fragments."""
        post_mock.return_value = ResponseStub(
            lines=[
                '{"response": "m"}',
                '{"response": "n"}',
                '{"done": true}',
            ]
        )

        provider = OllamaProvider("local", self.config_path)
        result = list(provider.stream("prompt", "system"))

        self.assertEqual(result, ["m", "n"])
        _, kwargs = post_mock.call_args
        self.assertTrue(kwargs["json"]["stream"])
        self.assertTrue(kwargs["stream"])


if __name__ == "__main__":
    unittest.main()
