"""Manual test script for TelegramNotifier."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.notifications.telegram_notifier import TelegramNotifier, DisabledNotifier, DECISIONS_LOG_NAME, DECISION_ERROR_PREFIX


def _hard_timeout(signum: Any, frame: Any) -> None:
    """Handle hard script timeout."""
    print("TELEGRAM TEST: FAILED: Wall clock timeout reached")
    sys.exit(1)


def main() -> int:
    """Run manual Telegram test sending three distinct messages."""
    # 1. Load .env manually to populate environment variables
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'\"")

    # 2. Check configuration status
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("SKIPPED: Telegram credentials not configured in environment")
        return 0

    print("Initializing TelegramNotifier...")
    notifier = TelegramNotifier.from_env(project_root=project_root)
    if isinstance(notifier, DisabledNotifier):
        print("SKIPPED: Notifier resolved to DisabledNotifier")
        return 0

    # 3. Track decisions.log to detect background thread failures
    log_path = project_root / DECISIONS_LOG_NAME
    initial_log_content = ""
    if log_path.exists():
        initial_log_content = log_path.read_text(encoding="utf-8")

    print("Sending 3 test messages...")

    # Message 1: Plain text
    notifier.send("ProjectOS Telegram test — if you see this, it works!")

    # Message 2: Phase complete
    notifier.send_phase_complete(
        project_name="TestProject",
        phase_number=1,
        phase_name="Setup",
        files_changed=3,
        tests_passing=12,
        next_phase_summary="Build Core Module",
        approval_id="test-approval-id"
    )

    # Message 3: Morning brief
    notifier.send_morning_brief(
        project_summaries=[{
            "project_name": "TestProject",
            "task_count": 5,
            "file_count": 3,
            "phase_status": "Planning"
        }],
        pending_approvals=2,
        blocked_tasks=1,
        token_alert="Token budget is at 85%"
    )

    # 4. Wait for notifier background threads to finish
    main_thread = threading.main_thread()
    threads = [t for t in threading.enumerate() if t is not main_thread]
    print(f"Waiting for {len(threads)} background thread(s) to finish...")
    for t in threads:
        t.join(timeout=10)

    # 5. Check if any errors were logged during sending
    if log_path.exists():
        current_log_content = log_path.read_text(encoding="utf-8")
        # Extract new log lines
        new_content = current_log_content[len(initial_log_content):]
        if DECISION_ERROR_PREFIX in new_content:
            print("TELEGRAM TEST: FAILED: Errors found in decisions.log:")
            for line in new_content.splitlines():
                if DECISION_ERROR_PREFIX in line:
                    print(line)
            return 1

    print("TELEGRAM TEST: SUCCESS: All test messages queued and sent without errors")
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, _hard_timeout)
    signal.alarm(30)
    sys.exit(main())
