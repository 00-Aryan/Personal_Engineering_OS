# TASK_38: Phase 5 Integration + Production Readiness Check

## Engineering Context

Phase 5 added full production observability:
  TASK_33: Distributed tracing
  TASK_34: Token budget management
  TASK_35: Cost tracking + provider economics
  TASK_36: Rate limiting + circuit breaker
  TASK_37: Alerting + anomaly detection

This final task integrates all observability components, verifies
end-to-end observability coverage, and performs a production
readiness assessment — a structured checklist used in engineering
orgs before shipping systems to production.

The production readiness check is not about perfection. It's about
known gaps: what works, what's missing, what the risks are, what
monitoring exists, what the runbook looks like.

## Pre-conditions
Run full test suite first. Report count before making any changes.
Read ALL files in core/observability/.
Read TASK_33 through TASK_37 result files for known gaps.

## Deliverables

### 1. scripts/observability_smoke.py

Full end-to-end observability pipeline smoke test.

Test Scenario A — Distributed Tracing:
  1. Initialize Tracer with TraceStore (tmp_path)
  2. Create a trace with 4 sequential spans:
     clone.handle → context_retrieval → code_review → quality_gate
  3. Each span: set tags, finish with OK status
  4. Assert: get_trace() returns all 4 spans
  5. Assert: spans sorted by started_at
  6. Assert: total duration computed correctly

Test Scenario B — Token Budget:
  1. Initialize TokenBudget with low limits (hard_limit=100)
  2. check_and_record with 50 token prompt → allowed
  3. check_and_record with 150 token prompt → blocked
  4. Assert: BudgetCheckResult.hard_limit_exceeded is True
  5. Assert: no API call made (mock provider not called)

Test Scenario C — Cost Tracking:
  1. Initialize CostTracker
  2. Record 5 calls: 3 to gemini (free), 2 to deepseek (paid)
  3. Assert: gemini calls show cost_usd == 0.0
  4. Assert: deepseek calls show cost_usd > 0.0
  5. Assert: get_daily_cost() totals are correct

Test Scenario D — Circuit Breaker:
  1. Initialize CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
  2. Trigger 3 consecutive failures
  3. Assert: state == OPEN
  4. Wait 1.1 seconds
  5. Trigger one success
  6. Assert: state == CLOSED

Test Scenario E — Alert Firing:
  1. Initialize AlertManager with test rules (low thresholds)
  2. Seed evaluation data with failing scores
  3. Run rule checks manually (not background thread)
  4. Assert: at least one alert fired
  5. Acknowledge it
  6. Assert: get_active_alerts() is empty

Print OBSERVABILITY SMOKE: PASSED or OBSERVABILITY SMOKE: FAILED.
Exit code 0 or 1.

### 2. docs/PRODUCTION_READINESS.md

Production readiness checklist. Fill each item with PASS, PARTIAL,
or FAIL based on actual system state.

# ProjectOS Production Readiness Assessment
Version: 0.3.0
Date: [current]
Assessed by: ProjectOS automated check + Aryan Kumar

## Reliability
- [ ] Retry logic on all external calls
- [ ] Circuit breakers for all providers
- [ ] Rate limiting enforced
- [ ] Graceful degradation when providers unavailable
- [ ] Process restarts recover queue state

## Observability
- [ ] All agent calls traced with timing
- [ ] Token usage tracked per agent per day
- [ ] Costs tracked in real currency
- [ ] Quality scores measured over time
- [ ] Alerts fire on threshold breaches
- [ ] Anomaly detection active

## Security
- [ ] No API keys in source code
- [ ] No API keys in log files
- [ ] File write safety policies enforced
- [ ] Consultation depth limits enforced
- [ ] No arbitrary code execution from agent output

## Quality
- [ ] LLM-as-judge evaluation for agent outputs
- [ ] Schema validation for structured outputs
- [ ] Regression detection with baselines
- [ ] Quality gate blocks low-quality writes
- [ ] Static analysis on generated code

## Operations
- [ ] Graceful shutdown on SIGINT/SIGTERM
- [ ] All state recoverable from .projectos_state/
- [ ] CLI provides access to all operational data
- [ ] Documentation covers all CLI commands
- [ ] CONTRIBUTING.md enables new contributors

Fill each item based on actual code review.
Add KNOWN GAPS section with honest assessment.
Add RISK REGISTER with top 3 risks and mitigations.

### 3. Update pyproject.toml
  Bump version: 0.3.0

### 4. Run all smoke tests in sequence
  uv run --no-sync python smoke_test.py --ci
  uv run --no-sync python scripts/evaluation_smoke.py
  uv run --no-sync python scripts/intelligence_smoke.py
  uv run --no-sync python scripts/observability_smoke.py
  All four must PASS before TASK_38 is marked DONE.

### 5. Final test run
  UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1
  uv run --no-sync pytest -v
  Report final total.

### 6. Write TASK_38_RESULT.md
  - Total files in core/observability/
  - Final test count (all phases combined)
  - All four smoke test results
  - Production readiness score (items passed / total)
  - Top 3 remaining risks
  - Phase 6 prerequisites
  - One paragraph: what ProjectOS is now vs what it was at v1

### 7. git tag
  After all tests pass:
  git add .
  git commit -m "feat: Phase 5 complete — production observability, v0.3.0"
  git tag v0.3.0
  git push origin main --tags

### 8. Update tasks/README.md
  Mark TASK_38 DONE.
  Add: Phase 6 — Agent Memory Distillation + Self-Improvement (PENDING)
