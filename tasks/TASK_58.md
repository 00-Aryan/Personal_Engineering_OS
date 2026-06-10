# TASK_58: Telegram Bot — Inbound Commands

## Engineering Context

TASK_57 built outbound notifications.
This task builds inbound command handling — Aryan can control
ProjectOS entirely from Telegram.

Commands:
/approve [id]           — approve a phase or escalation
/reject [id] [reason]   — reject with reason
/modify [id] [text]     — approve with modification instruction
/status                 — current system status
/brief                  — trigger morning brief now
/digest                 — trigger evening digest now
/answer [id] [text]     — answer project intake questions
/pause                  — pause all agent work
/resume                 — resume agent work
/help                   — list commands

## Pre-conditions
Read core/notifications/telegram_notifier.py from TASK_57.
Read core/clone_agent.py (escalation queue format).
Read AGENTS.md.

## Deliverables

### 1. core/notifications/telegram_commander.py

class TelegramCommander:
  """
  Polls Telegram for incoming messages and processes commands.
  
  Uses long polling (not webhook) — simpler, no server needed.
  Runs in a background daemon thread.
  Only processes messages from the configured CHAT_ID.
  Ignores all other senders (security).
  
  Polling interval: 2 seconds.
  Stops cleanly when stop() is called.
  """
  
  __init__(
    bot_token: str,
    chat_id: str,
    command_handlers: Dict[str, Callable],
    notifier: TelegramNotifier
  )
  
  start() -> None:
    Start background polling thread.
    Thread is daemon=True (dies when main process dies).
    Log: "Telegram commander started. Polling for commands."
  
  stop() -> None:
    Set stop flag. Polling thread exits cleanly.
  
  _poll() -> None:
    Loop while not stopped:
      GET https://api.telegram.org/bot{token}/getUpdates
        ?offset={last_update_id+1}&timeout=2
      For each update:
        Ignore if not from configured chat_id
        Parse command and args
        Call matching handler
        Acknowledge update
      Sleep 0 (long poll handles timing)
  
  _parse_command(text: str) -> Tuple[str, List[str]]:
    Parse "/command arg1 arg2" → ("command", ["arg1", "arg2"])
    Returns ("unknown", []) if not a valid command

### 2. core/notifications/command_registry.py

class CommandRegistry:
  """
  Routes Telegram commands to ProjectOS actions.
  """
  
  __init__(
    clone_agent: CloneAgent,
    phase_manager: Any,  (TASK_61 — use Optional for now)
    notifier: TelegramNotifier,
    state_dir: Path
  )
  
  handle_approve(args: List[str]) -> None:
    approval_id = args[0] if args else None
    If no id: notifier.send("❌ Usage: /approve [id]")
    
    Read escalation_queue.md or pending_phases.md
    Find item with matching id
    Mark as APPROVED
    Log to decisions.log: "Telegram approval: {id}"
    notifier.send(f"✅ Approved: {id}")
    
    If it's a phase approval: trigger phase continuation
    If it's an escalation: resume blocked event
  
  handle_reject(args: List[str]) -> None:
    approval_id = args[0] if args else None
    reason = " ".join(args[1:]) if len(args) > 1 else "No reason given"
    
    Mark item as REJECTED with reason
    Log to decisions.log
    notifier.send(f"❌ Rejected: {id}\nReason: {reason}")
  
  handle_modify(args: List[str]) -> None:
    approval_id = args[0] if args else None
    instruction = " ".join(args[1:]) if len(args) > 1 else ""
    
    If no instruction: notifier.send("❌ Usage: /modify [id] [instruction]")
    
    Mark as APPROVED_WITH_MODIFICATION
    Store instruction alongside approval
    Log to decisions.log
    notifier.send(f"🔄 Modification noted: {instruction}")
  
  handle_status(args: List[str]) -> None:
    Read .projectos_state/last_status.json
    Read .projectos_state/provider_status.json
    Count pending in escalation_queue.md
    Count blocked in blocked_tasks.md
    
    Send formatted status:
    📊 *ProjectOS Status*
    🤖 Agents: {N} registered
    ✅ Providers: {available list}
    📋 Pending approvals: {N}
    🔒 Blocked tasks: {N}
    🕐 Last activity: {timestamp}
  
  handle_brief(args: List[str]) -> None:
    Trigger MorningBriefGenerator immediately
    (TASK_63 will build this — for now send placeholder)
    notifier.send("📋 Brief generation triggered. Check back in 30 seconds.")
  
  handle_pause(args: List[str]) -> None:
    Write .projectos_state/paused flag file
    notifier.send("⏸ ProjectOS paused. All agent work suspended.")
    Log to decisions.log
  
  handle_resume(args: List[str]) -> None:
    Delete .projectos_state/paused flag file
    notifier.send("▶️ ProjectOS resumed.")
    Log to decisions.log
  
  handle_answer(args: List[str]) -> None:
    intake_id = args[0] if args else None
    answers = " ".join(args[1:])
    
    Write to .projectos_state/intake_answers/{intake_id}.txt
    notifier.send(f"📝 Answers recorded for intake {intake_id}")
  
  handle_help(args: List[str]) -> None:
    Send command reference message:
    📖 *ProjectOS Commands*
    `/approve [id]` — approve phase or decision
    `/reject [id] [reason]` — reject with reason
    `/modify [id] [instruction]` — approve with changes
    `/status` — system status
    `/brief` — morning brief now
    `/digest` — evening digest now
    `/pause` — pause all work
    `/resume` — resume work
    `/help` — this message

### 3. Update core/projectos.py

Add TelegramCommander initialization:
  If TELEGRAM_BOT_TOKEN set:
    registry = CommandRegistry(clone_agent, None, notifier, state_dir)
    commander = TelegramCommander(
      bot_token=token,
      chat_id=chat_id,
      command_handlers={
        "approve": registry.handle_approve,
        "reject": registry.handle_reject,
        "modify": registry.handle_modify,
        "status": registry.handle_status,
        "brief": registry.handle_brief,
        "pause": registry.handle_pause,
        "resume": registry.handle_resume,
        "answer": registry.handle_answer,
        "help": registry.handle_help,
      },
      notifier=notifier
    )
  
  On start(): commander.start()
  On stop(): commander.stop()

Add pause check to trigger system:
  In TriggerSystem._dispatch():
    If Path(".projectos_state/paused").exists():
      Log: "System paused — ignoring trigger"
      Return (do not dispatch event)

### 4. tests/test_notifications/test_telegram_commander.py
Mock all HTTP calls:
  - test_poll_ignores_messages_from_other_chats
  - test_poll_calls_correct_handler_for_command
  - test_approve_marks_escalation_approved
  - test_reject_stores_reason
  - test_pause_creates_flag_file
  - test_resume_removes_flag_file
  - test_unknown_command_sends_help
  - test_stop_exits_polling_loop_cleanly

## Constraints
- Commander only runs when TELEGRAM_BOT_TOKEN is set
- Only processes messages from exact configured CHAT_ID
- All handlers must complete in < 5 seconds
- Commander thread is daemon=True always
- handle_pause and handle_resume are the only commands that 
  take effect immediately — all others are asynchronous

## Verification
Full test suite. Write TASK_58_RESULT.md. Update tasks/README.md.
