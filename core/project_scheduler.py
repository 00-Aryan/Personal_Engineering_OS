"""Project Scheduler for ProjectOS."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from core.phase_manager import PhaseManager, PhaseStatus
from core.notifications.telegram_notifier import TelegramNotifier


def _write_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    import os
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


class ProjectScheduler:
    """Rotates ProjectOS attention across multiple projects."""

    def __init__(
        self,
        phase_manager: PhaseManager,
        notifier: TelegramNotifier,
        state_dir: Path | str,
    ) -> None:
        self.phase_manager = phase_manager
        self.notifier = notifier
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / "scheduler_state.yaml"
        self._logger = logging.getLogger("projectos.project_scheduler")
        self.projects: Dict[str, Dict[str, Any]] = {}
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and "projects" in data:
                self.projects = data["projects"]
        except Exception as e:
            self._logger.error(f"Failed to load scheduler state: {e}")

    def _save_state(self) -> None:
        try:
            content = yaml.safe_dump({"projects": self.projects})
            _write_atomically(self.state_file, content)
        except Exception as e:
            self._logger.error(f"Failed to save scheduler state: {e}")

    def register_project(
        self,
        project_name: str,
        project_root: Path | str,
        priority: int = 1,
    ) -> None:
        """Add project to rotation."""
        root_path = Path(project_root).resolve()
        last_worked = self.projects.get(project_name, {}).get("last_worked_at")
        self.projects[project_name] = {
            "root_path": str(root_path),
            "priority": priority,
            "last_worked_at": last_worked,
        }
        self._save_state()

    def record_work_done(self, project_name: str) -> None:
        """Update last_worked_at for project."""
        if project_name in self.projects:
            self.projects[project_name]["last_worked_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state()

    def _is_blocked(self, project_root: Path) -> bool:
        """Check if project has blocked tasks."""
        blocked_path = project_root / "blocked_tasks.md"
        if not blocked_path.exists():
            return False
        try:
            content = blocked_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                if not line.strip().startswith("|"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5:
                    if parts[1] != "task_id" and not parts[1].startswith("---"):
                        return True
        except Exception:
            pass
        return False

    def get_next_project(self) -> Optional[str]:
        """Returns the project name that should receive attention next."""
        if not self.projects:
            return None

        active_candidates = []
        pending_candidates = []
        now = datetime.now(timezone.utc)

        for name, info in self.projects.items():
            root_path = Path(info["root_path"])
            if self._is_blocked(root_path):
                continue

            phases = self.phase_manager._load_state(name)
            if not phases:
                continue

            active_phase = None
            for p in phases:
                if p.status != PhaseStatus.COMPLETE:
                    active_phase = p
                    break

            if active_phase is None:
                continue

            last_worked_str = info.get("last_worked_at")
            if last_worked_str:
                last_worked = datetime.fromisoformat(last_worked_str)
            else:
                last_worked = datetime.fromtimestamp(0, tz=timezone.utc)

            priority = info.get("priority", 1)
            time_since_work = (now - last_worked).total_seconds()
            if time_since_work < 0:
                time_since_work = 0.0

            score = time_since_work * priority

            if active_phase.status in (PhaseStatus.IN_PROGRESS, PhaseStatus.APPROVED):
                active_candidates.append((name, score, priority))
            elif active_phase.status == PhaseStatus.PENDING:
                pending_candidates.append((name, score, priority))

        candidates = active_candidates if active_candidates else pending_candidates
        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return candidates[0][0]
