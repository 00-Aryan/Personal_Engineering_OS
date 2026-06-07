"""Shared provider setup helpers for ProjectOS scripts."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

import requests
import yaml


ENCODING = "utf-8"
CONFIG_PATH = Path("config/models.yaml")
ENV_PATH = Path(".env")
STATE_DIR = Path(".projectos_state")
PROVIDER_STATUS_PATH = STATE_DIR / "provider_status.json"
PROVIDER_STATUS_VERSION = 1
STATUS_AVAILABLE = "available"
STATUS_SKIPPED = "skipped"
STATUS_UNAVAILABLE = "unavailable"
KEY_PROVIDERS = "providers"
KEY_AGENTS = "agents"
KEY_API_KEY_ENV = "api_key_env"
KEY_MODEL = "model"
KEY_PROVIDER = "provider"
KEY_DEFAULT_MODEL = "default_model"
KEY_COMPLETION_URL = "completion_url"
KEY_COMPLETION_URL_TEMPLATE = "completion_url_template"
KEY_BASE_URL = "base_url"
OLLAMA_BASE_URL_ENV = "OLLAMA_BASE_URL"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
GEMINI_MODELS_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
)
OLLAMA_TAGS_PATH = "/api/tags"
HEALTH_TIMEOUT_SECONDS = 10


def utc_timestamp() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def write_atomically(path: Path, content: str) -> None:
    """Write content to a path via temp-file replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding=ENCODING) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def load_env_file(env_path: Path = ENV_PATH) -> Dict[str, str]:
    """Load .env values into os.environ and return values found in the file."""
    loaded_values: Dict[str, str] = {}
    if not env_path.exists():
        return loaded_values

    try:
        from dotenv import dotenv_values, load_dotenv
    except ImportError:
        parsed_values = _parse_env_manually(env_path)
        for key, value in parsed_values.items():
            os.environ.setdefault(key, value)
        return parsed_values

    load_dotenv(env_path, override=False)
    dotenv_payload = dotenv_values(env_path)
    for key, value in dotenv_payload.items():
        if key and value is not None:
            loaded_values[str(key)] = str(value)
    return loaded_values


def load_model_config(config_path: Path = CONFIG_PATH) -> Mapping[str, Any]:
    """Read config/models.yaml as a mapping."""
    with config_path.open("r", encoding=ENCODING) as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, Mapping):
        raise ValueError("Model config must be a mapping.")
    return config


def build_provider_status(
    config: Mapping[str, Any],
    check_health: bool = True,
) -> Dict[str, Any]:
    """Build provider setup status for all configured providers."""
    providers = config.get(KEY_PROVIDERS, {})
    if not isinstance(providers, Mapping):
        providers = {}

    provider_statuses: Dict[str, Dict[str, Any]] = {}
    for provider_name, provider_config in providers.items():
        if not isinstance(provider_config, Mapping):
            provider_statuses[str(provider_name)] = _status_row(
                STATUS_UNAVAILABLE,
                False,
                "provider config is invalid",
                None,
                None,
                latency_ms=0,
                error="provider config is invalid",
            )
            continue
        provider_statuses[str(provider_name)] = _check_provider(
            str(provider_name),
            provider_config,
            config,
            check_health,
        )

    available_providers = [
        provider_name
        for provider_name, status in provider_statuses.items()
        if bool(status.get("available"))
    ]
    
    root_status = {
        "schema_version": PROVIDER_STATUS_VERSION,
        "generated_at": utc_timestamp(),
        "providers": provider_statuses,
        "available_providers": available_providers,
    }
    
    for provider_name, status in provider_statuses.items():
        root_status[provider_name] = {
            "available": status["available"],
            "latency_ms": status.get("latency_ms", 0),
            "error": status.get("error"),
        }
        
    return root_status


def write_provider_status(
    status: Mapping[str, Any],
    status_path: Path = PROVIDER_STATUS_PATH,
) -> None:
    """Write provider status JSON atomically."""
    rendered = json.dumps(status, indent=2, sort_keys=True) + "\n"
    write_atomically(status_path, rendered)


