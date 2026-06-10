"""Unit tests for the Planning Agent."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from typing import Mapping
from unittest.mock import Mock

from agents.planning_agent import PlanningAgent, Task
from core.events import AgentEvent, EventType


BACKLOG_FILE_NAME = "backlog.md"
DESCRIPTION_KEY = "description"
PROJECT_CONTEXT_KEY = "project_context"
TASKS_OUTPUT_KEY = "tasks"
TARGET_AGENT_KEY = "target_agent"
TASK_ID_KEY = "task_id"
TASK_TYPE_KEY = "task_type"
FEATURE_DESCRIPTION = "Add recurring reminders with email notifications."
PROJECT_CONTEXT = "Python service with existing event dispatch."
SOURCE_AGENT = "unit_test"
PLANNING_AGENT_NAME = "planning"
TEST_ENCODING = "utf-8"
TASK_ID_PATTERN = r"PLAN-\d{8}-001"
TASK_ID_PATTERN_SECOND = r"PLAN-\d{8}-002"
EXPECTED_SYSTEM_SNIPPET = "Valid JSON only"
BACKLOG_TITLE = "# ProjectOS Backlog"
HIGH_PRIORITY_HEADING = "## HIGH Priority"
TASK_TITLE = "Design reminder model"
TASK_TITLE_SECOND = "Add reminder tests"
TASK_TYPE_FEATURE = "feature"
TASK_TYPE_TEST = "test"
TASK_PRIORITY_HIGH = "HIGH"
TASK_PRIORITY_MEDIUM = "MEDIUM"
TASK_COMPLEXITY_MEDIUM = "M"
TASK_COMPLEXITY_SMALL = "S"
TASK_AGENT_ASSIGNMENT = "code_writing_agent"
TEST_AGENT_ASSIGNMENT = "test_agent"
ACCEPTANCE_CRITERION = "Reminder records can be stored"
ACCEPTANCE_CRITERION_SECOND = "Reminder tests cover scheduling"
DEPENDENCY_MODEL_ID = "draft-model"
DEPENDENCY_TEST_ID = "write-tests"
MALFORMED_JSON = "{not valid json"
PENDING_STATUS = "PENDING"


class PlanningAgentTestCase(unittest.TestCase):
    """Tests PlanningAgent backlog generation behavior."""

    def setUp(self) -> None:
        """Create an isolated PlanningAgent for each test."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.model_provider = Mock()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.disabled = True
        self.agent = PlanningAgent(
            model_provider=self.model_provider,
            logger=self.logger,
            project_root=self.project_root,
        )

    def tearDown(self) -> None:
        """Remove the isolated project root."""
        self._temp_dir.cleanup()

    def test_handle_new_feature_creates_backlog(self) -> None:
        """Verify NEW_FEATURE events produce tasks and backlog output."""
        self.model_provider.complete.return_value = self._model_json()
        event = self._new_feature_event()

        result = self.agent.handle(event)

        self.assertTrue(result.success)
        self.assertEqual(len(result.output[TASKS_OUTPUT_KEY]), 2)
        self.assertTrue((self.project_root / BACKLOG_FILE_NAME).exists())
        prompt, system_prompt, max_tokens = self.model_provider.complete.call_args.args
        self.assertIn(FEATURE_DESCRIPTION, prompt)
        self.assertIn(PROJECT_CONTEXT, prompt)
        self.assertIn(EXPECTED_SYSTEM_SNIPPET, system_prompt)
        self.assertGreater(max_tokens, 0)

    def test_backlog_md_written_correctly(self) -> None:
        """Verify backlog.md uses the required structured markdown format."""
        self.model_provider.complete.return_value = self._model_json()

        self.agent.handle(self._new_feature_event())

        backlog = self._read_backlog()
        self.assertIn(BACKLOG_TITLE, backlog)
        self.assertIn(HIGH_PRIORITY_HEADING, backlog)
        self.assertIn(TASK_TITLE, backlog)
        self.assertIn(f"- Type: {TASK_TYPE_FEATURE}", backlog)
        self.assertIn(f"- Complexity: {TASK_COMPLEXITY_MEDIUM}", backlog)
        self.assertIn(f"- Agent: {TASK_AGENT_ASSIGNMENT}", backlog)
        self.assertIn(f"  - [ ] {ACCEPTANCE_CRITERION}", backlog)
        self.assertIn(f"- Status: {PENDING_STATUS}", backlog)
        self.assertRegex(backlog, TASK_ID_PATTERN)

    def test_task_json_parse_valid(self) -> None:
        """Verify valid model JSON parses into Task dataclasses."""
        tasks = self.agent.parse_tasks(self._model_json())

        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(isinstance(task, Task) for task in tasks))
        self.assertRegex(tasks[0].id, TASK_ID_PATTERN)
        self.assertRegex(tasks[1].id, TASK_ID_PATTERN_SECOND)
        self.assertEqual(tasks[1].dependencies, [tasks[0].id])

    def test_task_json_parse_invalid_graceful(self) -> None:
        """Verify malformed JSON returns failure without crashing."""
        self.model_provider.complete.return_value = MALFORMED_JSON

        result = self.agent.handle(self._new_feature_event())

        self.assertFalse(result.success)
        self.assertFalse((self.project_root / BACKLOG_FILE_NAME).exists())

    def test_emits_backlog_changed_event(self) -> None:
        """Verify generated tasks emit BACKLOG_CHANGED events."""
        self.model_provider.complete.return_value = self._model_json()
        event = self._new_feature_event()

        result = self.agent.handle(event)

        self.assertEqual(len(result.next_events), 2)
        self.assertTrue(
            all(
                next_event.event_type is EventType.BACKLOG_CHANGED
                for next_event in result.next_events
            )
        )
        first_event = result.next_events[0]
        self.assertEqual(first_event.source_agent, PLANNING_AGENT_NAME)
        self.assertEqual(first_event.correlation_id, event.event_id)
        self.assertEqual(first_event.payload[TARGET_AGENT_KEY], TASK_AGENT_ASSIGNMENT)
        self.assertEqual(first_event.payload[TASK_TYPE_KEY], TASK_TYPE_FEATURE)
        self.assertEqual(first_event.payload[TASK_ID_KEY], first_event.payload["id"])

    def _new_feature_event(self) -> AgentEvent:
        """Create a valid NEW_FEATURE event."""
        return AgentEvent(
            event_type=EventType.NEW_FEATURE,
            source_agent=SOURCE_AGENT,
            payload={
                DESCRIPTION_KEY: FEATURE_DESCRIPTION,
                PROJECT_CONTEXT_KEY: PROJECT_CONTEXT,
            },
        )

    def _model_json(self) -> str:
        """Return mocked valid planning JSON."""
        return json.dumps(self._model_tasks())

    def _model_tasks(self) -> list[Mapping[str, object]]:
        """Return mocked model task dictionaries."""
        return [
            {
                "id": DEPENDENCY_MODEL_ID,
                "title": TASK_TITLE,
                "type": TASK_TYPE_FEATURE,
                "priority": TASK_PRIORITY_HIGH,
                "estimated_complexity": TASK_COMPLEXITY_MEDIUM,
                "dependencies": [],
                "acceptance_criteria": [ACCEPTANCE_CRITERION],
                "agent_assignment": TASK_AGENT_ASSIGNMENT,
                "blocked_by": None,
            },
            {
                "id": DEPENDENCY_TEST_ID,
                "title": TASK_TITLE_SECOND,
                "type": TASK_TYPE_TEST,
                "priority": TASK_PRIORITY_MEDIUM,
                "estimated_complexity": TASK_COMPLEXITY_SMALL,
                "dependencies": [DEPENDENCY_MODEL_ID],
                "acceptance_criteria": [ACCEPTANCE_CRITERION_SECOND],
                "agent_assignment": TEST_AGENT_ASSIGNMENT,
                "blocked_by": None,
            },
        ]

    def _read_backlog(self) -> str:
        """Read the isolated backlog file."""
        return (self.project_root / BACKLOG_FILE_NAME).read_text(
            encoding=TEST_ENCODING
        )


if __name__ == "__main__":
    unittest.main()
