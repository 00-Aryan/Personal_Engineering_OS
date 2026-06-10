"""Telegram notifier module for ProjectOS."""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

# Constants for "Zero hardcoded strings" rule
TEMPLATE_PHASE_COMPLETE = (
    "✅ *Phase {phase_number} Complete — {project_name}*\n\n"
    "📁 Files changed: {files_changed}\n"
    "🧪 Tests passing: {tests_passing}\n\n"
    "*Next: {next_phase_summary}*\n\n"
    "Reply:\n"
    "`/approve {approval_id}` — proceed to next phase\n"
    "`/reject {approval_id} [reason]` — stop and replan\n"
    "`/modify {approval_id} [instruction]` — adjust and proceed"
)

TEMPLATE_ESCALATION = (
    "⚠️ *Decision Required*\n\n"
    "*{title}*\n"
    "{reason}\n\n"
    "{details}\n\n"
    "Reply:\n"
    "`/approve {event_id}` — proceed\n"
    "`/reject {event_id} [reason]` — cancel this action"
)

TEMPLATE_MORNING_BRIEF_HEADER = "🌅 *ProjectOS Morning Brief*"
TEMPLATE_MORNING_BRIEF_PROJECT = (
    "📦 *{project_name}*\n"
    "• Completed overnight: {task_count} tasks\n"
    "• Changed: {file_count} files\n"
    "• Status: {phase_status}"
)
TEMPLATE_MORNING_BRIEF_FOOTER = (
    "📋 Pending your approval: {pending_approvals}\n"
    "🔒 Blocked tasks: {blocked_tasks}\n\n"
    "Use `/status` for full details\\."
)

TEMPLATE_EVENING_DIGEST_HEADER = "🌙 *Evening Digest*\n\n✅ Completed today: {completed_tasks} tasks"
TEMPLATE_EVENING_DIGEST_FILES = "📝 Files changed:"
TEMPLATE_EVENING_DIGEST_DECISIONS = "🏗 Architectural decisions:"
TEMPLATE_EVENING_DIGEST_ATTENTION = "⚠️ Needs your attention:"
VAL_NONE_TODAY = "None today"
VAL_ALL_CLEAR = "Nothing — all clear"

TEMPLATE_ALERT = "{emoji} *{severity} Alert — {component}*\n{message}"

TEMPLATE_PROJECT_STARTED = (
    "🚀 *New Project Detected: {project_name}*\n\n"
    "Before I plan, I need to know:\n"
    "{questions}\n\n"
    "Reply: `/answer {intake_id} [your answers one per line]`"
)

ENV_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_CHAT_ID = "TELEGRAM_CHAT_ID"
API_URL_FORMAT = "https://api.telegram.org/bot{token}/sendMessage"
PARSE_MODE_MARKDOWN_V2 = "MarkdownV2"
TRUNCATE_SUFFIX = "... [truncated]"
MAX_MESSAGE_LENGTH = 4096

EMOJI_CRITICAL = "🔴"
EMOJI_WARNING = "🟡"
EMOJI_INFO = "🟢"

SEV_CRITICAL = "CRITICAL"
SEV_WARNING = "WARNING"
SEV_INFO = "INFO"

DECISIONS_LOG_NAME = "decisions.log"
DECISION_ERROR_PREFIX = "[telegram_notifier] Error sending message: "
REDACTED_BOT_TOKEN = "<redacted-bot-token>"
TELEGRAM_BOT_URL_PATTERN = r"bot[^/\s]+/sendMessage"
TELEGRAM_BOT_URL_REPLACEMENT = f"bot{REDACTED_BOT_TOKEN}/sendMessage"


def _escape_md(text: Any) -> str:
    """Escape special characters for Telegram MarkdownV2 formatting."""
    if text is None:
        return ""
    text_str = str(text)
    # Characters that must be escaped outside code blocks in MarkdownV2
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return "".join(f"\\{c}" if c in escape_chars else c for c in text_str)


