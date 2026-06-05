"""Filesystem trigger system for ProjectOS."""

from __future__ import annotations

import queue
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.events import AgentEvent, EventType

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:

    class FileSystemEventHandler:
        """Fallback event handler base when watchdog is unavailable."""


    class Observer:
        """Fallback observer that keeps imports usable until watchdog is installed."""

        def __init__(self) -> None:
            """Initialize fallback observer state."""
            self.started = False
            self.stopped = False
            self.joined = False

        def schedule(
            self,
            event_handler: FileSystemEventHandler,
            path: str,
            recursive: bool,
        ) -> None:
            """Accept a watchdog-compatible schedule call."""

        def start(self) -> None:
            """Mark the fallback observer as started."""
            self.started = True

        def stop(self) -> None:
            """Mark the fallback observer as stopped."""
            self.stopped = True

        def join(self) -> None:
            """Mark the fallback observer as joined."""
            self.joined = True


ENCODING = "utf-8"
EMPTY_TEXT = ""
PYTHON_EXTENSION = ".py"
PYTHON_BYTECODE_EXTENSION = ".pyc"
GIT_DIR_NAME = ".git"
PYCACHE_DIR_NAME = "__pycache__"
TEST_FILE_PREFIX = "test_"
TEST_FILE_SUFFIX = "_test.py"

SOURCE_AGENT = "trigger_system"
PAYLOAD_KEY_FILE_PATH = "file_path"
PAYLOAD_KEY_MODIFIED_AT = "modified_at"


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class FileChangeHandler(FileSystemEventHandler):
    """Translate filesystem modifications into ProjectOS queue events."""

    def __init__(self, event_dispatcher: queue.Queue[AgentEvent]) -> None:
        """Initialize the handler with a queue dispatcher."""
        super().__init__()
        self.event_dispatcher = event_dispatcher

    def on_modified(self, event: Any) -> None:
        """Emit CODE_CHANGED for modified Python files without blocking."""
        if bool(getattr(event, "is_directory", False)):
            return

        src_path = getattr(event, "src_path", EMPTY_TEXT)
        if not isinstance(src_path, str) or not src_path:
            return

        changed_path = Path(src_path)
        if self._should_ignore(changed_path):
            return
        if changed_path.suffix != PYTHON_EXTENSION:
            return

        agent_event = AgentEvent(
            event_type=EventType.CODE_CHANGED,
            source_agent=SOURCE_AGENT,
            payload={
                PAYLOAD_KEY_FILE_PATH: str(changed_path),
                PAYLOAD_KEY_MODIFIED_AT: _utc_timestamp(),
            },
        )
        try:
            self.event_dispatcher.put_nowait(agent_event)
        except queue.Full:
            return

    def _should_ignore(self, changed_path: Path) -> bool:
        """Return whether a filesystem path should be ignored."""
        path_parts = set(changed_path.parts)
        if PYCACHE_DIR_NAME in path_parts or GIT_DIR_NAME in path_parts:
            return True
        if changed_path.suffix == PYTHON_BYTECODE_EXTENSION:
            return True
        return self._is_test_file(changed_path)

    def _is_test_file(self, changed_path: Path) -> bool:
        """Return whether a changed path is a Python test file."""
        file_name = changed_path.name
        return file_name.startswith(TEST_FILE_PREFIX) or file_name.endswith(
            TEST_FILE_SUFFIX
        )


class TriggerSystem:
    """Watch a directory and enqueue ProjectOS file-change events."""

    def __init__(
        self,
        watch_dir: Path | str,
        event_dispatcher: queue.Queue[AgentEvent],
    ) -> None:
        """Initialize the trigger system with a watch directory and queue."""
        self.watch_dir = Path(watch_dir)
        self.event_dispatcher = event_dispatcher
        self.handler = FileChangeHandler(event_dispatcher)
        self.observer = Observer()
        self._running = False

    def start(self) -> None:
        """Start the background file watcher thread."""
        if self._running:
            return
        self.observer.schedule(
            self.handler,
            str(self.watch_dir),
            recursive=True,
        )
        self.observer.start()
        self._running = True

    def stop(self) -> None:
        """Stop the background file watcher thread cleanly."""
        if not self._running:
            return
        self.observer.stop()
        self.observer.join()
        self._running = False


__all__ = ["FileChangeHandler", "TriggerSystem"]
