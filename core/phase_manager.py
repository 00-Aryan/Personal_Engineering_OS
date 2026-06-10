"""Phase Manager module for ProjectOS."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.events import AgentEvent, EventType
from core.notifications.telegram_notifier import TelegramNotifier
from core.task_queue import TaskQueue


class PhaseStatus(Enum):
    """Lifecycle status of a project phase."""

    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    REJECTED = "rejected"


@dataclass
class Task:
    """Task structure within a project phase."""

    id: str
    title: str
    type: str
    priority: str
    complexity: str
    dependencies: List[str]
    acceptance_criteria: List[str]
    agent_assignment: str
    status: str


@dataclass
class Phase:
    """Project phase containing metadata, lifecycle status, and tasks."""

    phase_id: str
    project_name: str
    phase_number: int
    phase_name: str
    goal: str
    tasks: List[Task]
    status: PhaseStatus
    approval_id: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    rejection_reason: Optional[str]


def _write_atomically(path: Path, content: str) -> None:
    """Write content to a path by replacing it with a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    import os
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file while preserving existing content."""
    existing_content = path.read_text(encoding="utf-8") if path.exists() else ""
    _write_atomically(path, f"{existing_content}{content}")


def phase_to_dict(phase: Phase) -> dict:
    """Serialize a Phase object to a dictionary."""
    return {
        "phase_id": phase.phase_id,
        "project_name": phase.project_name,
        "phase_number": phase.phase_number,
        "phase_name": phase.phase_name,
        "goal": phase.goal,
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "type": t.type,
                "priority": t.priority,
                "complexity": t.complexity,
                "dependencies": t.dependencies,
                "acceptance_criteria": t.acceptance_criteria,
                "agent_assignment": t.agent_assignment,
                "status": t.status,
            }
            for t in phase.tasks
        ],
        "status": phase.status.value,
        "approval_id": phase.approval_id,
        "created_at": phase.created_at.isoformat(),
        "started_at": phase.started_at.isoformat() if phase.started_at else None,
        "completed_at": phase.completed_at.isoformat() if phase.completed_at else None,
        "rejection_reason": phase.rejection_reason,
    }


def dict_to_phase(d: dict) -> Phase:
    """Deserialize a dictionary to a Phase object."""
    return Phase(
        phase_id=d["phase_id"],
        project_name=d["project_name"],
        phase_number=d["phase_number"],
        phase_name=d["phase_name"],
        goal=d["goal"],
        tasks=[
            Task(
                id=t["id"],
                title=t["title"],
                type=t["type"],
                priority=t["priority"],
                complexity=t["complexity"],
                dependencies=t["dependencies"],
                acceptance_criteria=t["acceptance_criteria"],
                agent_assignment=t["agent_assignment"],
                status=t["status"],
            )
            for t in d["tasks"]
        ],
        status=PhaseStatus(d["status"]),
        approval_id=d["approval_id"],
        created_at=datetime.fromisoformat(d["created_at"]),
        started_at=datetime.fromisoformat(d["started_at"]) if d["started_at"] else None,
        completed_at=datetime.fromisoformat(d["completed_at"]) if d["completed_at"] else None,
        rejection_reason=d["rejection_reason"],
    )


class PhaseManager:
    """Manages the lifecycle of project phases.

    State stored in .projectos/{project_name}/phase_state.yaml
    Updated atomically on every state transition.
    """

    def __init__(
        self,
        notifier: TelegramNotifier,
        state_dir: Path | str,
        task_queue: TaskQueue,
        clone_agent: Optional[Any] = None,
        agent_registry: Optional[Any] = None,
    ) -> None:
        """Initialize PhaseManager."""
        self.notifier = notifier
        self.state_dir = Path(state_dir)
        self.task_queue = task_queue
        self.clone_agent = clone_agent
        self.agent_registry = agent_registry
        self._logger = logging.getLogger("projectos.phase_manager")

    def _load_state(self, project_name: str) -> List[Phase]:
        """Load phases state for a project."""
        state_file = self.state_dir / project_name / "phase_state.yaml"
        if not state_file.exists():
            return []
        try:
            import yaml
            with open(state_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, list):
                return []
            return [dict_to_phase(d) for d in data]
        except Exception as e:
            self._logger.error(f"Failed to load phase state for {project_name}: {e}")
            return []

    def _save_state(self, project_name: str, phases: List[Phase]) -> None:
        """Save phases state atomically for a project."""
        state_file = self.state_dir / project_name / "phase_state.yaml"
        try:
            import yaml
            data = [phase_to_dict(p) for p in phases]
            content = yaml.safe_dump(data)
            _write_atomically(state_file, content)
        except Exception as e:
            self._logger.error(f"Failed to save phase state for {project_name}: {e}")

    def create_phases_from_plan(self, project_name: str, plan: dict, approval_id: Optional[str] = None) -> List[Phase]:
        """Convert plan dict to Phase objects and save them."""
        phases = []
        now = datetime.now(timezone.utc)
        plan_approval_id = approval_id or plan.get("approval_id") or str(uuid.uuid4())[:8]

        # Phase 0: Project Plan Approval Phase
        phase_0 = Phase(
            phase_id="phase_0",
            project_name=project_name,
            phase_number=0,
            phase_name="Project Plan",
            goal="Project onboarding and initial plan approval",
            tasks=[],
            status=PhaseStatus.AWAITING_APPROVAL,
            approval_id=plan_approval_id,
            created_at=now,
            started_at=now,
            completed_at=None,
            rejection_reason=None,
        )
        phases.append(phase_0)

        plan_phases = plan.get("phases", [])
        for idx, p in enumerate(plan_phases, 1):
            tasks_list = []
            for t_idx, t in enumerate(p.get("tasks", []), 1):
                tasks_list.append(
                    Task(
                        id=t.get("id") or f"PLAN-{now.strftime('%Y%m%d')}-{str(idx).zfill(2)}{str(t_idx).zfill(2)}",
                        title=t.get("title") or t.get("task_description") or "",
                        type=t.get("type") or "feature",
                        priority=t.get("priority") or "MEDIUM",
                        complexity=t.get("complexity") or "S",
                        dependencies=t.get("dependencies") or [],
                        acceptance_criteria=t.get("acceptance_criteria") or [],
                        agent_assignment=t.get("agent_assignment") or "code_writing_agent",
                        status=t.get("status") or "PENDING",
                    )
                )

            phases.append(
                Phase(
                    phase_id=p.get("phase_id") or f"phase_{idx}",
                    project_name=project_name,
                    phase_number=idx,
                    phase_name=p.get("name") or p.get("phase_name") or f"Phase {idx}",
                    goal=p.get("goal") or "",
                    tasks=tasks_list,
                    status=PhaseStatus.PENDING,
                    approval_id=str(uuid.uuid4())[:8] if idx > 1 else None,
                    created_at=now,
                    started_at=None,
                    completed_at=None,
                    rejection_reason=None,
                )
            )

        self._save_state(project_name, phases)
        return phases

    def get_current_phase(self, project_name: str) -> Optional[Phase]:
        """Returns the first phase with status IN_PROGRESS or APPROVED."""
        phases = self._load_state(project_name)
        for phase in phases:
            if phase.status in (PhaseStatus.IN_PROGRESS, PhaseStatus.APPROVED):
                return phase
        return None

    def complete_phase(self, project_name: str, phase_id: str) -> None:
        """Mark phase as COMPLETE. Find next phase and set to AWAITING_APPROVAL."""
        phases = self._load_state(project_name)
        current_phase = next((p for p in phases if p.phase_id == phase_id), None)
        if not current_phase:
            return

        current_phase.status = PhaseStatus.COMPLETE
        current_phase.completed_at = datetime.now(timezone.utc)

        next_phase = next((p for p in phases if p.phase_number == current_phase.phase_number + 1), None)
        if next_phase:
            next_phase.status = PhaseStatus.AWAITING_APPROVAL
            next_phase.approval_id = str(uuid.uuid4())[:8]

            self.notifier.send_phase_complete(
                project_name=project_name,
                phase_number=current_phase.phase_number,
                phase_name=current_phase.phase_name,
                files_changed=0,
                tests_passing=0,
                next_phase_summary=f"Start {next_phase.phase_name}: {next_phase.goal}",
                approval_id=next_phase.approval_id,
            )
        else:
            self.notifier.send(f"🎉 All phases completed for project {project_name}!")

        self._save_state(project_name, phases)

    def approve_phase(self, approval_id: str) -> bool:
        """Find phase with approval_id, set status to APPROVED, and submit tasks."""
        if not self.state_dir.exists():
            return False

        for project_dir in self.state_dir.iterdir():
            if not project_dir.is_dir():
                continue
            state_file = project_dir / "phase_state.yaml"
            if not state_file.exists():
                continue

            project_name = project_dir.name
            phases = self._load_state(project_name)
            for phase in phases:
                if phase.approval_id == approval_id:
                    if phase.status in (PhaseStatus.APPROVED, PhaseStatus.COMPLETE):
                        return True

                    phase.status = PhaseStatus.APPROVED
                    phase.started_at = datetime.now(timezone.utc)

                    if phase.phase_number == 0:
                        plan_path = self.state_dir / project_name / "plan.md"
                        approved_plan_path = self.state_dir / project_name / "approved_plan.md"
                        if plan_path.exists():
                            content = plan_path.read_text(encoding="utf-8")
                            _write_atomically(approved_plan_path, content)
                        else:
                            _write_atomically(
                                approved_plan_path,
                                f"# Approved Plan for {project_name}\n\nPlan approved at {datetime.now(timezone.utc).isoformat()}"
                            )

                        event = AgentEvent(
                            event_type=EventType.PLAN_APPROVED,
                            source_agent="phase_manager",
                            payload={
                                "project_name": project_name,
                                "approval_id": approval_id,
                            }
                        )
                        if self.clone_agent:
                            self.clone_agent.dispatch(event)

                        phase_1 = next((p for p in phases if p.phase_number == 1), None)
                        if phase_1:
                            phase_1.status = PhaseStatus.APPROVED
                            phase_1.started_at = datetime.now(timezone.utc)
                            self._submit_phase_tasks(phase_1)
                    else:
                        self._submit_phase_tasks(phase)

                    self._save_state(project_name, phases)
                    self._logger.info(f"Phase approved via Telegram: {approval_id}")

                    decision_line = f"Phase approved via Telegram: {approval_id}\n"
                    if self.clone_agent:
                        _append_atomically(self.clone_agent.project_root / "decisions.log", decision_line)
                    else:
                        _append_atomically(Path("decisions.log"), decision_line)

                    return True
        return False

    def reject_phase(self, approval_id: str, reason: str) -> bool:
        """Find phase with approval_id, set status to REJECTED, and trigger replanning."""
        if not self.state_dir.exists():
            return False

        for project_dir in self.state_dir.iterdir():
            if not project_dir.is_dir():
                continue
            state_file = project_dir / "phase_state.yaml"
            if not state_file.exists():
                continue

            project_name = project_dir.name
            phases = self._load_state(project_name)
            for phase in phases:
                if phase.approval_id == approval_id:
                    phase.status = PhaseStatus.REJECTED
                    phase.rejection_reason = reason
                    self._save_state(project_name, phases)

                    self.notifier.send(f"❌ Phase rejected. Reason: {reason}. Replanning...")

                    context_file_path = None
                    for fname in ["project_description.md", "project_context.md"]:
                        path1 = self.state_dir / project_name / fname
                        if path1.exists():
                            context_file_path = path1
                            break
                        if self.clone_agent:
                            path2 = self.clone_agent.project_root / fname
                            if path2.exists():
                                context_file_path = path2
                                break

                    if not context_file_path:
                        context_file_path = self.state_dir / project_name / "project_description.md"

                    event = AgentEvent(
                        event_type=EventType.NEW_PROJECT,
                        source_agent="phase_manager",
                        payload={
                            "context_file_path": str(context_file_path),
                            "rejection_reason": reason,
                            "rejected_phase_id": phase.phase_id,
                        }
                    )
                    if self.clone_agent:
                        self.clone_agent.dispatch(event)

                    return True
        return False

    def resume_phase(self, approval_id: str, instruction: Optional[str] = None) -> bool:
        """Resume a phase with optional instruction."""
        if instruction:
            self._logger.info(f"Resuming phase {approval_id} with instruction: {instruction}")
            decision_line = f"Phase modified via Telegram: {approval_id} - Instruction: {instruction}\n"
            if self.clone_agent:
                _append_atomically(self.clone_agent.project_root / "decisions.log", decision_line)
            else:
                _append_atomically(Path("decisions.log"), decision_line)
        return self.approve_phase(approval_id)

    def _submit_phase_tasks(self, phase: Phase) -> None:
        """Submit all tasks of a phase to the TaskQueue/CloneAgent."""
        clone_agent = self.clone_agent
        if not clone_agent and self.agent_registry:
            clone_agent = self.agent_registry.get("clone") or self.agent_registry.get("clone_agent")

        for task in phase.tasks:
            event = AgentEvent(
                event_type=EventType.BACKLOG_CHANGED,
                source_agent="phase_manager",
                payload={
                    "id": task.id,
                    "title": task.title,
                    "type": task.type,
                    "priority": task.priority,
                    "complexity": task.complexity,
                    "dependencies": task.dependencies,
                    "acceptance_criteria": task.acceptance_criteria,
                    "agent_assignment": task.agent_assignment,
                    "status": "PENDING",
                    "target_agent": task.agent_assignment,
                },
                correlation_id=phase.approval_id or task.id,
            )
            if clone_agent:
                self.task_queue.submit(event, clone_agent)
            else:
                self._logger.error("Cannot submit phase task: CloneAgent not available")

    def get_all_phases_status(self, project_name: str) -> List[Dict[str, Any]]:
        """Returns status summary for all phases."""
        phases = self._load_state(project_name)
        return [
            {
                "phase_id": p.phase_id,
                "phase_number": p.phase_number,
                "phase_name": p.phase_name,
                "status": p.status.value,
                "goal": p.goal,
            }
            for p in phases
        ]
