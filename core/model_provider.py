"""Model provider abstractions for ProjectOS agents."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, TYPE_CHECKING
from urllib.parse import quote, urlparse

import requests
import yaml

from core.retry import with_retry
from core.observability.token_budget import _local
from core.observability.circuit_breaker import CircuitOpenError

if TYPE_CHECKING:
    from core.observability.token_budget import TokenBudget


def _write_atomically(path: Path, content: str) -> None:
    """Write content to a path by replacing it with a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file while preserving existing content."""
    existing_content = path.read_text(encoding="utf-8") if path.exists() else ""
    _write_atomically(path, f"{existing_content}{content}")


CONFIG_KEY_AGENTS = "agents"
CONFIG_KEY_API_KEY_ENV = "api_key_env"
CONFIG_KEY_BASE_URL = "base_url"
CONFIG_KEY_COMPLETION_URL = "completion_url"
CONFIG_KEY_COMPLETION_URL_TEMPLATE = "completion_url_template"
CONFIG_KEY_DEFAULT_MODEL = "default_model"
CONFIG_KEY_MODEL = "model"
CONFIG_KEY_PROVIDER = "provider"
CONFIG_KEY_PROVIDERS = "providers"
CONFIG_KEY_STREAM_URL = "stream_url"
CONFIG_KEY_STREAM_URL_TEMPLATE = "stream_url_template"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "models.yaml"
HEALTH_CHECK_TIMEOUT_SECONDS = 5
PROVIDER_RETRY_ATTEMPTS = 3
PROVIDER_RETRY_BACKOFF_SECONDS = 1.0
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
GEMINI_MODELS_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
)
OLLAMA_BASE_URL_ENV = "OLLAMA_BASE_URL"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_GENERATE_PATH = "/api/generate"
OLLAMA_TAGS_PATH = "/api/tags"


class ModelProviderConfigError(RuntimeError):
    """Raised when model provider configuration is missing or invalid."""


class ModelProvider(ABC):
    """Abstract base class for provider-backed language model calls."""

    provider_key: str

    def __init__(
        self,
        agent_name: Optional[str] = None,
        config_path: Optional[Path | str] = None,
        token_budget: Optional[TokenBudget] = None,
        cost_tracker: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        circuit_breaker: Optional[Any] = None,
        fallback_router: Optional[Any] = None,
    ) -> None:
        """Load provider and model configuration for an optional agent."""
        self._config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config = self._load_config(self._config_path)
        self._agent_name = agent_name
        self._provider_config = self._load_provider_config()
        self._model_name = self._load_model_name()
        self.token_budget = token_budget
        self.cost_tracker = cost_tracker
        self.rate_limiter = rate_limiter
        self.circuit_breaker = circuit_breaker
        self.fallback_router = fallback_router

    def _project_root(self) -> Path:
        """Return project root based on config path."""
        resolved_path = self._config_path.resolve()
        if resolved_path.parent.name == "config":
            return resolved_path.parent.parent
        return Path.cwd()

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        agent_name: Optional[str] = None,
        token_budget: Optional[TokenBudget] = None,
        rate_limiter: Optional[Any] = None,
        circuit_breaker: Optional[Any] = None,
    ) -> str:
        """Return a complete model response for the provided prompt."""

    @abstractmethod
    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield streamed model response fragments for the provided prompt."""

    def health_check(self) -> bool:
        """Return whether this provider is reachable without raising."""
        return False

    def get_model_name(self) -> str:
        """Return the configured model name for this provider instance."""
        return self._model_name

    def _load_config(self, config_path: Path) -> Mapping[str, Any]:
        """Read and validate the YAML model configuration file."""
        if config_path.name == "models.yaml":
            sibling_projectos = config_path.parent / "projectos.yaml"
            if sibling_projectos.exists():
                import logging
                logging.getLogger("projectos.model_provider").warning(
                    "config/models.yaml is deprecated. Please use config/projectos.yaml instead."
                )
        with config_path.open("r", encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file)
        if not isinstance(config, Mapping):
            raise ModelProviderConfigError("Model config must be a mapping.")
        if "project" in config or config.get("version") == "0.3.0" or "token_budgets" in config:
            from core.config_loader import adapt_to_legacy_config
            config = adapt_to_legacy_config(config)
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

    def _with_retry(self, fn: Callable[[], Any]) -> Any:
        """Execute a provider request with standard retry policy."""
        return with_retry(
            fn,
            max_attempts=PROVIDER_RETRY_ATTEMPTS,
            backoff_seconds=PROVIDER_RETRY_BACKOFF_SECONDS,
        )


