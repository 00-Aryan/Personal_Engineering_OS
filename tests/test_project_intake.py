"""Unit tests for Project Intake Agent and Phase Manager."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from agents.project_intake_agent import ProjectIntakeAgent
from core.events import AgentEvent, EventType
from core.phase_manager import PhaseManager, PhaseStatus
from core.trigger_system import FileChangeHandler, TriggerSystem


class ProjectIntakeTestCase(unittest.TestCase):
    """Tests ProjectIntakeAgent and PhaseManager functionality."""

    def setUp(self) -> None:
        """Set up isolated directories and mock dependencies."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.state_dir = self.project_root / ".projectos_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.model_provider = Mock()
        self.notifier = Mock()
        self.task_queue = Mock()
        self.clone_agent = Mock()
        self.clone_agent.project_root = self.project_root

        # PhaseManager setup
        self.phase_manager = PhaseManager(
            notifier=self.notifier,
            state_dir=self.state_dir,
            task_queue=self.task_queue,
            clone_agent=self.clone_agent,
        )

        # Intake agent setup
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.disabled = True
        self.agent = ProjectIntakeAgent(
            model_provider=self.model_provider,
            logger=self.logger,
            notifier=self.notifier,
            project_root=self.project_root,
            state_dir=self.state_dir,
            phase_manager=self.phase_manager,
        )

    def tearDown(self) -> None:
        """Clean up the temporary directory."""
        self._temp_dir.cleanup()

    def test_new_project_event_triggers_intake(self) -> None:
        """Verify NEW_PROJECT event triggers the intake agent successfully."""
        description_file = self.project_root / "project_description.md"
        description_file.write_text("Project Name: TestProj\nBuild a compiler.", encoding="utf-8")

        # Mock LLM calls: extraction and planning
        self.model_provider.complete.side_effect = [
            json.dumps({"project_name": "TestProj", "description": "compiler", "tech_stack": "python", "goals": ["build it"]}),
            json.dumps({
                "project_name": "TestProj",
                "phases": [
                    {
                        "phase_id": "phase_1",
                        "phase_number": 1,
                        "name": "Implementation",
                        "goal": "Core compiler functionality",
                        "tasks": [
                            {
                                "title": "Lexer",
                                "type": "feature",
                                "priority": "HIGH",
                                "complexity": "S",
                                "acceptance_criteria": ["tokenize works"],
                            }
                        ],
                        "success_criteria": ["Lexer tests pass"],
                    }
                ],
            })
        ]

        # Use immediate timeout so wait_for_answers returns empty dict immediately
        event = AgentEvent(
            event_type=EventType.NEW_PROJECT,
            source_agent="unit_test",
            payload={"context_file_path": str(description_file), "timeout_hours": 0.0001},
        )

        result = self.agent.handle(event)

        self.assertTrue(result.success)
        self.assertIn("plan", result.output)
        self.assertEqual(result.output["plan"]["project_name"], "TestProj")
        self.assertTrue((self.project_root / ".projectos" / "TestProj" / "plan.md").exists())

    def test_intake_sends_questions_via_telegram(self) -> None:
        """Verify the intake agent sends clarifying questions via notifier."""
        description_file = self.project_root / "project_description.md"
        description_file.write_text("Project: SuperApp", encoding="utf-8")

        self.model_provider.complete.side_effect = [
            json.dumps({"project_name": "SuperApp"}),
            json.dumps({"project_name": "SuperApp", "phases": []})
        ]

        event = AgentEvent(
            event_type=EventType.NEW_PROJECT,
            source_agent="unit_test",
            payload={"context_file_path": str(description_file), "timeout_hours": 0.0001},
        )

        self.agent.handle(event)

        self.notifier.send_project_started.assert_called_once()
        args, kwargs = self.notifier.send_project_started.call_args
        self.assertEqual(kwargs.get("project_name"), "SuperApp")
        self.assertEqual(len(kwargs.get("questions")), len(self.agent.INTAKE_QUESTIONS))

    def test_intake_waits_for_answers(self) -> None:
        """Verify the intake agent reads written answers before planning."""
        description_file = self.project_root / "project_description.md"
        description_file.write_text("Project: SuperApp", encoding="utf-8")

        self.model_provider.complete.side_effect = [
            json.dumps({"project_name": "SuperApp"}),
            json.dumps({"project_name": "SuperApp", "phases": []})
        ]

        # Patch wait_for_answers to write to answers file mid-wait
        original_wait = self.agent._wait_for_answers
        
        def mock_wait(intake_id, timeout_hours):
            answers_dir = self.state_dir / "intake_answers"
            answers_dir.mkdir(parents=True, exist_ok=True)
            answers_file = answers_dir / f"{intake_id}.txt"
            answers_file.write_text(json.dumps({"question_1": "Myself"}), encoding="utf-8")
            return original_wait(intake_id, timeout_hours)

        self.agent._wait_for_answers = mock_wait

        event = AgentEvent(
            event_type=EventType.NEW_PROJECT,
            source_agent="unit_test",
            payload={"context_file_path": str(description_file), "timeout_hours": 0.01},
        )

        result = self.agent.handle(event)
        self.assertTrue(result.success)
        
        # Verify plan was generated based on the answers
        args, kwargs = self.model_provider.complete.call_args_list[1]
        prompt = kwargs.get("prompt") or args[0]
        self.assertIn("Myself", prompt)

    def test_intake_proceeds_on_timeout(self) -> None:
        """Verify that the intake agent proceeds with planning if answers timeout."""
        description_file = self.project_root / "project_description.md"
        description_file.write_text("Project: QuickApp", encoding="utf-8")

        self.model_provider.complete.side_effect = [
            json.dumps({"project_name": "QuickApp"}),
            json.dumps({"project_name": "QuickApp", "phases": []})
        ]

        # Use an extremely small timeout value
        event = AgentEvent(
            event_type=EventType.NEW_PROJECT,
            source_agent="unit_test",
            payload={"context_file_path": str(description_file), "timeout_hours": 0.00001},
        )

        result = self.agent.handle(event)
        self.assertTrue(result.success)
        self.notifier.send.assert_called()
        self.assertIn("No answers received", self.notifier.send.call_args[0][0])

    def test_phase_manager_creates_phases_from_plan(self) -> None:
        """Verify PhaseManager converts planning dict to Phase objects."""
        plan = {
            "project_name": "MyProj",
            "phases": [
                {
                    "phase_id": "phase_1",
                    "phase_number": 1,
                    "name": "Phase One",
                    "goal": "Setup",
                    "tasks": [
                        {
                            "title": "Configure tests",
                            "type": "test",
                            "priority": "HIGH",
                            "complexity": "S",
                            "acceptance_criteria": ["tests pass"],
                        }
                    ],
                }
            ]
        }

        phases = self.phase_manager.create_phases_from_plan("MyProj", plan, approval_id="app-123")

        self.assertEqual(len(phases), 2)  # phase_0 (planning) + phase_1
        self.assertEqual(phases[0].phase_id, "phase_0")
        self.assertEqual(phases[0].status, PhaseStatus.AWAITING_APPROVAL)
        self.assertEqual(phases[1].phase_id, "phase_1")
        self.assertEqual(phases[1].status, PhaseStatus.PENDING)

    def test_approve_phase_submits_tasks_to_queue(self) -> None:
        """Verify approving a phase updates status and submits its tasks to the queue."""
        plan = {
            "project_name": "MyProj",
            "phases": [
                {
                    "phase_id": "phase_1",
                    "phase_number": 1,
                    "name": "Phase One",
                    "goal": "Setup",
                    "tasks": [
                        {
                            "title": "Configure tests",
                            "type": "test",
                            "priority": "HIGH",
                            "complexity": "S",
                            "acceptance_criteria": ["tests pass"],
                        }
                    ],
                }
            ]
        }

        self.phase_manager.create_phases_from_plan("MyProj", plan, approval_id="app-123")
        
        # Approve phase_0 (planning phase)
        success = self.phase_manager.approve_phase("app-123")
        self.assertTrue(success)

        # Check that tasks from Phase 1 were submitted
        self.task_queue.submit.assert_called_once()
        submitted_event = self.task_queue.submit.call_args[0][0]
        self.assertEqual(submitted_event.event_type, EventType.BACKLOG_CHANGED)
        self.assertEqual(submitted_event.payload["title"], "Configure tests")

    def test_reject_phase_triggers_replanning(self) -> None:
        """Verify rejecting a phase transitions status to REJECTED and emits NEW_PROJECT."""
        plan = {
            "project_name": "MyProj",
            "phases": [
                {
                    "phase_id": "phase_1",
                    "phase_number": 1,
                    "name": "Phase One",
                    "goal": "Setup",
                    "tasks": [],
                }
            ]
        }

        self.phase_manager.create_phases_from_plan("MyProj", plan, approval_id="app-123")

        # Reject the phase
        success = self.phase_manager.reject_phase("app-123", reason="Too complex")
        self.assertTrue(success)

        # Verify event dispatching for replanning
        self.clone_agent.dispatch.assert_called_once()
        emitted_event = self.clone_agent.dispatch.call_args[0][0]
        self.assertEqual(emitted_event.event_type, EventType.NEW_PROJECT)
        self.assertEqual(emitted_event.payload.get("rejection_reason"), "Too complex")

    def test_trigger_system_detects_project_description_file(self) -> None:
        """Verify TriggerSystem FileChangeHandler enqueues NEW_PROJECT events."""
        dispatcher = Mock()
        handler = FileChangeHandler(dispatcher)

        # Trigger system callback simulation
        from types import SimpleNamespace
        event = SimpleNamespace(src_path=str(self.project_root / "project_description.md"), is_directory=False)
        handler.on_created(event)

        dispatcher.put_nowait.assert_called_once()
        enqueued_event = dispatcher.put_nowait.call_args[0][0]
        self.assertEqual(enqueued_event.event_type, EventType.NEW_PROJECT)
        self.assertEqual(enqueued_event.payload.get("context_file_path"), str(self.project_root / "project_description.md"))
