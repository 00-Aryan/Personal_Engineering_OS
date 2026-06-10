# TASK_57 Result: Telegram Bot — Notifications + Status

## Files Created or Modified

- **Created**: `core/notifications/__init__.py`
- **Created/updated**: `core/notifications/telegram_notifier.py`
  - Added `TelegramNotifier` and `DisabledNotifier`.
  - Added MarkdownV2 escaping, message truncation, background-thread delivery, silent error logging, and Telegram token redaction in error logs.
- **Modified**: `core/observability/alerting.py`
  - Wired fired alerts to `notifier.send_alert(...)`.
- **Modified**: `core/clone_agent.py`
  - Wired escalations to `notifier.send_escalation(...)` after queue writes.
- **Modified**: `core/projectos.py`
  - Initialized `TelegramNotifier.from_env(...)` and passed it to `AlertManager` and `CloneAgent`.
- **Modified**: `scripts/test_telegram.py`
  - Added manual live Telegram smoke script with `signal.alarm(30)`.
- **Created/updated**: `tests/test_notifications/test_telegram_notifier.py`
  - Added 10 unit tests covering fire-and-forget delivery, disabled behavior, formatting, MarkdownV2 escaping, HTTP-error handling, and token redaction.
- **Modified**: `pyproject.toml`, `uv.lock`, `requirements.txt`
  - Added Telegram dependency support and `python-telegram-bot>=20.0` in `requirements.txt`.

## Test Results

- **Notification unit tests**:
  - Command: `UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -q tests/test_notifications/test_telegram_notifier.py --timeout=30`
  - Result: `10 passed in 0.32s`
- **Full test suite**:
  - Command: `UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest`
  - Result: `448 passed, 1 warning in 74.70s`
- **Manual Telegram script**:
  - Command: `UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync python scripts/test_telegram.py`
  - Result: failed because this environment could not resolve `api.telegram.org`.
  - Verified behavior: new error logs redact the bot token as `/bot<redacted-bot-token>/sendMessage`.

## Decisions Made

1. **Plain vs formatted send paths**: `send()` treats caller input as plain text and escapes it for MarkdownV2. Structured notifier methods use an internal formatted path so bold/code formatting remains valid.
2. **Secret-safe error logging**: Telegram API URLs are redacted before being appended to `decisions.log`.
3. **No-op unconfigured behavior**: `from_env()` returns `DisabledNotifier` when either Telegram credential is missing, preserving the task requirement that unconfigured Telegram never crashes.

## Anything Flagged for Human Review

- Existing older `decisions.log` entries already contain a Telegram bot token from before the redaction fix. Because `decisions.log` is append-only by project rule, this task did not rewrite history. The bot token should be rotated manually.
- Live Telegram delivery could not be verified from this environment because DNS resolution for `api.telegram.org` failed.

## Next Task Dependency Check

- **Next task**: `TASK_58: Telegram Bot — Inbound Commands` is now unblocked.
