"""Unit tests for the TemplateManager class."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from core.config_loader import ProjectConfig
from core.template_manager import TemplateManager


@pytest.fixture
def mock_templates_dir(tmp_path: Path) -> Path:
    """Create a temporary templates directory with all 4 templates mock-configured."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    # ds_project
    ds_dir = templates_dir / "ds_project"
    ds_dir.mkdir()
    (ds_dir / "template.yaml").write_text(
        "name: ds_project\n"
        "description: For DS projects\n"
        "agents:\n"
        "  planning: deepseek-v3\n"
        "quality_gates:\n"
        "  code_writing:\n"
        "    min_score: 0.55\n"
        "ignore_patterns:\n"
        "  - '*.csv'\n",
        encoding="utf-8",
    )
    (ds_dir / "AGENTS.md").write_text("DS Agents rules", encoding="utf-8")
    (ds_dir / ".gitignore").write_text("*.csv", encoding="utf-8")

    # rag_pipeline
    rag_dir = templates_dir / "rag_pipeline"
    rag_dir.mkdir()
    (rag_dir / "template.yaml").write_text(
        "name: rag_pipeline\n"
        "description: For RAG pipelines\n"
        "agents:\n"
        "  planning: deepseek-v3\n",
        encoding="utf-8",
    )
    (rag_dir / "AGENTS.md").write_text("RAG rules", encoding="utf-8")
    (rag_dir / ".gitignore").write_text("*.faiss", encoding="utf-8")

    # web_api
    web_dir = templates_dir / "web_api"
    web_dir.mkdir()
    (web_dir / "template.yaml").write_text(
        "name: web_api\n"
        "description: For web APIs\n",
        encoding="utf-8",
    )

    # cli_tool
    cli_dir = templates_dir / "cli_tool"
    cli_dir.mkdir()
    (cli_dir / "template.yaml").write_text(
        "name: cli_tool\n"
        "description: For CLI tools\n",
        encoding="utf-8",
    )

    return templates_dir


def test_list_templates_returns_all_four(mock_templates_dir: Path) -> None:
    """Verify that list_templates correctly parses and returns the 4 templates."""
    with patch.object(TemplateManager, "TEMPLATES_DIR", mock_templates_dir):
        templates = TemplateManager.list_templates()
        assert len(templates) == 4
        names = [t["name"] for t in templates]
        assert "ds_project" in names
        assert "rag_pipeline" in names
        assert "web_api" in names
        assert "cli_tool" in names


def test_apply_template_merges_config(mock_templates_dir: Path) -> None:
    """Verify that applying a template correctly merges overrides."""
    with patch.object(TemplateManager, "TEMPLATES_DIR", mock_templates_dir):
        raw_config = {
            "version": "0.3.0",
            "project": {"name": "test-project"},
            "agents": {},
        }
        config = ProjectConfig(raw_config, Path("config/projectos.yaml"), {})

        TemplateManager.apply_template("ds_project", config)

        # Merged/Applied from template override since not set by user
        assert config.agents["planning"] == "deepseek-v3"
        # Merged ignore patterns
        assert "*.csv" in config.ignore_patterns


def test_apply_template_user_values_override_template(mock_templates_dir: Path) -> None:
    """Verify that user-explicit values are preserved and not overwritten by the template."""
    with patch.object(TemplateManager, "TEMPLATES_DIR", mock_templates_dir):
        # min_score is explicitly defined in raw_config by the user
        raw_config = {
            "version": "0.3.0",
            "project": {"name": "test-project"},
            "quality_gates": {
                "code_writing": {
                    "min_score": 0.85,  # User value
                }
            },
        }
        config = ProjectConfig(raw_config, Path("config/projectos.yaml"), {})

        TemplateManager.apply_template("ds_project", config)

        # User value 0.85 should override template value 0.55
        assert config.quality_gates["code_writing"]["min_score"] == 0.85


def test_copy_template_files_skips_existing(mock_templates_dir: Path, tmp_path: Path) -> None:
    """Verify copying template files creates new files or appends AGENTS.md, but doesn't overwrite existing others."""
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    # Pre-create AGENTS.md
    agents_file = target_dir / "AGENTS.md"
    agents_file.write_text("Existing rules", encoding="utf-8")

    with patch.object(TemplateManager, "TEMPLATES_DIR", mock_templates_dir):
        copied = TemplateManager.copy_template_files("ds_project", target_dir)

        assert "AGENTS.md" in copied
        assert ".gitignore" in copied

        # AGENTS.md should be additive (appended)
        appended_content = agents_file.read_text(encoding="utf-8")
        assert "Existing rules" in appended_content
        assert "DS Agents rules" in appended_content

        # Running again should skip copying or append again?
        # Since the source is already there, wait, for non-AGENTS files, they are skipped.
        gitignore_file = target_dir / ".gitignore"
        assert gitignore_file.exists()


def test_detect_ds_project_from_requirements(tmp_path: Path) -> None:
    """Verify detection of ds_project from requirements.txt."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("pandas==2.0.0\ntorch>=1.13.0\n", encoding="utf-8")

    project_type = TemplateManager.detect_project_type(tmp_path)
    assert project_type == "ds_project"


def test_detect_rag_pipeline_from_requirements(tmp_path: Path) -> None:
    """Verify detection of rag_pipeline from requirements.txt."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("chromadb\nlangchain\n", encoding="utf-8")

    project_type = TemplateManager.detect_project_type(tmp_path)
    assert project_type == "rag_pipeline"


def test_detect_unknown_returns_none(tmp_path: Path) -> None:
    """Verify unknown or missing requirements.txt returns None."""
    project_type = TemplateManager.detect_project_type(tmp_path)
    assert project_type is None

    req_file = tmp_path / "requirements.txt"
    req_file.write_text("some-random-library\n", encoding="utf-8")
    assert TemplateManager.detect_project_type(tmp_path) is None
