"""Unit tests for the Clone Agent supervisor."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from typing import Mapping
from unittest.mock import Mock

from core.clone_agent import CloneAgent, DecisionCategory
from core.events import AgentEvent, EventType


TARGET_AGENT_KEY = "target_agent"
TASK_TYPE_KEY = "task_type"
NEW_DEPENDENCY_KEY = "new_dependency"
DELETE_FILE_KEY = "delete_file"
DOCS_TASK_TYPE = "docs"
CODE_REVIEW_TARGET = "code_review"
TEST_AGENT_TARGET = "test_agent"
DOCS_AGENT_TARGET = "docs_agent"
PENDING_STATUS = "PENDING"
ESCALATE_CATEGORY = "ESCALATE"
AUTONOMOUS_CATEGORY = "AUTONOMOUS"
DEFER_PARALLEL_CATEGORY = "DEFER_PARALLEL"
BLOCKED_BY_PERMISSION = "permission"
ESCALATION_REASON = "delete requested"
SOURCE_AGENT = "unit_test"
TEST_ENCODING = "utf-8"


class CloneAgentTestCase(unittest.TestCase):
    """Tests CloneAgent decision and dispatch behavior."""

    def setUp(self) -> None:
        """Create an isolated CloneAgent for each test."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.model_provider = Mock()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.disabled = True
        self.agent = CloneAgent(
            model_provider=self.model_provider,
            logger=self.logger,
            project_root=self.project_root,
        )

    def tearDown(self) -> None:
        """Remove the isolated project root."""
        self._temp_dir.cleanup()

    def test_classify_autonomous(self) -> None:
        """Verify DOCS_UPDATED events are classified as autonomous."""
        event = self._event(EventType.DOCS_UPDATED)

        decision = self.agent.classify_decision(event)

        self.assertEqual(decision, DecisionCategory.AUTONOMOUS)

    def test_classify_escalate(self) -> None:
        """Verify new dependency payloads are escalated."""
        event = self._event(
            EventType.CODE_CHANGED,
            payload={NEW_DEPENDENCY_KEY: True},
        )

        decision = self.agent.classify_decision(event)

        self.assertEqual(decision, DecisionCategory.ESCALATE)

    def test_classify_defer(self) -> None:
        """Verify blocked events are deferred for parallel work."""
        event = self._event(
            EventType.CODE_CHANGED,
            blocked_by=BLOCKED_BY_PERMISSION,
        )

        decision = self.agent.classify_decision(event)

        self.assertEqual(decision, DecisionCategory.DEFER_PARALLEL)

    def test_dispatch_code_changed(self) -> None:
        """Verify CODE_CHANGED dispatches to review, test, and docs agents."""
        event = self._event(EventType.CODE_CHANGED)

        next_events = self.agent.dispatch(event)

        self.assertEqual(
            [next_event.payload[TARGET_AGENT_KEY] for next_event in next_events],
            [CODE_REVIEW_TARGET, TEST_AGENT_TARGET, DOCS_AGENT_TARGET],
        )
        self.assertEqual(len(next_events), 3)

    def test_dispatch_backlog(self) -> None:
        """Verify BACKLOG_CHANGED routes based on backlog task type."""
        event = self._event(
            EventType.BACKLOG_CHANGED,
            payload={TASK_TYPE_KEY: DOCS_TASK_TYPE},
        )

        next_events = self.agent.dispatch(event)

        self.assertEqual(len(next_events), 1)
        self.assertEqual(next_events[0].payload[TARGET_AGENT_KEY], DOCS_AGENT_TARGET)

    def test_handle_blocked_finds_independent_work(self) -> None:
        """Verify blocked handling returns queued events with no dependency."""
        independent_event = self._event(EventType.NEW_FEATURE)
        dependent_event = self._event(
            EventType.CODE_CHANGED,
            blocked_by=BLOCKED_BY_PERMISSION,
        )
        self.agent.event_queue = [independent_event, dependent_event]
        blocked_event = self._event(
            EventType.PERMISSION_BLOCKED,
            blocked_by=BLOCKED_BY_PERMISSION,
        )

        next_events = self.agent.handle_blocked(blocked_event)

        self.assertEqual(next_events, [independent_event])
        self.assertEqual(self.agent.event_queue, [dependent_event])
        blocked_tasks = self._read_file("blocked_tasks.md")
        self.assertIn(blocked_event.event_id, blocked_tasks)
        self.assertIn(blocked_event.correlation_id or blocked_event.event_id, blocked_tasks)

    def test_escalation_writes_to_queue(self) -> None:
        """Verify escalation writes queue and decision-log entries."""
        event = self._event(
            EventType.CODE_CHANGED,
            payload={DELETE_FILE_KEY: True},
        )

        self.agent.escalate(event, ESCALATION_REASON)

        escalation_queue = self._read_file("escalation_queue.md")
        decisions_log = self._read_file("decisions.log")
        self.assertIn(event.event_id, escalation_queue)
        self.assertIn(ESCALATION_REASON, escalation_queue)
        self.assertIn(PENDING_STATUS, escalation_queue)
        self.assertIn(event.event_id, decisions_log)
        self.assertIn(ESCALATE_CATEGORY, decisions_log)

    def test_decisions_logged_for_every_handle_call(self) -> None:
        """Verify each handle call appends one auditable decision."""
        autonomous_event = self._event(EventType.DOCS_UPDATED)
        blocked_event = self._event(
            EventType.PERMISSION_BLOCKED,
            blocked_by=BLOCKED_BY_PERMISSION,
        )

        self.agent.handle(autonomous_event)
        self.agent.handle(blocked_event)

        decisions_log = self._read_file("decisions.log")
        self.assertIn(autonomous_event.event_id, decisions_log)
        self.assertIn(blocked_event.event_id, decisions_log)
        self.assertIn(AUTONOMOUS_CATEGORY, decisions_log)
        self.assertIn(DEFER_PARALLEL_CATEGORY, decisions_log)
        self.model_provider.complete.assert_not_called()
        self.model_provider.stream.assert_not_called()

    def _event(
        self,
        event_type: EventType,
        payload: Mapping[str, object] | None = None,
        blocked_by: str | None = None,
    ) -> AgentEvent:
        """Create a test event with shared defaults."""
        return AgentEvent(
            event_type=event_type,
            source_agent=SOURCE_AGENT,
            payload=payload or {},
            blocked_by=blocked_by,
        )

    def _read_file(self, file_name: str) -> str:
        """Read a file from the isolated project root."""
        return (self.project_root / file_name).read_text(encoding=TEST_ENCODING)


if __name__ == "__main__":
    unittest.main()
