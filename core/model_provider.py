"""Model provider abstractions for ProjectOS agents."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional
from urllib.parse import quote

import requests
import yaml


CONFIG_KEY_AGENTS = "agents"
CONFIG_KEY_API_KEY_ENV = "api_key_env"
CONFIG_KEY_COMPLETION_URL = "completion_url"
CONFIG_KEY_COMPLETION_URL_TEMPLATE = "completion_url_template"
CONFIG_KEY_DEFAULT_MODEL = "default_model"
CONFIG_KEY_MODEL = "model"
CONFIG_KEY_PROVIDER = "provider"
CONFIG_KEY_PROVIDERS = "providers"
CONFIG_KEY_STREAM_URL = "stream_url"
CONFIG_KEY_STREAM_URL_TEMPLATE = "stream_url_template"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "models.yaml"


class ModelProviderConfigError(RuntimeError):
    """Raised when model provider configuration is missing or invalid."""


class ModelProvider(ABC):
    """Abstract base class for provider-backed language model calls."""

    provider_key: str

    def __init__(
        self,
        agent_name: Optional[str] = None,
        config_path: Optional[Path | str] = None,
    ) -> None:
        """Load provider and model configuration for an optional agent."""
        self._config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config = self._load_config(self._config_path)
        self._agent_name = agent_name
        self._provider_config = self._load_provider_config()
        self._model_name = self._load_model_name()

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return a complete model response for the provided prompt."""

    @abstractmethod
    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield streamed model response fragments for the provided prompt."""

    def get_model_name(self) -> str:
        """Return the configured model name for this provider instance."""
        return self._model_name

    def _load_config(self, config_path: Path) -> Mapping[str, Any]:
        """Read and validate the YAML model configuration file."""
        with config_path.open("r", encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file)
        if not isinstance(config, Mapping):
            raise ModelProviderConfigError("Model config must be a mapping.")
        return config

    def _load_provider_config(self) -> Mapping[str, Any]:
        """Return the provider-specific configuration section."""
        providers = self._config.get(CONFIG_KEY_PROVIDERS)
        if not isinstance(providers, Mapping):
            raise ModelProviderConfigError("Model config must define providers.")
        provider_config = providers.get(self.provider_key)
        if not isinstance(provider_config, Mapping):
            raise ModelProviderConfigError(
                f"Provider config missing for {self.provider_key}."
            )
        return provider_config

    def _load_model_name(self) -> str:
        """Resolve the configured model name from agent or provider config."""
        if self._agent_name:
            agents = self._config.get(CONFIG_KEY_AGENTS)
            if not isinstance(agents, Mapping):
                raise ModelProviderConfigError("Model config must define agents.")
            agent_config = agents.get(self._agent_name)
            if not isinstance(agent_config, Mapping):
                raise ModelProviderConfigError(
                    f"Agent config missing for {self._agent_name}."
                )
            configured_provider = agent_config.get(CONFIG_KEY_PROVIDER)
            if configured_provider != self.provider_key:
                raise ModelProviderConfigError(
                    f"Agent {self._agent_name} is not assigned to {self.provider_key}."
                )
            model_name = agent_config.get(CONFIG_KEY_MODEL)
        else:
            model_name = self._provider_config.get(CONFIG_KEY_DEFAULT_MODEL)

        if not isinstance(model_name, str) or not model_name:
            raise ModelProviderConfigError("Configured model name must be a string.")
        return model_name

    def _required_config_value(self, key: str) -> str:
        """Return a required string value from the provider config."""
        value = self._provider_config.get(key)
        if not isinstance(value, str) or not value:
            raise ModelProviderConfigError(
                f"Provider {self.provider_key} must define {key}."
            )
        return value

    def _optional_config_value(self, key: str) -> Optional[str]:
        """Return an optional string value from the provider config."""
        value = self._provider_config.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ModelProviderConfigError(
                f"Provider {self.provider_key} has invalid {key}."
            )
        return value

    def _api_key(self) -> Optional[str]:
        """Read the configured API key from the process environment."""
        api_key_env = self._optional_config_value(CONFIG_KEY_API_KEY_ENV)
        if not api_key_env:
            return None
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ModelProviderConfigError(
                f"Environment variable {api_key_env} is required."
            )
        return api_key

    def _format_template_url(self, config_key: str) -> str:
        """Render a configured provider URL template with model and API key."""
        api_key = self._api_key()
        if not api_key:
            raise ModelProviderConfigError(
                f"Provider {self.provider_key} requires an API key."
            )
        template = self._required_config_value(config_key)
        return template.format(
            model=quote(self.get_model_name(), safe=""),
            api_key=quote(api_key, safe=""),
        )

    def _post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        headers: Optional[Mapping[str, str]] = None,
        stream: bool = False,
    ) -> requests.Response:
        """Send a JSON POST request and raise for transport errors."""
        response = requests.post(url, json=payload, headers=headers, stream=stream)
        response.raise_for_status()
        return response


class OpenRouterProvider(ModelProvider):
    """Model provider implementation for the OpenRouter chat API."""

    provider_key = "openrouter"

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return a complete response from OpenRouter."""
        response = self._post_json(
            url=self._required_config_value(CONFIG_KEY_COMPLETION_URL),
            payload=self._chat_payload(prompt, system_prompt, max_tokens),
            headers=self._headers(),
        )
        response_payload = response.json()
        return str(response_payload["choices"][0]["message"]["content"])

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield streamed response fragments from OpenRouter."""
        response = self._post_json(
            url=self._required_config_value(CONFIG_KEY_STREAM_URL),
            payload=self._chat_payload(prompt, system_prompt, None, stream=True),
            headers=self._headers(),
            stream=True,
        )
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            text_line = line.decode("utf-8") if isinstance(line, bytes) else line
            if text_line.startswith("data:"):
                text_line = text_line[len("data:") :].strip()
            if text_line == "[DONE]":
                break
            chunk = json.loads(text_line)
            content = chunk["choices"][0].get("delta", {}).get("content")
            if content:
                yield str(content)

    def _headers(self) -> Dict[str, str]:
        """Return OpenRouter request headers using the environment API key."""
        api_key = self._api_key()
        if not api_key:
            raise ModelProviderConfigError("OpenRouter API key is required.")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _chat_payload(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: Optional[int],
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Build an OpenRouter chat completion payload."""
        payload: Dict[str, Any] = {
            "model": self.get_model_name(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stream:
            payload["stream"] = True
        return payload


class GeminiProvider(ModelProvider):
    """Model provider implementation for the Gemini REST API."""

    provider_key = "gemini"

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return a complete response from Gemini."""
        response = self._post_json(
            url=self._format_template_url(CONFIG_KEY_COMPLETION_URL_TEMPLATE),
            payload=self._gemini_payload(prompt, system_prompt, max_tokens),
        )
        return self._extract_text(response.json())

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield streamed response fragments from Gemini."""
        response = self._post_json(
            url=self._format_template_url(CONFIG_KEY_STREAM_URL_TEMPLATE),
            payload=self._gemini_payload(prompt, system_prompt, None),
            stream=True,
        )
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            text_line = line.decode("utf-8") if isinstance(line, bytes) else line
            if text_line.startswith("data:"):
                text_line = text_line[len("data:") :].strip()
            chunk = json.loads(text_line)
            content = self._extract_text(chunk)
            if content:
                yield content

    def _gemini_payload(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: Optional[int],
    ) -> Dict[str, Any]:
        """Build a Gemini generation payload."""
        payload: Dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
        }
        if max_tokens is not None:
            payload["generationConfig"] = {"maxOutputTokens": max_tokens}
        return payload

    def _extract_text(self, payload: Mapping[str, Any]) -> str:
        """Extract text from a Gemini response payload."""
        candidates = payload.get("candidates", [])
        if not candidates:
            return ""
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        return "".join(str(part.get("text", "")) for part in parts)


class OllamaProvider(ModelProvider):
    """Model provider implementation for the local Ollama API."""

    provider_key = "ollama"

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return a complete response from Ollama."""
        response = self._post_json(
            url=self._required_config_value(CONFIG_KEY_COMPLETION_URL),
            payload=self._ollama_payload(prompt, system_prompt, max_tokens, stream=False),
        )
        response_payload = response.json()
        return str(response_payload.get("response", ""))

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield streamed response fragments from Ollama."""
        response = self._post_json(
            url=self._required_config_value(CONFIG_KEY_STREAM_URL),
            payload=self._ollama_payload(prompt, system_prompt, None, stream=True),
            stream=True,
        )
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            text_line = line.decode("utf-8") if isinstance(line, bytes) else line
            chunk = json.loads(text_line)
            content = chunk.get("response")
            if content:
                yield str(content)

    def _ollama_payload(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: Optional[int],
        stream: bool,
    ) -> Dict[str, Any]:
        """Build an Ollama generation payload."""
        payload: Dict[str, Any] = {
            "model": self.get_model_name(),
            "prompt": prompt,
            "system": system_prompt,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["options"] = {"num_predict": max_tokens}
        return payload
