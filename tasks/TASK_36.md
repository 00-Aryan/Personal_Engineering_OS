# TASK_36: Rate Limiter + Circuit Breaker

## Engineering Context

TASK_12 added health checks and retry logic. That handles transient
failures. This task handles two different failure modes:

1. Rate limiting — you're sending requests too fast for the provider.
   The API returns 429. Current behavior: retry 3 times and fail.
   Correct behavior: back off intelligently, queue requests,
   resume when rate limit window resets.

2. Circuit breaker — a provider is consistently failing (not
   rate-limited, actually broken). Current behavior: retry 3 times
   per call, every call. This means 10 agent calls × 3 retries =
   30 failed API calls before anyone notices.
   Correct behavior: after N consecutive failures, open the circuit.
   Route to fallback. Periodically probe if provider recovered.

These are standard reliability patterns in production distributed
systems. They're especially critical for free-tier APIs that have
unpredictable availability.

## Pre-conditions
Read core/retry.py, core/model_provider.py, 
core/intelligence/fallback_router.py from TASK_15.
Read core/observability/tracer.py from TASK_33.

## Deliverables

### 1. core/observability/rate_limiter.py

class RateLimitStrategy(Enum):
  TOKEN_BUCKET = "token_bucket"
  SLIDING_WINDOW = "sliding_window"

class RateLimiter:
  """
  Token bucket rate limiter.
  
  Token bucket algorithm:
  - Bucket starts full (capacity tokens)
  - Each request consumes tokens proportional to estimated size
  - Tokens refill at rate tokens_per_second
  - If insufficient tokens: wait until enough refill, then proceed
  
  This smooths out bursts without dropping requests.
  """
  
  __init__(
    capacity: int,
    tokens_per_second: float,
    provider_name: str
  )
  
  acquire(tokens: int = 1, timeout: float = 30.0) -> bool:
    Block until tokens available or timeout.
    Returns True if acquired, False if timed out.
    Thread-safe via threading.Lock.
  
  try_acquire(tokens: int = 1) -> bool:
    Non-blocking. Returns False immediately if insufficient tokens.
  
  get_wait_time(tokens: int) -> float:
    Returns estimated seconds until tokens available.
    Returns 0.0 if immediately available.

class ProviderRateLimits:
  """Pre-configured rate limits per provider."""
  
  LIMITS = {
    "gemini": RateLimiter(capacity=1500, tokens_per_second=25.0,
                          provider_name="gemini"),
    "openrouter": RateLimiter(capacity=200, tokens_per_second=3.3,
                              provider_name="openrouter"),
    "ollama": RateLimiter(capacity=10000, tokens_per_second=100.0,
                          provider_name="ollama"),
    "default": RateLimiter(capacity=100, tokens_per_second=2.0,
                           provider_name="default")
  }
  
  @classmethod
  get(cls, provider_name: str) -> RateLimiter:
    Returns limiter for provider or default.

### 2. core/observability/circuit_breaker.py

class CircuitState(Enum):
  CLOSED = "closed"    (normal — requests pass through)
  OPEN = "open"        (failing — requests blocked immediately)
  HALF_OPEN = "half_open"  (testing — one probe request allowed)

@dataclass
class CircuitBreakerStats:
  provider_name: str
  state: CircuitState
  failure_count: int
  success_count: int
  last_failure_at: Optional[datetime]
  last_success_at: Optional[datetime]
  opened_at: Optional[datetime]
  total_requests: int
  blocked_requests: int

class CircuitBreaker:
  """
  Circuit breaker for model provider calls.
  
  State transitions:
  CLOSED → OPEN: after failure_threshold consecutive failures
  OPEN → HALF_OPEN: after recovery_timeout seconds
  HALF_OPEN → CLOSED: probe request succeeds
  HALF_OPEN → OPEN: probe request fails
  
  All state transitions logged to circuit_breaker.jsonl.
  """
  
  __init__(
    provider_name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    state_dir: Optional[Path] = None
  )
  
  call(fn: Callable, *args, **kwargs) -> Any:
    If OPEN and not recovery_timeout elapsed → raise CircuitOpenError
    If OPEN and recovery_timeout elapsed → set HALF_OPEN, allow one call
    Execute fn(*args, **kwargs)
    On success: record_success()
    On failure: record_failure()
    Return result or raise exception.
  
  record_success() -> None:
    If HALF_OPEN → transition to CLOSED, log recovery
    Increment success_count, reset failure_count
  
  record_failure() -> None:
    Increment failure_count
    If failure_count >= failure_threshold → transition to OPEN
    Log failure with timestamp
  
  get_stats() -> CircuitBreakerStats
  
  reset() -> None:
    Force back to CLOSED state. For manual recovery.

class CircuitOpenError(Exception):
  """Raised when circuit is OPEN and request is blocked."""
  pass

### 3. Update core/model_provider.py
  Each provider's complete() method:
  
  Add rate_limiter: Optional[RateLimiter] = None
  Add circuit_breaker: Optional[CircuitBreaker] = None
  
  In complete():
    1. If rate_limiter: acquire(tokens=estimate_tokens(prompt))
       If not acquired (timeout): log warning, return rate limit error str
    2. If circuit_breaker: wrap actual API call in circuit_breaker.call()
       On CircuitOpenError: log, return circuit open error str,
       trigger fallback router if available
    3. Existing retry logic still applies within circuit_breaker.call()

### 4. Update core/projectos.py
  Initialize ProviderRateLimits.
  Initialize one CircuitBreaker per provider.
  Pass to model providers.
  
  On status CLI command: show circuit breaker states.

### 5. New CLI command: projectos reliability
  projectos reliability status
    Shows rate limiter and circuit breaker state per provider.
    Format:
    Provider      Circuit    Failures  Last Failure     Rate (req/s)
    gemini        ● CLOSED   0         never            25.0
    openrouter    ● CLOSED   2         2m ago           3.3
    ollama        ○ OPEN     7         30s ago          100.0
  
  projectos reliability reset --provider ollama
    Force circuit breaker reset for a provider.

### 6. tests/test_observability/test_rate_limiter.py
  - test_acquire_succeeds_when_tokens_available
  - test_acquire_blocks_until_tokens_refill
  - test_try_acquire_returns_false_immediately
  - test_get_wait_time_accurate
  - test_thread_safety_concurrent_acquires

### 7. tests/test_observability/test_circuit_breaker.py
  - test_closed_state_allows_requests
  - test_opens_after_threshold_failures
  - test_open_state_raises_circuit_open_error
  - test_transitions_to_half_open_after_timeout
  - test_half_open_closes_on_success
  - test_half_open_reopens_on_failure
  - test_reset_returns_to_closed
  - test_stats_accurate_throughout_lifecycle

## Constraints
- RateLimiter.acquire() must be thread-safe
- CircuitBreaker.call() must be thread-safe
- Circuit state must persist across process restarts
  (save to circuit_state.json atomically)
- CircuitOpenError must include provider name and recovery_timeout
- Rate limiter never drops requests — only delays them (up to timeout)

## Verification
Full test suite. Write TASK_36_RESULT.md. Update tasks/README.md.
