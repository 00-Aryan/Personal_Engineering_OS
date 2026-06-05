"""Unit tests for ProjectOS multi-project registry."""

from __future__ import annotations

from pathlib import Path

from core.project_config import ProjectConfig, ProjectRegistry


CONFIG_FILE = "projects.yaml"
PROJECT_NAME = "example"
MISSING_PROJECT = "missing"
WATCH_PATTERNS = ["*.py", "*.md"]
IGNORE_PATTERNS = [".git", "__pycache__"]


def test_add_and_list_project(tmp_path: Path) -> None:
    """Verify a project can be added and listed from the registry."""
    registry = ProjectRegistry(tmp_path / CONFIG_FILE)
    project_root = tmp_path / "repo"
    project_root.mkdir()
    project_config = ProjectConfig(
        name=PROJECT_NAME,
        root_path=project_root,
        watch_patterns=WATCH_PATTERNS,
        ignore_patterns=IGNORE_PATTERNS,
    )

    registry.add_project(project_config)

    projects = registry.list_projects()
    assert len(projects) == 1
    assert projects[0].name == PROJECT_NAME
    assert projects[0].root_path == project_root.resolve()
    assert projects[0].state_dir == project_root.resolve() / ".projectos_state"


def test_remove_project(tmp_path: Path) -> None:
    """Verify removing a project deletes it from the registry."""
    registry = ProjectRegistry(tmp_path / CONFIG_FILE)
    project_root = tmp_path / "repo"
    project_root.mkdir()
    registry.add_project(
        ProjectConfig(
            name=PROJECT_NAME,
            root_path=project_root,
            watch_patterns=WATCH_PATTERNS,
            ignore_patterns=IGNORE_PATTERNS,
        )
    )

    registry.remove_project(PROJECT_NAME)

    assert registry.list_projects() == []


def test_get_project_returns_none_for_missing(tmp_path: Path) -> None:
    """Verify missing project lookup returns None."""
    registry = ProjectRegistry(tmp_path / CONFIG_FILE)

    assert registry.get_project(MISSING_PROJECT) is None


def test_disabled_project_not_in_list(tmp_path: Path) -> None:
    """Verify disabled projects are not returned by list_projects."""
    registry = ProjectRegistry(tmp_path / CONFIG_FILE)
    project_root = tmp_path / "repo"
    project_root.mkdir()
    registry.add_project(
        ProjectConfig(
            name=PROJECT_NAME,
            root_path=project_root,
            watch_patterns=WATCH_PATTERNS,
            ignore_patterns=IGNORE_PATTERNS,
            enabled=False,
        )
    )

    assert registry.list_projects() == []
    assert registry.get_project(PROJECT_NAME) is None


def test_config_file_created_if_missing(tmp_path: Path) -> None:
    """Verify registry initialization creates the config file."""
    config_path = tmp_path / CONFIG_FILE

    ProjectRegistry(config_path)

    assert config_path.exists()
