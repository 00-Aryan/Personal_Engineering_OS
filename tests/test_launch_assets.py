"""Tests for ProjectOS launch assets and announcements."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAUNCH_DIR = PROJECT_ROOT / "docs" / "launch"


def test_hackernews_post_exists() -> None:
    """Verify that hackernews_post.md exists and contains Show HN title."""
    hn_file = LAUNCH_DIR / "hackernews_post.md"
    assert hn_file.exists()
    content = hn_file.read_text(encoding="utf-8")
    assert "Show HN" in content
    assert "free tier" in content or "free" in content


def test_reddit_post_exists() -> None:
    """Verify that reddit_post.md exists and contains technical agent details."""
    reddit_file = LAUNCH_DIR / "reddit_post.md"
    assert reddit_file.exists()
    content = reddit_file.read_text(encoding="utf-8")
    assert "LLM-as-a-Judge" in content or "LLM-as-judge" in content
    assert "Semantic Routing" in content or "semantic routing" in content


def test_linkedin_post_exists() -> None:
    """Verify that linkedin_post.md exists and contains professional info."""
    linkedin_file = LAUNCH_DIR / "linkedin_post.md"
    assert linkedin_file.exists()
    content = linkedin_file.read_text(encoding="utf-8")
    assert "IIT Madras" in content


def test_launch_checklist_exists() -> None:
    """Verify that LAUNCH_CHECKLIST.md exists."""
    checklist_file = LAUNCH_DIR / "LAUNCH_CHECKLIST.md"
    assert checklist_file.exists()
    content = checklist_file.read_text(encoding="utf-8")
    assert "Launch Checklist" in content


def test_first_issue_template_exists() -> None:
    """Verify that FIRST_ISSUE.md exists."""
    issue_file = LAUNCH_DIR / "FIRST_ISSUE.md"
    assert issue_file.exists()
    content = issue_file.read_text(encoding="utf-8")
    assert "Good First Issue" in content


def test_hackernews_post_under_500_words() -> None:
    """Verify that the HN Show HN draft body/content is under 500 words."""
    hn_file = LAUNCH_DIR / "hackernews_post.md"
    assert hn_file.exists()
    content = hn_file.read_text(encoding="utf-8")
    words = content.split()
    assert len(words) < 500


def test_linkedin_post_under_200_words() -> None:
    """Verify that the LinkedIn post draft is under 200 words."""
    linkedin_file = LAUNCH_DIR / "linkedin_post.md"
    assert linkedin_file.exists()
    content = linkedin_file.read_text(encoding="utf-8")
    words = content.split()
    # Subtracting frontmatter/title parts if split captures them
    assert len(words) < 200
