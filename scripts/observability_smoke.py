#!/usr/bin/env python3
"""End-to-end smoke test for ProjectOS Phase 5 observability components."""

from __future__ import annotations

import sys
import time
import tempfile
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock

from core.observability.tracer import Tracer, TraceStore, SpanStatus
from core.observability.token_budget import TokenBudget
from core.observability.cost_tracker import CostTracker
from core.observability.circuit_breaker import CircuitBreaker, CircuitState, CircuitOpenError
from core.observability.alerting import AlertManager, Alert, AlertSeverity, AlertType, AlertRule
from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.base_evaluator import EvaluationResult
from core.model_provider import OllamaProvider


def test_scenario_a(tmp_path: Path) -> None:
    print("Running Test Scenario A: Distributed Tracing...")
    # 1. Initialize Tracer with TraceStore (tmp_path)
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    
    # 2. Create a trace with 4 sequential spans:
    #    clone.handle → context_retrieval → code_review → quality_gate
    trace_id = "trace-smoke-a"
    
    s1 = tracer.start_span("clone.handle", "smoke", trace_id=trace_id, tags={"tag1": "val1"})
    time.sleep(0.01)
    s2 = tracer.start_span("context_retrieval", "smoke", trace_id=trace_id, tags={"tag2": "val2"})
    time.sleep(0.01)
    s3 = tracer.start_span("code_review", "smoke", trace_id=trace_id, tags={"tag3": "val3"})
    time.sleep(0.01)
    s4 = tracer.start_span("quality_gate", "smoke", trace_id=trace_id, tags={"tag4": "val4"})
    
    # 3. Each span: set tags, finish with OK status
    s1.finish(SpanStatus.OK)
    s2.finish(SpanStatus.OK)
    s3.finish(SpanStatus.OK)
    s4.finish(SpanStatus.OK)
    
    # 4. Assert: get_trace() returns all 4 spans
    spans = tracer.get_trace(trace_id)
    assert len(spans) == 4, f"Expected 4 spans, got {len(spans)}"
    
    operation_names = [s.operation_name for s in spans]
    assert "clone.handle" in operation_names
    assert "context_retrieval" in operation_names
    assert "code_review" in operation_names
    assert "quality_gate" in operation_names
    
    # 5. Assert: spans sorted by started_at
    for i in range(len(spans) - 1):
        assert spans[i].started_at <= spans[i+1].started_at, f"Spans not sorted: {spans[i].started_at} > {spans[i+1].started_at}"
        
    # 6. Assert: total duration computed correctly
    earliest = min(s.started_at for s in spans)
    latest = max(s.ended_at for s in spans)
    duration_ms = int((latest - earliest).total_seconds() * 1000)
    assert duration_ms >= 30, f"Expected total duration >= 30ms, got {duration_ms}ms"
    print("Test Scenario A passed!")


def test_scenario_b(tmp_path: Path) -> None:
    print("Running Test Scenario B: Token Budget...")
    # 1. Initialize TokenBudget with low limits (hard_limit=100)
    budgets = {
        "test_agent": {
            "soft_limit_per_call": 50,
            "hard_limit_per_call": 100,
            "daily_limit": 1000,
        }
    }
    tb = TokenBudget(tmp_path, budgets=budgets)
    
    # Write config file for mock provider
    config_path = tmp_path / "models.yaml"
    with open(config_path, "w") as f:
        f.write("""
providers:
  ollama:
    default_model: llama3
agents:
  test_agent:
    provider: ollama
    model: llama3
""")
    
    provider = OllamaProvider("test_agent", config_path=config_path, token_budget=tb)
    mock_complete = MagicMock(return_value="api_response")
    provider._complete_once = mock_complete

    # 2. check_and_record with 50 token prompt → allowed
    res1 = tb.check_and_record("test_agent", "a" * 200)
    assert res1.allowed is True
    
    # 3. check_and_record with 150 token prompt → blocked
    res2 = tb.check_and_record("test_agent", "a" * 600)
    assert res2.allowed is False
    
    # 4. Assert: BudgetCheckResult.hard_limit_exceeded is True
    assert res2.hard_limit_exceeded is True
    
    # 5. Assert: no API call made (mock provider not called)
    res_provider = provider.complete("a" * 500, "sys", 50)
    assert "TOKEN_BUDGET_EXCEEDED" in res_provider
    mock_complete.assert_not_called()
    print("Test Scenario B passed!")


