"""Unit tests for ProjectOS write safety policies."""

from __future__ import annotations

from pathlib import Path

from core.safety import (
    DefaultSafetyPolicy,
    SafetyPolicy,
    REASON_ALLOWED,
    REASON_OUTSIDE_ALLOWED_DIRS,
    REASON_OVERSIZED_CONTENT,
    REASON_PROTECTED_FILE,
    WARNING_LARGE_DELETION,
)


ENCODING = "utf-8"
SMALL_CONTENT = "value = 1\n"
UPDATED_CONTENT = "value = 2\n"
OVERSIZED_CONTENT = "x" * 11


def test_write_to_allowed_dir_passes(tmp_path: Path) -> None:
    """Verify writes inside allowed directories are permitted."""
    allowed_dir = tmp_path / "agents"
    allowed_dir.mkdir()
    policy = SafetyPolicy([allowed_dir], [])

    result = policy.validate_write(allowed_dir / "new_agent.py", SMALL_CONTENT)

    assert result.allowed is True
    assert result.reason == REASON_ALLOWED


def test_write_outside_allowed_dir_blocked(tmp_path: Path) -> None:
    """Verify writes outside allowed directories are blocked."""
    policy = SafetyPolicy([tmp_path / "agents"], [])

    result = policy.validate_write(tmp_path / "outside.py", SMALL_CONTENT)

    assert result.allowed is False
    assert result.reason == REASON_OUTSIDE_ALLOWED_DIRS


def test_write_to_protected_file_blocked(tmp_path: Path) -> None:
    """Verify protected files are blocked even inside allowed directories."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    protected_file = config_dir / "models.yaml"
    protected_file.write_text("model: old\n", encoding=ENCODING)
    policy = SafetyPolicy([config_dir], [protected_file])

    result = policy.validate_write(protected_file, "model: new\n")

    assert result.allowed is False
    assert result.reason == REASON_PROTECTED_FILE


def test_oversized_content_blocked(tmp_path: Path) -> None:
    """Verify content over the configured size limit is blocked."""
    allowed_dir = tmp_path / "tests"
    allowed_dir.mkdir()
    policy = SafetyPolicy([allowed_dir], [], max_file_size_bytes=10)

    result = policy.validate_write(allowed_dir / "test_big.py", OVERSIZED_CONTENT)

    assert result.allowed is False
    assert result.reason == REASON_OVERSIZED_CONTENT


def test_large_deletion_generates_warning(tmp_path: Path) -> None:
    """Verify deleting more than half of existing lines creates a warning."""
    allowed_dir = tmp_path / "docs"
    allowed_dir.mkdir()
    file_path = allowed_dir / "guide.md"
    file_path.write_text("a\nb\nc\nd\n", encoding=ENCODING)
    policy = SafetyPolicy([allowed_dir], [])

    result = policy.validate_write(file_path, "a\n")

    assert result.allowed is True
    assert result.warnings == [WARNING_LARGE_DELETION]


def test_core_file_generates_diff_preview(tmp_path: Path) -> None:
    """Verify core files always produce a unified diff preview."""
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    file_path = core_dir / "sample.py"
    file_path.write_text("value = 1\n", encoding=ENCODING)
    policy = SafetyPolicy([core_dir], [], require_diff_preview=False)

    result = policy.validate_write(file_path, UPDATED_CONTENT)

    assert result.allowed is True
    assert result.diff_preview is not None
    assert "---" in result.diff_preview
    assert "+++" in result.diff_preview
    assert "-value = 1" in result.diff_preview
    assert "+value = 2" in result.diff_preview


def test_nonexistent_file_no_diff_generated(tmp_path: Path) -> None:
    """Verify missing files do not generate diff previews."""
    allowed_dir = tmp_path / "reviews"
    allowed_dir.mkdir()
    policy = SafetyPolicy([allowed_dir], [])

    result = policy.validate_write(allowed_dir / "new.md", SMALL_CONTENT)

    assert result.allowed is True
    assert result.diff_preview is None


def test_default_policy_blocks_core_base_agent(tmp_path: Path) -> None:
    """Verify DefaultSafetyPolicy protects core/base_agent.py."""
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    base_agent_path = core_dir / "base_agent.py"
    base_agent_path.write_text("class BaseAgent:\n    pass\n", encoding=ENCODING)
    policy = DefaultSafetyPolicy(tmp_path)

    result = policy.validate_write(base_agent_path, "class BaseAgent:\n    ...\n")

    assert result.allowed is False
    assert result.reason == REASON_OUTSIDE_ALLOWED_DIRS
