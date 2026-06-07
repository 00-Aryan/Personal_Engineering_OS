"""Threaded task queue for ProjectOS agent execution."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Tuple

from core.events import AgentEvent, AgentResult, EventType
from core.persistence import PersistenceManager


DEFAULT_MAX_WORKERS = 4
LOGGER_NAME = "projectos.task_queue"

PAYLOAD_KEY_PERMISSION_CONTEXT = "permission_context"
PAYLOAD_KEY_PERMISSION_GRANTED = "permission_granted"


@dataclass
class BlockedTask:
    """A deferred event and the agent that should resume it."""

    event: AgentEvent
    target_agent: Any


class TaskQueue:
    """Run agent work in a non-blocking ThreadPoolExecutor."""

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        result_callback: Optional[Callable[[AgentResult], None]] = None,
        persistence_manager: Optional[PersistenceManager] = None,
    ) -> None:
        """Initialize the queue with a bounded worker pool."""
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._blocked_tasks: dict[str, BlockedTask] = {}
        self._pending_count = 0
        self._lock = threading.Lock()
        self._logger = logging.getLogger(LOGGER_NAME)
        self._result_callback = result_callback
        self._persistence_manager = persistence_manager

    def submit(
        self,
        event: AgentEvent,
        target_agent: Any,
    ) -> Optional[Future[Optional[AgentResult]]]:
        """Submit one event to a target agent without blocking the caller."""
        try:
            if self._should_block(event):
                self._store_blocked(event, target_agent)
                if self._persistence_manager is not None:
                    self._persistence_manager.save_blocked_task(event)
                return None

            if self._persistence_manager is not None:
                self._persistence_manager.save_pending_event(event)
            future = self._executor.submit(self._run_target_agent, event, target_agent)
            with self._lock:
                self._pending_count += 1
            future.add_done_callback(
                lambda completed_future, event_id=event.event_id: self._mark_done(
                    completed_future,
                    event_id,
                )
            )
            return future
        except Exception as error:
            self._logger.exception("TaskQueue submit failed: %s", error)
            return None

    def submit_batch(
        self,
        events_agents: Iterable[Tuple[AgentEvent, Any]],
    ) -> List[Future[Optional[AgentResult]]]:
        """Submit multiple event and agent pairs in one pass."""
        futures: List[Future[Optional[AgentResult]]] = []
        try:
            for event, target_agent in events_agents:
                future = self.submit(event, target_agent)
                if future is not None:
                    futures.append(future)
        except Exception as error:
            self._logger.exception("TaskQueue submit_batch failed: %s", error)
        return futures

    def get_pending_count(self) -> int:
        """Return the number of submitted tasks that have not completed."""
        try:
            with self._lock:
                return self._pending_count
        except Exception as error:
            self._logger.exception("TaskQueue pending count failed: %s", error)
            return 0

    def get_blocked(self) -> List[AgentEvent]:
        """Return currently blocked events."""
        try:
            with self._lock:
                return [
                    blocked_task.event
                    for blocked_task in self._blocked_tasks.values()
                ]
        except Exception as error:
            self._logger.exception("TaskQueue get_blocked failed: %s", error)
            return []

    def unblock(
        self,
        correlation_id: str,
    ) -> Optional[Future[Optional[AgentResult]]]:
        """Resume a blocked task by correlation ID with permission context."""
        try:
            with self._lock:
                blocked_task = self._blocked_tasks.pop(correlation_id, None)
            if blocked_task is None:
                return None
            if self._persistence_manager is not None:
                self._persistence_manager.clear_blocked_task(correlation_id)

            resumed_event = self._permission_granted_event(blocked_task.event)
            return self.submit(resumed_event, blocked_task.target_agent)
        except Exception as error:
            self._logger.exception("TaskQueue unblock failed: %s", error)
            return None

    def restore_blocked(
        self,
        event: AgentEvent,
        target_agent: Any,
    ) -> None:
        """Restore one blocked event into the in-memory blocked task map."""
        try:
            self._store_blocked(event, target_agent)
        except Exception as error:
            self._logger.exception("TaskQueue restore_blocked failed: %s", error)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the underlying executor without raising to the caller."""
        try:
            self._executor.shutdown(wait=wait)
        except Exception as error:
            self._logger.exception("TaskQueue shutdown failed: %s", error)

    def _run_target_agent(
        self,
        event: AgentEvent,
        target_agent: Any,
    ) -> Optional[AgentResult]:
        """Run the target agent handle method and swallow failures."""
        try:
            from core.observability.token_budget import _local
            _local.current_task_id = event.event_id
        except Exception:
            pass

        try:
            result = target_agent.handle(event)
            if result is not None and self._result_callback is not None:
                self._result_callback(result)
            return result
        except Exception as error:
            self._logger.exception("Target agent execution failed: %s", error)
            return None

    def _mark_done(
        self,
        future: Future[Optional[AgentResult]],
        event_id: str,
    ) -> None:
        """Decrement pending task count after a submitted future completes."""
        try:
            if self._persistence_manager is not None:
                self._persistence_manager.clear_pending_event(event_id)
            with self._lock:
                self._pending_count = max(self._pending_count - 1, 0)
        except Exception as error:
            self._logger.exception("TaskQueue completion callback failed: %s", error)

    def _should_block(self, event: AgentEvent) -> bool:
        """Return whether an event should be stored as blocked."""
        if bool(event.payload.get(PAYLOAD_KEY_PERMISSION_GRANTED)):
            return False
        return (
            event.blocked_by is not None
            or event.event_type is EventType.PERMISSION_BLOCKED
        )

    def _store_blocked(self, event: AgentEvent, target_agent: Any) -> None:
        """Store a blocked event by correlation ID."""
        correlation_id = self._correlation_id(event)
        with self._lock:
            self._blocked_tasks[correlation_id] = BlockedTask(event, target_agent)

    def _permission_granted_event(self, event: AgentEvent) -> AgentEvent:
        """Return a resumed copy of an event with permission context."""
        payload = dict(event.payload)
        payload[PAYLOAD_KEY_PERMISSION_CONTEXT] = EventType.PERMISSION_GRANTED.value
        payload[PAYLOAD_KEY_PERMISSION_GRANTED] = True
        return AgentEvent(
            event_type=event.event_type,
            source_agent=event.source_agent,
            payload=payload,
            correlation_id=self._correlation_id(event),
            blocked_by=None,
            priority=event.priority,
        )

    def _correlation_id(self, event: AgentEvent) -> str:
        """Return a stable correlation key for queue bookkeeping."""
        return event.correlation_id or event.event_id