def test_scenario_c(tmp_path: Path) -> None:
    print("Running Test Scenario C: Cost Tracking...")
    # 1. Initialize CostTracker
    tracker = CostTracker(tmp_path)
    
    # 2. Record 5 calls: 3 to gemini (free), 2 to deepseek (paid)
    r1 = tracker.record("test_agent", "gemini", 1000, 1000, model="gemini-1.5-flash")
    r2 = tracker.record("test_agent", "gemini", 1500, 1500, model="gemini-1.5-flash")
    r3 = tracker.record("test_agent", "gemini", 2000, 2000, model="gemini-1.5-flash")
    
    r4 = tracker.record("test_agent", "openrouter", 1000, 1000, model="deepseek/deepseek-chat")
    r5 = tracker.record("test_agent", "openrouter", 2000, 2000, model="deepseek/deepseek-chat")
    
    # 3. Assert: gemini calls show cost_usd == 0.0
    assert r1.cost_usd == 0.0, f"Expected 0.0, got {r1.cost_usd}"
    assert r2.cost_usd == 0.0
    assert r3.cost_usd == 0.0
    
    # 4. Assert: deepseek calls show cost_usd > 0.0
    assert r4.cost_usd > 0.0, f"Expected > 0.0, got {r4.cost_usd}"
    assert r5.cost_usd > 0.0
    
    # 5. Assert: get_daily_cost() totals are correct
    daily_cost = tracker.get_daily_cost()
    expected_usd = r4.cost_usd + r5.cost_usd
    assert abs(daily_cost["total_usd"] - expected_usd) < 1e-9, f"Expected {expected_usd}, got {daily_cost['total_usd']}"
    assert daily_cost["free_tier_calls"] == 3
    assert daily_cost["paid_calls"] == 2
    print("Test Scenario C passed!")


def test_scenario_d(tmp_path: Path) -> None:
    print("Running Test Scenario D: Circuit Breaker...")
    # 1. Initialize CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    cb = CircuitBreaker("smoke-provider", failure_threshold=3, recovery_timeout=1.0, state_dir=tmp_path)
    
    # 2. Trigger 3 consecutive failures
    def failing_fn():
        raise ValueError("fail")
        
    for _ in range(3):
        try:
            cb.call(failing_fn)
        except ValueError:
            pass
            
    # 3. Assert: state == OPEN
    assert cb.state == CircuitState.OPEN, f"Expected OPEN, got {cb.state}"
    
    # 4. Wait 1.1 seconds
    time.sleep(1.1)
    
    # 5. Trigger one success
    res = cb.call(lambda: "success")
    assert res == "success"
    
    # 6. Assert: state == CLOSED
    assert cb.state == CircuitState.CLOSED, f"Expected CLOSED, got {cb.state}"
    print("Test Scenario D passed!")


def test_scenario_e(tmp_path: Path) -> None:
    print("Running Test Scenario E: Alert Firing...")
    # 1. Initialize AlertManager with test rules (low thresholds)
    manager = AlertManager(tmp_path)
    
    # 2. Seed evaluation data with failing scores
    store = EvaluationStore(tmp_path)
    for _ in range(10):
        res = EvaluationResult(
            evaluator_name="llm_judge",
            agent_name="planning",
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            criteria_scores={"correctness": 0.4},
            weighted_score=0.40,
            passed=False,
            reasoning="test",
            raw_output_sample="test",
            evaluation_duration_ms=100,
            evaluator_model="test",
            metadata={},
        )
        store.save(res)
        
    # 3. Run rule checks manually (not background thread)
    manager.evaluate_rules()
    
    # 4. Assert: at least one alert fired
    active = manager.get_active_alerts()
    assert len(active) > 0, "Expected at least one alert to fire"
    
    # 5. Acknowledge it
    alert_id = active[0].alert_id
    success = manager.acknowledge(alert_id)
    assert success is True
    
    # 6. Assert: get_active_alerts() is empty
    active_after = manager.get_active_alerts()
    assert len(active_after) == 0, f"Expected empty list, got {active_after}"
    print("Test Scenario E passed!")


def main() -> int:
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            test_scenario_a(tmp_path)
            test_scenario_b(tmp_path)
            test_scenario_c(tmp_path)
            test_scenario_d(tmp_path)
            test_scenario_e(tmp_path)
            
        print("OBSERVABILITY SMOKE: PASSED")
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"OBSERVABILITY SMOKE: FAILED - {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
