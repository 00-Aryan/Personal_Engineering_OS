"""Tests for ProjectOS provider setup scripts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from scripts import live_smoke, setup_providers
from scripts.provider_setup import (
    PROVIDER_STATUS_VERSION,
    build_provider_status,
    provider_status_schema_errors,
)


TEST_ENCODING = "utf-8"


def test_setup_script_runs_without_keys(tmp_path: Path) -> None:
    """Verify setup writes skipped statuses when no provider keys are present."""
    config_path = _write_config(tmp_path)
    env_path = tmp_path / ".env"
    status_path = tmp_path / "provider_status.json"

    with patch.dict(os.environ, {}, clear=True), patch("scripts.provider_setup.requests.get") as get_mock:
        exit_code = setup_providers.main(
            [
                "--no-prompt",
                "--config",
                str(config_path),
                "--env-file",
                str(env_path),
                "--status-file",
                str(status_path),
            ]
        )

    payload = json.loads(status_path.read_text(encoding=TEST_ENCODING))
    assert exit_code == 0
    assert payload["available_providers"] == []
    assert all(
        provider["status"] == "skipped"
        for provider in payload["providers"].values()
    )
    get_mock.assert_not_called()


def test_env_example_file_exists() -> None:
    """Verify .env.example documents provider env vars."""
    env_example = Path(".env.example")

    assert env_example.exists()
    content = env_example.read_text(encoding=TEST_ENCODING)
    assert "OPENROUTER_API_KEY=" in content
    assert "GEMINI_API_KEY=" in content


def test_gitignore_excludes_env_files() -> None:
    """Verify local env files are ignored while example remains tracked."""
    content = Path(".gitignore").read_text(encoding=TEST_ENCODING)

    assert ".env" in content
    assert ".env.*" in content
    assert "!.env.example" in content


def test_provider_status_json_schema_valid(tmp_path: Path) -> None:
    """Verify generated provider status matches the expected schema."""
    config = {
        "providers": {
            "openrouter": {
                "api_key_env": "OPENROUTER_API_KEY",
                "default_model": "openrouter-free",
            },
        },
        "agents": {
            "planning": {
                "provider": "openrouter",
                "model": "deepseek-v3",
            },
        },
    }

    with patch.dict(os.environ, {}, clear=True):
        status = build_provider_status(config)

    assert status["schema_version"] == PROVIDER_STATUS_VERSION
    assert provider_status_schema_errors(status) == []


def test_live_smoke_skipped_message_when_no_providers(
    tmp_path: Path,
    capsys,
) -> None:
    """Verify live smoke prints skip message when no providers are available."""
    status_path = _write_empty_status(tmp_path)
    config_path = _write_config(tmp_path)

    exit_code = live_smoke.main(
        [
            "--config",
            str(config_path),
            "--status-file",
            str(status_path),
            "--env-file",
            str(tmp_path / ".env"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No available providers; skipping live smoke." in captured.out


def test_live_smoke_exits_zero_when_skipped(tmp_path: Path) -> None:
    """Verify skipped live smoke exits zero."""
    status_path = _write_empty_status(tmp_path)
    config_path = _write_config(tmp_path)

    exit_code = live_smoke.main(
        [
            "--config",
            str(config_path),
            "--status-file",
            str(status_path),
            "--env-file",
            str(tmp_path / ".env"),
        ]
    )

    assert exit_code == 0


def _write_config(tmp_path: Path) -> Path:
    """Write a test model config."""
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        "\n".join(
            [
                "providers:",
                "  openrouter:",
                "    api_key_env: OPENROUTER_API_KEY",
                "    completion_url: https://openrouter.test/chat",
                "    stream_url: https://openrouter.test/chat",
                "    default_model: openrouter-free",
                "  gemini:",
                "    api_key_env: GEMINI_API_KEY",
                "    completion_url_template: https://gemini.test/{model}?key={api_key}",
                "    stream_url_template: https://gemini.test/{model}?key={api_key}",
                "    default_model: gemini-flash",
                "  ollama:",
                "    default_model: ollama-fallback",
                "agents:",
                "  planning:",
                "    provider: openrouter",
                "    model: deepseek-v3",
                "  clone:",
                "    provider: gemini",
                "    model: gemini-flash",
                "  local:",
                "    provider: ollama",
                "    model: ollama-fallback",
            ]
        )
        + "\n",
        encoding=TEST_ENCODING,
    )
    return config_path


def _write_empty_status(tmp_path: Path) -> Path:
    """Write a status payload with no available providers."""
    status_path = tmp_path / "provider_status.json"
    status_path.write_text(
        json.dumps(
            {
                "schema_version": PROVIDER_STATUS_VERSION,
                "generated_at": "2026-06-07T00:00:00+00:00",
                "providers": {},
                "available_providers": [],
            }
        ),
        encoding=TEST_ENCODING,
    )
    return status_path