def load_provider_status(status_path: Path = PROVIDER_STATUS_PATH) -> Dict[str, Any]:
    """Load provider status JSON or return an empty status document."""
    if not status_path.exists():
        return {
            "schema_version": PROVIDER_STATUS_VERSION,
            "generated_at": None,
            "providers": {},
            "available_providers": [],
        }
    payload = json.loads(status_path.read_text(encoding=ENCODING))
    if not isinstance(payload, dict):
        raise ValueError("Provider status must be a JSON object.")
    return payload


def provider_status_schema_errors(status: Mapping[str, Any]) -> list[str]:
    """Return schema validation errors for provider_status.json payloads."""
    errors: list[str] = []
    if status.get("schema_version") != PROVIDER_STATUS_VERSION:
        errors.append("schema_version must be 1")
    if "generated_at" not in status:
        errors.append("generated_at is required")
    providers = status.get("providers")
    if not isinstance(providers, Mapping):
        errors.append("providers must be an object")
        providers = {}
    available = status.get("available_providers")
    if not isinstance(available, list):
        errors.append("available_providers must be a list")
    for provider_name, provider_status in providers.items():
        if not isinstance(provider_status, Mapping):
            errors.append(f"{provider_name} status must be an object")
            continue
        for required_key in ("status", "available", "reason", "model"):
            if required_key not in provider_status:
                errors.append(f"{provider_name}.{required_key} is required")
    return errors


def available_provider_names(status: Mapping[str, Any]) -> list[str]:
    """Return provider names marked available in a status payload."""
    available = status.get("available_providers")
    if isinstance(available, list):
        return [str(provider_name) for provider_name in available]
    providers = status.get("providers", {})
    if not isinstance(providers, Mapping):
        return []
    return [
        str(provider_name)
        for provider_name, provider_status in providers.items()
        if isinstance(provider_status, Mapping) and bool(provider_status.get("available"))
    ]


def provider_class_name(provider_name: str) -> str:
    """Return the model provider class name for a provider key."""
    if provider_name == "openrouter":
        return "OpenRouterProvider"
    if provider_name == "gemini":
        return "GeminiProvider"
    if provider_name == "ollama":
        return "OllamaProvider"
    raise ValueError(f"Unsupported provider: {provider_name}")


def first_agent_for_provider(config: Mapping[str, Any], provider_name: str) -> str | None:
    """Return the first configured agent that uses a provider."""
    agents = config.get(KEY_AGENTS, {})
    if not isinstance(agents, Mapping):
        return None
    for agent_name, agent_config in agents.items():
        if isinstance(agent_config, Mapping) and agent_config.get(KEY_PROVIDER) == provider_name:
            return str(agent_name)
    return None


def _check_provider(
    provider_name: str,
    provider_config: Mapping[str, Any],
    config: Mapping[str, Any],
    check_health: bool,
) -> Dict[str, Any]:
    """Check one provider's configured credentials and optional health."""
    api_key_env = provider_config.get(KEY_API_KEY_ENV)
    if isinstance(api_key_env, str) and api_key_env and not os.environ.get(api_key_env):
        return _status_row(
            STATUS_SKIPPED,
            False,
            f"missing environment variable {api_key_env}",
            api_key_env,
            _provider_model(provider_name, provider_config, config),
            latency_ms=0,
            error=f"missing environment variable {api_key_env}",
        )

    if provider_name == "ollama" and not _ollama_is_configured(provider_config):
        return _status_row(
            STATUS_SKIPPED,
            False,
            f"set {OLLAMA_BASE_URL_ENV} to enable local Ollama",
            None,
            _provider_model(provider_name, provider_config, config),
            latency_ms=0,
            error="OLLAMA_BASE_URL is not set",
        )

    if not check_health:
        return _status_row(
            STATUS_AVAILABLE,
            True,
            "credentials configured",
            api_key_env if isinstance(api_key_env, str) else None,
            _provider_model(provider_name, provider_config, config),
            latency_ms=0,
            error=None,
        )

    start_time = time.perf_counter()
    health_ok, reason = _health_check(provider_name, provider_config)
    end_time = time.perf_counter()
    latency_ms = int((end_time - start_time) * 1000) if health_ok else 0

    return _status_row(
        STATUS_AVAILABLE if health_ok else STATUS_UNAVAILABLE,
        health_ok,
        reason,
        api_key_env if isinstance(api_key_env, str) else None,
        _provider_model(provider_name, provider_config, config),
        latency_ms=latency_ms,
        error=None if health_ok else reason,
    )


