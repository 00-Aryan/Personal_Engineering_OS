"""Git integration helpers for ProjectOS audit history."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional


GIT_COMMAND = "git"
GIT_TIMEOUT_SECONDS = 30
PROJECTOS_AUTHOR_NAME = "ProjectOS"
PROJECTOS_AUTHOR_EMAIL = "projectos@local"
PROTECTED_BRANCHES = frozenset({"main", "master"})
LOGGER_NAME = "projectos.git_manager"
LOG_PROTECTED_BRANCH = "commit skipped: protected branch"
LOG_GIT_COMMAND_FAILED = "git command failed: %s"


class GitManager:
    """Small non-raising wrapper around git commands."""

    def __init__(self, repo_path: Path) -> None:
        """Initialize the manager for a repository path."""
        self.repo_path = Path(repo_path)
        self._logger = logging.getLogger(LOGGER_NAME)

    def is_git_repo(self) -> bool:
        """Return whether repo_path is inside a git work tree."""
        completed_process = self._run(
            ["rev-parse", "--is-inside-work-tree"],
            check=False,
        )
        return (
            completed_process is not None
            and completed_process.returncode == 0
            and completed_process.stdout.strip() == "true"
        )

    def stage_file(self, file_path: Path) -> bool:
        """Stage a file path and return False on failure."""
        completed_process = self._run(["add", str(file_path)], check=False)
        return completed_process is not None and completed_process.returncode == 0

    def commit(self, message: str, author: str = PROJECTOS_AUTHOR_NAME) -> Optional[str]:
        """Commit staged changes and return the new short hash when successful."""
        if self._current_branch() in PROTECTED_BRANCHES:
            self._logger.warning(LOG_PROTECTED_BRANCH)
            return None
        if not self._has_staged_changes():
            return None

        completed_process = self._run(
            [
                "commit",
                "-m",
                message,
                "--author",
                f"{author} <{PROJECTOS_AUTHOR_EMAIL}>",
            ],
            check=False,
        )
        if completed_process is None or completed_process.returncode != 0:
            return None
        return self.get_last_commit_hash()

    def get_diff(self, file_path: Path) -> str:
        """Return git diff content for one file, or empty text on failure."""
        completed_process = self._run(
            ["diff", "HEAD", "--", str(file_path)],
            check=False,
        )
        if completed_process is None or completed_process.returncode != 0:
            return ""
        return completed_process.stdout

    def get_last_commit_hash(self) -> Optional[str]:
        """Return the short HEAD hash, or None when unavailable."""
        completed_process = self._run(
            ["rev-parse", "--short", "HEAD"],
            check=False,
        )
        if completed_process is None or completed_process.returncode != 0:
            return None
        commit_hash = completed_process.stdout.strip()
        return commit_hash or None

    def create_branch(self, name: str) -> bool:
        """Create and switch to a new branch, returning False on failure."""
        completed_process = self._run(["checkout", "-b", name], check=False)
        return completed_process is not None and completed_process.returncode == 0

    def _has_staged_changes(self) -> bool:
        """Return whether the git index has staged changes."""
        completed_process = self._run(
            ["diff", "--cached", "--quiet"],
            check=False,
        )
        return completed_process is not None and completed_process.returncode == 1

    def _current_branch(self) -> Optional[str]:
        """Return the current branch name when available."""
        completed_process = self._run(
            ["branch", "--show-current"],
            check=False,
        )
        if completed_process is None or completed_process.returncode != 0:
            return None
        branch_name = completed_process.stdout.strip()
        return branch_name or None

    def _run(
        self,
        args: list[str],
        check: bool,
    ) -> Optional[subprocess.CompletedProcess[str]]:
        """Run one git command without shell expansion and never raise."""
        try:
            return subprocess.run(
                [GIT_COMMAND, *args],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
                check=check,
                env=self._git_env(),
            )
        except Exception as error:
            self._logger.warning(LOG_GIT_COMMAND_FAILED, error)
            return None

    def _git_env(self) -> dict[str, str]:
        """Return environment values needed for local ProjectOS commits."""
        env = dict(os.environ)
        env.setdefault("GIT_COMMITTER_NAME", PROJECTOS_AUTHOR_NAME)
        env.setdefault("GIT_COMMITTER_EMAIL", PROJECTOS_AUTHOR_EMAIL)
        return env


__all__ = ["GitManager"]
