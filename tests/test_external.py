"""Tests for ProjectOS multi-project orchestration and isolation."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from core.events import AgentEvent, EventType
from core.project_config import ProjectConfig, ProjectRegistry
from core.projectos import MultiProjectOS, ProjectOS
from scripts.dogfood import DogfoodMockModelProvider


def test_project_registry_isolation(tmp_path: Path) -> None:
    """Verify adding and removing projects does not impact other registries."""
    registry_a_path = tmp_path / "registry_a.yaml"
    registry_b_path = tmp_path / "registry_b.yaml"

    registry_a = ProjectRegistry(registry_a_path)
    registry_b = ProjectRegistry(registry_b_path)

    project_root_a = tmp_path / "project_a"
    project_root_a.mkdir()
    config_a = ProjectConfig.create("project_a", project_root_a)

    project_root_b = tmp_path / "project_b"
    project_root_b.mkdir()
    config_b = ProjectConfig.create("project_b", project_root_b)

    registry_a.add_project(config_a)
    registry_b.add_project(config_b)

    assert len(registry_a.list_projects()) == 1
    assert registry_a.list_projects()[0].name == "project_a"

    assert len(registry_b.list_projects()) == 1
    assert registry_b.list_projects()[0].name == "project_b"

    registry_a.remove_project("project_a")
    assert len(registry_a.list_projects()) == 0
    assert len(registry_b.list_projects()) == 1


def test_multi_project_os_starts_and_stops(tmp_path: Path) -> None:
    """Verify MultiProjectOS initializes and manages multiple project runtimes."""
    registry_path = tmp_path / "projects.yaml"
    registry = ProjectRegistry(registry_path)

    config_path = tmp_path / "models.yaml"
    config_path.write_text(
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

    project_root_1 = tmp_path / "proj1"
    project_root_1.mkdir()
    (project_root_1 / "agents").mkdir()
    (project_root_1 / "reviews").mkdir()
    config_1 = ProjectConfig.create("proj1", project_root_1, models_config=config_path)
    registry.add_project(config_1)

    project_root_2 = tmp_path / "proj2"
    project_root_2.mkdir()
    (project_root_2 / "agents").mkdir()
    (project_root_2 / "reviews").mkdir()
    config_2 = ProjectConfig.create("proj2", project_root_2, models_config=config_path)
    registry.add_project(config_2)

    def custom_from_config(config: ProjectConfig, provider_factory: Any = None) -> ProjectOS:
        return ProjectOS(
            config_path=config.models_config,
            provider_factory=lambda agent_name, path: DogfoodMockModelProvider(agent_name, path),
            project_root=config.root_path,
            state_dir=config.state_dir,
            project_name=config.name,
        )

    with patch.object(ProjectOS, "from_project_config", side_effect=custom_from_config):
        multi_os = MultiProjectOS(registry)
        try:
            multi_os.start()
            time.sleep(0.5)

            assert "proj1" in multi_os.instances
            assert "proj2" in multi_os.instances

            # Verify both runs are running
            status = multi_os.status()
            assert status["proj1"]["running"] is True
            assert status["proj2"]["running"] is True
        finally:
            multi_os.stop()


def test_state_and_file_isolation(tmp_path: Path) -> None:
    """Verify that multiple runtimes execute in isolation without leaking state or files."""
    registry_path = tmp_path / "projects.yaml"
    registry = ProjectRegistry(registry_path)

    config_path = tmp_path / "models.yaml"
    config_path.write_text(
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

    project_root_1 = tmp_path / "proj1"
    project_root_1.mkdir()
    (project_root_1 / "agents").mkdir()
    (project_root_1 / "reviews").mkdir()
    (project_root_1 / "tests").mkdir()
    config_1 = ProjectConfig.create("proj1", project_root_1, models_config=config_path)
    registry.add_project(config_1)

    project_root_2 = tmp_path / "proj2"
    project_root_2.mkdir()
    (project_root_2 / "agents").mkdir()
    (project_root_2 / "reviews").mkdir()
    (project_root_2 / "tests").mkdir()
    config_2 = ProjectConfig.create("proj2", project_root_2, models_config=config_path)
    registry.add_project(config_2)

    def custom_from_config(config: ProjectConfig, provider_factory: Any = None) -> ProjectOS:
        return ProjectOS(
            config_path=config.models_config,
            provider_factory=lambda agent_name, path: DogfoodMockModelProvider(agent_name, path),
            project_root=config.root_path,
            state_dir=config.state_dir,
            project_name=config.name,
        )

    with patch.object(ProjectOS, "from_project_config", side_effect=custom_from_config):
        multi_os = MultiProjectOS(registry)
        try:
            # Write file in proj1
            file_1 = project_root_1 / "agents" / "helper1.py"
            file_1.write_text("def run1() -> None: pass", encoding="utf-8")

            multi_os.start()
            time.sleep(0.5)

            instance_1 = multi_os.instances["proj1"]
            instance_2 = multi_os.instances["proj2"]

            # Submit event to proj1
            event = AgentEvent(
                event_type=EventType.CODE_CHANGED,
                source_agent="test_suite",
                payload={"file_path": str(file_1)},
            )
            instance_1.submit_event(event)

            # Wait for instance 1 to become idle
            timeout = 5.0
            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout:
                if instance_1.task_queue.get_pending_count() == 0:
                    break
                time.sleep(0.1)

            # Assert that proj1 got reviews and proj2 did not
            assert len(list((project_root_1 / "reviews").glob("helper1.py*_review.md"))) == 1
            assert len(list((project_root_2 / "reviews").glob("*.md"))) == 0

            # Assert state directories are isolated
            assert (project_root_1 / ".projectos_state").exists()
            assert (project_root_2 / ".projectos_state").exists()

            # Ensure decisions.log in proj2 was not touched by proj1 event
            assert not (project_root_2 / "decisions.log").exists() or (project_root_2 / "decisions.log").read_text(encoding="utf-8") == ""

        finally:
            multi_os.stop()
