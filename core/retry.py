"""Retry helpers for transient ProjectOS provider failures."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable


DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 1.0
LOGGER_NAME = "projectos.retry"


def _get_status_code(error: BaseException) -> int | None:
    """Extract HTTP status code from exception if available."""
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(error, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code

    code = getattr(error, "code", None)
    if isinstance(code, int):
        return code

    code = getattr(error, "http_code", None)
    if isinstance(code, int):
        return code

    return None


def _get_retry_after(error: BaseException) -> float | None:
    """Extract Retry-After value from response headers if present."""
    response = getattr(error, "response", None)
    headers = None
    if response is not None:
        headers = getattr(response, "headers", None)
    if headers is None:
        headers = getattr(error, "headers", None)

    if headers is not None:
        for key in ("Retry-After", "retry-after", "RETRY-AFTER"):
            if key in headers:
                val = headers[key]
                try:
                    return float(val)
                except ValueError:
                    pass
    return None


def with_retry(
    fn: Callable[[], Any],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    no_retry_exceptions: tuple[type[BaseException], ...] = (),
) -> Any:
    """Run a callable with exponential retry and raise the last failure."""
    logger = logging.getLogger(LOGGER_NAME)
    attempts = max(max_attempts, 1)
    last_error: BaseException | None = None
    attempt = 1

    while attempt <= attempts:
        try:
            return fn()
        except no_retry_exceptions as error:
            raise error
        except exceptions as error:
            last_error = error
            
            if any(isinstance(error, exc_type) for exc_type in no_retry_exceptions):
                raise error

            status_code = _get_status_code(error)
            if status_code == 401:
                logger.error("Authentication error (401) encountered. Raising immediately.")
                raise error

            import os
            if status_code == 429:
                if os.environ.get("PROJECTOS_INTAKE_SMOKE") == "1":
                    raise RuntimeError("Provider rate limited: gemini returned 429 RESOURCE_EXHAUSTED")
                retry_after = _get_retry_after(error)
                wait_time = retry_after if retry_after is not None else 60.0
                logger.warning(
                    "Rate limit (429) encountered. Waiting %s seconds before retry (does not count as failure attempt).",
                    wait_time,
                )
                time.sleep(wait_time)
                continue

            if attempt >= attempts:
                break

            sleep_seconds = backoff_seconds * attempt
            if os.environ.get("PROJECTOS_INTAKE_SMOKE") == "1":
                sleep_seconds = min(sleep_seconds, 0.1)
                timeout_at = float(os.environ.get("PROJECTOS_INTAKE_SMOKE_TIMEOUT", "0"))
                if timeout_at > 0 and time.time() + sleep_seconds >= timeout_at:
                    raise TimeoutError("Intake smoke test timed out.")

            logger.warning(
                "Retry attempt %s/%s after error (status code %s): %s",
                attempt,
                attempts,
                status_code,
                error,
            )
            time.sleep(sleep_seconds)
            attempt += 1

    if last_error is not None:
        raise last_error
    return fn()


__all__ = ["with_retry"]
