# TASK_12: Live Provider Integration + Health Checks

## Problem
All tests use mocked providers. Real API calls have never been tested.
Transient failures have no retry logic. Dead providers silently fail.

## Pre-conditions
Read core/model_provider.py fully before writing anything.

## Deliverables

### 1. Update core/model_provider.py

Add to ModelProvider base class:
  health_check() -> bool
    Returns True if provider is reachable, False otherwise.
    Must complete within 5 seconds. Never raises.

Add to OpenRouterProvider:
  health_check(): GET https://openrouter.ai/api/v1/models
  Returns True if status 200, False otherwise.
  Timeout: 5 seconds.

Add to GeminiProvider:
  health_check(): lightweight models list call.

Add to OllamaProvider:
  health_check(): GET http://localhost:11434/api/tags
  Returns True if reachable, False otherwise.

### 2. core/retry.py

def with_retry(
  fn: Callable,
  max_attempts: int = 3,
  backoff_seconds: float = 1.0,
  exceptions: tuple = (Exception,)
) -> Any:
  Retries fn up to max_attempts times.
  Waits backoff_seconds * attempt between retries (exponential).
  Logs each retry attempt with attempt number and error.
  Raises last exception if all attempts fail.

### 3. Update all providers
  Wrap complete() and stream() calls with with_retry().
  Max 3 attempts, 1 second initial backoff.

### 4. core/provider_health.py

class ProviderHealthMonitor:
  __init__(providers: Dict[str, ModelProvider], check_interval: int = 300)
  start() → background thread calling health_check() every interval
  get_status() -> Dict[str, bool] (provider name → healthy)
  stop() → clean shutdown

### 5. Update projectos status CLI command
  Show provider health: Healthy / Unreachable for each provider.

### 6. tests/test_retry.py
  - test_succeeds_on_first_attempt
  - test_retries_on_failure_then_succeeds
  - test_raises_after_max_attempts
  - test_exponential_backoff_timing (mock time.sleep, verify calls)

### 7. tests/test_provider_health.py
  - test_health_check_returns_true_on_200 (mocked HTTP)
  - test_health_check_returns_false_on_timeout
  - test_health_check_returns_false_on_connection_error
  - test_monitor_updates_status_dict

## Constraints
- health_check() must NEVER raise — only return bool
- Retry logic must not be copy-pasted into each provider
- No new dependencies (use urllib or requests already in requirements)

## Verification
Full test suite. Write TASK_12_RESULT.md. Update tasks/README.md.
