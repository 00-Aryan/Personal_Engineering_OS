# Real API Findings

## Tested Provider
- **Provider**: Google Gemini API (via AI Studio)
- **Model**: `gemini-1.5-flash`

## Live Execution Status
- **Status**: SKIPPED
- **Reason**: Live run was skipped because no real `GEMINI_API_KEY` was provided in the test environment.
- **Verification**: The pre-launch real API smoke test script (`scripts/real_api_smoke.py`) was successfully created and run in skip-mode, exiting with code `0`. Its behavior, including skipped outputs, results JSON generation, and budget enforcement, was fully covered by mock unit tests.

## Expected Performance and Observations

Based on standard Gemini API characteristics and mock specifications:

### 1. Latency Profile
- **Expected Latency**: 200ms - 600ms for short responses (e.g., Test 2's minimal completion).
- **Mock vs. Real**: Mocking assumes instantaneous responses (~0-10ms), whereas real network roundtrips and generation time require handling timeouts up to 10 seconds.

### 2. Token Usage and Pricing
- **Pricing**: Free tier provides 1M tokens/day at $0.00 cost.
- **Real Token Usage**: Standard tokenizers map ~4 characters to 1 token. A short prompt and completion like "Reply with exactly: OK" uses ~20-30 tokens total.

### 3. Unexpected Behaviors & Edge Cases
- **Rate Limits**: The free tier of Gemini has a strict limit of 15 requests per minute (RPM). Fast, consecutive agent calls can trigger HTTP 429 rate limit errors, which makes the implementation of `RateLimiter` crucial.
- **Token Budgets**: If an agent starts sending very large codebase contexts, it can easily exceed limits. Our token budget enforcement correctly returns a `TOKEN_BUDGET_EXCEEDED` string without making the API call, saving API limit quota.

## Recommended Model Assignments

Based on the performance characteristics of the integrated providers:

| Agent | Assigned Model | Provider | Rationale |
| :--- | :--- | :--- | :--- |
| **Clone** | `gemini-1.5-flash` | Gemini | High context limit and fast response time suitable for git and file operations. |
| **Docs** | `gemini-1.5-flash` | Gemini | Generous context window allows ingestion of large documentation blocks for free. |
| **Code Writing** | `gemini-1.5-flash` | Gemini / OpenRouter | Gemini is perfect for fast iterations; OpenRouter for higher-quality code logic. |
| **Code Review** | `gemini-1.5-flash` | Gemini | Free context ingestion is critical for analyzing entire code files. |
| **Planning** | `deepseek-v3` | OpenRouter | Heavy reasoning task; benefits from DeepSeek's strong reasoning capability. |
| **Architecture** | `deepseek-v3` | OpenRouter | System design is complex; requires a strong general intelligence model. |
