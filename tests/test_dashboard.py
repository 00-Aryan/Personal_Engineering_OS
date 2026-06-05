"""Unit tests for the ProjectOS terminal dashboard."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from cli.dashboard import Dashboard
from core.decision_log import DecisionLogger
from core.persistence import PersistenceManager


PENDING_COUNT = 2
BLOCKED_COUNT = 1
CLONE_AGENT = "clone"
CLONE_STATUS = "ACTIVE"
GEMINI_PROVIDER = "gemini"
OLLAMA_PROVIDER = "ollama"
EVENT_ID_ONE = "event-1"
EVENT_ID_TWO = "event-2"
AUTONOMOUS_CATEGORY = "AUTONOMOUS"
ESCALATE_CATEGORY = "ESCALATE"
OUTCOME = "outcome"
REASONING = "reasoning"


class FakeTaskQueue:
    """TaskQueue test double for dashboard data collection."""

    def get_pending_count(self) -> int:
        """Return a fixed pending count."""
        return PENDING_COUNT

    def get_blocked(self) -> list[Any]:
        """Return fixed blocked task placeholders."""
        return [object() for _item in range(BLOCKED_COUNT)]


class FakeHealthMonitor:
    """ProviderHealthMonitor test double for dashboard data collection."""

    def get_status(self) -> dict[str, bool]:
        """Return fixed provider health statuses."""
        return {
            GEMINI_PROVIDER: True,
            OLLAMA_PROVIDER: False,
        }


class DashboardTestCase(unittest.TestCase):
    """Tests dashboard setup and component data fetching."""

    def setUp(self) -> None:
        """Create isolated dashboard dependencies."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.decision_logger = DecisionLogger(self.project_root)
        self.persistence_manager = PersistenceManager(self.project_root / "state")
        self.persistence_manager.snapshot_status({CLONE_AGENT: CLONE_STATUS})
        self.dashboard = Dashboard(
            task_queue=FakeTaskQueue(),
            decision_logger=self.decision_logger,
            persistence_manager=self.persistence_manager,
            health_monitor=FakeHealthMonitor(),
        )

    def tearDown(self) -> None:
        """Clean up isolated dashboard dependencies."""
        self.dashboard.stop()
        self._temp_dir.cleanup()

    def test_dashboard_initializes_without_error(self) -> None:
        """Verify dashboard construction stores component references."""
        self.assertIs(self.dashboard.task_queue.__class__, FakeTaskQueue)
        self.assertIs(self.dashboard.decision_logger, self.decision_logger)
        self.assertIs(self.dashboard.persistence_manager, self.persistence_manager)

    def test_dashboard_stop_does_not_raise(self) -> None:
        """Verify stopping an inactive dashboard is safe."""
        self.dashboard.stop()
        self.dashboard.stop()

    def test_layout_data_fetched_from_components(self) -> None:
        """Verify dashboard data is fetched from queue, health, and decisions."""
        self.decision_logger.log(
            EVENT_ID_ONE,
            None,
            CLONE_AGENT,
            AUTONOMOUS_CATEGORY,
            REASONING,
            OUTCOME,
        )
        self.decision_logger.log(
            EVENT_ID_TWO,
            None,
            CLONE_AGENT,
            ESCALATE_CATEGORY,
            REASONING,
            OUTCOME,
        )

        data = self.dashboard.layout_data()

        self.assertEqual(data.queue.pending, PENDING_COUNT)
        self.assertEqual(data.queue.blocked, BLOCKED_COUNT)
        self.assertGreaterEqual(data.queue.completed_today, 2)
        self.assertEqual(data.agents[0].name, CLONE_AGENT)
        self.assertEqual(data.agents[0].status, CLONE_STATUS)
        self.assertEqual(data.providers[0].name, GEMINI_PROVIDER)
        self.assertTrue(data.providers[0].healthy)
        self.assertEqual(data.providers[1].name, OLLAMA_PROVIDER)
        self.assertFalse(data.providers[1].healthy)
        self.assertEqual(len(data.recent_decisions), 2)
        self.assertEqual(data.recent_decisions[-1].decision_category, ESCALATE_CATEGORY)


if __name__ == "__main__":
    unittest.main()