class OpenRouterProvider(ModelProvider):
    """Model provider implementation for the OpenRouter chat API."""

    provider_key = "openrouter"

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        agent_name: Optional[str] = None,
        token_budget: Optional[TokenBudget] = None,
        rate_limiter: Optional[Any] = None,
        circuit_breaker: Optional[Any] = None,
    ) -> str:
        """Return a complete response from OpenRouter."""
        from core.observability.token_budget import _local
        event_id = getattr(_local, "current_task_id", None)
        if event_id:
            from core.task_queue import record_model_call
            if not record_model_call(event_id, self._project_root()):
                return f"MODEL_CALL_BLOCKED: Event [{event_id}] blocked: exceeded max model calls (5)"

        tb = token_budget or getattr(self, "token_budget", None)
        a_name = agent_name or self._agent_name or "default"
        if tb:
            if not hasattr(_local, "last_provider"):
                _local.last_provider = {}
            _local.last_provider[a_name] = self.provider_key
            if not hasattr(_local, "last_model"):
                _local.last_model = {}
            _local.last_model[a_name] = self.get_model_name()

            check = tb.check_and_record(a_name, prompt + system_prompt)
            if check.hard_limit_exceeded:
                return f"TOKEN_BUDGET_EXCEEDED: {check.warning_message}"
            if check.soft_limit_exceeded:
                log_path = self._project_root() / "decisions.log"
                _append_atomically(log_path, f"[model_provider] {check.warning_message}\n")

        # 1. Rate limiter check
        rl = rate_limiter or getattr(self, "rate_limiter", None)
        if rl:
            estimated_tokens = len(prompt + system_prompt) // 4
            acquired = rl.acquire(tokens=estimated_tokens)
            if not acquired:
                import logging
                logging.getLogger("projectos.model_provider").warning(
                    f"Rate limit timeout acquiring {estimated_tokens} tokens for {self.provider_key}"
                )
                return "RATE_LIMIT_ERROR"

        # 2. Circuit breaker check
        cb = circuit_breaker or getattr(self, "circuit_breaker", None)
        def make_call():
            return self._with_retry(
                lambda: self._complete_once(prompt, system_prompt, max_tokens)
            )

        try:
            if cb:
                result = str(cb.call(make_call))
            else:
                result = str(make_call())
        except CircuitOpenError as e:
            import logging
            logging.getLogger("projectos.model_provider").warning(
                f"Circuit open for provider {self.provider_key}: {e}"
            )
            fr = getattr(self, "fallback_router", None)
            if fr and not getattr(_local, "in_fallback", False):
                if not hasattr(_local, "in_fallback"):
                    _local.in_fallback = False
                _local.in_fallback = True
                try:
                    return fr.complete(
                        prompt,
                        system_prompt,
                        max_tokens,
                        agent_name=agent_name,
                        token_budget=token_budget,
                        rate_limiter=rate_limiter,
                        circuit_breaker=circuit_breaker,
                    )
                finally:
                    _local.in_fallback = False
            
            if getattr(_local, "in_fallback", False):
                raise e
            return "CIRCUIT_OPEN_ERROR"

        if result in ("RATE_LIMIT_ERROR", "CIRCUIT_OPEN_ERROR"):
            return result

        record = None
        if tb:
            record = tb.record_completion(a_name, result)

        ct = getattr(self, "cost_tracker", None)
        if ct:
            task_id = getattr(_local, "current_task_id", None)
            trace_id = None
            if getattr(self, "tracer", None):
                try:
                    with self.tracer._lock:
                        trace_id = self.tracer._event_to_trace.get(task_id)
                except Exception:
                    pass
            prompt_tokens = record.prompt_tokens if record else len(prompt + system_prompt) // 4
            completion_tokens = record.completion_tokens if record else len(result) // 4
            ct.record(
                agent_name=a_name,
                provider=self.provider_key,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                trace_id=trace_id,
                task_id=task_id,
                model=self.get_model_name(),
            )

        return result

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield streamed response fragments from OpenRouter."""
        return iter(
            self._with_retry(lambda: list(self._stream_once(prompt, system_prompt)))
        )

    def health_check(self) -> bool:
        """Return whether the OpenRouter models endpoint is reachable."""
        try:
            response = requests.get(
                OPENROUTER_MODELS_URL,
                timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
            )
            return response.status_code == 200
        except Exception:
            return False

    def _complete_once(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return one non-retried complete response from OpenRouter."""
        response = self._post_json(
            url=self._required_config_value(CONFIG_KEY_COMPLETION_URL),
            payload=self._chat_payload(prompt, system_prompt, max_tokens),
            headers=self._headers(),
        )
        response_payload = response.json()
        return str(response_payload["choices"][0]["message"]["content"])

    def _stream_once(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield one non-retried stream from OpenRouter."""
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
        agent_name: Optional[str] = None,
        token_budget: Optional[TokenBudget] = None,
        rate_limiter: Optional[Any] = None,
        circuit_breaker: Optional[Any] = None,
    ) -> str:
        """Return a complete response from Gemini."""
        from core.observability.token_budget import _local
        event_id = getattr(_local, "current_task_id", None)
        if event_id:
            from core.task_queue import record_model_call
            if not record_model_call(event_id, self._project_root()):
                return f"MODEL_CALL_BLOCKED: Event [{event_id}] blocked: exceeded max model calls (5)"

        tb = token_budget or getattr(self, "token_budget", None)
        a_name = agent_name or self._agent_name or "default"
        if tb:
            if not hasattr(_local, "last_provider"):
                _local.last_provider = {}
            _local.last_provider[a_name] = self.provider_key
            if not hasattr(_local, "last_model"):
                _local.last_model = {}
            _local.last_model[a_name] = self.get_model_name()

            check = tb.check_and_record(a_name, prompt + system_prompt)
            if check.hard_limit_exceeded:
                return f"TOKEN_BUDGET_EXCEEDED: {check.warning_message}"
            if check.soft_limit_exceeded:
                log_path = self._project_root() / "decisions.log"
                _append_atomically(log_path, f"[model_provider] {check.warning_message}\n")

        # 1. Rate limiter check
        rl = rate_limiter or getattr(self, "rate_limiter", None)
        if rl:
            estimated_tokens = len(prompt + system_prompt) // 4
            acquired = rl.acquire(tokens=estimated_tokens)
            if not acquired:
                import logging
                logging.getLogger("projectos.model_provider").warning(
                    f"Rate limit timeout acquiring {estimated_tokens} tokens for {self.provider_key}"
                )
                return "RATE_LIMIT_ERROR"

        # 2. Circuit breaker check
        cb = circuit_breaker or getattr(self, "circuit_breaker", None)
        def make_call():
            return self._with_retry(
                lambda: self._complete_once(prompt, system_prompt, max_tokens)
            )

        try:
            if cb:
                result = str(cb.call(make_call))
            else:
                result = str(make_call())
        except CircuitOpenError as e:
            import logging
            logging.getLogger("projectos.model_provider").warning(
                f"Circuit open for provider {self.provider_key}: {e}"
            )
            fr = getattr(self, "fallback_router", None)
            if fr and not getattr(_local, "in_fallback", False):
                if not hasattr(_local, "in_fallback"):
                    _local.in_fallback = False
                _local.in_fallback = True
                try:
                    return fr.complete(
                        prompt,
                        system_prompt,
                        max_tokens,
                        agent_name=agent_name,
                        token_budget=token_budget,
                        rate_limiter=rate_limiter,
                        circuit_breaker=circuit_breaker,
                    )
                finally:
                    _local.in_fallback = False
            
            if getattr(_local, "in_fallback", False):
                raise e
            return "CIRCUIT_OPEN_ERROR"

        if result in ("RATE_LIMIT_ERROR", "CIRCUIT_OPEN_ERROR"):
            return result

        record = None
        if tb:
            record = tb.record_completion(a_name, result)

        ct = getattr(self, "cost_tracker", None)
        if ct:
            task_id = getattr(_local, "current_task_id", None)
            trace_id = None
            if getattr(self, "tracer", None):
                try:
                    with self.tracer._lock:
                        trace_id = self.tracer._event_to_trace.get(task_id)
                except Exception:
                    pass
            prompt_tokens = record.prompt_tokens if record else len(prompt + system_prompt) // 4
            completion_tokens = record.completion_tokens if record else len(result) // 4
            ct.record(
                agent_name=a_name,
                provider=self.provider_key,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                trace_id=trace_id,
                task_id=task_id,
                model=self.get_model_name(),
            )

        return result

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield streamed response fragments from Gemini."""
        return iter(
            self._with_retry(lambda: list(self._stream_once(prompt, system_prompt)))
        )

    def health_check(self) -> bool:
        """Return whether the Gemini models endpoint is reachable."""
        try:
            api_key = self._api_key()
            if not api_key:
                return False
            response = requests.get(
                GEMINI_MODELS_URL_TEMPLATE.format(api_key=quote(api_key, safe="")),
                timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
            )
            return response.status_code == 200
        except Exception:
            return False

    def _complete_once(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return one non-retried complete response from Gemini."""
        response = self._post_json(
            url=self._format_template_url(CONFIG_KEY_COMPLETION_URL_TEMPLATE),
            payload=self._gemini_payload(prompt, system_prompt, max_tokens),
        )
        return self._extract_text(response.json())

    def _stream_once(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield one non-retried stream from Gemini."""
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
        agent_name: Optional[str] = None,
        token_budget: Optional[TokenBudget] = None,
        rate_limiter: Optional[Any] = None,
        circuit_breaker: Optional[Any] = None,
    ) -> str:
        """Return a complete response from Ollama."""
        from core.observability.token_budget import _local
        event_id = getattr(_local, "current_task_id", None)
        if event_id:
            from core.task_queue import record_model_call
            if not record_model_call(event_id, self._project_root()):
                return f"MODEL_CALL_BLOCKED: Event [{event_id}] blocked: exceeded max model calls (5)"

        tb = token_budget or getattr(self, "token_budget", None)
        a_name = agent_name or self._agent_name or "default"
        if tb:
            if not hasattr(_local, "last_provider"):
                _local.last_provider = {}
            _local.last_provider[a_name] = self.provider_key
            if not hasattr(_local, "last_model"):
                _local.last_model = {}
            _local.last_model[a_name] = self.get_model_name()

            check = tb.check_and_record(a_name, prompt + system_prompt)
            if check.hard_limit_exceeded:
                return f"TOKEN_BUDGET_EXCEEDED: {check.warning_message}"
            if check.soft_limit_exceeded:
                log_path = self._project_root() / "decisions.log"
                _append_atomically(log_path, f"[model_provider] {check.warning_message}\n")

        # 1. Rate limiter check
        rl = rate_limiter or getattr(self, "rate_limiter", None)
        if rl:
            estimated_tokens = len(prompt + system_prompt) // 4
            acquired = rl.acquire(tokens=estimated_tokens)
            if not acquired:
                import logging
                logging.getLogger("projectos.model_provider").warning(
                    f"Rate limit timeout acquiring {estimated_tokens} tokens for {self.provider_key}"
                )
                return "RATE_LIMIT_ERROR"

        # 2. Circuit breaker check
        cb = circuit_breaker or getattr(self, "circuit_breaker", None)
        def make_call():
            return self._with_retry(
                lambda: self._complete_once(prompt, system_prompt, max_tokens)
            )

        try:
            if cb:
                result = str(cb.call(make_call))
            else:
                result = str(make_call())
        except CircuitOpenError as e:
            import logging
            logging.getLogger("projectos.model_provider").warning(
                f"Circuit open for provider {self.provider_key}: {e}"
            )
            fr = getattr(self, "fallback_router", None)
            if fr and not getattr(_local, "in_fallback", False):
                if not hasattr(_local, "in_fallback"):
                    _local.in_fallback = False
                _local.in_fallback = True
                try:
                    return fr.complete(
                        prompt,
                        system_prompt,
                        max_tokens,
                        agent_name=agent_name,
                        token_budget=token_budget,
                        rate_limiter=rate_limiter,
                        circuit_breaker=circuit_breaker,
                    )
                finally:
                    _local.in_fallback = False
            
            if getattr(_local, "in_fallback", False):
                raise e
            return "CIRCUIT_OPEN_ERROR"

        if result in ("RATE_LIMIT_ERROR", "CIRCUIT_OPEN_ERROR"):
            return result

        record = None
        if tb:
            record = tb.record_completion(a_name, result)

        ct = getattr(self, "cost_tracker", None)
        if ct:
            task_id = getattr(_local, "current_task_id", None)
            trace_id = None
            if getattr(self, "tracer", None):
                try:
                    with self.tracer._lock:
                        trace_id = self.tracer._event_to_trace.get(task_id)
                except Exception:
                    pass
            prompt_tokens = record.prompt_tokens if record else len(prompt + system_prompt) // 4
            completion_tokens = record.completion_tokens if record else len(result) // 4
            ct.record(
                agent_name=a_name,
                provider=self.provider_key,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                trace_id=trace_id,
                task_id=task_id,
                model=self.get_model_name(),
            )

        return result

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield streamed response fragments from Ollama."""
        return iter(
            self._with_retry(lambda: list(self._stream_once(prompt, system_prompt)))
        )

    def health_check(self) -> bool:
        """Return whether the local Ollama API is reachable."""
        try:
            response = requests.get(
                self._ollama_url(OLLAMA_TAGS_PATH),
                timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
            )
            return response.status_code == 200
        except Exception:
            return False

    def _complete_once(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return one non-retried complete response from Ollama."""
        response = self._post_json(
            url=self._ollama_url(OLLAMA_GENERATE_PATH),
            payload=self._ollama_payload(prompt, system_prompt, max_tokens, stream=False),
        )
        response_payload = response.json()
        return str(response_payload.get("response", ""))

    def _stream_once(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield one non-retried stream from Ollama."""
        response = self._post_json(
            url=self._ollama_url(OLLAMA_GENERATE_PATH),
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

    def _ollama_url(self, path: str) -> str:
        """Return an Ollama URL from env, config base URL, or legacy URL config."""
        base_url = self._ollama_base_url()
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    def _ollama_base_url(self) -> str:
        """Return the configured Ollama base URL with localhost as final default."""
        env_base_url = os.environ.get(OLLAMA_BASE_URL_ENV)
        if env_base_url:
            return env_base_url

        configured_base_url = self._optional_config_value(CONFIG_KEY_BASE_URL)
        if configured_base_url:
            return configured_base_url

        configured_generate_url = self._optional_config_value(CONFIG_KEY_COMPLETION_URL)
        if configured_generate_url:
            return self._base_url_from_generate_url(configured_generate_url)

        return DEFAULT_OLLAMA_BASE_URL

    def _base_url_from_generate_url(self, generate_url: str) -> str:
        """Derive a base URL from a legacy Ollama generate endpoint URL."""
        parsed_url = urlparse(generate_url)
        if not parsed_url.scheme or not parsed_url.netloc:
            return DEFAULT_OLLAMA_BASE_URL
        return f"{parsed_url.scheme}://{parsed_url.netloc}"
