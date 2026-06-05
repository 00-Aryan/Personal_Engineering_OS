"""Retry helpers for transient ProjectOS provider failures."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable


DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 1.0
LOGGER_NAME = "projectos.retry"


def with_retry(
    fn: Callable[[], Any],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Any:
    """Run a callable with exponential retry and raise the last failure."""
    logger = logging.getLogger(LOGGER_NAME)
    attempts = max(max_attempts, 1)
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except exceptions as error:
            last_error = error
            if attempt >= attempts:
                break
            sleep_seconds = backoff_seconds * attempt
            logger.warning(
                "Retry attempt %s/%s after error: %s",
                attempt,
                attempts,
                error,
            )
            time.sleep(sleep_seconds)

    if last_error is not None:
        raise last_error
    return fn()


__all__ = ["with_retry"]