def _redact_sensitive_text(text: str) -> str:
    """Redact Telegram bot tokens from loggable error text."""
    return re.sub(TELEGRAM_BOT_URL_PATTERN, TELEGRAM_BOT_URL_REPLACEMENT, text)


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file while preserving existing content atomically."""
    try:
        path = Path(path).resolve()
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        
        existing = ""
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                existing = f.read()
                
        temp_path = parent / f"{path.name}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(existing + content)
            
        temp_path.replace(path)
    except Exception:
        # Fallback to standard append if atomic write fails
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass


class TelegramNotifier:
    """Sends structured messages to Aryan's Telegram bot.

    All methods are async-safe: they use threading to fire-and-forget.
    No method blocks the calling agent.
    No method raises — all errors logged silently to decisions.log.
    """

    def __init__(self, bot_token: str, chat_id: str, project_root: Optional[Path | str] = None) -> None:
        """Initialize the Telegram notifier with bot credentials and project root."""
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.logger = logging.getLogger("projectos.telegram_notifier")

    @classmethod
    def from_env(cls, project_root: Optional[Path | str] = None) -> TelegramNotifier:
        """Load bot credentials from environment or return DisabledNotifier if missing."""
        bot_token = os.environ.get(ENV_BOT_TOKEN)
        chat_id = os.environ.get(ENV_CHAT_ID)
        if not bot_token or not chat_id:
            return DisabledNotifier()
        return cls(bot_token, chat_id, project_root=project_root)

    def send(self, message: str) -> None:
        """Send a plain-text message in a background thread."""
        self._send_formatted(_escape_md(message))

    def _send_formatted(self, message: str) -> None:
        """Send a pre-formatted MarkdownV2 message in a background thread."""
        if not self.bot_token or not self.chat_id:
            return

        # Truncate message to fit within Telegram's 4096-character limit
        if len(message) > MAX_MESSAGE_LENGTH:
            message = message[:MAX_MESSAGE_LENGTH - len(TRUNCATE_SUFFIX)] + TRUNCATE_SUFFIX

        # Fire and forget via background thread
        thread = threading.Thread(
            target=self._send_http,
            args=(message,),
            name="TelegramNotifierThread",
            daemon=True
        )
        thread.start()

    def _send_http(self, message: str) -> None:
        """Execute HTTP POST request to Telegram Bot API."""
        try:
            url = API_URL_FORMAT.format(token=self.bot_token)
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": PARSE_MODE_MARKDOWN_V2
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as e:
            try:
                err_msg = str(e)
                if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                    err_msg += f" - Response: {e.response.text}"
                err_msg = _redact_sensitive_text(err_msg)
                log_path = self.project_root / DECISIONS_LOG_NAME
                _append_atomically(log_path, f"{DECISION_ERROR_PREFIX}{err_msg}\n")
            except Exception:
                pass

    def send_phase_complete(
        self,
        project_name: str,
        phase_number: int,
        phase_name: str,
        files_changed: int,
        tests_passing: int,
        next_phase_summary: str,
        approval_id: str
    ) -> None:
        """Send phase completion notification with approval/rejection/modification commands."""
        # Variables inside backticks (code style) do not need escaping.
        # Other variables do.
        escaped_project_name = _escape_md(project_name)
        escaped_next_phase = _escape_md(next_phase_summary)

        message = TEMPLATE_PHASE_COMPLETE.format(
            phase_number=phase_number,
            project_name=escaped_project_name,
            files_changed=files_changed,
            tests_passing=tests_passing,
            next_phase_summary=escaped_next_phase,
            approval_id=approval_id
        )
        self._send_formatted(message)

    def send_escalation(
        self,
        title: str,
        reason: str,
        event_id: str,
        details: str
    ) -> None:
        """Send decision requirement escalation message."""
        escaped_title = _escape_md(title)
        escaped_reason = _escape_md(reason)
        escaped_details = _escape_md(details)

        message = TEMPLATE_ESCALATION.format(
            title=escaped_title,
            reason=escaped_reason,
            details=escaped_details,
            event_id=event_id
        )
        self._send_formatted(message)

    def send_morning_brief(
        self,
        project_summaries: List[Dict[str, Any]],
        pending_approvals: int,
        blocked_tasks: int,
        token_alert: Optional[str] = None
    ) -> None:
        """Send morning status brief of active projects and pending approvals."""
        lines = [TEMPLATE_MORNING_BRIEF_HEADER]
        if token_alert:
            lines.append(f"\n{_escape_md(token_alert)}")
        lines.append("")

        lines.append("For each project:")
        for summary in project_summaries:
            p_name = summary.get("project_name") or summary.get("name") or "Unknown"
            t_count = summary.get("task_count", 0)
            f_count = summary.get("file_count") or summary.get("files_changed") or 0
            p_status = summary.get("phase_status") or summary.get("status") or "Unknown"

            proj_text = TEMPLATE_MORNING_BRIEF_PROJECT.format(
                project_name=_escape_md(p_name),
                task_count=t_count,
                file_count=f_count,
                phase_status=_escape_md(p_status)
            )
            lines.append(proj_text)

        lines.append("")
        lines.append(
            TEMPLATE_MORNING_BRIEF_FOOTER.format(
                pending_approvals=pending_approvals,
                blocked_tasks=blocked_tasks
            )
        )

        self._send_formatted("\n".join(lines))

    def send_evening_digest(
        self,
        completed_tasks: int,
        changed_files: List[str],
        architectural_decisions: List[str],
        needs_attention: List[str]
    ) -> None:
        """Send evening summary digest of daily progress."""
        lines = [
            TEMPLATE_EVENING_DIGEST_HEADER.format(completed_tasks=completed_tasks),
            "",
            TEMPLATE_EVENING_DIGEST_FILES
        ]
        if changed_files:
            lines.extend(f"• {_escape_md(f)}" for f in changed_files)
        else:
            lines.append(_escape_md("None"))

        lines.append("")
        lines.append(TEMPLATE_EVENING_DIGEST_DECISIONS)
        if architectural_decisions:
            lines.extend(f"• {_escape_md(d)}" for d in architectural_decisions)
        else:
            lines.append(_escape_md(VAL_NONE_TODAY))

        lines.append("")
        lines.append(TEMPLATE_EVENING_DIGEST_ATTENTION)
        if needs_attention:
            lines.extend(f"• {_escape_md(a)}" for a in needs_attention)
        else:
            lines.append(_escape_md(VAL_ALL_CLEAR))

        self._send_formatted("\n".join(lines))

    def send_alert(
        self,
        severity: str,
        message: str,
        component: str
    ) -> None:
        """Send real-time alert with severity indicator emoji."""
        sev_lower = severity.lower()
        if "critical" in sev_lower:
            emoji = EMOJI_CRITICAL
            sev_label = SEV_CRITICAL
        elif "warning" in sev_lower:
            emoji = EMOJI_WARNING
            sev_label = SEV_WARNING
        else:
            emoji = EMOJI_INFO
            sev_label = SEV_INFO

        formatted = TEMPLATE_ALERT.format(
            emoji=emoji,
            severity=sev_label,
            component=_escape_md(component),
            message=_escape_md(message)
        )
        self._send_formatted(formatted)

    def send_project_started(
        self,
        project_name: str,
        questions: List[str],
        intake_id: str
    ) -> None:
        """Send intake request when a new project is detected."""
        q_list = "\n".join(f"{i}\\. {_escape_md(q)}" for i, q in enumerate(questions, 1))
        formatted = TEMPLATE_PROJECT_STARTED.format(
            project_name=_escape_md(project_name),
            questions=q_list,
            intake_id=intake_id
        )
        self._send_formatted(formatted)


class DisabledNotifier(TelegramNotifier):
    """A no-op subclass of TelegramNotifier used when Telegram credentials are unconfigured."""

    def __init__(self) -> None:
        """Initialize DisabledNotifier with empty credentials."""
        super().__init__("", "", project_root=None)

    def send(self, message: str) -> None:
        """No-op: do nothing."""
        pass

    def send_phase_complete(
        self,
        project_name: str,
        phase_number: int,
        phase_name: str,
        files_changed: int,
        tests_passing: int,
        next_phase_summary: str,
        approval_id: str
    ) -> None:
        """No-op: do nothing."""
        pass

    def send_escalation(
        self,
        title: str,
        reason: str,
        event_id: str,
        details: str
    ) -> None:
        """No-op: do nothing."""
        pass

    def send_morning_brief(
        self,
        project_summaries: List[Dict[str, Any]],
        pending_approvals: int,
        blocked_tasks: int,
        token_alert: Optional[str] = None
    ) -> None:
        """No-op: do nothing."""
        pass

    def send_evening_digest(
        self,
        completed_tasks: int,
        changed_files: List[str],
        architectural_decisions: List[str],
        needs_attention: List[str]
    ) -> None:
        """No-op: do nothing."""
        pass

    def send_alert(
        self,
        severity: str,
        message: str,
        component: str
    ) -> None:
        """No-op: do nothing."""
        pass

    def send_project_started(
        self,
        project_name: str,
        questions: List[str],
        intake_id: str
    ) -> None:
        """No-op: do nothing."""
        pass
