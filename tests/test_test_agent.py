"""Unit tests for the Test Agent."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from agents.test_agent import TestAgent
from core.events import AgentEvent, EventType


SOURCE_AGENT = "unit_test"
TEST_ENCODING = "utf-8"
SOURCE_RELATIVE_PATH = "src/example.py"
TASK_ID = "PLAN-20260605-001"
TASK_ID_KEY = "task_id"
FILE_PATH_KEY = "file_path"
SOURCE_FILE_KEY = "source_file"
TEST_FILE_KEY = "test_file"
PASSED_KEY = "passed"
FAILED_KEY = "failed"
SOURCE_CODE = (
    "def add(left: int, right: int) -> int:\n"
    "    \"\"\"Return the sum of two integers.\"\"\"\n"
    "    return left + right\n"
)
GENERATED_TESTS = (
    "import pytest\n\n"
    "def test_add() -> None:\n"
    "    \"\"\"Verify add returns the integer sum.\"\"\"\n"
    "    assert True\n"
)
PASSING_OUTPUT = "1 passed in 0.01s"
FAILING_OUTPUT = "1 failed, 2 passed in 0.02s"
PYTEST_COMMAND = "python3"
PYTEST_MODULE_FLAG = "-m"
PYTEST_MODULE_NAME = "pytest"


class TestAgentTestCase(unittest.TestCase):
    """Tests TestAgent generation and pytest execution behavior."""

    def setUp(self) -> None:
        """Create an isolated TestAgent for each test."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.model_provider = Mock()
        self.model_provider.complete.return_value = GENERATED_TESTS
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.disabled = True
        self.agent = TestAgent(
            model_provider=self.model_provider,
            logger=self.logger,
            project_root=self.project_root,
        )
        self.source_path = self._write_source_file()

    def tearDown(self) -> None:
        """Remove the isolated project root."""
        self._temp_dir.cleanup()

    @patch("agents.test_agent.subprocess.run")
    def test_generates_test_file_for_source(self, run_mock: Any) -> None:
        """Verify TestAgent writes generated tests for a source file."""
        run_mock.return_value = self._completed_process(PASSING_OUTPUT)

        result = self.agent.handle(self._code_event())

        test_path = self.project_root / "tests" / "test_example.py"
        self.assertTrue(result.success)
        self.assertTrue(test_path.exists())
        self.assertEqual(test_path.read_text(encoding=TEST_ENCODING), GENERATED_TESTS)

    @patch("agents.test_agent.subprocess.run")
    def test_runs_pytest_after_generating(self, run_mock: Any) -> None:
        """Verify TestAgent invokes pytest for the generated test file."""
        run_mock.return_value = self._completed_process(PASSING_OUTPUT)
        test_path = self.project_root / "tests" / "test_example.py"

        self.agent.handle(self._code_event())

        run_mock.assert_called_once_with(
            [PYTEST_COMMAND, PYTEST_MODULE_FLAG, PYTEST_MODULE_NAME, str(test_path)],
            cwd=self.project_root,
            capture_output=True,
            text=True,
        )

    @patch("agents.test_agent.subprocess.run")
    def test_failed_tests_set_escalate(self, run_mock: Any) -> None:
        """Verify failed generated tests set escalation on the result."""
        run_mock.return_value = self._completed_process(FAILING_OUTPUT, returncode=1)

        result = self.agent.handle(self._code_event())

        self.assertTrue(result.success)
        self.assertTrue(result.escalate)
        self.assertEqual(result.output[PASSED_KEY], 2)
        self.assertEqual(result.output[FAILED_KEY], 1)

    @patch("agents.test_agent.subprocess.run")
    def test_emits_tests_done_event_with_counts(self, run_mock: Any) -> None:
        """Verify TestAgent emits TESTS_DONE with parsed counts."""
        run_mock.return_value = self._completed_process(FAILING_OUTPUT, returncode=1)

        result = self.agent.handle(self._code_event())

        self.assertEqual(len(result.next_events), 1)
        next_event = result.next_events[0]
        self.assertIs(next_event.event_type, EventType.TESTS_DONE)
        self.assertEqual(next_event.payload[PASSED_KEY], 2)
        self.assertEqual(next_event.payload[FAILED_KEY], 1)
        self.assertEqual(next_event.payload[SOURCE_FILE_KEY], str(self.source_path))
        self.assertIn("test_example.py", next_event.payload[TEST_FILE_KEY])

    def _write_source_file(self) -> Path:
        """Write a source file for TestAgent tests."""
        source_path = self.project_root / SOURCE_RELATIVE_PATH
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(SOURCE_CODE, encoding=TEST_ENCODING)
        return source_path

    def _code_event(self) -> AgentEvent:
        """Create a valid CODE_WRITTEN event."""
        return AgentEvent(
            event_type=EventType.CODE_WRITTEN,
            source_agent=SOURCE_AGENT,
            payload={
                FILE_PATH_KEY: str(self.source_path),
                TASK_ID_KEY: TASK_ID,
            },
        )

    def _completed_process(
        self,
        stdout: str,
        returncode: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        """Return a mocked pytest completed process."""
        return subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=stdout,
            stderr="",
        )


if __name__ == "__main__":
    unittest.main()
