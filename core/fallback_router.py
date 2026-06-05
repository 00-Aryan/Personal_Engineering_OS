"""Fallback routing for ProjectOS model providers."""

from __future__ import annotations

import logging
from typing import Iterator, List, Mapping

from core.model_provider import ModelProvider
from core.provider_health import ProviderHealthMonitor


LOGGER_NAME = "projectos.fallback_router"
ERROR_ALL_PROVIDERS_FAILED = "All providers failed; attempted: {attempted}"
LOG_PROVIDER_USED = "FallbackRouter used provider %s"
LOG_PROVIDER_FAILED = "FallbackRouter provider %s failed: %s"


class FallbackRouter(ModelProvider):
    """ModelProvider that tries a primary provider, then configured fallbacks."""

    provider_key = "fallback_router"

    def __init__(
        self,
        primary: ModelProvider,
        fallbacks: List[ModelProvider],
        health_monitor: ProviderHealthMonitor,
    ) -> None:
        """Initialize the router with ordered providers and health state."""
        self.primary = primary
        self.fallbacks = list(fallbacks)
        self.health_monitor = health_monitor
        self._logger = logging.getLogger(LOGGER_NAME)

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return completion text from the first healthy successful provider."""
        attempted: List[str] = []
        for provider in self._providers():
            provider_name = self._provider_name(provider)
            attempted.append(provider_name)
            if not self._is_provider_healthy(provider_name):
                continue
            try:
                response = provider.complete(prompt, system_prompt, max_tokens)
            except Exception as error:
                self._logger.warning(LOG_PROVIDER_FAILED, provider_name, error)
                continue
            self._logger.info(LOG_PROVIDER_USED, provider_name)
            return response
        raise RuntimeError(
            ERROR_ALL_PROVIDERS_FAILED.format(attempted=", ".join(attempted))
        )

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield stream chunks from the first healthy successful provider."""
        attempted: List[str] = []
        for provider in self._providers():
            provider_name = self._provider_name(provider)
            attempted.append(provider_name)
            if not self._is_provider_healthy(provider_name):
                continue
            try:
                chunks = list(provider.stream(prompt, system_prompt))
            except Exception as error:
                self._logger.warning(LOG_PROVIDER_FAILED, provider_name, error)
                continue
            self._logger.info(LOG_PROVIDER_USED, provider_name)
            return iter(chunks)
        raise RuntimeError(
            ERROR_ALL_PROVIDERS_FAILED.format(attempted=", ".join(attempted))
        )

    def get_active_provider(self) -> str:
        """Return the first currently healthy provider name in fallback order."""
        for provider in self._providers():
            provider_name = self._provider_name(provider)
            if self._is_provider_healthy(provider_name):
                return provider_name
        return self._provider_name(self.primary)

    def get_model_name(self) -> str:
        """Return the active provider model name when available."""
        for provider in self._providers():
            provider_name = self._provider_name(provider)
            if self._is_provider_healthy(provider_name):
                return provider.get_model_name()
        return self.primary.get_model_name()

    def health_check(self) -> bool:
        """Return whether any routed provider is currently healthy."""
        return any(
            self._is_provider_healthy(self._provider_name(provider))
            for provider in self._providers()
        )

    def _providers(self) -> List[ModelProvider]:
        """Return providers in primary-first fallback order."""
        return [self.primary, *self.fallbacks]

    def _provider_name(self, provider: ModelProvider) -> str:
        """Return a stable provider name for health lookup and logging."""
        explicit_name = getattr(provider, "name", None)
        if isinstance(explicit_name, str) and explicit_name:
            return explicit_name
        provider_key = getattr(provider, "provider_key", None)
        if isinstance(provider_key, str) and provider_key:
            return provider_key
        try:
            return provider.get_model_name()
        except Exception:
            return provider.__class__.__name__

    def _is_provider_healthy(self, provider_name: str) -> bool:
        """Return health state, treating missing health records as usable."""
        status = self.health_monitor.get_status()
        if not isinstance(status, Mapping):
            return True
        return bool(status.get(provider_name, True))


__all__ = ["FallbackRouter"]
