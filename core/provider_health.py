"""Background provider health monitoring for ProjectOS."""

from __future__ import annotations

import logging
import threading
from typing import Dict

from core.model_provider import ModelProvider


DEFAULT_CHECK_INTERVAL_SECONDS = 300
LOGGER_NAME = "projectos.provider_health"
THREAD_NAME = "projectos-provider-health"


class ProviderHealthMonitor:
    """Poll configured model providers and expose their latest health status."""

    def __init__(
        self,
        providers: Dict[str, ModelProvider],
        check_interval: int = DEFAULT_CHECK_INTERVAL_SECONDS,
    ) -> None:
        """Initialize provider health state without starting the thread."""
        self.providers = dict(providers)
        self.check_interval = check_interval
        self._status: Dict[str, bool] = {
            provider_name: False for provider_name in self.providers
        }
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._logger = logging.getLogger(LOGGER_NAME)

    def start(self) -> None:
        """Start health checks in a daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=THREAD_NAME,
            daemon=True,
        )
        self._thread.start()

    def get_status(self) -> Dict[str, bool]:
        """Return a copy of the latest provider health statuses."""
        with self._lock:
            return dict(self._status)

    def stop(self) -> None:
        """Stop the background health monitor cleanly."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(float(self.check_interval), 0.1))

    def _run(self) -> None:
        """Poll providers until the monitor is stopped."""
        while not self._stop_event.is_set():
            self._check_once()
            self._stop_event.wait(self.check_interval)

    def _check_once(self) -> None:
        """Run one health check pass across all providers."""
        next_status: Dict[str, bool] = {}
        for provider_name, provider in self.providers.items():
            try:
                next_status[provider_name] = bool(provider.health_check())
            except Exception as error:
                self._logger.warning(
                    "Provider health check failed for %s: %s",
                    provider_name,
                    error,
                )
                next_status[provider_name] = False
        with self._lock:
            self._status.update(next_status)


__all__ = ["ProviderHealthMonitor"]
