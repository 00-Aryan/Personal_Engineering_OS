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
from core.project_context import ProjectContextLoader

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

# Global SYSTEM_PROMPT removed (defined as class attribute instead)

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

    SYSTEM_PROMPT = """You are a senior QA engineer.
Your role is to write comprehensive pytest tests.

ALWAYS:
- Write tests for both happy path and failure cases
- Mock all external calls (HTTP, file system, APIs)
- Use descriptive test names: test_[function]_[scenario]_[expected]
- Add docstrings to every test
- Keep each test focused on one behavior

NEVER:
- Write tests that make real API calls
- Write tests that depend on other tests
- Write tests that modify shared state
- Output anything except valid pytest code

Output: Raw Python pytest code only. No explanation. No fences.
{project_context}"""


    def __init__(
        self,
        model_provider: ModelProvider,
        logger: logging.Logger,
        project_root: Path | str = DEFAULT_PROJECT_ROOT,
        memory_manager: Optional["MemoryManager"] = None,
        collaboration_broker: Optional["CollaborationBroker"] = None,
        context_loader: Optional[ProjectContextLoader] = None,
    ) -> None:
        """Initialize TestAgent with model access and project paths."""
        super().__init__(
            AGENT_NAME,
            ROLE_DESCRIPTION,
            model_provider,
            logger,
            memory_manager=memory_manager,
            collaboration_broker=collaboration_broker,
            context_loader=context_loader,
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
        params = self.get_model_params()
        generated_tests = self.model_provider.complete(
            prompt=prompt,
            system_prompt=self.build_system_prompt(self.SYSTEM_PROMPT),
            temperature=params["temperature"],
            max_tokens=params["max_tokens"],
            top_p=params["top_p"],
            agent_name=self.name,
        )
        generated_tests_normalized = self._normalized_tests(generated_tests)
        _write_atomically(test_path, generated_tests_normalized)

        blocked, flagged = self._scan_test_code(generated_tests_normalized)
        if blocked:
            warning_reason = "Test execution blocked: dangerous pattern detected"
            self.logger.warning("%s: %s", warning_reason, blocked)
            self._write_security_warning(source_path, event, blocked, flagged)
            self._log_decision(event, DECISION_FAILURE, warning_reason)
            return AgentResult(
                success=True,
                output={
                    OUTPUT_KEY_TEST_FILE: str(test_path),
                    OUTPUT_KEY_PASSED: 0,
                    OUTPUT_KEY_FAILED: 0,
                    "blocked": True,
                    "blocked_reasons": blocked,
                },
                next_events=[],
                escalate=True,
                escalation_reason=warning_reason,
            )

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
        """Run pytest for a generated test file with a 30 second timeout."""
        command = [PYTEST_COMMAND, PYTEST_MODULE_FLAG, PYTEST_MODULE_NAME, str(test_path)]
        try:
            return subprocess.run(
                command,
                cwd=self.project_root,
                capture_output=SUBPROCESS_CAPTURE_OUTPUT,
                text=SUBPROCESS_TEXT_MODE,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="pytest execution timed out after 30 seconds",
                stderr=str(e),
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

    def _scan_test_code(self, code_str: str) -> tuple[list[str], list[str]]:
        """Scan code string for dangerous patterns using AST."""
        import ast
        blocked = []
        flagged = []
        try:
            tree = ast.parse(code_str)
        except Exception:
            return [], []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    if name.name in ("os", "subprocess", "sys"):
                        flagged.append(f"import {name.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module in ("os", "subprocess", "sys"):
                    flagged.append(f"from {node.module} import ...")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        module_name = node.func.value.id
                        attr_name = node.func.attr
                        if module_name == "os" and attr_name == "system":
                            blocked.append("os.system")
                        elif module_name == "subprocess" and attr_name == "run":
                            blocked.append("subprocess.run")
                elif isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    if func_name in ("eval", "exec", "system", "run"):
                        blocked.append(func_name)
                    elif func_name == "open":
                        mode_val = "r"
                        for kw in node.keywords:
                            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                                mode_val = str(kw.value.value)
                        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                            mode_val = str(node.args[1].value)
                        
                        if any(char in mode_val for char in ("w", "a", "x", "+")):
                            is_outside_tests = True
                            if len(node.args) >= 1:
                                path_node = node.args[0]
                                if isinstance(path_node, ast.Constant) and isinstance(path_node.value, str):
                                    path_str = path_node.value
                                    norm_path = os.path.normpath(path_str)
                                    if norm_path.startswith("tests") or "tests/" in norm_path or "tests\\" in norm_path or norm_path.startswith("./tests"):
                                        is_outside_tests = False
                            if is_outside_tests:
                                blocked.append("open() in write mode outside tests/ directory")
        return blocked, flagged

    def _write_security_warning(
        self,
        source_path: Path,
        event: AgentEvent,
        blocked: list[str],
        flagged: list[str],
    ) -> None:
        """Write a security warning warning to the review report."""
        review_report_val = event.payload.get("review_report")
        report_path = None
        if review_report_val:
            report_path = self._resolve_path(review_report_val)
        else:
            reviews_dir = self.project_root / "reviews"
            if reviews_dir.exists():
                matching_reports = sorted(
                    reviews_dir.glob(f"{source_path.name}*_review.md"),
                    key=os.path.getmtime,
                )
                if matching_reports:
                    report_path = matching_reports[-1]
        
        if not report_path:
            reviews_dir = self.project_root / "reviews"
            reviews_dir.mkdir(parents=True, exist_ok=True)
            report_path = reviews_dir / f"{source_path.name}_review.md"

        warning_msg = (
            f"\n\n## WARNING: Test Execution Blocked\n"
            f"Dangerous pattern detected in generated tests.\n"
            f"- **Blocked patterns**: {', '.join(blocked)}\n"
        )
        if flagged:
            warning_msg += f"- **Flagged patterns**: {', '.join(flagged)}\n"
        warning_msg += f"- **Timestamp**: {_utc_timestamp()}\n"

        if report_path.exists():
            _append_atomically(report_path, warning_msg)
        else:
            _write_atomically(report_path, warning_msg)


__all__ = ["TestAgent"]