# Thread-safe event call count dictionary and lock for reasoning loop protection
event_call_counts: dict[str, int] = {}
event_call_counts_lock = threading.Lock()


def record_model_call(event_id: str, project_root: Path) -> bool:
    """Record a model call for a given event ID.
    
    If the call count exceeds 5, block further calls, log warning,
    and write to the escalation queue.
    
    Returns True if the call is allowed, False if blocked.
    """
    global event_call_counts
    with event_call_counts_lock:
        count = event_call_counts.get(event_id, 0) + 1
        event_call_counts[event_id] = count
        
    if count > 5:
        logger = logging.getLogger(LOGGER_NAME)
        logger.warning("Event [%s] blocked: exceeded max model calls (5)", event_id)
        
        # Write to escalation queue (potential_reasoning_loop escalation)
        escalation_queue_path = project_root / "escalation_queue.md"
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()
        reason = "potential_reasoning_loop"
        row = f"| {timestamp} | {event_id} | {reason} | PENDING |\n"
        
        try:
            if not escalation_queue_path.exists():
                header = "| Timestamp | Event ID | Reason | Status |\n|---|---|---|---|\n"
                _write_atomically_task_queue(escalation_queue_path, header)
            _append_atomically_task_queue(escalation_queue_path, row)
        except Exception as e:
            logger.exception("Failed to write to escalation queue: %s", e)
            
        return False
        
    return True


def _write_atomically_task_queue(path: Path, content: str) -> None:
    import tempfile
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    except Exception:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise


def _append_atomically_task_queue(path: Path, content: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    _write_atomically_task_queue(path, f"{existing}{content}")


__all__ = ["BlockedTask", "TaskQueue", "record_model_call"]
