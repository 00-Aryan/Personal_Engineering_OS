"""Tests verifying correctness and structure of ProjectOS documentation files."""

from __future__ import annotations

import re
from pathlib import Path


def test_readme_under_800_lines() -> None:
    """Verify README.md exists and is well within the 800 line limit."""
    readme_path = Path("README.md")
    assert readme_path.exists()
    lines = readme_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) < 800


def test_readme_has_quick_start_section() -> None:
    """Verify README.md contains a Quick Start section."""
    readme_path = Path("README.md")
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    assert "## Quick Start" in content or "## Setup" in content


def test_readme_has_agent_roster_section() -> None:
    """Verify README.md contains an Agent Roster section."""
    readme_path = Path("README.md")
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    assert "## Agent Roster" in content


def test_faq_has_eight_questions() -> None:
    """Verify FAQ.md exists and contains exactly 8 questions."""
    faq_path = Path("docs/FAQ.md")
    assert faq_path.exists()
    content = faq_path.read_text(encoding="utf-8")
    
    # Match markdown headers starting with numbers, e.g., "### 1." or "### 1. Does it work..."
    questions = re.findall(r"^###\s+\d+\.", content, flags=re.MULTILINE)
    assert len(questions) == 8


def test_demo_script_exists() -> None:
    """Verify docs/DEMO_SCRIPT.md exists and contains expected headings."""
    demo_path = Path("docs/DEMO_SCRIPT.md")
    assert demo_path.exists()
    content = demo_path.read_text(encoding="utf-8")
    assert "# ProjectOS Demo" in content
    assert "## Demo Sequence" in content


def test_issue_templates_exist() -> None:
    """Verify bug report and feature request templates exist under .github/."""
    bug_path = Path(".github/ISSUE_TEMPLATE/bug_report.md")
    feat_path = Path(".github/ISSUE_TEMPLATE/feature_request.md")
    assert bug_path.exists()
    assert feat_path.exists()


def test_pr_template_exists() -> None:
    """Verify pull request template exists under .github/."""
    pr_path = Path(".github/PULL_REQUEST_TEMPLATE.md")
    assert pr_path.exists()
    content = pr_path.read_text(encoding="utf-8")
    assert "## Checklist" in content
