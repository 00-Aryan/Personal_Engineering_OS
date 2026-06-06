"""Tests for ProjectOS agent collaboration."""

from __future__ import annotations

import json
import logging
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from core.agent_registry import AgentRegistry
from core.base_agent import BaseAgent
from core.events import AgentEvent, AgentResult
from core.intelligence.collaboration import (
    CollaborationBroker,
    ConsultationRequest,
    ConsultationType,
)


TEST_ENCODING = "utf-8"
REQUESTING_AGENT = "planning"
TARGET_AGENT = "architecture"
QUESTION = "Is this plan viable?"
ANSWER = "Use the existing service boundary."
RECOMMENDED_ACTION = "continue"
TIMEOUT_SECONDS = 0.001
SLEEP_SECONDS = 0.05


class FakeModelProvider:
    """Minimal model provider test double."""


class RespondingAgent:
    """Test agent that returns a deterministic consultation answer."""

    def __init__(self, output: Any) -> None:
        """Initialize the fake target with fixed output."""
        self.output = output
        self.handled_events: list[AgentEvent] = []

    def handle(self, event: AgentEvent) -> AgentResult:
        """Capture the event and return the fixed output."""
        self.handled_events.append(event)
        return AgentResult(success=True, output=self.output)


class SlowAgent:
    """Test agent that exceeds the configured broker timeout."""

    def handle(self, event: AgentEvent) -> AgentResult:
        """Sleep long enough to force a timeout."""
        time.sleep(SLEEP_SECONDS)
        return AgentResult(success=True, output=ANSWER)


class MinimalAgent(BaseAgent):
    """Concrete BaseAgent for testing helper methods."""

    def __init__(self) -> None:
        """Initialize a minimal agent with no collaboration broker."""
        super().__init__(
            "minimal",
            "minimal test agent",
            FakeModelProvider(),
            logging.getLogger(__name__),
        )

    def handle(self, event: AgentEvent) -> AgentResult:
        """Return a successful result for abstract method compliance."""
        return AgentResult(success=True, output={})


class CollaborationTestCase(unittest.TestCase):
    """Unit tests for the CollaborationBroker and BaseAgent helper."""

    def setUp(self) -> None:
        """Create an isolated collaboration broker."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.log_path = self.project_root / "collaboration.jsonl"
        self.registry = AgentRegistry()
        self.target = RespondingAgent(
            {
                "answer": ANSWER,
                "confidence": 0.9,
                "recommended_action": RECOMMENDED_ACTION,
            }
        )
        self.registry.register(TARGET_AGENT, self.target)  # type: ignore[arg-type]
        self.broker = CollaborationBroker(self.registry, self.log_path)

    def tearDown(self) -> None:
        """Remove the isolated project root."""
        self._temp_dir.cleanup()

    def test_consult_returns_result(self) -> None:
        """Verify a broker consultation returns the target answer."""
        result = self.broker.consult(self._request())

        self.assertEqual(result.answer, ANSWER)
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(result.recommended_action, RECOMMENDED_ACTION)
        self.assertEqual(len(self.target.handled_events), 1)
        self.assertEqual(self.target.handled_events[0].payload["depth"], 1)

    def test_depth_limit_prevents_cascading(self) -> None:
        """Verify depth-limited consultations do not call the target."""
        request = self._request(depth=1)

        result = self.broker.consult(request)

        self.assertEqual(result.confidence, 0.0)
        self.assertIn("depth limit", result.answer)
        self.assertEqual(self.target.handled_events, [])

    def test_agent_cannot_consult_itself(self) -> None:
        """Verify self-consultations are rejected."""
        request = ConsultationRequest(
            requesting_agent=TARGET_AGENT,
            target_agent=TARGET_AGENT,
            consultation_type=ConsultationType.FEASIBILITY_CHECK,
            question=QUESTION,
            context="",
        )

        result = self.broker.consult(request)

        self.assertEqual(result.confidence, 0.0)
        self.assertIn("cannot consult themselves", result.answer)

    def test_consultation_logged_to_jsonl(self) -> None:
        """Verify consultations are appended to the JSONL audit log."""
        result = self.broker.consult(self._request())

        records = self._log_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["consultation_id"], result.consultation_id)
        self.assertEqual(records[0]["answer"], ANSWER)

    def test_timeout_returns_graceful_result(self) -> None:
        """Verify timeout failures return a graceful consultation result."""
        registry = AgentRegistry()
        registry.register(TARGET_AGENT, SlowAgent())  # type: ignore[arg-type]
        broker = CollaborationBroker(
            registry,
            self.log_path,
            timeout_seconds=TIMEOUT_SECONDS,
        )

        result = broker.consult(self._request())

        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.answer, "Consultation timed out")

    def test_collaboration_stats_tracked(self) -> None:
        """Verify broker stats aggregate logged consultations."""
        self.broker.consult(self._request())
        self.broker.consult(
            self._request(consultation_type=ConsultationType.ARCHITECTURE_REVIEW)
        )

        stats = self.broker.get_collaboration_stats()

        self.assertEqual(stats["total_consultations"], 2)
        self.assertEqual(stats["by_requesting_agent"][REQUESTING_AGENT], 2)
        self.assertEqual(stats["by_type"]["feasibility_check"], 1)
        self.assertEqual(stats["by_type"]["architecture_review"], 1)

    def test_consult_with_no_broker_returns_none(self) -> None:
        """Verify BaseAgent.consult is a no-op without a broker."""
        agent = MinimalAgent()

        answer = agent.consult(TARGET_AGENT, QUESTION, "")

        self.assertIsNone(answer)

    def _request(
        self,
        depth: int = 0,
        consultation_type: ConsultationType = ConsultationType.FEASIBILITY_CHECK,
    ) -> ConsultationRequest:
        """Return a standard consultation request."""
        return ConsultationRequest(
            requesting_agent=REQUESTING_AGENT,
            target_agent=TARGET_AGENT,
            consultation_type=consultation_type,
            question=QUESTION,
            context="context",
            depth=depth,
        )

    def _log_records(self) -> list[dict[str, Any]]:
        """Read collaboration JSONL records from the test log."""
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding=TEST_ENCODING).splitlines()
        ]


if __name__ == "__main__":
    unittest.main()
