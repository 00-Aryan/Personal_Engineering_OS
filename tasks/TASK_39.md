# TASK_39: Real API Key Wiring + Live Provider Validation

## Engineering Context

Every test in ProjectOS uses mocked providers. The system has never
made a single real API call. This is the most important gap between
a well-engineered demo and a usable tool.

This task wires real credentials, validates each provider actually
responds, and makes ProjectOS runnable end-to-end for the first time.

The 3 risks flagged in TASK_38 production readiness report cannot be
assessed without real API calls. This task is the prerequisite for
every subsequent Phase 6 task.

## Pre-conditions
Read core/model_provider.py, core/observability/circuit_breaker.py,
core/observability/rate_limiter.py, config/models.yaml completely.
Do not modify any test files — mocked tests must continue to pass.

## Deliverables

### 1. scripts/setup_providers.py

Interactive setup script that:
1. Checks which environment variables are set:
   - GEMINI_API_KEY
   - OPENROUTER_API_KEY
   - OLLAMA_BASE_URL (default http://localhost:11434)
2. For each set variable → run health_check() on that provider
3. For each missing variable → print setup instructions, skip
4. Writes .env.example to project root with all variable names
5. Writes .projectos_state/provider_status.json:
   {provider_name: {available: bool, latency_ms: int, error: str|null}}
6. Prints summary table:
   Provider      Status        Latency    Model
   gemini        ✓ Available   234ms      gemini-1.5-flash
   openrouter    ✗ No API key  -          -
   ollama        ✗ Not running -          -
7. Exits 0 if at least one provider available, else exits 1

### 2. scripts/live_smoke.py

End-to-end live test using ONE real API call per available provider.
Not a benchmark. Just proof the integration works.

For each available provider (from provider_status.json):
  Send exactly this prompt:
  "Reply with exactly: PROJECTOS_LIVE_TEST_OK"
  
  Assert response contains "PROJECTOS_LIVE_TEST_OK"
  Record: latency_ms, tokens_used, provider_name
  Write to .projectos_state/live_smoke_results.json

Print:
  LIVE SMOKE PASSED: N providers verified
  or
  LIVE SMOKE FAILED: [provider] returned [response]

Exit 0 on all available providers passing.
Exit 1 on any available provider failing.

IMPORTANT: If NO providers are available (all keys missing):
  Print: "LIVE SMOKE SKIPPED: No providers configured"
  Exit 0 — this is not a failure, just unconfigured.

### 3. Update .gitignore
Add:
  .env
  .env.local
  .projectos_state/provider_status.json
  .projectos_state/live_smoke_results.json

These contain API keys or live data. Never commit.

### 4. Create .env.exampleProjectOS Provider Configuration
Copy this file to .env and fill in your keys
Never commit .env to git
Gemini (free tier: 1M tokens/day)
Get at: https://aistudio.google.com/apikey
GEMINI_API_KEY=your_gemini_api_key_here
OpenRouter (free models available)
Get at: https://openrouter.ai/keys
OPENROUTER_API_KEY=your_openrouter_api_key_here
Ollama (local, free, no key needed)
Install: https://ollama.ai
OLLAMA_BASE_URL=http://localhost:11434### 5. Update scripts/run_next.sh
Before running any task:
  Check if .projectos_state/provider_status.json exists.
  If not: run setup_providers.py first (non-interactive mode).
  Log which providers are available for this run.

### 6. Update README.md
Add section before Quick Start: "Provider Setup"
  Step 1: Copy .env.example to .env
  Step 2: Fill in at least one API key
  Step 3: python scripts/setup_providers.py
  Step 4: python scripts/live_smoke.py
  Step 5: projectos run

### 7. tests/test_provider_setup.py
Do NOT make real API calls in tests.
Mock subprocess and requests:
  - test_setup_script_runs_without_keys (all skipped)
  - test_env_example_file_exists
  - test_gitignore_excludes_env_files
  - test_provider_status_json_schema_valid
  - test_live_smoke_skipped_message_when_no_providers
  - test_live_smoke_exits_zero_when_skipped

## Constraints
- setup_providers.py must run non-interactively with --no-prompt flag
- live_smoke.py must complete in < 30 seconds per provider
- No API keys hardcoded anywhere — env vars only
- If python-dotenv not installed: read .env manually (stdlib only)
- .env file loading: try python-dotenv first, fall back to manual parse

## Verification
Full test suite must still pass (mocked tests unchanged).
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest
Write TASK_39_RESULT.md. Update tasks/README.md.
