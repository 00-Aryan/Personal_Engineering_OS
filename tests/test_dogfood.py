"""Tests for ProjectOS dogfooding runner."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import pytest
from core.events import AgentEvent, EventType
from core.projectos import ProjectOS
from scripts import dogfood
from scripts.provider_setup import PROVIDER_STATUS_VERSION


@pytest.fixture(autouse=True)
def cleanup_timers() -> Generator[None, None, None]:
    """Ensure any threading.Timer instances started during tests are canceled on teardown."""
    timers = []
    original_timer = threading.Timer

    def mock_timer(*args: Any, **kwargs: Any) -> threading.Timer:
        t = original_timer(*args, **kwargs)
        timers.append(t)
        return t

    with patch("threading.Timer", side_effect=mock_timer):
        try:
            yield
        finally:
            for t in timers:
                t.cancel()


def setup_dummy_project(tmp_path: Path) -> Path:
    """Create a dummy project structure to satisfy indexing and execution requirements."""
    # Create directories
    (tmp_path / "core").mkdir(parents=True, exist_ok=True)
    (tmp_path / "agents").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cli").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reviews").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "adr").mkdir(parents=True, exist_ok=True)

    # Write 12 dummy files, each with 5 functions to get 72 chunks
    for i in range(4):
        (tmp_path / "core" / f"core_file_{i}.py").write_text(
            "def f1(): pass\ndef f2(): pass\ndef f3(): pass\ndef f4(): pass\ndef f5(): pass\n",
            encoding="utf-8"
        )
        (tmp_path / "agents" / f"agent_file_{i}.py").write_text(
            "def f1(): pass\ndef f2(): pass\ndef f3(): pass\ndef f4(): pass\ndef f5(): pass\n",
            encoding="utf-8"
        )
        (tmp_path / "cli" / f"cli_file_{i}.py").write_text(
            "def f1(): pass\ndef f2(): pass\ndef f3(): pass\ndef f4(): pass\ndef f5(): pass\n",
            encoding="utf-8"
        )

    # We also need core/clone_agent.py to exist because Phase B triggers a review on it
    (tmp_path / "core" / "clone_agent.py").write_text(
        "def dummy_clone(): pass\n",
        encoding="utf-8"
    )

    # config/models.yaml
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "models.yaml"
    config_file.write_text(
        "providers:\n"
        "  gemini:\n"
        "    api_key_env: GEMINI_API_KEY\n"
        "    completion_url_template: https://gemini.test\n"
        "    stream_url_template: https://gemini.test\n"
        "    default_model: gemini-flash\n"
        "agents:\n"
        "  clone:\n"
        "    provider: gemini\n"
        "    model: gemini-flash\n"
        "  planning:\n"
        "    provider: gemini\n"
        "    model: gemini-flash\n"
        "  code_writing:\n"
        "    provider: gemini\n"
        "    model: gemini-flash\n"
        "  code_review:\n"
        "    provider: gemini\n"
        "    model: gemini-flash\n"
        "  architecture:\n"
        "    provider: gemini\n"
        "    model: gemini-flash\n"
        "  test:\n"
        "    provider: gemini\n"
        "    model: gemini-flash\n"
        "  docs:\n"
        "    provider: gemini\n"
        "    model: gemini-flash\n",
        encoding="utf-8"
    )
    return config_file


def test_dogfood_script_mock_mode(tmp_path: Path) -> None:
    """Verify dogfood script runs successfully in mock mode."""
    config_file = setup_dummy_project(tmp_path)
    decisions_log = tmp_path / "decisions.log"
    decisions_log.touch()

    exit_code = dogfood.main([
        "--mock",
        "--config", str(config_file),
        "--project-root", str(tmp_path),
        "--state-dir", str(tmp_path / ".projectos_state"),
    ])

    assert exit_code == 0


def test_dogfood_script_respects_provider_status(tmp_path: Path) -> None:
    """Verify dogfood script defaults to mock mode when no providers are available."""
    config_file = setup_dummy_project(tmp_path)
    decisions_log = tmp_path / "decisions.log"
    decisions_log.touch()

    state_dir = tmp_path / ".projectos_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    status_file = state_dir / "provider_status.json"
    status_file.write_text(json.dumps({
        "schema_version": PROVIDER_STATUS_VERSION,
        "generated_at": "2026-06-07T00:00:00+00:00",
        "providers": {},
        "available_providers": []
    }), encoding="utf-8")

    exit_code = dogfood.main([
        "--config", str(config_file),
        "--project-root", str(tmp_path),
        "--state-dir", str(state_dir),
    ])

    assert exit_code == 0


def test_dogfood_indexing_phase_completes(tmp_path: Path) -> None:
    """Verify that Phase A (Indexing) completes successfully and creates index report."""
    config_file = setup_dummy_project(tmp_path)
    state_dir = tmp_path / ".projectos_state"

    exit_code = dogfood.main([
        "--mock",
        "--config", str(config_file),
        "--project-root", str(tmp_path),
        "--state-dir", str(state_dir),
    ])
    assert exit_code == 0

    index_report_file = state_dir / "dogfood_indexing.json"
    assert index_report_file.exists()
    report = json.loads(index_report_file.read_text(encoding="utf-8"))
    assert report["files_indexed"] >= 10
    assert report["chunks_created"] >= 50


def test_dogfood_triggers_review_event(tmp_path: Path) -> None:
    """Verify that CODE_CHANGED event is processed and reviews are populated."""
    config_file = setup_dummy_project(tmp_path)
    exit_code = dogfood.main([
        "--mock",
        "--config", str(config_file),
        "--project-root", str(tmp_path),
        "--state-dir", str(tmp_path / ".projectos_state"),
    ])
    assert exit_code == 0

    reviews_dir = tmp_path / "reviews"
    review_files = list(reviews_dir.glob("clone_agent.py_*_review.md"))
    assert len(review_files) > 0


def test_dogfood_report_written(tmp_path: Path) -> None:
    """Verify that docs/dogfood_report.md is correctly written."""
    config_file = setup_dummy_project(tmp_path)
    exit_code = dogfood.main([
        "--mock",
        "--config", str(config_file),
        "--project-root", str(tmp_path),
        "--state-dir", str(tmp_path / ".projectos_state"),
    ])
    assert exit_code == 0

    report_path = tmp_path / "docs" / "dogfood_report.md"
    assert report_path.exists()
    report_content = report_path.read_text(encoding="utf-8")
    assert "# ProjectOS Dogfood Report" in report_content
    assert "## Indexing" in report_content
    assert "## Code Review Findings" in report_content


def test_run_for_duration_stops_cleanly(tmp_path: Path) -> None:
    """Verify that ProjectOS.run_for_duration stops cleanly and returns performance data."""
    config_file = setup_dummy_project(tmp_path)
    project_os = ProjectOS(
        config_path=config_file,
        provider_factory=lambda name, path: dogfood.DogfoodMockModelProvider(name, path),
        project_root=tmp_path,
        state_dir=tmp_path / ".projectos_state",
    )

    result = project_os.run_for_duration(seconds=1)
    assert isinstance(result, dict)
    assert "events_processed" in result
    assert "decisions_logged" in result
    assert "errors" in result
    assert len(result["errors"]) == 0


def test_dogfood_handles_provider_failure_gracefully(tmp_path: Path) -> None:
    """Verify that dogfood script handles completions/provider failure gracefully."""
    config_file = setup_dummy_project(tmp_path)

    # Let's write a provider factory that raises an exception on complete()
    class FailingProvider(dogfood.DogfoodMockModelProvider):
        def complete(self, *args, **kwargs) -> str:
            raise RuntimeError("API Connection Failure")

    # Monkey patch provider factory in dogfood
    original_factory = dogfood.DogfoodMockModelProvider
    try:
        # We can temporarily override the class instantiation inside main by subclassing/mocking
        # Or we can just let it run with mock but raise an error inside one of the agent calls
        # Let's define a mock provider factory that fails
        def failing_factory(name: str, path: Any) -> Any:
            return FailingProvider(name, path)

        # We can test this by running dogfood main with our failing factory
        # To do this cleanly, we can temporarily wrap dogfood.main or mock its provider_factory
        # Since main accepts argv, let's mock it
        # Actually, let's just assert that if the run fails with an error, the script exits 0
        # and dogfood_report.md is still written.
        # Let's monkeypatch main's provider_factory logic by overriding ProjectOS initialization
        # or we can mock ProjectOS.submit_event to raise an exception.
        # Let's mock project_os.submit_event to raise an exception during review phase!
        # If it raises an exception, Phase B fails, but the script continues.
        
        # Let's monkeypatch dogfood's provider_factory:
        # Instead of monkeypatching the imports, let's subclass or patch ProjectOS
        from unittest.mock import patch
        with patch("scripts.dogfood.ProjectOS.submit_event", side_effect=RuntimeError("Simulated API failure")):
            exit_code = dogfood.main([
                "--mock",
                "--config", str(config_file),
                "--project-root", str(tmp_path),
                "--state-dir", str(tmp_path / ".projectos_state"),
            ])
            
            assert exit_code == 0
            
            report_path = tmp_path / "docs" / "dogfood_report.md"
            assert report_path.exists()
            report_content = report_path.read_text(encoding="utf-8")
            # The failure should be recorded under Real Bugs Found
            assert "Simulated API failure" in report_content
    finally:
        pass


def test_dogfood_script_mock_only_mode(tmp_path: Path) -> None:
    """Verify dogfood script runs successfully with the --mock-only flag."""
    config_file = setup_dummy_project(tmp_path)
    decisions_log = tmp_path / "decisions.log"
    decisions_log.touch()

    exit_code = dogfood.main([
        "--mock-only",
        "--config", str(config_file),
        "--project-root", str(tmp_path),
        "--state-dir", str(tmp_path / ".projectos_state"),
    ])

    assert exit_code == 0

