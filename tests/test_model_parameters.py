"""Tests for model parameter tuning and Ollama provider integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from agents.code_writing_agent import CodeWritingAgent
from core.events import AgentEvent, EventType
from core.model_provider import OllamaProvider


def test_temperature_passed_to_provider(tmp_path):
    """Verify that when an agent handles an event, the configured temperature is passed to provider.complete."""
    mock_provider = MagicMock()
    mock_provider._config = {
        "model_parameters": {
            "code_writing": {
                "temperature": 0.05,
                "max_tokens": 750,
                "top_p": 0.8
            }
        }
    }
    mock_provider.complete.return_value = "def test(): pass"
    
    agent = CodeWritingAgent(
        model_provider=mock_provider,
        logger=MagicMock(),
        project_root=tmp_path,
    )
    
    event = AgentEvent(
        event_type=EventType.CODE_WRITTEN,
        source_agent="planning",
        payload={
            "task_id": "T1",
            "file_path": "test.py",
            "task_description": "write helper",
        }
    )
    agent.handle(event)
    
    mock_provider.complete.assert_any_call(
        ANY,
        ANY,
        750,
        temperature=0.05,
        top_p=0.8,
        agent_name="code_writing"
    )


def test_agent_uses_configured_temperature(tmp_path):
    """Verify agent's get_model_params correctly loads configuration."""
    mock_provider = MagicMock()
    mock_provider._config = {
        "model_parameters": {
            "code_writing": {
                "temperature": 0.15,
                "max_tokens": 1200,
                "top_p": 0.95
            }
        }
    }
    
    agent = CodeWritingAgent(
        model_provider=mock_provider,
        logger=MagicMock(),
        project_root=tmp_path,
    )
    
    params = agent.get_model_params()
    assert params["temperature"] == 0.15
    assert params["max_tokens"] == 1200
    assert params["top_p"] == 0.95


def test_default_params_when_not_configured(tmp_path):
    """Verify default parameters are returned when there is no configuration."""
    mock_provider = MagicMock()
    mock_provider._config = {}  # Empty config
    
    agent = CodeWritingAgent(
        model_provider=mock_provider,
        logger=MagicMock(),
        project_root=tmp_path,
    )
    
    params = agent.get_model_params()
    assert params["temperature"] == 0.3
    assert params["max_tokens"] == 1000
    assert params["top_p"] == 0.9


def test_ollama_provider_passes_temperature():
    """Verify OllamaProvider complete() packs temperature and top_p into request options."""
    config = {
        "providers": {
            "ollama": {
                "type": "ollama",
                "default_model": "llama3.2:1b",
                "base_url": "http://localhost:11434"
            }
        }
    }
    
    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "test output"}
        mock_post.return_value = mock_response
        
        provider = OllamaProvider(agent_name=None, config_path=None)
        provider._config = config
        provider._provider_config = config["providers"]["ollama"]
        provider._model_name = "llama3.2:1b"
        
        provider.complete(
            prompt="hello",
            system_prompt="system",
            max_tokens=500,
            temperature=0.12,
            top_p=0.88
        )
        
        args, kwargs = mock_post.call_args
        payload = kwargs.get("json") or args[1]
        assert "options" in payload
        assert payload["options"]["temperature"] == 0.12
        assert payload["options"]["top_p"] == 0.88
        assert payload["options"]["num_predict"] == 500


def test_conservative_mode_reduces_max_tokens(tmp_path):
    """Verify token budget conservative mode caps max_tokens at 500."""
    mock_tb = MagicMock()
    mock_tb.conservative_mode_active.return_value = True
    
    mock_provider = MagicMock()
    mock_provider.token_budget = mock_tb
    mock_provider._config = {
        "model_parameters": {
            "code_writing": {
                "temperature": 0.1,
                "max_tokens": 1000,
                "top_p": 0.9
            }
        }
    }
    
    agent = CodeWritingAgent(
        model_provider=mock_provider,
        logger=MagicMock(),
        project_root=tmp_path,
    )
    
    params = agent.get_model_params()
    assert params["max_tokens"] == 500
