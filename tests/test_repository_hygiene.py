"""Tests for repository hygiene and open source standards."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_security_md_exists() -> None:
    """Verify that SECURITY.md exists and contains expected email and content."""
    security_file = PROJECT_ROOT / "SECURITY.md"
    assert security_file.exists()
    content = security_file.read_text(encoding="utf-8")
    assert "22f2000697@ds.study.iitm.ac.in" in content
    assert "Security Policy" in content


def test_changelog_md_exists() -> None:
    """Verify docs/CHANGELOG.md exists and contains Keep a Changelog details."""
    changelog_file = PROJECT_ROOT / "docs" / "CHANGELOG.md"
    assert changelog_file.exists()
    content = changelog_file.read_text(encoding="utf-8")
    assert "Changelog" in content
    assert "Keep a Changelog" in content
    assert "[0.5.0]" in content
    assert "[0.4.0]" in content
    assert "[0.3.0]" in content
    assert "[0.2.0]" in content
    assert "[0.1.0]" in content


def test_repository_yaml_exists() -> None:
    """Verify that .github/repository.yaml exists and has expected metadata."""
    repo_file = PROJECT_ROOT / ".github" / "repository.yaml"
    assert repo_file.exists()
    content = repo_file.read_text(encoding="utf-8")
    assert "name: Personal_Engineering_OS" in content
    assert "ai-agents" in content


def test_github_actions_ci_yml_exists() -> None:
    """Verify that .github/workflows/ci.yml exists."""
    ci_file = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists()


def test_license_file_exists() -> None:
    """Verify that LICENSE exists."""
    license_file = PROJECT_ROOT / "LICENSE"
    assert license_file.exists()


def test_readme_has_ci_badge() -> None:
    """Verify that README.md has a valid CI badge URL."""
    readme_file = PROJECT_ROOT / "README.md"
    assert readme_file.exists()
    content = readme_file.read_text(encoding="utf-8")
    assert "https://github.com/00-Aryan/Personal_Engineering_OS/actions/workflows/ci.yml/badge.svg" in content


def test_all_issue_templates_exist() -> None:
    """Verify that bug report and feature request templates exist under .github/ISSUE_TEMPLATE/."""
    issue_dir = PROJECT_ROOT / ".github" / "ISSUE_TEMPLATE"
    assert issue_dir.is_dir()
    
    bug_report = issue_dir / "bug_report.md"
    feature_request = issue_dir / "feature_request.md"
    
    assert bug_report.exists()
    assert feature_request.exists()