def _health_check(
    provider_name: str,
    provider_config: Mapping[str, Any],
) -> tuple[bool, str]:
    """Run a bounded health check for one provider."""
    try:
        if provider_name == "openrouter":
            response = requests.get(
                OPENROUTER_MODELS_URL,
                timeout=HEALTH_TIMEOUT_SECONDS,
            )
        elif provider_name == "gemini":
            api_key_env = provider_config.get(KEY_API_KEY_ENV)
            api_key = os.environ.get(str(api_key_env))
            response = requests.get(
                GEMINI_MODELS_URL_TEMPLATE.format(api_key=api_key),
                timeout=HEALTH_TIMEOUT_SECONDS,
            )
        elif provider_name == "ollama":
            response = requests.get(
                f"{_ollama_base_url(provider_config).rstrip('/')}{OLLAMA_TAGS_PATH}",
                timeout=HEALTH_TIMEOUT_SECONDS,
            )
        else:
            return False, "unsupported provider"
    except Exception as error:
        return False, f"health check failed: {error}"
    if response.status_code == 200:
        return True, "health check passed"
    return False, f"health check returned HTTP {response.status_code}"


def _status_row(
    status: str,
    available: bool,
    reason: str,
    api_key_env: str | None,
    model: str | None,
    latency_ms: int = 0,
    error: str | None = None,
) -> Dict[str, Any]:
    """Return one provider status row."""
    return {
        "status": status,
        "available": available,
        "reason": reason,
        "api_key_env": api_key_env,
        "model": model,
        "latency_ms": latency_ms,
        "error": error,
    }


def _provider_model(
    provider_name: str,
    provider_config: Mapping[str, Any],
    config: Mapping[str, Any],
) -> str | None:
    """Return the first agent model for a provider or provider default."""
    agents = config.get(KEY_AGENTS, {})
    if isinstance(agents, Mapping):
        for agent_config in agents.values():
            if (
                isinstance(agent_config, Mapping)
                and agent_config.get(KEY_PROVIDER) == provider_name
                and isinstance(agent_config.get(KEY_MODEL), str)
            ):
                return str(agent_config[KEY_MODEL])
    default_model = provider_config.get(KEY_DEFAULT_MODEL)
    return str(default_model) if isinstance(default_model, str) else None


def _ollama_is_configured(provider_config: Mapping[str, Any]) -> bool:
    """Return whether Ollama has an explicit local endpoint configured."""
    return bool(
        os.environ.get(OLLAMA_BASE_URL_ENV)
        or provider_config.get(KEY_BASE_URL)
        or provider_config.get(KEY_COMPLETION_URL)
    )


def _ollama_base_url(provider_config: Mapping[str, Any]) -> str:
    """Return Ollama base URL from env, config, or default."""
    env_base_url = os.environ.get(OLLAMA_BASE_URL_ENV)
    if env_base_url:
        return env_base_url
    configured_base_url = provider_config.get(KEY_BASE_URL)
    if isinstance(configured_base_url, str) and configured_base_url:
        return configured_base_url
    completion_url = provider_config.get(KEY_COMPLETION_URL)
    if isinstance(completion_url, str) and "/api/" in completion_url:
        return completion_url.split("/api/", 1)[0]
    return DEFAULT_OLLAMA_BASE_URL


def _parse_env_manually(env_path: Path) -> Dict[str, str]:
    """Parse simple KEY=VALUE lines from a .env file."""
    values: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding=ENCODING).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values
