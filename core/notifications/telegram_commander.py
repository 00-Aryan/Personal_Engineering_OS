"""Telegram commander module for ProjectOS."""

from __future__ import annotations

import logging
import time
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
import requests

from core.notifications.telegram_notifier import TelegramNotifier

LOGGER_NAME = "projectos.telegram_commander"
logger = logging.getLogger(LOGGER_NAME)


class TelegramCommander:
    """Polls Telegram for incoming messages and processes commands.

    Uses long polling (not webhook) — simpler, no server needed.
    Runs in a background daemon thread.
    Only processes messages from the configured CHAT_ID.
    Ignores all other senders (security).

    Polling interval: 2 seconds.
    Stops cleanly when stop() is called.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        command_handlers: Dict[str, Callable[[List[str]], None]],
        notifier: TelegramNotifier,
    ) -> None:
        """Initialize the Telegram commander."""
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.command_handlers = command_handlers
        self.notifier = notifier
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_update_id: Optional[int] = None

    def start(self) -> None:
        """Start background polling thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll,
            name="TelegramCommanderThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("Telegram commander started. Polling for commands.")

    def stop(self) -> None:
        """Set stop flag. Polling thread exits cleanly."""
        self._stop_event.set()

    def _poll(self) -> None:
        """Loop while not stopped, fetching updates from Telegram."""
        while not self._stop_event.is_set():
            try:
                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
                params: Dict[str, Any] = {"timeout": 2}
                if self._last_update_id is not None:
                    params["offset"] = self._last_update_id + 1

                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    logger.warning("Telegram getUpdates returned ok=False: %s", data)
                    time.sleep(2)
                    continue

                updates = data.get("result", [])
                for update in updates:
                    update_id = update.get("update_id")
                    if update_id is not None:
                        if self._last_update_id is None or update_id > self._last_update_id:
                            self._last_update_id = update_id

                    message = update.get("message")
                    if not message:
                        continue

                    chat = message.get("chat")
                    if not chat:
                        continue

                    # Ignore if not from configured chat_id
                    if str(chat.get("id")) != str(self.chat_id):
                        continue

                    text = message.get("text")
                    if not text:
                        continue

                    command, args = self._parse_command(text)
                    if command == "unknown":
                        help_handler = self.command_handlers.get("help")
                        if help_handler:
                            try:
                                help_handler([])
                            except Exception as e:
                                logger.exception("Error executing help handler: %s", e)
                        continue

                    handler = self.command_handlers.get(command)
                    if handler:
                        try:
                            handler(args)
                        except Exception as e:
                            logger.exception("Error executing command handler for /%s: %s", command, e)
                    else:
                        help_handler = self.command_handlers.get("help")
                        if help_handler:
                            try:
                                help_handler([])
                            except Exception as e:
                                logger.exception("Error executing help handler for unknown command: %s", e)

            except Exception as e:
                logger.debug("Error in Telegram polling loop: %s", e)
                time.sleep(2)

            time.sleep(0.01)

    def _parse_command(self, text: str) -> Tuple[str, List[str]]:
        """Parse "/command arg1 arg2" → ("command", ["arg1", "arg2"])."""
        if not text or not text.startswith("/"):
            return "unknown", []
        text = text[1:].strip()
        if not text:
            return "unknown", []
        parts = text.split()
        if not parts:
            return "unknown", []
        command = parts[0].lower()
        if "@" in command:
            command = command.split("@")[0]
        args = parts[1:]
        return command, args
