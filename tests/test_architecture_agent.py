"""Unit tests for the Architecture Agent."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from typing import Mapping
from unittest.mock import Mock

from agents.architecture_agent import ArchitectureAgent
from core.events import AgentEvent, EventType


SOURCE_AGENT = "unit_test"
TEST_ENCODING = "utf-8"
QUESTION_KEY = "question"
CONTEXT_KEY = "context"
AFFECTED_COMPONENTS_KEY = "affected_components"
QUESTION = "Should ProjectOS route filesystem events through Clone?"
CONTEXT = "Clone owns event dispatch decisions."
COMPONENT = "core/trigger_system.py"
DECISION_REQUIRED = "Route filesystem events through Clone"
RECOMMENDATION = "Use a queue-only trigger system and let Clone dispatch."
ADR_CONTENT = "# ADR: Route filesystem events through Clone\n\nUse queue-only triggers."
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_LOW = "LOW"
ADR_PATH_KEY = "adr_path"
RECOMMENDATION_KEY = "recommendation"
CONFIDENCE_KEY = "confidence"
ERROR_KEY = "error"
INVALID_JSON = "{invalid json"


class ArchitectureAgentTestCase(unittest.TestCase):
    """Tests ArchitectureAgent ADR generation behavior."""

    def setUp(self) -> None:
        """Create an isolated ArchitectureAgent for each test."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.model_provider = Mock()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.disabled = True
        self.agent = ArchitectureAgent(
            model_provider=self.model_provider,
            logger=self.logger,
            project_root=self.project_root,
        )

    def tearDown(self) -> None:
        """Remove the isolated project root."""
        self._temp_dir.cleanup()

    def test_handle_architecture_question_writes_adr(self) -> None:
        """Verify a valid architecture question writes an ADR file."""
        self.model_provider.complete.return_value = self._model_json(CONFIDENCE_HIGH)

        result = self.agent.handle(self._architecture_event())

        adr_path = Path(result.output[ADR_PATH_KEY])
        self.assertTrue(result.success)
        self.assertEqual(result.output[RECOMMENDATION_KEY], RECOMMENDATION)
        self.assertTrue(adr_path.exists())
        self.assertEqual(adr_path.read_text(encoding=TEST_ENCODING), ADR_CONTENT + "\n")
        prompt, system_prompt, max_tokens = self.model_provider.complete.call_args.args
        self.assertIn(QUESTION, prompt)
        self.assertIn(CONTEXT, prompt)
        self.assertIn(COMPONENT, prompt)
        self.assertIn("principal systems architect", system_prompt)
        self.assertGreater(max_tokens, 0)

    def test_low_confidence_escalates(self) -> None:
        """Verify LOW confidence decisions request escalation."""
        self.model_provider.complete.return_value = self._model_json(CONFIDENCE_LOW)

        result = self.agent.handle(self._architecture_event())

        self.assertTrue(result.success)
        self.assertTrue(result.escalate)
        self.assertEqual(result.output[CONFIDENCE_KEY], CONFIDENCE_LOW)

    def test_invalid_json_fails_gracefully(self) -> None:
        """Verify malformed model JSON returns failure without writing ADRs."""
        self.model_provider.complete.return_value = INVALID_JSON

        result = self.agent.handle(self._architecture_event())

        self.assertFalse(result.success)
        self.assertIn(ERROR_KEY, result.output)
        self.assertFalse((self.project_root / "docs" / "adr").exists())

    def _architecture_event(self) -> AgentEvent:
        """Create a valid ARCHITECTURE_QUESTION event."""
        return AgentEvent(
            event_type=EventType.ARCHITECTURE_QUESTION,
            source_agent=SOURCE_AGENT,
            payload={
                QUESTION_KEY: QUESTION,
                CONTEXT_KEY: CONTEXT,
                AFFECTED_COMPONENTS_KEY: [COMPONENT],
            },
        )

    def _model_json(self, confidence: str) -> str:
        """Return mocked valid architecture JSON."""
        return json.dumps(self._model_decision(confidence))

    def _model_decision(self, confidence: str) -> Mapping[str, object]:
        """Return a mocked model decision dictionary."""
        return {
            "decision_required": DECISION_REQUIRED,
            "risks": ["Clone may become overloaded"],
            "alternatives": [
                {
                    "name": "Queue-only trigger",
                    "pros": ["Clear routing"],
                    "cons": ["Requires Clone polling"],
                }
            ],
            "recommendation": RECOMMENDATION,
            "adr_content": ADR_CONTENT,
            "confidence": confidence,
        }


if __name__ == "__main__":
    unittest.main()
