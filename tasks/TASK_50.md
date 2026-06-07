# TASK_50: Pre-Launch API Key Validation + Real Smoke

## Engineering Context

ProjectOS has 381 passing tests. All use mocked providers.
Before a public launch, we must verify the system works with at
least one real API key producing real model output.

If we launch without this verification and users report that
basic functionality is broken, the GitHub repo gets abandoned.
This task prevents that by doing what no previous task has done:
making real API calls and verifying real outputs.

## Pre-conditions
Read scripts/live_smoke.py, scripts/setup_providers.py.
Read core/model_provider.py completely.
Read AGENTS.md.

## Deliverables

### 1. Set up real Gemini API key

Aryan must do this step manually before running TASK_50:
  1. Go to https://aistudio.google.com/apikey
  2. Create a free API key
  3. Add to .env: GEMINI_API_KEY=your_key_here
  4. Run: python scripts/setup_providers.py --no-prompt
  5. Verify output shows: gemini ✓ Available

If key is already set, skip to deliverable 2.

### 2. scripts/real_api_smoke.py

Tests real API integration with minimal token usage.
Each test uses the shortest possible prompt.

Test 1 — Provider connectivity:
  GeminiProvider.health_check() → must return True
  Log: latency_ms

Test 2 — Minimal completion:
  GeminiProvider.complete(
    prompt="Reply: OK",
    system_prompt="Reply with exactly: OK",
    max_tokens=5
  )
  Assert: response contains "OK"
  Log: tokens_used, latency_ms, cost_usd

Test 3 — Token budget enforcement:
  Set hard limit to 10 tokens for test agent.
  Try to complete with 50 token prompt.
  Assert: returns "TOKEN_BUDGET_EXCEEDED" string.
  Assert: no real API call made.

Test 4 — Circuit breaker with real provider:
  Run 1 successful completion.
  Assert: circuit state is CLOSED.
  Assert: no failures recorded.

Test 5 — Rate limiter non-blocking:
  Acquire 1 token from gemini rate limiter.
  Assert: acquire returns True immediately.
  Assert: no delay for first request.

Write to .projectos_state/real_api_smoke_results.json:
  {timestamp, provider, tests_passed, tests_failed,
   total_tokens_used, total_cost_usd, latency_ms_avg}

Print:
  REAL API SMOKE: PASSED (N/5 tests)
  Tokens used: N (estimated cost: $X.XX)
  or
  REAL API SMOKE: FAILED: [reason]

Exit 0 on all 5 tests passing.
Exit 1 on any failure.
Exit 0 with "SKIPPED" message if no API key available.

### 3. Update .github/workflows/ci.yml

Add optional real-api job:
  real-api:
    if: secrets.GEMINI_API_KEY != ''
    runs-on: ubuntu-latest
    steps:
      - checkout
      - setup Python 3.12
      - install uv
      - uv pip install -e ".[dev]"
      - env: GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: python scripts/real_api_smoke.py
    
    This job only runs when the secret is configured.
    Never blocks the main CI pipeline.

### 4. Document real API findings

Write docs/real_api_findings.md:
  - Which provider was tested
  - Real latency observed
  - Real token usage per call
  - Any unexpected behavior vs mock assumptions
  - Recommended model assignments based on real performance

### 5. Fix any bugs found during real API testing

Read real_api_smoke_results.json after running.
Fix any failures found.
Bugs found during real testing take priority over all other work.

### 6. tests/test_real_api_smoke.py
No real API calls in tests:
  - test_smoke_skips_cleanly_without_api_key
  - test_results_json_schema_valid
  - test_exit_zero_on_skip
  - test_budget_enforcement_without_api_call

## Constraints
- script must exit 0 when no API key (SKIPPED not FAILED)
- Total real token usage must be < 500 tokens
- Total real cost must be < $0.01
- real_api_smoke_results.json added to .gitignore
- Never commit API keys

## Verification
python scripts/real_api_smoke.py
Document results honestly in TASK_50_RESULT.md.
Write TASK_50_RESULT.md. Update tasks/README.md.
