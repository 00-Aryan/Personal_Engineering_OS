"""Test Agent implementation for ProjectOS."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional, TYPE_CHECKING

from core.base_agent import BaseAgent
from core.events import AgentEvent, AgentResult, EventType
from core.model_provider import ModelProvider

if TYPE_CHECKING:
    from core.intelligence.collaboration import CollaborationBroker
    from core.intelligence.memory_manager import MemoryManager


AGENT_NAME = "test"
ROLE_DESCRIPTION = "Pytest generation and execution agent."
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]

ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

DECISIONS_LOG_NAME = "decisions.log"
TESTS_DIR_NAME = "tests"
TEST_FILE_PREFIX = "test_"
MODEL_MAX_TOKENS = 8192

SYSTEM_PROMPT = (
    "You are a senior QA engineer and Python testing expert.\n"
    "You write comprehensive pytest unit tests.\n"
    "Rules:\n"
    "- Every test has a clear docstring explaining what it tests\n"
    "- Use pytest fixtures, not unittest\n"
    "- Mock all external calls (HTTP, file system where appropriate)\n"
    "- Test both happy path and failure cases\n"
    "- Output ONLY valid Python test code, no markdown"
)

PAYLOAD_KEY_FAILED = "failed"
PAYLOAD_KEY_FILE_PATH = "file_path"
PAYLOAD_KEY_PASSED = "passed"
PAYLOAD_KEY_SOURCE_FILE = "source_file"
PAYLOAD_KEY_TASK_ID = "task_id"
PAYLOAD_KEY_TEST_FILE = "test_file"

PROMPT_SOURCE_FILE_LABEL = "Source file:"
PROMPT_TASK_ID_LABEL = "Task ID:"
PROMPT_SOURCE_CODE_LABEL = "Source code:"
PROMPT_EXISTING_TESTS_LABEL = "Existing tests:"
PROMPT_INSTRUCTION = "Return only the complete pytest test file content."
PROMPT_SECTION_SEPARATOR = "\n\n"

PYTEST_COMMAND = "python3"
PYTEST_MODULE_FLAG = "-m"
PYTEST_MODULE_NAME = "pytest"
SUBPROCESS_TEXT_MODE = True
SUBPROCESS_CAPTURE_OUTPUT = True

COUNT_PATTERN_TEMPLATE = r"(?P<count>\d+)\s+{label}"
PASSED_LABEL = "passed"
FAILED_LABEL = "failed"

DECISION_LOG_PREFIX = "["
DECISION_LOG_SEPARATOR = "] ["
DECISION_LOG_SUFFIX = "]\n"
DECISION_SUCCESS = "SUCCESS"
DECISION_FAILURE = "FAILURE"
DECISION_REASON_GENERATED_TEMPLATE = (
    "Generated tests for {source_file}; passed {passed}; failed {failed}"
)
DECISION_REASON_MISSING_PAYLOAD = "test agent event missing file_path"
DECISION_REASON_FILE_NOT_FOUND = "test agent source file not found"
DECISION_REASON_UNSUPPORTED_EVENT = "test agent received unsupported event type"
ESCALATION_REASON_FAILED_TESTS = "generated tests failed"

OUTPUT_KEY_ERROR = "error"
OUTPUT_KEY_FAILED = "failed"
OUTPUT_KEY_PASSED = "passed"
OUTPUT_KEY_TEST_FILE = "test_file"


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _write_atomically(path: Path, content: str) -> None:
    """Write content to a path by replacing it with a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{TEMP_PREFIX}{path.name}.",
        suffix=TEMP_SUFFIX,
        dir=str(path.parent),
    )
    try:
        with os.fdopen(
            file_descriptor,
            FILE_WRITE_MODE,
            encoding=ENCODING,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file while preserving existing content."""
    existing_content = path.read_text(encoding=ENCODING) if path.exists() else EMPTY_TEXT
    _write_atomically(path, f"{existing_content}{content}")


class TestAgent(BaseAgent):
    """Agent that generates pytest files and runs them."""

    __test__ = False

    def __init__(
        self,
        model_provider: ModelProvider,
        logger: logging.Logger,
        project_root: Path | str = DEFAULT_PROJECT_ROOT,
        memory_manager: Optional["MemoryManager"] = None,
        collaboration_broker: Optional["CollaborationBroker"] = None,
    ) -> None:
        """Initialize TestAgent with model access and project paths."""
        super().__init__(
            AGENT_NAME,
            ROLE_DESCRIPTION,
            model_provider,
            logger,
            memory_manager=memory_manager,
            collaboration_broker=collaboration_broker,
        )
        self.project_root = Path(project_root)

    def handle(self, event: AgentEvent) -> AgentResult:
        """Generate and run tests for CODE_WRITTEN or CODE_CHANGED events."""
        if event.event_type not in (EventType.CODE_WRITTEN, EventType.CODE_CHANGED):
            return self._failure_result(event, DECISION_REASON_UNSUPPORTED_EVENT)

        file_path_value = event.payload.get(PAYLOAD_KEY_FILE_PATH)
        if not isinstance(file_path_value, str) or not file_path_value:
            return self._failure_result(event, DECISION_REASON_MISSING_PAYLOAD)

        source_path = self._resolve_path(file_path_value)
        if not source_path.exists():
            return self._failure_result(event, DECISION_REASON_FILE_NOT_FOUND)

        test_path = self._test_file_path(source_path)
        source_code = source_path.read_text(encoding=ENCODING)
        existing_tests = self._existing_tests(test_path)
        prompt = self._build_prompt(event.payload, source_path, source_code, existing_tests)
        generated_tests = self.model_provider.complete(
            prompt,
            SYSTEM_PROMPT,
            MODEL_MAX_TOKENS,
        )
        _write_atomically(test_path, self._normalized_tests(generated_tests))

        completed_process = self._run_pytest(test_path)
        pytest_output = self._pytest_output(completed_process)
        passed = self._count_for_label(pytest_output, PASSED_LABEL)
        failed = self._count_for_label(pytest_output, FAILED_LABEL)
        reasoning = DECISION_REASON_GENERATED_TEMPLATE.format(
            source_file=str(source_path),
            passed=passed,
            failed=failed,
        )
        self._log_decision(event, DECISION_SUCCESS, reasoning)
        return AgentResult(
            success=True,
            output={
                OUTPUT_KEY_TEST_FILE: str(test_path),
                OUTPUT_KEY_PASSED: passed,
                OUTPUT_KEY_FAILED: failed,
            },
            next_events=[self._tests_done_event(event, source_path, test_path, passed, failed)],
            escalate=failed > 0,
            escalation_reason=ESCALATION_REASON_FAILED_TESTS if failed > 0 else None,
        )

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve a payload file path against the project root."""
        candidate_path = Path(file_path)
        if candidate_path.is_absolute():
            return candidate_path
        return self.project_root / candidate_path

    def _test_file_path(self, source_path: Path) -> Path:
        """Return the generated test path for a source file."""
        return self.project_root / TESTS_DIR_NAME / f"{TEST_FILE_PREFIX}{source_path.name}"

    def _existing_tests(self, test_path: Path) -> str:
        """Return existing test content when present."""
        if test_path.exists():
            return test_path.read_text(encoding=ENCODING)
        return EMPTY_TEXT

    def _build_prompt(
        self,
        payload: Mapping[str, Any],
        source_path: Path,
        source_code: str,
        existing_tests: str,
    ) -> str:
        """Build the model prompt for pytest generation."""
        task_id = payload.get(PAYLOAD_KEY_TASK_ID)
        task_id_text = str(task_id) if task_id is not None else EMPTY_TEXT
        return PROMPT_SECTION_SEPARATOR.join(
            [
                f"{PROMPT_SOURCE_FILE_LABEL} {source_path}",
                f"{PROMPT_TASK_ID_LABEL} {task_id_text}",
                f"{PROMPT_SOURCE_CODE_LABEL}\n{source_code}",
                f"{PROMPT_EXISTING_TESTS_LABEL}\n{existing_tests}",
                PROMPT_INSTRUCTION,
            ]
        )

    def _normalized_tests(self, generated_tests: str) -> str:
        """Normalize generated test content before writing."""
        return generated_tests.strip() + NEWLINE

    def _run_pytest(self, test_path: Path) -> subprocess.CompletedProcess[str]:
        """Run pytest for a generated test file."""
        command = [PYTEST_COMMAND, PYTEST_MODULE_FLAG, PYTEST_MODULE_NAME, str(test_path)]
        return subprocess.run(
            command,
            cwd=self.project_root,
            capture_output=SUBPROCESS_CAPTURE_OUTPUT,
            text=SUBPROCESS_TEXT_MODE,
        )

    def _pytest_output(self, completed_process: subprocess.CompletedProcess[str]) -> str:
        """Return combined pytest stdout and stderr output."""
        return f"{completed_process.stdout}{NEWLINE}{completed_process.stderr}"

    def _count_for_label(self, pytest_output: str, label: str) -> int:
        """Parse a pytest count for a summary label."""
        pattern = COUNT_PATTERN_TEMPLATE.format(label=label)
        matches = list(re.finditer(pattern, pytest_output))
        if not matches:
            return 0
        return int(matches[-1].group("count"))

    def _tests_done_event(
        self,
        parent_event: AgentEvent,
        source_path: Path,
        test_path: Path,
        passed: int,
        failed: int,
    ) -> AgentEvent:
        """Create a TESTS_DONE event with parsed pytest counts."""
        return AgentEvent(
            event_type=EventType.TESTS_DONE,
            source_agent=self.name,
            payload={
                PAYLOAD_KEY_PASSED: passed,
                PAYLOAD_KEY_FAILED: failed,
                PAYLOAD_KEY_TEST_FILE: str(test_path),
                PAYLOAD_KEY_SOURCE_FILE: str(source_path),
            },
            correlation_id=parent_event.correlation_id or parent_event.event_id,
            priority=parent_event.priority,
        )

    def _failure_result(self, event: AgentEvent, reason: str) -> AgentResult:
        """Log and return a non-crashing failure result."""
        self._log_decision(event, DECISION_FAILURE, reason)
        return AgentResult(success=False, output={OUTPUT_KEY_ERROR: reason})

    def _log_decision(self, event: AgentEvent, outcome: str, reasoning: str) -> None:
        """Append one TestAgent decision to decisions.log."""
        decision_line = (
            f"{DECISION_LOG_PREFIX}{_utc_timestamp()}{DECISION_LOG_SEPARATOR}"
            f"{event.event_id}{DECISION_LOG_SEPARATOR}"
            f"{outcome}{DECISION_LOG_SEPARATOR}"
            f"{reasoning}{DECISION_LOG_SUFFIX}"
        )
        _append_atomically(self.project_root / DECISIONS_LOG_NAME, decision_line)
        self.log_decision(reasoning, outcome)


__all__ = ["TestAgent"]
