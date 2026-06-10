import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from core.observability.token_budget import TokenBudget, TokenUsageRecord
from core.model_provider import ModelProvider


def test_check_allows_under_soft_limit(tmp_path):
    budgets = {
        "test_agent": {
            "soft_limit_per_call": 100,
            "hard_limit_per_call": 200,
            "daily_limit": 1000,
        }
    }
    tb = TokenBudget(tmp_path, budgets=budgets)
    # prompt length 200 -> 50 estimated tokens
    result = tb.check_and_record("test_agent", "a" * 200)
    assert result.allowed is True
    assert result.soft_limit_exceeded is False
    assert result.hard_limit_exceeded is False
    assert result.daily_limit_exceeded is False


def test_check_warns_over_soft_limit(tmp_path):
    budgets = {
        "test_agent": {
            "soft_limit_per_call": 50,
            "hard_limit_per_call": 200,
            "daily_limit": 1000,
        }
    }
    tb = TokenBudget(tmp_path, budgets=budgets)
    # prompt length 300 -> 75 estimated tokens
    result = tb.check_and_record("test_agent", "a" * 300)
    assert result.allowed is True
    assert result.soft_limit_exceeded is True
    assert result.hard_limit_exceeded is False
    assert "soft limit" in result.warning_message.lower()


def test_check_blocks_over_hard_limit(tmp_path):
    budgets = {
        "test_agent": {
            "soft_limit_per_call": 50,
            "hard_limit_per_call": 100,
            "daily_limit": 1000,
        }
    }
    tb = TokenBudget(tmp_path, budgets=budgets)
    # prompt length 600 -> 150 estimated tokens
    result = tb.check_and_record("test_agent", "a" * 600)
    assert result.allowed is False
    assert result.hard_limit_exceeded is True
    assert "hard limit" in result.warning_message.lower()


def test_daily_limit_blocks_when_exceeded(tmp_path):
    budgets = {
        "test_agent": {
            "soft_limit_per_call": 100,
            "hard_limit_per_call": 200,
            "daily_limit": 100,
        }
    }
    tb = TokenBudget(tmp_path, budgets=budgets)
    # First call: prompt length 200 -> 50 tokens (allowed)
    result1 = tb.check_and_record("test_agent", "a" * 200)
    assert result1.allowed is True
    tb.record_completion("test_agent", "b" * 100) # completion: 25 tokens. Total 75

    # Second call: prompt length 200 -> 50 tokens. Total would be 125 > 100 daily limit (blocked)
    result2 = tb.check_and_record("test_agent", "a" * 200)
    assert result2.allowed is False
    assert result2.daily_limit_exceeded is True
    assert "daily limit" in result2.warning_message.lower()


def test_record_completion_persists_to_jsonl(tmp_path):
    tb = TokenBudget(tmp_path)
    tb.check_and_record("code_review", "prompt_text")
    record = tb.record_completion("code_review", "completion_text", trace_id="tr-1", event_id="ev-1")
    
    assert record.record_id is not None
    assert record.agent_name == "code_review"
    assert record.prompt_tokens == len("prompt_text") // 4
    assert record.completion_tokens == len("completion_text") // 4
    assert record.trace_id == "tr-1"
    assert record.event_id == "ev-1"
    
    log_file = tmp_path / "token_usage.jsonl"
    assert log_file.exists()
    
    with open(log_file, "r") as f:
        lines = f.readlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["record_id"] == record.record_id
    assert data["agent_name"] == "code_review"
    assert data["trace_id"] == "tr-1"


def test_get_daily_usage_accurate(tmp_path):
    tb = TokenBudget(tmp_path)
    tb.check_and_record("planning", "a" * 400) # 100 tokens
    tb.record_completion("planning", "b" * 200) # 50 tokens. Total 150
    
    tb.check_and_record("planning", "a" * 100) # 25 tokens
    tb.record_completion("planning", "b" * 100) # 25 tokens. Total 50
    
    usage = tb.get_daily_usage("planning")
    assert usage == 200


