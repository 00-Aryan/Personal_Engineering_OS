import pytest
from core.pre_write_validator import PreWriteValidator, ValidationResult

def test_valid_python_passes_syntax_check() -> None:
    validator = PreWriteValidator()
    result = validator.validate(
        proposed_content="def hello():\n    return 'world'\n",
        task_description="Implement hello world function",
        target_file_path="hello.py",
    )
    assert result.valid
    assert result.check_name == ""
    assert result.action == "WRITE"

def test_invalid_python_fails_syntax_check() -> None:
    validator = PreWriteValidator()
    result = validator.validate(
        proposed_content="def hello(\n",
        task_description="Implement hello world function",
        target_file_path="hello.py",
    )
    assert not result.valid
    assert result.check_name == "syntax"
    assert result.action == "RETRY_ONCE"
    assert "Syntax error" in result.reason

def test_new_file_over_150_lines_discarded() -> None:
    validator = PreWriteValidator(max_new_file_lines=150)
    proposed = "line\n" * 151
    result = validator.validate(
        proposed_content=proposed,
        task_description="Create a long script to parse files",
        target_file_path="hello.py",
        existing_content=None,
    )
    assert not result.valid
    assert result.check_name == "size"
    assert result.action == "DISCARD"

def test_existing_file_size_ratio_discarded() -> None:
    validator = PreWriteValidator(max_size_ratio=2.5)
    existing = "line1\nline2\nline3\nline4\n"
    proposed = "line\n" * 11
    result = validator.validate(
        proposed_content=proposed,
        task_description="Modify existing script to parse files",
        target_file_path="hello.py",
        existing_content=existing,
    )
    assert not result.valid
    assert result.check_name == "size_ratio"
    assert result.action == "DISCARD"

def test_relevant_output_passes_relevance_check() -> None:
    validator = PreWriteValidator()
    task = "implement AST parsing module"
    proposed = "def run_parsing():\n    # custom module\n    pass\n"
    result = validator.validate(
        proposed_content=proposed,
        task_description=task,
        target_file_path="hello.py",
    )
    assert result.valid

def test_irrelevant_output_fails_relevance_check() -> None:
    validator = PreWriteValidator()
    task = "implement AST parsing module"
    proposed = "def hello():\n    return 'world'\n"
    result = validator.validate(
        proposed_content=proposed,
        task_description=task,
        target_file_path="hello.py",
    )
    assert not result.valid
    assert result.check_name == "relevance"
    assert result.action == "DISCARD"

def test_vague_task_skips_relevance_check() -> None:
    validator = PreWriteValidator()
    task = "do it"
    proposed = "def hello():\n    return 'world'\n"
    result = validator.validate(
        proposed_content=proposed,
        task_description=task,
        target_file_path="hello.py",
    )
    assert result.valid

def test_non_python_file_skips_syntax_check() -> None:
    validator = PreWriteValidator()
    proposed = "def hello(\n# Update documentation for helper"
    result = validator.validate(
        proposed_content=proposed,
        task_description="Update documentation for helper",
        target_file_path="README.md",
    )
    assert result.valid

def test_retry_prompt_includes_failure_reason() -> None:
    validator = PreWriteValidator()
    original_prompt = "Generate the code."

    res_syntax = ValidationResult(
        valid=False,
        reason="Syntax error: invalid syntax",
        check_name="syntax",
        original_size=0,
        output_size=1,
        action="RETRY_ONCE",
    )
    prompt_syntax = validator.retry_with_constraint(original_prompt, res_syntax)
    assert "CRITICAL: Previous output had syntax error: Syntax error: invalid syntax. Output valid Python only." in prompt_syntax

    res_size = ValidationResult(
        valid=False,
        reason="Exceeds max lines",
        check_name="size",
        original_size=0,
        output_size=200,
        action="DISCARD",
    )
    prompt_size = validator.retry_with_constraint(original_prompt, res_size)
    assert f"CRITICAL: Output must be under {validator.max_new_file_lines} lines. Be concise." in prompt_size

    res_relevance = ValidationResult(
        valid=False,
        reason="Low relevance",
        check_name="relevance",
        original_size=0,
        output_size=5,
        action="DISCARD",
    )
    prompt_relevance = validator.retry_with_constraint(
        original_prompt,
        res_relevance,
        task_description="build the parser module",
    )
    assert "CRITICAL: Output must specifically address: build the parser module. Stay focused." in prompt_relevance


def test_code_writing_agent_proceeds_on_valid_output(tmp_path) -> None:
    import logging
    from unittest.mock import MagicMock
    from agents.code_writing_agent import CodeWritingAgent
    from core.events import AgentEvent, EventType

    logger = logging.getLogger("test")
    model_provider = MagicMock()
    model_provider.complete.return_value = "def run_parsing():\n    # custom module\n    pass\n"

    agent = CodeWritingAgent(
        model_provider=model_provider,
        logger=logger,
        project_root=tmp_path,
    )

    event = AgentEvent(
        event_type=EventType.CODE_WRITTEN,
        source_agent="planning",
        payload={
            "task_id": "task-123",
            "file_path": "dummy.py",
            "task_description": "implement AST parsing module",
            "acceptance_criteria": ["criteria 1"],
        }
    )

    result = agent.handle(event)

    assert result.success is True
    assert (tmp_path / "dummy.py").exists()
    assert (tmp_path / "dummy.py").read_text() == "def run_parsing():\n    # custom module\n    pass\n"
    model_provider.complete.assert_called_once()


def test_code_writing_agent_discards_on_validation_failure(tmp_path) -> None:
    import logging
    from unittest.mock import MagicMock
    from agents.code_writing_agent import CodeWritingAgent
    from core.events import AgentEvent, EventType

    logger = logging.getLogger("test")
    model_provider = MagicMock()
    model_provider.complete.return_value = "def hello():\n    return 'world'\n"

    agent = CodeWritingAgent(
        model_provider=model_provider,
        logger=logger,
        project_root=tmp_path,
    )

    event = AgentEvent(
        event_type=EventType.CODE_WRITTEN,
        source_agent="planning",
        payload={
            "task_id": "task-123",
            "file_path": "dummy.py",
            "task_description": "implement AST parsing module",
            "acceptance_criteria": ["criteria 1"],
        }
    )

    result = agent.handle(event)

    assert result.success is False
    assert result.escalate is True
    assert "discarded" in result.output
    assert not (tmp_path / "dummy.py").exists()
    model_provider.complete.assert_called_once()


def test_code_writing_agent_retries_on_syntax_error(tmp_path) -> None:
    import logging
    from unittest.mock import MagicMock
    from agents.code_writing_agent import CodeWritingAgent
    from core.events import AgentEvent, EventType

    logger = logging.getLogger("test")
    model_provider = MagicMock()
    model_provider.complete.side_effect = [
        "def run_parsing(\n",
        "def run_parsing():\n    # custom module\n    pass\n"
    ]

    agent = CodeWritingAgent(
        model_provider=model_provider,
        logger=logger,
        project_root=tmp_path,
    )

    event = AgentEvent(
        event_type=EventType.CODE_WRITTEN,
        source_agent="planning",
        payload={
            "task_id": "task-123",
            "file_path": "dummy.py",
            "task_description": "implement AST parsing module",
            "acceptance_criteria": ["criteria 1"],
        }
    )

    result = agent.handle(event)

    assert result.success is True
    assert (tmp_path / "dummy.py").exists()
    assert (tmp_path / "dummy.py").read_text() == "def run_parsing():\n    # custom module\n    pass\n"
    assert model_provider.complete.call_count == 2
