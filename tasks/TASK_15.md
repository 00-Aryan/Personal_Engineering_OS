# TASK_15: Ollama Local Fallback + Model Benchmark

## Purpose
Guarantee ₹0 cost operation. Automatically fall back to Ollama
when cloud providers fail health checks. Add benchmark runner
to determine which free model performs best per agent task type.

## Pre-conditions
Read core/model_provider.py, core/provider_health.py, 
core/retry.py, config/models.yaml fully.

## Deliverables

### 1. Update providers/ollama_provider.py
  Full implementation of OllamaProvider:
  complete(): POST http://localhost:11434/api/generate
    payload: {model, prompt, stream: false}
    Returns response.response field.
  stream(): POST with stream:true, yield chunks.
  get_model_name(): reads from config.
  health_check(): GET /api/tags, returns True if reachable.

### 2. core/fallback_router.py

class FallbackRouter:
  __init__(
    primary: ModelProvider,
    fallbacks: List[ModelProvider],
    health_monitor: ProviderHealthMonitor
  )
  
  complete(prompt, system_prompt, max_tokens) -> str
    Try primary first.
    If primary unhealthy or raises → try fallbacks in order.
    Log which provider was used for every call.
    If all fail → raise with clear message listing all attempted.
  
  get_active_provider() -> str (name of currently healthy provider)

### 3. Update config/models.yaml
  Add fallback section:
  fallback_chain:
    planning: [deepseek-v3, ollama-deepseek-r1, ollama-llama3]
    code_writing: [openrouter-free, ollama-codellama, ollama-llama3]
    code_review: [openrouter-free, ollama-codellama]
    clone: [gemini-flash, ollama-llama3]
    test: [openrouter-free, ollama-codellama]
    docs: [gemini-flash, ollama-llama3]
    architecture: [deepseek-v3, ollama-deepseek-r1]

### 4. scripts/benchmark.py
  Benchmarks each agent's model assignments.
  
  Tasks to benchmark (hardcoded, no API calls in tests):
  - Planning: "Add user authentication to a Flask app"
  - Code Review: review core/base_agent.py
  - Code Writing: "Write a function to parse JSON safely"
  
  For each model in config:
    Run 3 completions, measure:
    - latency_ms (average)
    - output_length (tokens approx: len/4)
    - success_rate (did it return valid output)
  
  Write results to docs/benchmark_results.md as table:
  | Agent | Model | Latency ms | Output Len | Success Rate |
  
  Print summary: recommended model per agent based on results.
  
  Note: benchmark.py requires real API keys. Skip gracefully if 
  provider returns auth error — log "skipped: no API key" and continue.

### 5. tests/test_fallback_router.py
  - test_uses_primary_when_healthy (mocked)
  - test_falls_back_to_first_fallback_on_primary_failure
  - test_falls_back_to_second_if_first_also_fails
  - test_raises_if_all_providers_fail
  - test_logs_which_provider_was_used

### 6. tests/test_ollama_provider.py
  - test_complete_sends_correct_payload (mocked HTTP)
  - test_complete_returns_response_field
  - test_health_check_true_on_200
  - test_health_check_false_on_connection_error

## Constraints
- FallbackRouter must implement ModelProvider interface
- benchmark.py must never be imported by production code
- Ollama base URL configurable via OLLAMA_BASE_URL env var
- Default: http://localhost:11434

## Verification
Full test suite. Write TASK_15_RESULT.md. Update tasks/README.md.
