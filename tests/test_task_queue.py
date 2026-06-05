"""Unit tests for TaskQueue."""

from __future__ import annotations

import logging
import unittest

from core.events import AgentEvent, AgentResult, EventType
from core.task_queue import TaskQueue


SOURCE_AGENT = "unit_test"
CORRELATION_ID = "corr-123"
PERMISSION_CONTEXT_KEY = "permission_context"
PERMISSION_GRANTED_KEY = "permission_granted"


class RecordingAgent:
    """Target agent test double that records handled events."""

    def __init__(self) -> None:
        """Initialize captured event state."""
        self.events: list[AgentEvent] = []

    def handle(self, event: AgentEvent) -> AgentResult:
        """Record an event and return a successful result."""
        self.events.append(event)
        return AgentResult(success=True, output={"handled": True})


class FailingAgent:
    """Target agent test double that raises during handling."""

    def handle(self, event: AgentEvent) -> AgentResult:
        """Raise to verify TaskQueue swallows target exceptions."""
        raise RuntimeError("boom")


class TaskQueueTestCase(unittest.TestCase):
    """Tests TaskQueue execution and blocked-task behavior."""

    def setUp(self) -> None:
        """Disable queue logging noise for intentional failure tests."""
        self.logger = logging.getLogger("projectos.task_queue")
        self._logger_disabled = self.logger.disabled
        self.logger.disabled = True

    def tearDown(self) -> None:
        """Shutdown any queue created by a test."""
        queue = getattr(self, "task_queue", None)
        if queue is not None:
            queue.shutdown(wait=True)
        self.logger.disabled = self._logger_disabled

    def test_submit_runs_target_agent(self) -> None:
        """Verify submit executes the target agent in the worker pool."""
        self.task_queue = TaskQueue(max_workers=1)
        agent = RecordingAgent()
        event = self._event(EventType.CODE_CHANGED)

        future = self.task_queue.submit(event, agent)
        self.assertIsNotNone(future)
        result = future.result(timeout=5)

        self.assertTrue(result.success)
        self.assertEqual(agent.events, [event])
        self.assertEqual(self.task_queue.get_pending_count(), 0)

    def test_blocked_event_stored_and_unblocked(self) -> None:
        """Verify blocked events are deferred and resume with permission context."""
        self.task_queue = TaskQueue(max_workers=1)
        agent = RecordingAgent()
        event = self._event(
            EventType.CODE_CHANGED,
            correlation_id=CORRELATION_ID,
            blocked_by="approval",
        )

        future = self.task_queue.submit(event, agent)
        self.assertIsNone(future)
        self.assertEqual(self.task_queue.get_blocked(), [event])

        resumed_future = self.task_queue.unblock(CORRELATION_ID)
        self.assertIsNotNone(resumed_future)
        resumed_future.result(timeout=5)

        self.assertEqual(len(agent.events), 1)
        resumed_event = agent.events[0]
        self.assertIs(resumed_event.event_type, EventType.CODE_CHANGED)
        self.assertEqual(resumed_event.correlation_id, CORRELATION_ID)
        self.assertIsNone(resumed_event.blocked_by)
        self.assertEqual(
            resumed_event.payload[PERMISSION_CONTEXT_KEY],
            EventType.PERMISSION_GRANTED.value,
        )
        self.assertTrue(resumed_event.payload[PERMISSION_GRANTED_KEY])

    def test_target_exception_does_not_raise_to_caller(self) -> None:
        """Verify target exceptions are contained inside the queue worker."""
        self.task_queue = TaskQueue(max_workers=1)
        event = self._event(EventType.CODE_CHANGED)

        future = self.task_queue.submit(event, FailingAgent())
        self.assertIsNotNone(future)

        self.assertIsNone(future.result(timeout=5))

    def _event(
        self,
        event_type: EventType,
        correlation_id: str | None = None,
        blocked_by: str | None = None,
    ) -> AgentEvent:
        """Create a test event with shared defaults."""
        return AgentEvent(
            event_type=event_type,
            source_agent=SOURCE_AGENT,
            payload={},
            correlation_id=correlation_id,
            blocked_by=blocked_by,
        )


if __name__ == "__main__":
    unittest.main()
