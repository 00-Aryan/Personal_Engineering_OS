"""Unit tests for the filesystem trigger system."""

from __future__ import annotations

import queue
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core import trigger_system
from core.events import AgentEvent, EventType
from core.trigger_system import FileChangeHandler, TriggerSystem


TEST_ENCODING = "utf-8"
SOURCE_CODE = "value = 1\n"
PYTHON_FILE_NAME = "example.py"
PYCACHE_DIR_NAME = "__pycache__"
TEST_FILE_NAME = "test_example.py"
BYTECODE_FILE_NAME = "example.pyc"
FILE_PATH_KEY = "file_path"
MODIFIED_AT_KEY = "modified_at"


def test_py_file_change_emits_code_changed_event(tmp_path: Path) -> None:
    """Verify Python file modifications enqueue CODE_CHANGED events."""
    dispatcher: queue.Queue[AgentEvent] = queue.Queue()
    handler = FileChangeHandler(dispatcher)
    changed_file = tmp_path / PYTHON_FILE_NAME
    changed_file.write_text(SOURCE_CODE, encoding=TEST_ENCODING)

    handler.on_modified(_modified_event(changed_file))

    agent_event = dispatcher.get_nowait()
    assert agent_event.event_type is EventType.CODE_CHANGED
    assert agent_event.payload[FILE_PATH_KEY] == str(changed_file)
    assert MODIFIED_AT_KEY in agent_event.payload


def test_pycache_ignored(tmp_path: Path) -> None:
    """Verify pycache and bytecode file changes do not enqueue events."""
    dispatcher: queue.Queue[AgentEvent] = queue.Queue()
    handler = FileChangeHandler(dispatcher)
    pycache_dir = tmp_path / PYCACHE_DIR_NAME
    pycache_dir.mkdir()
    changed_file = pycache_dir / BYTECODE_FILE_NAME
    changed_file.write_text(SOURCE_CODE, encoding=TEST_ENCODING)

    handler.on_modified(_modified_event(changed_file))

    assert dispatcher.empty()


def test_test_files_not_triggered(tmp_path: Path) -> None:
    """Verify files starting with test_ do not enqueue CODE_CHANGED events."""
    dispatcher: queue.Queue[AgentEvent] = queue.Queue()
    handler = FileChangeHandler(dispatcher)
    changed_file = tmp_path / TEST_FILE_NAME
    changed_file.write_text(SOURCE_CODE, encoding=TEST_ENCODING)

    handler.on_modified(_modified_event(changed_file))

    assert dispatcher.empty()


def test_stop_cleans_up_watcher_thread(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Verify TriggerSystem stop calls observer stop and join."""
    created_observers: list[FakeObserver] = []

    def observer_factory() -> "FakeObserver":
        """Create and capture a fake observer instance."""
        observer = FakeObserver()
        created_observers.append(observer)
        return observer

    monkeypatch.setattr(trigger_system, "Observer", observer_factory)
    system = TriggerSystem(tmp_path, queue.Queue())

    system.start()
    system.stop()

    observer = created_observers[0]
    assert observer.scheduled
    assert observer.started
    assert observer.stopped
    assert observer.joined


def _modified_event(changed_file: Path) -> SimpleNamespace:
    """Create a watchdog-like modified file event."""
    return SimpleNamespace(src_path=str(changed_file), is_directory=False)


class FakeObserver:
    """Small watchdog observer test double."""

    def __init__(self) -> None:
        """Initialize fake observer state flags."""
        self.scheduled = False
        self.started = False
        self.stopped = False
        self.joined = False

    def schedule(
        self,
        event_handler: FileChangeHandler,
        path: str,
        recursive: bool,
    ) -> None:
        """Record that a handler was scheduled."""
        self.scheduled = True

    def start(self) -> None:
        """Record that the observer was started."""
        self.started = True

    def stop(self) -> None:
        """Record that the observer was stopped."""
        self.stopped = True

    def join(self) -> None:
        """Record that the observer thread was joined."""
        self.joined = True
