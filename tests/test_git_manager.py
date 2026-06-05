"""Unit tests for ProjectOS git integration."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from core.git_manager import GitManager


TEST_BRANCH = "projectos-test"
TEST_FILE_NAME = "example.py"
INITIAL_CONTENT = "value = 1\n"
UPDATED_CONTENT = "value = 2\n"
COMMIT_MESSAGE = "projectos: test commit"


def test_is_git_repo_true_after_init(tmp_path: Path) -> None:
    """Verify GitManager detects an initialized git repository."""
    _init_repo(tmp_path)

    assert GitManager(tmp_path).is_git_repo() is True


def test_is_git_repo_false_without_init(tmp_path: Path) -> None:
    """Verify GitManager returns false outside git repositories."""
    _require_git()

    assert GitManager(tmp_path).is_git_repo() is False


def test_stage_file_succeeds(tmp_path: Path) -> None:
    """Verify stage_file stages an existing file."""
    _init_repo(tmp_path)
    manager = GitManager(tmp_path)
    file_path = _write_file(tmp_path, INITIAL_CONTENT)

    assert manager.stage_file(file_path) is True
    assert _git_stdout(tmp_path, ["diff", "--cached", "--name-only"]) == TEST_FILE_NAME


def test_commit_returns_hash(tmp_path: Path) -> None:
    """Verify commit returns a short commit hash after staging changes."""
    manager = _prepared_manager(tmp_path)
    file_path = _write_file(tmp_path, INITIAL_CONTENT)
    assert manager.stage_file(file_path) is True

    commit_hash = manager.commit(COMMIT_MESSAGE)

    assert commit_hash is not None
    assert len(commit_hash) >= 7


def test_commit_returns_none_when_nothing_staged(tmp_path: Path) -> None:
    """Verify commit returns None when there is nothing staged."""
    manager = _prepared_manager(tmp_path)

    assert manager.commit(COMMIT_MESSAGE) is None


def test_get_diff_returns_empty_on_clean(tmp_path: Path) -> None:
    """Verify get_diff returns empty text for a clean tracked file."""
    manager = _prepared_manager(tmp_path)
    file_path = _write_file(tmp_path, INITIAL_CONTENT)
    assert manager.stage_file(file_path) is True
    assert manager.commit(COMMIT_MESSAGE) is not None

    assert manager.get_diff(file_path) == ""


def test_get_diff_returns_content_after_change(tmp_path: Path) -> None:
    """Verify get_diff returns content after a tracked file changes."""
    manager = _prepared_manager(tmp_path)
    file_path = _write_file(tmp_path, INITIAL_CONTENT)
    assert manager.stage_file(file_path) is True
    assert manager.commit(COMMIT_MESSAGE) is not None
    file_path.write_text(UPDATED_CONTENT, encoding="utf-8")

    diff = manager.get_diff(file_path)

    assert "-value = 1" in diff
    assert "+value = 2" in diff


def _prepared_manager(repo_path: Path) -> GitManager:
    """Initialize a repo and switch to a non-protected branch."""
    _init_repo(repo_path)
    manager = GitManager(repo_path)
    assert manager.create_branch(TEST_BRANCH) is True
    return manager


def _init_repo(repo_path: Path) -> None:
    """Initialize a temporary git repository or skip if git is missing."""
    _require_git()
    _run_git(repo_path, ["init"])


def _write_file(repo_path: Path, content: str) -> Path:
    """Write the shared test source file."""
    file_path = repo_path / TEST_FILE_NAME
    file_path.write_text(content, encoding="utf-8")
    return file_path


def _git_stdout(repo_path: Path, args: list[str]) -> str:
    """Return stdout from a git command."""
    completed_process = _run_git(repo_path, args)
    return completed_process.stdout.strip()


def _run_git(repo_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run git for test setup and assertions."""
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        env=_git_env(),
    )


def _git_env() -> dict[str, str]:
    """Return git identity environment for test commits."""
    env = dict(os.environ)
    env.setdefault("GIT_COMMITTER_NAME", "ProjectOS")
    env.setdefault("GIT_COMMITTER_EMAIL", "projectos@local")
    return env


def _require_git() -> None:
    """Skip tests when git is not installed."""
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        pytest.skip("git is not installed")
