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
    assert "## Agent Roster" in content or "## Agents" in content


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


def test_readme_under_700_words_body() -> None:
    """Verify README.md body text is under 700 words (headings, tables, and code blocks excluded)."""
    readme_path = Path("README.md")
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    
    # Strip code blocks
    content_no_code = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
    
    # Process line by line
    body_lines = []
    for line in content_no_code.splitlines():
        stripped = line.strip()
        # Exclude headers
        if stripped.startswith("#"):
            continue
        # Exclude table rows (lines starting/ending with | or having | in them like separator lines)
        if stripped.startswith("|") or (stripped.startswith(":") and "|" in stripped) or (stripped.startswith("-") and "|" in stripped):
            continue
        # Also exclude badge lines or links that are purely links (like [![CI Status]...)
        if re.match(r"^\[\!\[", stripped) or re.match(r"^\[", stripped):
            continue
        body_lines.append(stripped)
        
    body_text = " ".join(body_lines)
    # Strip HTML comments
    body_text = re.sub(r"<!--.*?-->", "", body_text, flags=re.DOTALL)
    # Strip standard markdown links formatting [text](url) -> text
    body_text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", body_text)
    
    words = [w for w in re.split(r"\s+", body_text) if w]
    word_count = len(words)
    assert word_count <= 700, f"README has {word_count} body words, which exceeds the 700-word limit."


def test_known_limitations_file_exists() -> None:
    """Verify KNOWN_LIMITATIONS.md exists in the root directory."""
    path = Path("KNOWN_LIMITATIONS.md")
    assert path.exists()


def test_future_scope_file_exists() -> None:
    """Verify FUTURE_SCOPE.md exists in the root directory."""
    path = Path("FUTURE_SCOPE.md")
    assert path.exists()


def test_readme_has_honest_limitations_section() -> None:
    """Verify README.md contains an Honest Limitations section."""
    readme_path = Path("README.md")
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    assert "## Honest Limitations" in content


def test_readme_does_not_mention_internal_build_process() -> None:
    """Verify README.md does not contain references to tasks, phases, AGY, or Codex."""
    readme_path = Path("README.md")
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    forbidden = ["task_", "phase ", "internal build", "agy", "codex"]
    for word in forbidden:
        assert word not in content.lower(), f"README contains forbidden term: {word}"


def test_readme_has_telegram_commands_section() -> None:
    """Verify README.md contains a Telegram Commands section."""
    readme_path = Path("README.md")
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    assert "Telegram Commands" in content
