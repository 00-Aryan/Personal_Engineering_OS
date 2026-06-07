"""Open-source readiness checks for ProjectOS."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LICENSE_FILE = "LICENSE"
CONTRIBUTING_FILE = "CONTRIBUTING.md"
PYPROJECT_FILE = "pyproject.toml"
README_FILE = "README.md"
SMOKE_TEST_FILE = "smoke_test.py"
ENCODING = "utf-8"

PROJECT_KEY = "project"
VERSION_KEY = "version"
DESCRIPTION_KEY = "description"
EXPECTED_VERSION = "0.5.0"
EXPECTED_DESCRIPTION = (
    "Personal Engineering OS — autonomous multi-agent system for software "
    "project management"
)
QUICKSTART_HEADING = "## Quick Start"
CI_FLAG = "--ci"
CI_SMOKE_PASSED = "CI SMOKE: PASSED"
PYTHONDONTWRITEBYTECODE = "PYTHONDONTWRITEBYTECODE"

AGENT_MODULES = (
    "agents.architecture_agent",
    "agents.code_review_agent",
    "agents.code_writing_agent",
    "agents.docs_agent",
    "agents.planning_agent",
    "agents.test_agent",
)


def test_license_file_exists() -> None:
    """Verify the repository has a license file."""
    assert (PROJECT_ROOT / LICENSE_FILE).exists()


def test_contributing_md_exists() -> None:
    """Verify the repository has contributor documentation."""
    assert (PROJECT_ROOT / CONTRIBUTING_FILE).exists()


def test_pyproject_has_version() -> None:
    """Verify pyproject.toml declares the open-source version."""
    project = _pyproject()[PROJECT_KEY]

    assert project[VERSION_KEY] == EXPECTED_VERSION


def test_pyproject_has_description() -> None:
    """Verify pyproject.toml declares the required project description."""
    project = _pyproject()[PROJECT_KEY]

    assert project[DESCRIPTION_KEY] == EXPECTED_DESCRIPTION


def test_readme_has_quickstart_section() -> None:
    """Verify README.md keeps the quick-start section."""
    readme = (PROJECT_ROOT / README_FILE).read_text(encoding=ENCODING)

    assert QUICKSTART_HEADING in readme


def test_all_agents_importable() -> None:
    """Verify all public agent modules import cleanly."""
    for module_name in AGENT_MODULES:
        assert importlib.import_module(module_name) is not None


def test_smoke_test_exits_zero() -> None:
    """Verify smoke_test.py --ci exits cleanly and prints the CI marker."""
    env = dict(os.environ)
    env[PYTHONDONTWRITEBYTECODE] = "1"

    completed_process = subprocess.run(
        [sys.executable, SMOKE_TEST_FILE, CI_FLAG],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed_process.returncode == 0
    assert CI_SMOKE_PASSED in completed_process.stdout


def _pyproject() -> dict[str, Any]:
    """Read pyproject.toml as a Python mapping."""
    return tomllib.loads(
        (PROJECT_ROOT / PYPROJECT_FILE).read_text(encoding=ENCODING)
    )
