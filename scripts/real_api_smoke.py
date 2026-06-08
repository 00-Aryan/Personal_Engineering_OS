#!/usr/bin/env python3
"""Run pre-launch real API smoke tests for ProjectOS."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Hard wall clock timeout - script dies after 30 seconds
def _hard_timeout(signum: Any, frame: Any) -> None:
    print("REAL API SMOKE: FAILED: Wall clock timeout reached")
    sys.exit(1)

from scripts.provider_setup import CONFIG_PATH, ENV_PATH, load_env_file, load_model_config
from core.model_provider import GeminiProvider
from core.observability.token_budget import TokenBudget
from core.observability.cost_tracker import CostTracker
from core.observability.circuit_breaker import CircuitBreaker, CircuitState
from core.observability.rate_limiter import ProviderRateLimits

RESULTS_PATH = Path(".projectos_state/real_api_smoke_results.json")

def main() -> int:
    """Run real API smoke checks for Gemini provider."""
    load_env_file(ENV_PATH)
    config = load_model_config(CONFIG_PATH)

    api_key = os.environ.get("GEMINI_API_KEY")
    # If key is missing, empty, or default placeholder, skip the tests cleanly
    if not api_key or api_key == "your_gemini_api_key_here":
        print("REAL API SMOKE: SKIPPED (No API key available)")
        _write_results(
            tests_passed=0,
            tests_failed=0,
            total_tokens=0,
            total_cost=0.0,
            avg_latency=0,
            status="SKIPPED"
        )
        return 0

    tb = TokenBudget(Path(".projectos_state"))
    ct = CostTracker(Path(".projectos_state"))

    # Instantiate GeminiProvider using clone agent config
    try:
        provider = GeminiProvider(
            agent_name="clone",
            config_path=CONFIG_PATH,
            token_budget=tb,
            cost_tracker=ct
        )
    except Exception as e:
        print(f"REAL API SMOKE: FAILED: Could not initialize provider - {e}")
        _write_results(0, 5, 0, 0.0, 0, "FAILED")
        return 1

    tests_passed = 0
    t1_latency = 0
    t2_latency = 0
    t4_latency = 0
    tokens_used_t2 = 0
    cost_usd_t2 = 0.0
    tokens_used_t4 = 0
    cost_usd_t4 = 0.0

    # Test 1 — Provider connectivity
    try:
        print("Running Test 1 - Provider connectivity...")
        t1_start = time.perf_counter()
        health_ok = provider.health_check()
        t1_end = time.perf_counter()
        t1_latency = int((t1_end - t1_start) * 1000)

        if not health_ok:
            raise RuntimeError("GeminiProvider.health_check() returned False")
        tests_passed += 1
        print(f"Test 1 passed. Latency: {t1_latency}ms")
    except Exception as e:
        print(f"Test 1 failed: {e}")
        _write_results(tests_passed, 5 - tests_passed, 0, 0.0, t1_latency, "FAILED")
        print(f"REAL API SMOKE: FAILED: Test 1 failed - {e}")
        return 1

    # Test 2 — Minimal completion
    try:
        print("Running Test 2 - Minimal completion...")
        t2_start = time.perf_counter()
        response = provider.complete(
            prompt="Reply: OK",
            system_prompt="Reply with exactly: OK",
            max_tokens=5
        )
        t2_end = time.perf_counter()
        t2_latency = int((t2_end - t2_start) * 1000)

        if "OK" not in response:
            raise RuntimeError(f"Response does not contain 'OK'. Got: '{response}'")

        # Read tokens and cost from the latest records
        if tb.log_path.exists():
            try:
                with open(tb.log_path, "r", encoding="utf-8") as f:
                    lines = list(f)
                    if lines:
                        tb_data = json.loads(lines[-1])
                        if tb_data.get("agent_name") == "clone":
                            tokens_used_t2 = tb_data.get("total_tokens", 0)
            except Exception:
                pass
        if not tokens_used_t2:
            tokens_used_t2 = (len("Reply: OK" + "Reply with exactly: OK") + len(response)) // 4

        if ct.log_path.exists():
            try:
                with open(ct.log_path, "r", encoding="utf-8") as f:
                    lines = list(f)
                    if lines:
                        ct_data = json.loads(lines[-1])
                        if ct_data.get("agent_name") == "clone":
                            cost_usd_t2 = ct_data.get("cost_usd", 0.0)
            except Exception:
                pass

        tests_passed += 1
        print(f"Test 2 passed. Response: '{response}', Tokens: {tokens_used_t2}, Cost: ${cost_usd_t2:.6f}, Latency: {t2_latency}ms")
    except Exception as e:
        print(f"Test 2 failed: {e}")
        _write_results(tests_passed, 5 - tests_passed, tokens_used_t2, cost_usd_t2, int((t1_latency + t2_latency)/2), "FAILED")
        print(f"REAL API SMOKE: FAILED: Test 2 failed - {e}")
        return 1

    # Test 3 — Token budget enforcement
    try:
        print("Running Test 3 - Token budget enforcement...")
        custom_budgets = {
            "test_agent": {
                "hard_limit_per_call": 10
            }
        }
        tb_test = TokenBudget(state_dir=Path(".projectos_state"), budgets=custom_budgets)

        original_complete_once = provider._complete_once
        complete_once_called = False

        def mock_complete_once(*args: Any, **kwargs: Any) -> str:
            nonlocal complete_once_called
            complete_once_called = True
            return "OK"

        provider._complete_once = mock_complete_once

        prompt_50_tokens = "A" * 200
        response_t3 = provider.complete(
            prompt=prompt_50_tokens,
            system_prompt="",
            max_tokens=5,
            agent_name="test_agent",
            token_budget=tb_test
        )

        provider._complete_once = original_complete_once

        if "TOKEN_BUDGET_EXCEEDED" not in response_t3:
            raise RuntimeError(f"Expected response containing 'TOKEN_BUDGET_EXCEEDED', got: '{response_t3}'")
        if complete_once_called:
            raise RuntimeError("Real API call was made despite budget limit exceeded")

        tests_passed += 1
        print("Test 3 passed.")
    except Exception as e:
        print(f"Test 3 failed: {e}")
        _write_results(tests_passed, 5 - tests_passed, tokens_used_t2, cost_usd_t2, int((t1_latency + t2_latency)/2), "FAILED")
        print(f"REAL API SMOKE: FAILED: Test 3 failed - {e}")
        return 1

    # Test 4 — Circuit breaker with real provider
    try:
        print("Running Test 4 - Circuit breaker with real provider...")
        cb = CircuitBreaker("gemini", state_dir=Path(".projectos_state"))
        cb.reset()

        t4_start = time.perf_counter()
        response_t4 = provider.complete(
            prompt="Reply: OK",
            system_prompt="Reply with exactly: OK",
            max_tokens=5,
            circuit_breaker=cb
        )
        t4_end = time.perf_counter()
        t4_latency = int((t4_end - t4_start) * 1000)

        if "OK" not in response_t4:
            raise RuntimeError(f"Response does not contain 'OK'. Got: '{response_t4}'")

        stats = cb.get_stats()
        if stats.state != CircuitState.CLOSED:
            raise RuntimeError(f"Circuit breaker state is {stats.state}, expected CLOSED")
        if stats.failure_count != 0:
            raise RuntimeError(f"Circuit breaker recorded {stats.failure_count} failures, expected 0")

        # Read tokens and cost from the latest records
        if tb.log_path.exists():
            try:
                with open(tb.log_path, "r", encoding="utf-8") as f:
                    lines = list(f)
                    if lines:
                        tb_data = json.loads(lines[-1])
                        if tb_data.get("agent_name") == "clone":
                            tokens_used_t4 = tb_data.get("total_tokens", 0)
            except Exception:
                pass
        if not tokens_used_t4:
            tokens_used_t4 = (len("Reply: OK" + "Reply with exactly: OK") + len(response_t4)) // 4

        if ct.log_path.exists():
            try:
                with open(ct.log_path, "r", encoding="utf-8") as f:
                    lines = list(f)
                    if lines:
                        ct_data = json.loads(lines[-1])
                        if ct_data.get("agent_name") == "clone":
                            cost_usd_t4 = ct_data.get("cost_usd", 0.0)
            except Exception:
                pass

        tests_passed += 1
        print(f"Test 4 passed. Response: '{response_t4}', Latency: {t4_latency}ms")
    except Exception as e:
        print(f"Test 4 failed: {e}")
        _write_results(
            tests_passed,
            5 - tests_passed,
            tokens_used_t2 + tokens_used_t4,
            cost_usd_t2 + cost_usd_t4,
            int((t1_latency + t2_latency + t4_latency)/3),
            "FAILED"
        )
        print(f"REAL API SMOKE: FAILED: Test 4 failed - {e}")
        return 1

    # Test 5 — Rate limiter non-blocking
    try:
        print("Running Test 5 - Rate limiter non-blocking...")
        rl = ProviderRateLimits.get("gemini")
        with rl._lock:
            rl.tokens = float(rl.capacity)

        t5_start = time.perf_counter()
        acquired = rl.acquire(tokens=1, timeout=0.1)
        t5_end = time.perf_counter()
        t5_duration_ms = (t5_end - t5_start) * 1000

        if not acquired:
            raise RuntimeError("Failed to acquire rate limit token")
        if t5_duration_ms > 50.0:
            raise RuntimeError(f"Rate limiter blocked for {t5_duration_ms:.2f}ms, expected < 50ms")

        tests_passed += 1
        print(f"Test 5 passed. Duration: {t5_duration_ms:.2f}ms")
    except Exception as e:
        print(f"Test 5 failed: {e}")
        _write_results(
            tests_passed,
            5 - tests_passed,
            tokens_used_t2 + tokens_used_t4,
            cost_usd_t2 + cost_usd_t4,
            int((t1_latency + t2_latency + t4_latency)/3),
            "FAILED"
        )
        print(f"REAL API SMOKE: FAILED: Test 5 failed - {e}")
        return 1

    # Final successful metrics
    total_tokens = tokens_used_t2 + tokens_used_t4
    total_cost = cost_usd_t2 + cost_usd_t4
    avg_latency = int((t1_latency + t2_latency + t4_latency) / 3)

    _write_results(tests_passed, 0, total_tokens, total_cost, avg_latency, "PASSED")
    print(f"REAL API SMOKE: PASSED (5/5 tests)")
    print(f"Tokens used: {total_tokens} (estimated cost: ${total_cost:.5f})")
    return 0

def _write_results(
    tests_passed: int,
    tests_failed: int,
    total_tokens: int,
    total_cost: float,
    avg_latency: int,
    status: str
) -> None:
    """Write results to .projectos_state/real_api_smoke_results.json."""
    results_path = RESULTS_PATH
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "gemini",
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "total_tokens_used": total_tokens,
        "total_cost_usd": total_cost,
        "latency_ms_avg": avg_latency,
        "status": status
    }
    results_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    signal.signal(signal.SIGALRM, _hard_timeout)
    signal.alarm(30)
    sys.exit(main())