def test_usage_summary_spans_multiple_days(tmp_path):
    tb = TokenBudget(tmp_path)
    log_file = tmp_path / "token_usage.jsonl"
    
    today_str = datetime.now(timezone.utc).date().isoformat()
    yesterday_str = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    
    # Write manual records
    rec1 = {
        "record_id": "r1",
        "timestamp": f"{today_str}T12:00:00Z",
        "agent_name": "code_review",
        "operation": "model_call",
        "provider": "gemini",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "estimated_cost_usd": 0.0,
    }
    rec2 = {
        "record_id": "r2",
        "timestamp": f"{yesterday_str}T15:00:00Z",
        "agent_name": "code_review",
        "operation": "model_call",
        "provider": "gemini",
        "prompt_tokens": 200,
        "completion_tokens": 100,
        "total_tokens": 300,
        "estimated_cost_usd": 0.0,
    }
    
    with open(log_file, "w") as f:
        f.write(json.dumps(rec1) + "\n")
        f.write(json.dumps(rec2) + "\n")
        
    summary = tb.get_usage_summary(days=7)
    assert "code_review" in summary
    assert summary["code_review"]["total_tokens"] == 450
    assert summary["code_review"]["total_calls"] == 2
    assert summary["code_review"]["avg_per_call"] == 225.0
    assert summary["code_review"]["daily_breakdown"][today_str] == 150
    assert summary["code_review"]["daily_breakdown"][yesterday_str] == 300


def test_trim_context_fits_within_budget(tmp_path):
    tb = TokenBudget(tmp_path)
    context = "chunk1\n---\nchunk2\n---\nchunk3" # length 30 -> 7 tokens
    
    # 5 tokens remaining (should trim chunk3)
    trimmed = tb.trim_context_to_budget(context, 5)
    assert "chunk3" not in trimmed
    assert "chunk2" in trimmed


def test_trim_context_empty_returns_empty(tmp_path):
    tb = TokenBudget(tmp_path)
    assert tb.trim_context_to_budget("", 10) == ""


from core.model_provider import OllamaProvider

def test_hard_limit_prevents_api_call(tmp_path):
    budgets = {
        "test_agent": {
            "soft_limit_per_call": 10,
            "hard_limit_per_call": 20,
            "daily_limit": 1000,
        }
    }
    tb = TokenBudget(tmp_path, budgets=budgets)
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
    # Mock _complete_once to check if it's called
    mock_complete = MagicMock(return_value="api_response")
    provider._complete_once = mock_complete
    
    # Prompt is length 100 -> 25 estimated tokens (exceeds hard limit 20)
    result = provider.complete("a" * 100, "sys", 50)
    assert "TOKEN_BUDGET_EXCEEDED" in result
    mock_complete.assert_not_called()


def test_conservative_mode_inactive_below_threshold(tmp_path):
    budgets = {
        "code_writing": {
            "daily_limit": 1000,
        }
    }
    tb = TokenBudget(tmp_path, budgets=budgets)
    tb.check_and_record("code_writing", "a" * 1200)  # 300 prompt tokens
    tb.record_completion("code_writing", "b" * 800)  # 200 completion tokens. Total 500
    assert tb.conservative_mode_active("code_writing") is False


def test_conservative_mode_active_at_threshold(tmp_path):
    budgets = {
        "code_writing": {
            "daily_limit": 1000,
        }
    }
    tb = TokenBudget(tmp_path, budgets=budgets)
    tb.check_and_record("code_writing", "a" * 1200)  # 300 prompt tokens
    tb.record_completion("code_writing", "b" * 1200)  # 300 completion tokens. Total 600
    assert tb.conservative_mode_active("code_writing") is True


def test_check_daily_threshold_alert_returns_string(tmp_path):
    budgets = {
        "code_writing": {
            "daily_limit": 1000,
        }
    }
    tb = TokenBudget(tmp_path, budgets=budgets)
    tb.check_and_record("code_writing", "a" * 1600)  # 400 prompt tokens
    tb.record_completion("code_writing", "b" * 1200)  # 300 completion tokens. Total 700
    alert = tb.check_daily_threshold_alert("code_writing")
    assert alert is not None
    assert "conservative" in alert.lower()


from agents.code_writing_agent import CodeWritingAgent
from core.events import AgentEvent, EventType
from unittest.mock import ANY

def test_conservative_mode_reduces_token_limits(tmp_path):
    mock_tb = MagicMock()
    mock_tb.conservative_mode_active.return_value = True

    mock_provider = MagicMock()
    mock_provider.complete.return_value = "def dummy_func():\n    pass\n"
    mock_provider.token_budget = mock_tb

    logger = MagicMock()
    agent = CodeWritingAgent(
        model_provider=mock_provider,
        logger=logger,
        project_root=tmp_path,
    )

    event = AgentEvent(
        event_type=EventType.CODE_WRITTEN,
        source_agent="planning",
        payload={
            "task_id": "TASK_TEST",
            "file_path": "dummy.py",
            "task_description": "write dummy function",
            "acceptance_criteria": ["criteria 1"],
        }
    )

    agent.handle(event)

    args, kwargs = mock_provider.complete.call_args
    assert args[2] == 500

