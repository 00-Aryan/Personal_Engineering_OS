"""Unit tests for the Documentation Agent."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agents.docs_agent import DocsAgent
from core.events import AgentEvent, EventType


SOURCE_AGENT = "unit_test"
TEST_ENCODING = "utf-8"
SOURCE_RELATIVE_PATH = "src/example.py"
FILE_PATH_KEY = "file_path"
SOURCE_FILE_KEY = "source_file"
ADDED_DOCSTRINGS_KEY = "added_docstrings"
TASK_ID_KEY = "task_id"
TASK_ID = "PLAN-20260605-001"
SOURCE_WITH_MISSING_DOCSTRING = (
    "def greet(name: str) -> str:\n"
    "    return f\"Hello, {name}\"\n"
)
SOURCE_WITH_ADDED_DOCSTRING = (
    "def greet(name: str) -> str:\n"
    "    \"\"\"Return a greeting for a name.\"\"\"\n"
    "    return f\"Hello, {name}\"\n"
)
SOURCE_WITH_EXISTING_DOCSTRING = (
    "def greet(name: str) -> str:\n"
    "    \"\"\"Keep this documentation.\"\"\"\n"
    "    return f\"Hello, {name}\"\n"
)
SOURCE_WITH_REMOVED_DOCSTRING = (
    "def greet(name: str) -> str:\n"
    "    return f\"Hello, {name}\"\n"
)
EXISTING_DOCSTRING_TEXT = "Keep this documentation."
ADDED_DOCSTRING_TEXT = "Return a greeting for a name."


class DocsAgentTestCase(unittest.TestCase):
    """Tests DocsAgent documentation update behavior."""

    def setUp(self) -> None:
        """Create an isolated DocsAgent for each test."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.model_provider = Mock()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.disabled = True
        self.agent = DocsAgent(
            model_provider=self.model_provider,
            logger=self.logger,
            project_root=self.project_root,
        )

    def tearDown(self) -> None:
        """Remove the isolated project root."""
        self._temp_dir.cleanup()

    def test_adds_missing_docstrings(self) -> None:
        """Verify DocsAgent writes model output with missing docstrings added."""
        source_path = self._write_source(SOURCE_WITH_MISSING_DOCSTRING)
        self.model_provider.complete.return_value = SOURCE_WITH_ADDED_DOCSTRING

        result = self.agent.handle(self._code_event(source_path))

        updated_source = source_path.read_text(encoding=TEST_ENCODING)
        self.assertTrue(result.success)
        self.assertIn(ADDED_DOCSTRING_TEXT, updated_source)
        self.assertEqual(result.output[ADDED_DOCSTRINGS_KEY], 1)

    def test_never_removes_existing_docs(self) -> None:
        """Verify DocsAgent preserves existing docstrings if model omits them."""
        source_path = self._write_source(SOURCE_WITH_EXISTING_DOCSTRING)
        self.model_provider.complete.return_value = SOURCE_WITH_REMOVED_DOCSTRING

        result = self.agent.handle(self._code_event(source_path))

        updated_source = source_path.read_text(encoding=TEST_ENCODING)
        self.assertTrue(result.success)
        self.assertIn(EXISTING_DOCSTRING_TEXT, updated_source)

    def test_emits_docs_updated_event(self) -> None:
        """Verify DocsAgent emits DOCS_UPDATED with source metadata."""
        source_path = self._write_source(SOURCE_WITH_MISSING_DOCSTRING)
        self.model_provider.complete.return_value = SOURCE_WITH_ADDED_DOCSTRING

        result = self.agent.handle(self._tests_done_event(source_path))

        self.assertEqual(len(result.next_events), 1)
        next_event = result.next_events[0]
        self.assertIs(next_event.event_type, EventType.DOCS_UPDATED)
        self.assertEqual(next_event.payload[FILE_PATH_KEY], str(source_path))
        self.assertEqual(next_event.payload[ADDED_DOCSTRINGS_KEY], 1)

    def _write_source(self, source_code: str) -> Path:
        """Write a source file for DocsAgent tests."""
        source_path = self.project_root / SOURCE_RELATIVE_PATH
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(source_code, encoding=TEST_ENCODING)
        return source_path

    def _code_event(self, source_path: Path) -> AgentEvent:
        """Create a valid CODE_WRITTEN event."""
        return AgentEvent(
            event_type=EventType.CODE_WRITTEN,
            source_agent=SOURCE_AGENT,
            payload={
                FILE_PATH_KEY: str(source_path),
                TASK_ID_KEY: TASK_ID,
            },
        )

    def _tests_done_event(self, source_path: Path) -> AgentEvent:
        """Create a valid TESTS_DONE event."""
        return AgentEvent(
            event_type=EventType.TESTS_DONE,
            source_agent=SOURCE_AGENT,
            payload={
                SOURCE_FILE_KEY: str(source_path),
                TASK_ID_KEY: TASK_ID,
            },
        )


if __name__ == "__main__":
    unittest.main()
