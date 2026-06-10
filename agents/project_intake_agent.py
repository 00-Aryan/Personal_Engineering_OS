"""Project Intake Agent for ProjectOS."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.base_agent import BaseAgent
from core.events import AgentEvent, AgentResult, EventType
from core.model_provider import ModelProvider
from core.notifications.telegram_notifier import TelegramNotifier
from core.project_context import ProjectContextLoader


class ProjectIntakeAgent(BaseAgent):
    """Handles new project onboarding.

    Triggered when: project_description.md or project_context.md
    appears in any watched directory.
    """

    SYSTEM_PROMPT = """
  You are a senior engineering project manager onboarding a new project.
  Your role is to understand the project deeply before planning.
  
  ALWAYS:
  - Ask for clarification on ambiguous requirements
  - Identify unstated technical constraints
  - Suggest phasing that delivers value incrementally
  - Keep phases to 5-7 tasks maximum
  
  NEVER:
  - Assume the tech stack if not stated
  - Plan more than 4 phases initially (add more later)
  - Include tasks that depend on unavailable resources
  
  {project_context}
  """

    INTAKE_QUESTIONS = [
        "What is the primary user of this system? (e.g. yourself, end users, API consumers)",
        "What is the most important thing to get working first?",
        "Are there existing files I should build on, or is this from scratch?",
        "What should I absolutely not change or break?",
        "Any deadline or time pressure on any part of this?",
    ]

    def __init__(
        self,
        model_provider: ModelProvider,
        logger: logging.Logger,
        notifier: TelegramNotifier,
        memory_manager: Optional[Any] = None,
        context_retriever: Optional[Any] = None,
        context_loader: Optional[ProjectContextLoader] = None,
        project_root: Optional[Path | str] = None,
        state_dir: Optional[Path | str] = None,
        phase_manager: Optional[Any] = None,
    ) -> None:
        """Initialize ProjectIntakeAgent."""
        super().__init__(
            name="project_intake",
            role_description="Handles new project onboarding",
            model_provider=model_provider,
            logger=logger,
            context_retriever=context_retriever,
            memory_manager=memory_manager,
            collaboration_broker=None,
            context_loader=context_loader,
        )
        self.notifier = notifier
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.state_dir = Path(state_dir) if state_dir else Path(".projectos_state")
        self.phase_manager = phase_manager

    def handle(self, event: AgentEvent) -> AgentResult:
        """Handle a new project event."""
        if event.event_type != EventType.NEW_PROJECT:
            return AgentResult(
                success=False,
                output={"error": f"Unsupported event type: {event.event_type}"},
            )

        file_path = event.payload.get("context_file_path")
        if not file_path:
            return AgentResult(
                success=False,
                output={"error": "Missing context_file_path in payload"},
            )

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            return AgentResult(
                success=False,
                output={"error": f"File does not exist: {file_path}"},
            )

        try:
            content = file_path_obj.read_text(encoding="utf-8")
        except Exception as e:
            return AgentResult(
                success=False,
                output={"error": f"Failed to read file: {e}"},
            )

        # 1. Extract name, description, tech stack, goals from content
        parent_dir_name = file_path_obj.parent.name
        if not parent_dir_name or parent_dir_name == ".":
            parent_dir_name = file_path_obj.resolve().parent.name

        extract_prompt = (
            f"Analyze the following project description:\n\n{content}\n\n"
            f"Please extract: project name, description, tech stack, and goals.\n"
            f"Return ONLY a valid JSON object with keys: 'project_name', 'description', 'tech_stack', 'goals'.\n"
            f"Use '{parent_dir_name}' as the default for 'project_name' if none is found."
        )

        system_prompt = self.build_system_prompt(self.SYSTEM_PROMPT)

        detected_name = parent_dir_name
        try:
            params = self.get_model_params()
            model_output = self.model_provider.complete(
                prompt=extract_prompt,
                system_prompt=system_prompt,
                temperature=params["temperature"],
                max_tokens=params["max_tokens"],
                top_p=params["top_p"],
                agent_name=self.name,
            )
            cleaned = model_output.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()
            extracted = json.loads(cleaned)
            detected_name = extracted.get("project_name") or parent_dir_name
        except Exception as e:
            self.logger.warning(
                f"Failed to extract project name via LLM: {e}. Falling back to {parent_dir_name}"
            )

        # 2. Ask clarifying questions
        intake_id = str(uuid.uuid4())[:8]

        from core.notifications.telegram_notifier import DisabledNotifier
        if not self.notifier or isinstance(self.notifier, DisabledNotifier):
            # If notifier not configured: write to .projectos/{project}/questions.md instead
            questions_dir = self.project_root / ".projectos" / detected_name
            questions_dir.mkdir(parents=True, exist_ok=True)
            questions_file = questions_dir / "questions.md"
            q_content = f"# Intake Questions for {detected_name}\n\n"
            q_content += "Please provide answers to the following questions to proceed with planning:\n\n"
            for q in self.INTAKE_QUESTIONS:
                q_content += f"- {q}\n"
            q_content += f"\nTo answer, write to `.projectos_state/intake_answers/{intake_id}.txt`"

            from core.phase_manager import _write_atomically
            _write_atomically(questions_file, q_content)
        else:
            self.notifier.send_project_started(
                project_name=detected_name,
                questions=self.INTAKE_QUESTIONS,
                intake_id=intake_id,
            )

        # 3. Poll for answers
        timeout_hours = event.payload.get("timeout_hours", 24)
        answers = self._wait_for_answers(intake_id, timeout_hours=timeout_hours)
        if not answers:
            if self.notifier and not isinstance(self.notifier, DisabledNotifier):
                self.notifier.send(
                    f"⏰ No answers received for {detected_name}. "
                    "Will proceed with best-effort planning."
                )
            answers = {}

        # 4. Generate plan
        plan = self._generate_phased_plan(content, answers)

        # 5. Send plan for approval
        approval_id = str(uuid.uuid4())[:8]
        plan_summary = f"Generated {len(plan.get('phases', []))} phases for {detected_name}."
        if plan.get("phases"):
            first_p = plan["phases"][0]
            plan_summary = f"Phase 1: {first_p.get('name')} - Goal: {first_p.get('goal')}"

        if self.notifier and not isinstance(self.notifier, DisabledNotifier):
            self.notifier.send_phase_complete(
                project_name=detected_name,
                phase_number=0,
                phase_name="Project Plan",
                files_changed=0,
                tests_passing=0,
                next_phase_summary=plan_summary,
                approval_id=approval_id,
            )

        # 6. Initialize phases in PhaseManager
        if self.phase_manager:
            self.phase_manager.create_phases_from_plan(
                detected_name, plan, approval_id=approval_id
            )

        # 7. Write plan to file regardless of approval
        project_dir = self.project_root / ".projectos" / detected_name
        project_dir.mkdir(parents=True, exist_ok=True)

        plan_md = f"# Plan for {detected_name}\n\n"
        for phase in plan.get("phases", []):
            plan_md += f"## Phase {phase.get('phase_number')}: {phase.get('name')}\n"
            plan_md += f"Goal: {phase.get('goal')}\n\n"
            plan_md += "Tasks:\n"
            for t in phase.get("tasks", []):
                plan_md += f"- [ ] {t.get('title')} ({t.get('priority')}, {t.get('complexity')})\n"
                for ac in t.get("acceptance_criteria", []):
                    plan_md += f"  - Acceptance: {ac}\n"
            plan_md += "\n"

        from core.phase_manager import _write_atomically
        _write_atomically(project_dir / "plan.md", plan_md)
        _write_atomically(project_dir / "phases.yaml", yaml.safe_dump(plan))

        return AgentResult(
            success=True,
            output={"plan": plan, "approval_id": approval_id},
        )

    def _wait_for_answers(self, intake_id: str, timeout_hours: float) -> dict:
        """Poll .projectos_state/intake_answers/{intake_id}.txt for answers."""
        import time
        answers_file = self.state_dir / "intake_answers" / f"{intake_id}.txt"
        total_seconds = timeout_hours * 3600.0
        polled_seconds = 0.0
        poll_interval = 0.5 if timeout_hours < 0.05 else 30.0

        event = threading.Event()
        while polled_seconds < total_seconds:
            if answers_file.exists():
                try:
                    content = answers_file.read_text(encoding="utf-8").strip()
                    try:
                        return json.loads(content)
                    except json.JSONDecodeError:
                        lines = content.splitlines()
                        parsed = {}
                        for i, line in enumerate(lines):
                            parsed[f"question_{i+1}"] = line.strip()
                        parsed["raw_answers"] = content
                        return parsed
                except Exception as e:
                    self.logger.warning(f"Failed to read/parse answers file: {e}")

            # wait without blocking the main thread
            event.wait(poll_interval)
            polled_seconds += poll_interval

        return {}

    def _generate_phased_plan(self, description: str, answers: dict) -> dict:
        """Call model provider to generate phases from description and answers."""
        answers_str = "\n".join(f"- {k}: {v}" for k, v in answers.items())
        prompt = (
            f"Please generate a phased project plan based on the following project description and intake answers.\n\n"
            f"Project Description:\n{description}\n\n"
            f"Intake Answers:\n{answers_str}\n\n"
            f"Requirements:\n"
            f"- Split the project into a maximum of 4 phases.\n"
            f"- Each phase must contain between 1 and 7 tasks.\n"
            f"- Each phase must have a name, a goal, a list of tasks, and success_criteria.\n"
            f"- Each task must have a title, a type (feature/bug/refactor/test/docs), a priority (HIGH/MEDIUM/LOW), a complexity (S/M), and acceptance_criteria (list of strings).\n\n"
            f"Return ONLY a valid JSON object matching this schema:\n"
            f"{{\n"
            f"  \"project_name\": \"Name of the project\",\n"
            f"  \"phases\": [\n"
            f"    {{\n"
            f"      \"phase_id\": \"phase_1\",\n"
            f"      \"phase_number\": 1,\n"
            f"      \"name\": \"Phase Name\",\n"
            f"      \"goal\": \"Phase Goal\",\n"
            f"      \"tasks\": [\n"
            f"        {{\n"
            f"          \"title\": \"Task Title\",\n"
            f"          \"type\": \"feature\",\n"
            f"          \"priority\": \"HIGH\",\n"
            f"          \"complexity\": \"S\",\n"
            f"          \"acceptance_criteria\": [\"Criteria 1\", \"Criteria 2\"]\n"
            f"        }}\n"
            f"      ],\n"
            f"      \"success_criteria\": [\"Success criteria 1\"]\n"
            f"    }}\n"
            f"  ]\n"
            f"}}"
        )

        system_prompt = self.build_system_prompt(self.SYSTEM_PROMPT)
        try:
            params = self.get_model_params()
            model_output = self.model_provider.complete(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=params["temperature"],
                max_tokens=params["max_tokens"],
                top_p=params["top_p"],
                agent_name=self.name,
            )
            cleaned_output = model_output.strip()
            if cleaned_output.startswith("```"):
                lines = cleaned_output.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned_output = "\n".join(lines).strip()
            plan = json.loads(cleaned_output)
            if "phases" in plan and isinstance(plan["phases"], list):
                plan["phases"] = plan["phases"][:4]
                for phase in plan["phases"]:
                    if "tasks" in phase and isinstance(phase["tasks"], list):
                        phase["tasks"] = phase["tasks"][:7]
            return plan
        except Exception as e:
            self.logger.error(f"Failed to parse phased plan: {e}")
            return {
                "project_name": "New Project",
                "phases": [
                    {
                        "phase_id": "phase_1",
                        "phase_number": 1,
                        "name": "Phase 1: Foundation",
                        "goal": "Establish core functionality",
                        "tasks": [
                            {
                                "title": "Setup basic structure",
                                "type": "feature",
                                "priority": "HIGH",
                                "complexity": "S",
                                "acceptance_criteria": ["Initial files exist"],
                            }
                        ],
                        "success_criteria": ["Basic structure compiles"],
                    }
                ],
            }
