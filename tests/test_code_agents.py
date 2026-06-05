"""Unit tests for Code Writing and Code Review agents."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from typing import Mapping
from unittest.mock import Mock

from agents.code_review_agent import CodeReviewAgent, ReviewIssue
from agents.code_writing_agent import CodeWritingAgent
from core.events import AgentEvent, EventType


SOURCE_AGENT = "unit_test"
TEST_ENCODING = "utf-8"
TEST_MODEL_NAME = "test-review-model"

TASK_ID_KEY = "task_id"
FILE_PATH_KEY = "file_path"
TASK_DESCRIPTION_KEY = "task_description"
ACCEPTANCE_CRITERIA_KEY = "acceptance_criteria"
AFFECTED_FILES_KEY = "affected_files"
ISSUES_KEY = "issues"
REPORT_PATH_KEY = "report_path"
CRITICAL_COUNT_KEY = "critical_count"

TASK_ID = "PLAN-20260605-001"
RELATIVE_FILE_PATH = "generated/example.py"
TASK_DESCRIPTION = "Create a greeting helper."
ACCEPTANCE_CRITERION = "Function returns a greeting string."
GENERATED_CODE = (
    "GREETING = \"hello\"\n\n"
    "def greet(name: str) -> str:\n"
    "    \"\"\"Return a greeting for a name.\"\"\"\n"
    "    return f\"{GREETING}, {name}\"\n"
)

SEVERITY_HIGH = "HIGH"
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_MEDIUM = "MEDIUM"
CATEGORY_LOGIC = "logic"
CATEGORY_SECURITY = "security"
ISSUE_DESCRIPTION = "Return value misses punctuation."
ISSUE_FIX = "Append punctuation to the returned greeting."
CRITICAL_DESCRIPTION = "Uses unsafe dynamic execution."
CRITICAL_FIX = "Remove dynamic execution."
LINE_NUMBER = 5
MALFORMED_JSON = "{not valid json"
EMPTY_JSON_ARRAY = "[]"
REPORT_TITLE = "# Code Review: example.py"
REPORT_SUMMARY = "Total issues:"
REVIEWS_DIR_NAME = "reviews"
REVIEW_SUFFIX = "_review.md"
BACKLOG_FILE_NAME = "backlog.md"
BACKLOG_DONE_STATUS = "- Status: DONE"
BACKLOG_BLOCKED_STATUS = "- Status: BLOCKED"


class CodeAgentsTestCase(unittest.TestCase):
    """Tests code writing and review agent behavior."""

    def setUp(self) -> None:
        """Create isolated agents and mocked providers for each test."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.model_provider = Mock()
        self.model_provider.get_model_name.return_value = TEST_MODEL_NAME
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.disabled = True
        self.writer = CodeWritingAgent(
            model_provider=self.model_provider,
            logger=self.logger,
            project_root=self.project_root,
        )
        self.reviewer = CodeReviewAgent(
            model_provider=self.model_provider,
            logger=self.logger,
            project_root=self.project_root,
        )

    def tearDown(self) -> None:
        """Remove the isolated project root."""
        self._temp_dir.cleanup()

    def test_code_writing_creates_file(self) -> None:
        """Verify CodeWritingAgent creates the requested file."""
        self.model_provider.complete.return_value = GENERATED_CODE

        result = self.writer.handle(self._writing_event())

        written_path = self.project_root / RELATIVE_FILE_PATH
        self.assertTrue(result.success)
        self.assertTrue(written_path.exists())
        self.assertEqual(written_path.read_text(encoding=TEST_ENCODING), GENERATED_CODE)

    def test_code_writing_emits_code_written_event(self) -> None:
        """Verify CodeWritingAgent emits a CODE_WRITTEN event."""
        self.model_provider.complete.return_value = GENERATED_CODE
        event = self._writing_event()

        result = self.writer.handle(event)

        self.assertEqual(len(result.next_events), 1)
        next_event = result.next_events[0]
        self.assertIs(next_event.event_type, EventType.CODE_WRITTEN)
        self.assertEqual(next_event.source_agent, "code_writing")
        self.assertEqual(next_event.correlation_id, event.event_id)
        self.assertEqual(next_event.payload[TASK_ID_KEY], TASK_ID)
        self.assertIn(
            str(self.project_root / RELATIVE_FILE_PATH),
            next_event.payload[AFFECTED_FILES_KEY],
        )

    def test_code_review_parses_issues_correctly(self) -> None:
        """Verify CodeReviewAgent parses valid review JSON."""
        issues = self.reviewer.parse_issues(self._review_json())

        self.assertEqual(len(issues), 1)
        self.assertTrue(all(isinstance(issue, ReviewIssue) for issue in issues))
        self.assertEqual(issues[0].severity, SEVERITY_HIGH)
        self.assertEqual(issues[0].category, CATEGORY_LOGIC)
        self.assertEqual(issues[0].line_number, LINE_NUMBER)

    def test_code_review_critical_sets_escalate_true(self) -> None:
        """Verify critical review issues escalate the result."""
        file_path = self._write_review_target()
        self._write_backlog()
        self.model_provider.complete.return_value = self._critical_review_json()

        result = self.reviewer.handle(self._review_event(file_path))

        self.assertTrue(result.success)
        self.assertTrue(result.escalate)
        self.assertEqual(result.next_events[0].payload[CRITICAL_COUNT_KEY], 1)
        self.assertIn(BACKLOG_BLOCKED_STATUS, self._read_backlog())

    def test_code_review_empty_array_no_escalation(self) -> None:
        """Verify empty review arrays do not escalate."""
        file_path = self._write_review_target()
        self._write_backlog()
        self.model_provider.complete.return_value = EMPTY_JSON_ARRAY

        result = self.reviewer.handle(self._review_event(file_path))

        self.assertTrue(result.success)
        self.assertFalse(result.escalate)
        self.assertEqual(result.output[ISSUES_KEY], [])
        self.assertIn(BACKLOG_DONE_STATUS, self._read_backlog())

    def test_code_review_invalid_json_graceful(self) -> None:
        """Verify malformed review JSON returns failure without crashing."""
        file_path = self._write_review_target()
        self.model_provider.complete.return_value = MALFORMED_JSON

        result = self.reviewer.handle(self._review_event(file_path))

        self.assertFalse(result.success)
        self.assertEqual(self._review_report_count(), 0)

    def test_review_report_written_to_reviews_dir(self) -> None:
        """Verify review reports are written in the reviews directory."""
        file_path = self._write_review_target()
        self.model_provider.complete.return_value = self._review_json()

        result = self.reviewer.handle(self._review_event(file_path))

        report_path = Path(result.output[REPORT_PATH_KEY])
        report_content = report_path.read_text(encoding=TEST_ENCODING)
        self.assertTrue(report_path.exists())
        self.assertEqual(report_path.parent, self.project_root / REVIEWS_DIR_NAME)
        self.assertIn(REPORT_TITLE, report_content)
        self.assertIn(TEST_MODEL_NAME, report_content)
        self.assertIn(REPORT_SUMMARY, report_content)
        self.assertEqual(self._review_report_count(), 1)

    def _writing_event(self) -> AgentEvent:
        """Create a valid code-writing event."""
        return AgentEvent(
            event_type=EventType.BACKLOG_CHANGED,
            source_agent=SOURCE_AGENT,
            payload={
                TASK_ID_KEY: TASK_ID,
                FILE_PATH_KEY: RELATIVE_FILE_PATH,
                TASK_DESCRIPTION_KEY: TASK_DESCRIPTION,
                ACCEPTANCE_CRITERIA_KEY: [ACCEPTANCE_CRITERION],
            },
        )

    def _review_event(self, file_path: Path) -> AgentEvent:
        """Create a valid code-review event."""
        return AgentEvent(
            event_type=EventType.CODE_WRITTEN,
            source_agent=SOURCE_AGENT,
            payload={
                TASK_ID_KEY: TASK_ID,
                FILE_PATH_KEY: str(file_path),
            },
        )

    def _write_review_target(self) -> Path:
        """Write a source file for code-review tests."""
        file_path = self.project_root / RELATIVE_FILE_PATH
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(GENERATED_CODE, encoding=TEST_ENCODING)
        return file_path

    def _write_backlog(self) -> None:
        """Write a minimal backlog containing the shared task ID."""
        backlog = (
            "# ProjectOS Backlog\n"
            "Last updated: 2026-06-05T00:00:00+00:00\n\n"
            "## HIGH Priority\n"
            f"### [{TASK_ID}] Example task\n"
            "- Type: feature\n"
            "- Complexity: M\n"
            "- Agent: code_writing_agent\n"
            "- Acceptance:\n"
            "  - [ ] Works\n"
            "- Dependencies: None\n"
            "- Status: PENDING\n"
        )
        (self.project_root / BACKLOG_FILE_NAME).write_text(
            backlog,
            encoding=TEST_ENCODING,
        )

    def _read_backlog(self) -> str:
        """Read the test backlog file."""
        return (self.project_root / BACKLOG_FILE_NAME).read_text(
            encoding=TEST_ENCODING
        )

    def _review_json(self) -> str:
        """Return mocked review JSON with one high issue."""
        return json.dumps(
            [
                {
                    "severity": SEVERITY_HIGH,
                    "category": CATEGORY_LOGIC,
                    "line_number": LINE_NUMBER,
                    "description": ISSUE_DESCRIPTION,
                    "suggested_fix": ISSUE_FIX,
                }
            ]
        )

    def _critical_review_json(self) -> str:
        """Return mocked review JSON with one critical issue."""
        return json.dumps(
            [
                {
                    "severity": SEVERITY_CRITICAL,
                    "category": CATEGORY_SECURITY,
                    "line_number": None,
                    "description": CRITICAL_DESCRIPTION,
                    "suggested_fix": CRITICAL_FIX,
                }
            ]
        )

    def _review_report_count(self) -> int:
        """Return the number of markdown review reports."""
        return len(
            [
                path
                for path in (self.project_root / REVIEWS_DIR_NAME).iterdir()
                if path.name.endswith(REVIEW_SUFFIX)
            ]
        )


if __name__ == "__main__":
    unittest.main()
