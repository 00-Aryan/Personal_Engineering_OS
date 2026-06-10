"""Command registry module for ProjectOS."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.clone_agent import CloneAgent, _write_atomically, _append_atomically
from core.events import AgentEvent, EventType
from core.notifications.telegram_notifier import TelegramNotifier, _escape_md

LOGGER_NAME = "projectos.command_registry"
logger = logging.getLogger(LOGGER_NAME)


class CommandRegistry:
    """Routes Telegram commands to ProjectOS actions."""

    def __init__(
        self,
        clone_agent: CloneAgent,
        phase_manager: Any,
        notifier: TelegramNotifier,
        state_dir: Path,
        brief_generator: Optional[Any] = None,
    ) -> None:
        """Initialize CommandRegistry."""
        self.clone_agent = clone_agent
        self.phase_manager = phase_manager
        self.notifier = notifier
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.brief_generator = brief_generator

    def handle_approve(self, args: List[str]) -> None:
        """Approve a phase or escalation."""
        approval_id = args[0] if args else None
        if not approval_id:
            self.notifier.send("❌ Usage: /approve [id]")
            return

        if self.phase_manager is not None:
            try:
                if self.phase_manager.approve_phase(approval_id):
                    self.notifier.send(f"✅ Approved: {approval_id}")
                    return
            except Exception as e:
                self.notifier.send(f"❌ Error approving phase: {e}")

        escalation_path = self.clone_agent._escalation_queue_path
        pending_phases_path = self.state_dir / "pending_phases.md"
        pending_phases_root_path = self.clone_agent.project_root / "pending_phases.md"

        updated = self._update_markdown_status(escalation_path, approval_id, "APPROVED")
        is_phase = False
        if not updated:
            updated = self._update_markdown_status(pending_phases_path, approval_id, "APPROVED")
            if updated:
                is_phase = True
            else:
                updated = self._update_markdown_status(pending_phases_root_path, approval_id, "APPROVED")
                if updated:
                    is_phase = True

        if not updated:
            self.notifier.send(f"❌ ID {approval_id} not found in pending queue.")
            return

        decision_line = f"Telegram approval: {approval_id}\n"
        _append_atomically(self.clone_agent._decisions_log_path, decision_line)

        self.notifier.send(f"✅ Approved: {approval_id}")

        if is_phase:
            if self.phase_manager is not None:
                try:
                    self.phase_manager.resume_phase(approval_id)
                except Exception as e:
                    self.notifier.send(f"❌ Error resuming phase: {e}")
        else:
            grant_event = AgentEvent(
                event_type=EventType.PERMISSION_GRANTED,
                source_agent="telegram_commander",
                payload={},
                correlation_id=approval_id,
            )
            self.clone_agent.handle(grant_event)

    def handle_reject(self, args: List[str]) -> None:
        """Reject with reason."""
        approval_id = args[0] if args else None
        if not approval_id:
            self.notifier.send("❌ Usage: /reject [id] [reason]")
            return

        reason = " ".join(args[1:]) if len(args) > 1 else "No reason given"

        if self.phase_manager is not None:
            try:
                if self.phase_manager.reject_phase(approval_id, reason):
                    return
            except Exception as e:
                self.notifier.send(f"❌ Error rejecting phase: {e}")

        escalation_path = self.clone_agent._escalation_queue_path
        pending_phases_path = self.state_dir / "pending_phases.md"
        pending_phases_root_path = self.clone_agent.project_root / "pending_phases.md"

        updated = self._update_markdown_status(
            escalation_path, approval_id, "REJECTED", rejection_reason=reason
        )
        if not updated:
            updated = self._update_markdown_status(
                pending_phases_path, approval_id, "REJECTED", rejection_reason=reason
            )
            if not updated:
                updated = self._update_markdown_status(
                    pending_phases_root_path, approval_id, "REJECTED", rejection_reason=reason
                )

        if not updated:
            self.notifier.send(f"❌ ID {approval_id} not found in pending queue.")
            return

        decision_line = f"Telegram rejection: {approval_id} - Reason: {reason}\n"
        _append_atomically(self.clone_agent._decisions_log_path, decision_line)

        self.notifier.send(f"❌ Rejected: {approval_id}\nReason: {reason}")

    def handle_modify(self, args: List[str]) -> None:
        """Approve with modification instruction."""
        approval_id = args[0] if args else None
        instruction = " ".join(args[1:]) if len(args) > 1 else ""

        if not approval_id or not instruction:
            self.notifier.send("❌ Usage: /modify [id] [instruction]")
            return

        escalation_path = self.clone_agent._escalation_queue_path
        pending_phases_path = self.state_dir / "pending_phases.md"
        pending_phases_root_path = self.clone_agent.project_root / "pending_phases.md"

        updated = self._update_markdown_status(
            escalation_path, approval_id, "APPROVED_WITH_MODIFICATION", rejection_reason=f"Modification: {instruction}"
        )
        is_phase = False
        if not updated:
            updated = self._update_markdown_status(
                pending_phases_path, approval_id, "APPROVED_WITH_MODIFICATION", rejection_reason=f"Modification: {instruction}"
            )
            if updated:
                is_phase = True
            else:
                updated = self._update_markdown_status(
                    pending_phases_root_path, approval_id, "APPROVED_WITH_MODIFICATION", rejection_reason=f"Modification: {instruction}"
                )
                if updated:
                    is_phase = True

        if not updated:
            self.notifier.send(f"❌ ID {approval_id} not found in pending queue.")
            return

        decision_line = f"Telegram modification: {approval_id} - Instruction: {instruction}\n"
        _append_atomically(self.clone_agent._decisions_log_path, decision_line)

        self.notifier.send(f"🔄 Modification noted: {instruction}")

        if is_phase:
            if self.phase_manager is not None:
                try:
                    self.phase_manager.resume_phase(approval_id, instruction=instruction)
                except TypeError:
                    try:
                        self.phase_manager.resume_phase(approval_id)
                    except Exception as e:
                        self.notifier.send(f"❌ Error resuming phase: {e}")
                except Exception as e:
                    self.notifier.send(f"❌ Error resuming phase: {e}")
        else:
            grant_event = AgentEvent(
                event_type=EventType.PERMISSION_GRANTED,
                source_agent="telegram_commander",
                payload={"instruction": instruction},
                correlation_id=approval_id,
            )
            self.clone_agent.handle(grant_event)

    def handle_status(self, args: List[str]) -> None:
        """Send current system status."""
        last_status_path = self.state_dir / "last_status.json"
        last_status = {}
        if last_status_path.exists():
            try:
                import json
                last_status = json.loads(last_status_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        provider_status_path = self.state_dir / "provider_status.json"
        provider_status = {}
        if provider_status_path.exists():
            try:
                import json
                provider_status = json.loads(provider_status_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        num_agents = len(set(self.clone_agent.agent_registry.list_all().values())) if self.clone_agent.agent_registry else 0

        available_providers = provider_status.get("available_providers", [])
        if not available_providers:
            available_providers = [
                name for name, healthy in last_status.get("provider_health", {}).items() if healthy
            ]
        available_list = ", ".join(available_providers) if available_providers else "None"

        pending_count = self._count_pending_escalations()
        blocked_count = self._count_blocked_tasks()
        last_activity = last_status.get("timestamp", "N/A")

        escaped_providers = _escape_md(available_list)
        escaped_last_activity = _escape_md(last_activity)

        status_msg = (
            "📊 *ProjectOS Status*\n"
            f"🤖 Agents: {num_agents} registered\n"
            f"✅ Providers: {escaped_providers}\n"
            f"📋 Pending approvals: {pending_count}\n"
            f"🔒 Blocked tasks: {blocked_count}\n"
            f"🕐 Last activity: {escaped_last_activity}"
        )
        self.notifier._send_formatted(status_msg)

    def handle_brief(self, args: List[str]) -> None:
        """Trigger morning brief generator."""
        if self.brief_generator is not None:
            try:
                self.brief_generator.generate_morning_brief()
            except Exception as e:
                self.notifier.send(f"❌ Error generating brief: {e}")
        else:
            self.notifier.send("❌ Brief generator not configured.")

    def handle_digest(self, args: List[str]) -> None:
        """Trigger evening digest generator."""
        if self.brief_generator is not None:
            try:
                self.brief_generator.generate_evening_digest()
            except Exception as e:
                self.notifier.send(f"❌ Error generating digest: {e}")
        else:
            self.notifier.send("❌ Digest generator not configured.")

    def handle_pause(self, args: List[str]) -> None:
        """Pause all agent work."""
        paused_file = self.state_dir / "paused"
        paused_file.touch()
        self.notifier.send("⏸ ProjectOS paused. All agent work suspended.")

        decision_line = "ProjectOS paused\n"
        _append_atomically(self.clone_agent._decisions_log_path, decision_line)

    def handle_resume(self, args: List[str]) -> None:
        """Resume agent work."""
        paused_file = self.state_dir / "paused"
        if paused_file.exists():
            paused_file.unlink()
        self.notifier.send("▶️ ProjectOS resumed.")

        decision_line = "ProjectOS resumed\n"
        _append_atomically(self.clone_agent._decisions_log_path, decision_line)

    def handle_answer(self, args: List[str]) -> None:
        """Answer project intake questions."""
        intake_id = args[0] if args else None
        answers = " ".join(args[1:]) if len(args) > 1 else ""
        if not intake_id:
            self.notifier.send("❌ Usage: /answer [id] [answers]")
            return

        answers_dir = self.state_dir / "intake_answers"
        answers_dir.mkdir(parents=True, exist_ok=True)
        answers_file = answers_dir / f"{intake_id}.txt"

        _write_atomically(answers_file, answers)
        self.notifier.send(f"📝 Answers recorded for intake {intake_id}")

    def handle_help(self, args: List[str]) -> None:
        """List available commands."""
        help_msg = (
            "📖 *ProjectOS Commands*\n"
            "`/approve [id]` \\- approve phase or decision\n"
            "`/reject [id] [reason]` \\- reject with reason\n"
            "`/modify [id] [instruction]` \\- approve with changes\n"
            "`/status` \\- system status\n"
            "`/brief` \\- morning brief now\n"
            "`/digest` \\- evening digest now\n"
            "`/pause` \\- pause all work\n"
            "`/resume` \\- resume work\n"
            "`/help` \\- this message"
        )
        self.notifier._send_formatted(help_msg)

    def _update_markdown_status(self, file_path: Path, item_id: str, new_status: str, rejection_reason: Optional[str] = None) -> bool:
        """Update the status of a pending item in a markdown table file."""
        if not file_path.exists():
            return False
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return False

        lines = content.splitlines()
        updated = False
        for i, line in enumerate(lines):
            if not line.strip().startswith("|"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 5:
                if parts[2] == item_id and parts[4] == "PENDING":
                    parts[4] = new_status
                    if rejection_reason and len(parts) >= 4:
                        parts[3] = f"{parts[3]} ({rejection_reason})"
                    lines[i] = "| " + " | ".join(parts[1:-1]) + " |"
                    updated = True
        if updated:
            _write_atomically(file_path, "\n".join(lines) + "\n")
        return updated

    def _count_pending_escalations(self) -> int:
        """Count pending escalations in escalation_queue.md."""
        escalation_path = self.clone_agent._escalation_queue_path
        if not escalation_path.exists():
            return 0
        try:
            content = escalation_path.read_text(encoding="utf-8")
        except Exception:
            return 0
        count = 0
        for line in content.splitlines():
            if not line.strip().startswith("|"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 5:
                if parts[4] == "PENDING" and parts[2] != "event_id":
                    count += 1
        return count

    def _count_blocked_tasks(self) -> int:
        """Count blocked tasks in blocked_tasks.md."""
        blocked_path = self.clone_agent._blocked_tasks_path
        if not blocked_path.exists():
            return 0
        try:
            content = blocked_path.read_text(encoding="utf-8")
        except Exception:
            return 0
        count = 0
        for line in content.splitlines():
            if not line.strip().startswith("|"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 5:
                if parts[1] != "task_id" and not parts[1].startswith("---"):
                    count += 1
        return count
