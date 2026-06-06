"""Unit tests for the CostTracker observability component."""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from core.observability.cost_tracker import CostTracker, ProviderPricing, CostRecord


@pytest.fixture
def temp_state_dir():
    """Fixture that provides a temporary directory for tracker state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_free_tier_records_zero_cost(temp_state_dir):
    """Test that free tier model calls record zero cost."""
    tracker = CostTracker(temp_state_dir)
    # gemini-flash has a daily free tier up to 1M tokens, so this is free
    record = tracker.record(
        agent_name="clone",
        provider="gemini",
        input_tokens=1000,
        output_tokens=1000,
        model="gemini-1.5-flash",
    )
    assert record.cost_usd == 0.0
    assert record.cost_inr == 0.0
    assert record.is_free_tier is True


def test_paid_tier_computes_correct_cost(temp_state_dir):
    """Test that paid models calculate the correct token costs."""
    tracker = CostTracker(temp_state_dir, usd_to_inr=100.0)
    # deepseek-v3 has:
    # input_cost_per_1k_tokens = 0.00014
    # output_cost_per_1k_tokens = 0.00028
    # For 10k input: 10 * 0.00014 = 0.0014 USD
    # For 5k output: 5 * 0.00028 = 0.0014 USD
    # Total: 0.0028 USD * 100 = 0.28 INR
    record = tracker.record(
        agent_name="planning",
        provider="openrouter",
        input_tokens=10000,
        output_tokens=5000,
        model="deepseek/deepseek-chat",
    )
    assert abs(record.cost_usd - 0.0028) < 1e-9
    assert abs(record.cost_inr - 0.28) < 1e-9
    assert record.is_free_tier is False


def test_inr_conversion_applied(temp_state_dir):
    """Test that the exchange rate is correctly applied to calculate INR costs."""
    tracker = CostTracker(temp_state_dir, usd_to_inr=80.0)
    record = tracker.record(
        agent_name="planning",
        provider="openrouter",
        input_tokens=10000,
        output_tokens=5000,
        model="deepseek/deepseek-chat",
    )
    assert abs(record.cost_inr - (record.cost_usd * 80.0)) < 1e-9


def test_get_daily_cost_aggregates_correctly(temp_state_dir):
    """Test that daily costs are correctly summarized and aggregated."""
    tracker = CostTracker(temp_state_dir, usd_to_inr=100.0)
    # 1 free call
    tracker.record("clone", "gemini", 1000, 1000, model="gemini-1.5-flash")
    # 1 paid call (costing 0.0028 USD / 0.28 INR)
    tracker.record("planning", "openrouter", 10000, 5000, model="deepseek/deepseek-chat")

    daily = tracker.get_daily_cost()
    assert daily["free_tier_calls"] == 1
    assert daily["paid_calls"] == 1
    assert abs(daily["total_usd"] - 0.0028) < 1e-9
    assert abs(daily["total_inr"] - 0.28) < 1e-9
    assert daily["by_agent"]["clone"]["usd"] == 0.0
    assert abs(daily["by_agent"]["planning"]["usd"] - 0.0028) < 1e-9


def test_get_task_cost_sums_all_calls(temp_state_dir):
    """Test that get_task_cost aggregates costs for specific tasks."""
    tracker = CostTracker(temp_state_dir, usd_to_inr=100.0)
    tracker.record("planning", "openrouter", 10000, 5000, task_id="task-123", model="deepseek/deepseek-chat")
    tracker.record("planning", "openrouter", 10000, 5000, task_id="task-123", model="deepseek/deepseek-chat")
    tracker.record("planning", "openrouter", 10000, 5000, task_id="task-456", model="deepseek/deepseek-chat")

    task_cost = tracker.get_task_cost("task-123")
    assert task_cost["calls"] == 2
    assert abs(task_cost["total_usd"] - 0.0056) < 1e-9


def test_monthly_projection_low_confidence_under_3_days(temp_state_dir):
    """Test that monthly projection handles confidence rating based on days of data."""
    tracker = CostTracker(temp_state_dir)
    projection_low = tracker.get_monthly_projection(days_of_data=2)
    assert projection_low["confidence"] == "low"

    projection_med = tracker.get_monthly_projection(days_of_data=7)
    assert projection_med["confidence"] == "medium"

    projection_high = tracker.get_monthly_projection(days_of_data=14)
    assert projection_high["confidence"] == "high"


def test_costs_jsonl_append_only(temp_state_dir):
    """Test that the log file is updated in an append-only fashion."""
    tracker = CostTracker(temp_state_dir)
    tracker.record("clone", "gemini", 100, 100, model="gemini-1.5-flash")
    tracker.record("clone", "gemini", 200, 200, model="gemini-1.5-flash")

    assert tracker.log_path.exists()
    lines = tracker.log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    data1 = json.loads(lines[0])
    data2 = json.loads(lines[1])
    assert data1["input_tokens"] == 100
    assert data2["input_tokens"] == 200


def test_recommend_model_swap_suggests_ollama(temp_state_dir):
    """Test model swap recommendations when costs exceed daily limit threshold."""
    tracker = CostTracker(temp_state_dir, usd_to_inr=100.0)

    mock_config = {
        "agents": {
            "planning": {
                "model": "deepseek-v3",
                "provider": "openrouter",
            }
        },
        "pricing": {
            "alert_threshold_daily_inr": 10.0,
            "usd_to_inr": 100.0,
        },
    }

    # Patch yaml.safe_load to return our mock configuration
    with patch("yaml.safe_load", return_value=mock_config):
        # Under threshold daily cost (0 INR so far), should recommend nothing
        rec = tracker.recommend_model_swap("planning")
        assert rec is None

        # Exceed daily threshold (42 INR)
        tracker.record("planning", "openrouter", 1000000, 1000000, model="deepseek/deepseek-chat")

        # When Ollama is available, recommend swapping to Ollama local
        with patch.object(tracker, "_is_ollama_available", return_value=True):
            rec = tracker.recommend_model_swap("planning")
            assert rec is not None
            assert "Ollama" in rec

            # When Ollama is not available, recommend the next cheapest model (gemini-flash or openrouter-free)
            with patch.object(tracker, "_is_ollama_available", return_value=False):
                rec = tracker.recommend_model_swap("planning")
                assert rec is not None
                assert ("openrouter-free" in rec or "gemini-flash" in rec)
