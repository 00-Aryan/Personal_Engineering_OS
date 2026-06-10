# TASK_57: Telegram Bot — Notifications + Status

## Engineering Context

Aryan needs to manage ProjectOS from anywhere using his phone.
This task builds the outbound half: ProjectOS sends structured
messages to Aryan via Telegram.

The inbound half (Aryan sending commands) is TASK_58.
Keep them separate — both must work independently.

## Pre-conditions
Read core/projectos.py, core/clone_agent.py.
Read core/observability/alerting.py.
AGENTS.md.

Aryan must have completed manual Telegram setup:
  TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
  
If either is missing: all Telegram functions silently skip.
Never crash when Telegram is unconfigured.

## Deliverables

### 1. Add dependency
uv add python-telegram-bot
Add to requirements.txt: python-telegram-bot>=20.0

### 2. core/notifications/telegram_notifier.py

Create core/notifications/__init__.py (empty)

class TelegramNotifier:
  """
  Sends structured messages to Aryan's Telegram.
  
  All methods are async-safe: they use threading to fire-and-forget.
  No method blocks the calling agent.
  No method raises — all errors logged silently.
  
  If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set:
    All methods return immediately (no-op).
  """
  
  __init__(bot_token: str, chat_id: str)
  
  @classmethod
  from_env(cls) -> TelegramNotifier:
    Read TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.
    If either missing: return DisabledNotifier (no-op subclass).
  
  send(message: str) -> None:
    Fire-and-forget via threading.Thread.
    Uses requests.post to Telegram Bot API.
    Format: Markdown parse mode.
    On any error: log to decisions.log, continue.
  
  send_phase_complete(
    project_name: str,
    phase_number: int,
    phase_name: str,
    files_changed: int,
    tests_passing: int,
    next_phase_summary: str,
    approval_id: str
  ) -> None:
    Sends formatted message:
    ✅ *Phase {phase_number} Complete — {project_name}*
    
    📁 Files changed: {files_changed}
    🧪 Tests passing: {tests_passing}
    
    *Next: {next_phase_summary}*
    
    Reply:
    `/approve {approval_id}` — proceed to next phase
    `/reject {approval_id} [reason]` — stop and replan
    `/modify {approval_id} [instruction]` — adjust and proceed
  
  send_escalation(
    title: str,
    reason: str,
    event_id: str,
    details: str
  ) -> None:
    ⚠️ *Decision Required*
    
    *{title}*
    {reason}
    
    {details}
    
    Reply:
    `/approve {event_id}` — proceed
    `/reject {event_id} [reason]` — cancel this action
  
  send_morning_brief(
    project_summaries: List[Dict],
    pending_approvals: int,
    blocked_tasks: int,
    token_alert: Optional[str]
  ) -> None:
    🌅 *ProjectOS Morning Brief*
    
    {token_alert if present}
    
    For each project:
    📦 *{project_name}*
    • Completed overnight: {task_count} tasks
    • Changed: {file_count} files
    • Status: {phase_status}
    
    📋 Pending your approval: {pending_approvals}
    🔒 Blocked tasks: {blocked_tasks}
    
    Use `/status` for full details.
  
  send_evening_digest(
    completed_tasks: int,
    changed_files: List[str],
    architectural_decisions: List[str],
    needs_attention: List[str]
  ) -> None:
    🌙 *Evening Digest*
    
    ✅ Completed today: {completed_tasks} tasks
    
    📝 Files changed:
    {file list}
    
    🏗 Architectural decisions:
    {decision list or "None today"}
    
    ⚠️ Needs your attention:
    {attention list or "Nothing — all clear"}
  
  send_alert(
    severity: str,
    message: str,
    component: str
  ) -> None:
    {emoji based on severity: 🔴 CRITICAL, 🟡 WARNING, 🟢 INFO}
    *{severity} Alert — {component}*
    {message}
  
  send_project_started(
    project_name: str,
    questions: List[str],
    intake_id: str
  ) -> None:
    🚀 *New Project Detected: {project_name}*
    
    Before I plan, I need to know:
    {numbered question list}
    
    Reply: `/answer {intake_id} [your answers one per line]`

### 3. Wire into existing components

Update core/observability/alerting.py:
  Add notifier: Optional[TelegramNotifier] = None to AlertManager.
  After any alert fires: notifier.send_alert(severity, message, component)

Update core/clone_agent.py:
  Add notifier: Optional[TelegramNotifier] = None.
  After escalate() writes to escalation_queue.md:
    notifier.send_escalation(title, reason, event_id, details)

Update core/projectos.py:
  Initialize TelegramNotifier.from_env()
  Pass to AlertManager and CloneAgent.

### 4. scripts/test_telegram.py

Quick test script — run manually to verify Telegram is working:
  python scripts/test_telegram.py
  
  Sends 3 test messages:
  1. Plain text: "ProjectOS Telegram test — if you see this, it works!"
  2. Phase complete notification (fake data)
  3. Morning brief (fake data)
  
  Exits 0 if all 3 send successfully.
  Exits 0 with "SKIPPED" if no token configured.

### 5. tests/test_notifications/test_telegram_notifier.py
Create tests/test_notifications/__init__.py

All tests mock requests.post:
  - test_send_fires_in_background_thread
  - test_send_never_raises_on_http_error
  - test_disabled_notifier_is_noop
  - test_from_env_returns_disabled_when_no_token
  - test_phase_complete_message_format
  - test_escalation_message_format
  - test_morning_brief_format
  - test_alert_message_uses_correct_emoji

## Constraints
- ALL Telegram methods are fire-and-forget (never await)
- ALL Telegram methods are silent on error (never raise)
- If TELEGRAM_BOT_TOKEN not set: ALL methods are no-op
- Messages use Telegram MarkdownV2 formatting
- Message length must not exceed 4096 chars (Telegram limit)
  Truncate with "... [truncated]" if needed

## Verification
python scripts/test_telegram.py (if token configured)
Full test suite. Write TASK_57_RESULT.md. Update tasks/README.md.
