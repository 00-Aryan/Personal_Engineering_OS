# TASK_44: Phase 6 Hardening + Real-World Fixes

## Engineering Context

TASK_39-43 revealed real-world usage patterns and bugs.
This task is the hardening pass: fix everything that broke,
address the top risks from TASK_38 production readiness report,
and bring production readiness from 84.6% to >= 92%.

This is not a feature task. This is a quality task.
Every item here is a known gap from previous tasks.

## Pre-conditions
Read in order:
  TASK_38_RESULT.md (production readiness gaps)
  TASK_39_RESULT.md (provider setup issues)
  TASK_40_RESULT.md (dogfood bugs)
  TASK_41_RESULT.md (external project issues)
  TASK_42_RESULT.md (performance fixes applied)
  TASK_43_RESULT.md (config consolidation issues)

Compile complete list of unfixed issues before writing any code.

## Deliverables

### 1. Fix R1: Sandbox Escape via Test Execution

From TASK_38: TestAgent runs pytest on generated code in host context.

Minimal fix (no Docker required):
  In agents/test_agent.py, before running generated tests:
  1. Scan generated test file for dangerous patterns:
     - import os, subprocess, sys (flag but allow)
     - os.system, subprocess.run, eval, exec (block)
     - open() with write mode outside tests/ dir (block)
  2. If dangerous pattern found:
     Skip execution, write warning to review report.
     Set escalate=True in AgentResult.
     Log: "Test execution blocked: dangerous pattern detected"
  3. Add max_execution_time: 30 seconds (subprocess timeout)
  
  This is not perfect sandboxing but eliminates the obvious risks
  without requiring Docker.

### 2. Fix R2: Token Budget Loop Drain

From TASK_38: Infinite reasoning loops can drain daily budgets.

Fix in core/task_queue.py:
  Add per-event call count tracking.
  If same event_id triggers > 5 model calls → block further calls.
  Log: "Event [id] blocked: exceeded max model calls (5)"
  Emit ESCALATE with reason "potential_reasoning_loop"

Fix in core/clone_agent.py:
  Track events processed per minute.
  If > 20 events/minute → slow down: add 3 second delay between dispatches.
  Log warning: "High event rate detected, throttling"

### 3. Fix R3: Circuit Breaker Flapping

From TASK_38: Brief outages cause rapid state transitions.

Fix in core/observability/circuit_breaker.py:
  Add minimum_open_duration: float = 30.0
  Circuit cannot transition OPEN → HALF_OPEN until it has been
  OPEN for at least minimum_open_duration seconds.
  This prevents rapid open/close cycling on flickering providers.
  
  Add consecutive_success_threshold: int = 3
  HALF_OPEN → CLOSED only after 3 consecutive successes.
  Currently closes on first success — too eager.

### 4. Fix Graceful Shutdown (PARTIAL in TASK_38)

From TASK_38: Signal handling was PARTIAL.

In core/projectos.py:
  Register handlers for both SIGINT and SIGTERM:
    signal.signal(signal.SIGINT, self._shutdown_handler)
    signal.signal(signal.SIGTERM, self._shutdown_handler)
  
  _shutdown_handler():
    Set shutdown flag.
    Stop TriggerSystem.
    Stop TaskQueue (wait=True, timeout=10 seconds).
    Stop AlertManager.
    Flush all JSONL writers.
    Save PersistenceManager snapshot.
    Log: "ProjectOS shutdown complete"
    sys.exit(0)

### 5. Fix Retry Logic (PARTIAL in TASK_38)

From TASK_38: Retry was PARTIAL.

In core/retry.py:
  Add specific handling for HTTP status codes:
    429 (rate limit): wait Retry-After header value if present,
                      else wait 60 seconds, do not count as failure
    503 (unavailable): retry with exponential backoff
    401 (auth error): do NOT retry (wrong key — retrying is useless)
    
  Update with_retry() signature:
    add: no_retry_exceptions: tuple = () 
    If exception matches no_retry_exceptions → raise immediately

### 6. Re-run Production Readiness Assessment

Update docs/PRODUCTION_READINESS.md with fixes applied.
Re-score every checklist item.
Target: >= 92% (24/26 items PASS).

### 7. Final Phase 6 Verification

Run in sequence:
  python scripts/setup_providers.py --no-prompt
  UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest
  python smoke_test.py --ci
  python scripts/evaluation_smoke.py
  python scripts/intelligence_smoke.py
  python scripts/observability_smoke.py
  projectos config validate

All must pass or exit cleanly.

### 8. Commit and tag
  git add .
  git commit -m "feat: Phase 6 complete — real-world validation, v0.4.0"
  git tag v0.4.0

### 9. Write TASK_44_RESULT.md
  - Complete list of issues fixed (from all Phase 6 tasks)
  - Final test count
  - Final production readiness score
  - All smoke test results
  - What changed between v0.3.0 and v0.4.0 in one paragraph
  - Phase 7 prerequisites

## Constraints
- Do not introduce new features — fixes only
- Test count must not decrease
- All 4 smoke tests must still pass after every fix
- Production readiness score must improve

## Verification
Full test suite. All 4 smoke tests. Write TASK_44_RESULT.md.
Update tasks/README.md. Update tasks/PHASES.md.
