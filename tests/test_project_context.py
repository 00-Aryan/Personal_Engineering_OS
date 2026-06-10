"""Tests for project context loading, parsing, and base agent prompt injection."""

from pathlib import Path
import pytest
from unittest.mock import MagicMock

from core.project_context import ProjectContext, ProjectContextLoader
from core.base_agent import BaseAgent
from core.events import AgentEvent, AgentResult
from core.model_provider import ModelProvider


class DummyAgent(BaseAgent):
    """Dummy agent subclass for testing BaseAgent functionality."""

    SYSTEM_PROMPT = "Role prompt.\n{project_context}"

    def handle(self, event: AgentEvent) -> AgentResult:
        return AgentResult(success=True, output={})


def test_load_returns_none_when_no_file(tmp_path):
    """Verify load returns None when no context file exists."""
    loader = ProjectContextLoader(tmp_path)
    assert loader.load() is None


def test_load_parses_description_section(tmp_path):
    """Verify description and domain sections are correctly parsed."""
    file_path = tmp_path / "project_description.md"
    file_path.write_text(
        "# My Test Project\n\n"
        "## Description\n"
        "This is a test description.\n"
        "It has multiple lines.\n\n"
        "## Domain\n"
        "Test domain.\n",
        encoding="utf-8"
    )
    loader = ProjectContextLoader(tmp_path)
    context = loader.load()
    assert context is not None
    assert context.project_name == "My Test Project"
    assert context.description == "This is a test description.\nIt has multiple lines."
    assert context.domain == "Test domain."


def test_load_parses_tech_stack_list(tmp_path):
    """Verify list sections like tech stack are parsed into lists."""
    file_path = tmp_path / "project_description.md"
    file_path.write_text(
        "# Test Stack Project\n\n"
        "## Tech Stack\n"
        "- Python 3.12\n"
        "- FastAPI\n"
        "- Supabase\n",
        encoding="utf-8"
    )
    loader = ProjectContextLoader(tmp_path)
    context = loader.load()
    assert context is not None
    assert context.tech_stack == ["Python 3.12", "FastAPI", "Supabase"]
    assert context.primary_language == "Python 3.12"



def test_load_returns_none_on_malformed_file(tmp_path):
    """Verify None is returned without crashing on malformed files (missing name)."""
    file_path = tmp_path / "project_description.md"
    file_path.write_text(
        "## Description\n"
        "Missing project name header.\n",
        encoding="utf-8"
    )
    loader = ProjectContextLoader(tmp_path)
    assert loader.load() is None


def test_to_system_prompt_injection_format():
    """Verify ProjectContext formatting matches the specified format."""
    context = ProjectContext(
        project_name="TestProj",
        description="Test Desc",
        tech_stack=["Python", "FastAPI"],
        primary_language="Python",
        domain="Test Domain",
        key_files=["src/main.py"],
        conventions=["Use dataclasses"],
        constraints=["Free Gemini tier"],
        context_file_path="project_description.md"
    )
    expected = (
        "--- PROJECT CONTEXT ---\n"
        "Project: TestProj\n"
        "Domain: Test Domain\n"
        "Tech Stack: Python, FastAPI\n"
        "Key Files: src/main.py\n"
        "Conventions: Use dataclasses\n"
        "Constraints: Free Gemini tier\n"
        "--- END CONTEXT ---"
    )
    assert ProjectContextLoader.to_system_prompt_injection(context) == expected


def test_create_template_writes_valid_file(tmp_path):
    """Verify template creation writes a valid md file that can be parsed."""
    output_path = tmp_path / "project_description.md"
    loader = ProjectContextLoader(tmp_path)
    loader.create_template(output_path)
    assert output_path.exists()

    context = loader.load()
    assert context is not None
    assert context.project_name == "Project Name"
    assert "FastAPI" in context.tech_stack


def test_base_agent_injects_context_into_prompt(tmp_path):
    """Verify BaseAgent injects project context when context loader is provided."""
    file_path = tmp_path / "project_description.md"
    file_path.write_text(
        "# AgentProj\n\n"
        "## Domain\n"
        "Agent Testing\n",
        encoding="utf-8"
    )
    mock_provider = MagicMock(spec=ModelProvider)
    mock_logger = MagicMock()
    loader = ProjectContextLoader(tmp_path)

    agent = DummyAgent(
        name="dummy",
        role_description="Test dummy agent",
        model_provider=mock_provider,
        logger=mock_logger,
        context_loader=loader
    )

    system_prompt = agent.build_system_prompt(agent.SYSTEM_PROMPT)
    assert "Role prompt." in system_prompt
    assert "--- PROJECT CONTEXT ---" in system_prompt
    assert "Project: AgentProj" in system_prompt
    assert "Domain: Agent Testing" in system_prompt


def test_base_agent_handles_missing_context_loader():
    """Verify BaseAgent replaces placeholder with empty string when loader is missing."""
    mock_provider = MagicMock(spec=ModelProvider)
    mock_logger = MagicMock()

    agent = DummyAgent(
        name="dummy",
        role_description="Test dummy agent",
        model_provider=mock_provider,
        logger=mock_logger,
        context_loader=None
    )

    system_prompt = agent.build_system_prompt(agent.SYSTEM_PROMPT)
    assert system_prompt == "Role prompt.\n"


def test_load_finds_project_context_md_filename(tmp_path):
    """Verify that project_context.md is loaded if project_description.md is missing."""
    file_path = tmp_path / "project_context.md"
    file_path.write_text(
        "# Project Context File\n\n"
        "## Description\n"
        "Alternative context file content.\n",
        encoding="utf-8"
    )
    loader = ProjectContextLoader(tmp_path)
    context = loader.load()
    assert context is not None
    assert context.project_name == "Project Context File"
    assert context.description == "Alternative context file content."
    assert context.context_file_path == str(file_path)


def test_load_truncates_files_over_word_limit(tmp_path):
    """Verify that file is truncated to WORD_LIMIT (2000) words before parsing."""
    words = ["word"] * 2005
    description_content = " ".join(words)
    file_path = tmp_path / "project_description.md"
    file_path.write_text(
        "# Large Project\n\n"
        "## Description\n"
        f"{description_content}\n",
        encoding="utf-8"
    )
    loader = ProjectContextLoader(tmp_path)
    context = loader.load()
    assert context is not None
    parsed_words = context.description.split()
    assert len(parsed_words) < 2005
    # Word count includes "#", "Large", "Project", "##", "Description" (5 words).
    # Remaining capacity is 1995 words.
    assert len(parsed_words) == 1995


def test_to_system_prompt_injection_format_multiple_items():
    """Verify ProjectContext formatting with multiple conventions and constraints."""
    context = ProjectContext(
        project_name="TestProj",
        description="Test Desc",
        tech_stack=["Python", "FastAPI"],
        primary_language="Python",
        domain="Test Domain",
        key_files=["src/main.py", "src/utils.py"],
        conventions=["Use dataclasses", "Always use uv"],
        constraints=["Free Gemini tier", "Under 120 lines"],
        context_file_path="project_description.md"
    )
    expected = (
        "--- PROJECT CONTEXT ---\n"
        "Project: TestProj\n"
        "Domain: Test Domain\n"
        "Tech Stack: Python, FastAPI\n"
        "Key Files: src/main.py, src/utils.py\n"
        "Conventions: Use dataclasses | Always use uv\n"
        "Constraints: Free Gemini tier | Under 120 lines\n"
        "--- END CONTEXT ---"
    )
    assert ProjectContextLoader.to_system_prompt_injection(context) == expected

