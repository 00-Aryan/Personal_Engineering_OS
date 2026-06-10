"""Daily UX brief and digest generator for ProjectOS."""

from __future__ import annotations

import logging
import re
import os
import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from core.notifications.telegram_notifier import TelegramNotifier
from core.observability.token_budget import TokenBudget


def _write_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
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


class BriefGenerator:
    """Generates morning brief and evening digest."""

    def __init__(
        self,
        notifier: TelegramNotifier,
        state_dir: Path | str,
        project_roots: List[Path | str],
    ) -> None:
        self.notifier = notifier
        self.state_dir = Path(state_dir)
        self.project_roots = [Path(p).resolve() for p in project_roots]
        self.last_brief_file = self.state_dir / "last_brief.txt"
        self._logger = logging.getLogger("projectos.brief_generator")
        self._timers: List[threading.Timer] = []

    def _get_since_timestamp(self) -> datetime:
        if self.last_brief_file.exists():
            try:
                content = self.last_brief_file.read_text(encoding="utf-8").strip()
                return datetime.fromisoformat(content)
            except Exception:
                pass
        return datetime.now(timezone.utc) - timedelta(days=1)

    def _parse_decisions_log(self, project_root: Path, since: datetime) -> List[Dict[str, Any]]:
        log_path = project_root / "decisions.log"
        entries = []
        if not log_path.exists():
            return entries
        
        pattern = re.compile(r"^\[([^\]]+)\]\s+\[([^\]]+)\]\s+\[([^\]]+)\]\s+\[(.*)\]")
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    match = pattern.match(line.strip())
                    if match:
                        ts_str, task_id, status, desc = match.groups()
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts > since:
                                entries.append({
                                    "timestamp": ts,
                                    "task_id": task_id,
                                    "status": status,
                                    "description": desc,
                                })
                        except Exception:
                            pass
        except Exception:
            pass
        return entries

    def _count_completed_tasks(self, project_root: Path, since: datetime) -> int:
        entries = self._parse_decisions_log(project_root, since)
        count = 0
        for entry in entries:
            if entry["status"] in ("DONE", "SUCCESS"):
                count += 1
        return count

    def _get_changed_files(self, project_root: Path, since: datetime) -> List[str]:
        changed = set()
        try:
            import subprocess
            since_str = since.isoformat()
            res = subprocess.run(
                ["git", "log", f"--since={since_str}", "--name-only", "--pretty=format:"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if line and (project_root / line).exists():
                        changed.add(line)
        except Exception:
            pass

        try:
            import subprocess
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if len(line) > 3:
                        file_path = line[3:].strip()
                        if file_path and (project_root / file_path).exists():
                            changed.add(file_path)
        except Exception:
            pass

        if not changed:
            for folder in ("core", "agents", "cli", "docs"):
                dir_path = project_root / folder
                if dir_path.exists() and dir_path.is_dir():
                    for f in dir_path.glob("**/*"):
                        if f.is_file() and not any(p in f.parts for p in (".git", ".venv", "__pycache__")):
                            try:
                                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                                if mtime > since:
                                    changed.add(str(f.relative_to(project_root)))
                            except Exception:
                                pass
        return sorted(list(changed))

    def _get_phase_status(self, project_name: str) -> str:
        state_file = self.state_dir / project_name / "phase_state.yaml"
        if not state_file.exists():
            return "no active phase"
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, list):
                return "no active phase"
            for p in data:
                status = p.get("status")
                if status != "complete":
                    return str(status)
            return "complete"
        except Exception:
            return "unknown"

    def _count_pending_approvals(self, project_root: Path, project_name: str) -> int:
        count = 0
        state_file = self.state_dir / project_name / "phase_state.yaml"
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, list):
                    for p in data:
                        if p.get("status") == "awaiting_approval":
                            count += 1
            except Exception:
                pass

        esc_path = project_root / "escalation_queue.md"
        if esc_path.exists():
            try:
                content = esc_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if not line.strip().startswith("|"):
                        continue
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 5:
                        if parts[4] == "PENDING" and parts[2] != "event_id":
                            count += 1
            except Exception:
                pass
        return count

    def _count_blocked_tasks(self, project_root: Path) -> int:
        blocked_path = project_root / "blocked_tasks.md"
        if not blocked_path.exists():
            return 0
        try:
            content = blocked_path.read_text(encoding="utf-8")
            count = 0
            for line in content.splitlines():
                if not line.strip().startswith("|"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5:
                    if parts[1] != "task_id" and not parts[1].startswith("---"):
                        count += 1
            return count
        except Exception:
            return 0

    def _check_token_alerts(self, project_root: Path) -> List[str]:
        alerts = []
        state_dir = project_root / ".projectos_state"
        if not state_dir.exists():
            return alerts
        try:
            tb = TokenBudget(state_dir)
            for agent in ("clone", "planning", "code_writing", "code_review", "architecture", "test", "docs"):
                alert = tb.check_daily_threshold_alert(agent)
                if alert:
                    alerts.append(f"[{project_root.name}] {alert}")
        except Exception:
            pass
        return alerts

    def generate_morning_brief(self) -> str:
        since = self._get_since_timestamp()
        now = datetime.now(timezone.utc)

        project_summaries = []
        total_pending_approvals = 0
        total_blocked_tasks = 0
        token_alerts = []

        if not self.project_roots:
            brief_text = (
                "🌅 *ProjectOS Morning Brief*\n\n"
                "No active projects registered.\n\n"
                "📋 Pending your approval: 0\n"
                "🔒 Blocked tasks: 0\n\n"
                "Use `/status` for full details."
            )
            self.notifier.send(brief_text)
            _write_atomically(Path("morning_brief.md"), brief_text)
            _write_atomically(self.last_brief_file, now.isoformat())
            return brief_text

        for root in self.project_roots:
            p_name = root.name
            tasks_done = self._count_completed_tasks(root, since)
            files_changed = len(self._get_changed_files(root, since))
            status = self._get_phase_status(p_name)

            project_summaries.append({
                "project_name": p_name,
                "task_count": tasks_done,
                "file_count": files_changed,
                "phase_status": status,
            })

            total_pending_approvals += self._count_pending_approvals(root, p_name)
            total_blocked_tasks += self._count_blocked_tasks(root)
            token_alerts.extend(self._check_token_alerts(root))

        token_alert_str = "\n".join(token_alerts) if token_alerts else None

        self.notifier.send_morning_brief(
            project_summaries=project_summaries,
            pending_approvals=total_pending_approvals,
            blocked_tasks=total_blocked_tasks,
            token_alert=token_alert_str,
        )

        lines = ["🌅 *ProjectOS Morning Brief*"]
        if token_alert_str:
            lines.append(f"\n{token_alert_str}")
        lines.append("")
        lines.append("For each project:")
        for summary in project_summaries:
            lines.append(
                f"📦 *{summary['project_name']}*\n"
                f"• Completed overnight: {summary['task_count']} tasks\n"
                f"• Changed: {summary['file_count']} files\n"
                f"• Status: {summary['phase_status']}"
            )
        lines.append("")
        lines.append(
            f"📋 Pending your approval: {total_pending_approvals}\n"
            f"🔒 Blocked tasks: {total_blocked_tasks}\n\n"
            "Use `/status` for full details."
        )
        brief_text = "\n".join(lines)

        for root in self.project_roots:
            _write_atomically(root / "morning_brief.md", brief_text)

        _write_atomically(self.last_brief_file, now.isoformat())
        return brief_text

    def _get_evening_digest_data(self, root: Path, since: datetime) -> Dict[str, Any]:
        p_name = root.name
        entries = self._parse_decisions_log(root, since)
        
        completed_tasks = 0
        decisions = []
        for entry in entries:
            if entry["status"] in ("DONE", "SUCCESS"):
                completed_tasks += 1
                if "architectural decision" in entry["description"].lower() or "adr" in entry["description"].lower():
                    decisions.append(entry["description"])

        adr_dir = root / "docs" / "adr"
        if adr_dir.exists() and adr_dir.is_dir():
            for f in adr_dir.glob("*.md"):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                    if mtime > since:
                        decisions.append(f"ADR created/modified: {f.name}")
                except Exception:
                    pass

        changed_files = self._get_changed_files(root, since)

        escalations = []
        esc_path = root / "escalation_queue.md"
        if esc_path.exists():
            try:
                content = esc_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if not line.strip().startswith("|"):
                        continue
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 5:
                        if parts[4] == "PENDING" and parts[2] != "event_id":
                            escalations.append(f"[{p_name}] Approval needed for event {parts[2]}: {parts[3]}")
            except Exception:
                pass

        return {
            "completed_tasks": completed_tasks,
            "changed_files": changed_files,
            "decisions": decisions,
            "escalations": escalations,
        }

    def generate_evening_digest(self) -> str:
        since = self._get_since_timestamp()
        
        total_completed = 0
        all_changed_files = []
        all_decisions = []
        all_escalations = []

        if not self.project_roots:
            digest_text = (
                "🌙 *Evening Digest*\n\n"
                "✅ Completed today: 0 tasks\n\n"
                "📝 Files changed:\nNone\n\n"
                "🏗 Architectural decisions:\nNone today\n\n"
                "⚠️ Needs your attention:\nNothing — all clear"
            )
            self.notifier.send(digest_text)
            _write_atomically(Path("evening_digest.md"), digest_text)
            return digest_text

        for root in self.project_roots:
            data = self._get_evening_digest_data(root, since)
            total_completed += data["completed_tasks"]
            all_changed_files.extend(data["changed_files"])
            all_decisions.extend(data["decisions"])
            all_escalations.extend(data["escalations"])

        self.notifier.send_evening_digest(
            completed_tasks=total_completed,
            changed_files=all_changed_files[:10],
            architectural_decisions=all_decisions,
            needs_attention=all_escalations,
        )

        lines = [
            f"🌙 *Evening Digest*\n\n✅ Completed today: {total_completed} tasks",
            "",
            "📝 Files changed:"
        ]
        if all_changed_files:
            lines.extend(f"• {f}" for f in all_changed_files[:10])
            if len(all_changed_files) > 10:
                lines.append(f"• and {len(all_changed_files) - 10} more files...")
        else:
            lines.append("None")

        lines.append("")
        lines.append("🏗 Architectural decisions:")
        if all_decisions:
            lines.extend(f"• {d}" for d in all_decisions)
        else:
            lines.append("None today")

        lines.append("")
        lines.append("⚠️ Needs your attention:")
        if all_escalations:
            lines.extend(f"• {e}" for e in all_escalations)
        else:
            lines.append("Nothing — all clear")

        digest_text = "\n".join(lines)

        for root in self.project_roots:
            _write_atomically(root / "evening_digest.md", digest_text)

        return digest_text

    def cancel_timers(self) -> None:
        """Cancel any active timers."""
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()

    def schedule_briefs(
        self,
        morning_time: str = "08:00",
        evening_time: str = "21:00",
    ) -> None:
        self.cancel_timers()

        def run_morning_job():
            try:
                self.generate_morning_brief()
            except Exception as e:
                self._logger.exception("Error running scheduled morning brief")
            schedule_next(morning_time, run_morning_job)

        def run_evening_job():
            try:
                self.generate_evening_digest()
            except Exception as e:
                self._logger.exception("Error running scheduled evening digest")
            schedule_next(evening_time, run_evening_job)

        def schedule_next(time_str: str, job_func: Any):
            parts = time_str.split(":")
            hour = int(parts[0])
            minute = int(parts[1])

            now = datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            
            delay = (target - now).total_seconds()
            timer = threading.Timer(delay, job_func)
            timer.daemon = True
            timer.start()
            self._timers.append(timer)

        schedule_next(morning_time, run_morning_job)
        schedule_next(evening_time, run_evening_job)
