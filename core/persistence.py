"""Durable queue persistence for ProjectOS runtime state."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from core.events import AgentEvent, EventPriority, EventType


ENCODING = "utf-8"
EMPTY_TEXT = ""
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

BLOCKED_QUEUE_FILE_NAME = "blocked_queue.json"
PENDING_QUEUE_FILE_NAME = "pending_queue.json"
STATUS_FILE_NAME = "last_status.json"

EVENT_KEY_EVENT_TYPE = "event_type"
EVENT_KEY_SOURCE_AGENT = "source_agent"
EVENT_KEY_PAYLOAD = "payload"
EVENT_KEY_EVENT_ID = "event_id"
EVENT_KEY_CORRELATION_ID = "correlation_id"
EVENT_KEY_TIMESTAMP = "timestamp"
EVENT_KEY_BLOCKED_BY = "blocked_by"
EVENT_KEY_PRIORITY = "priority"

STATUS_KEY_TIMESTAMP = "timestamp"
STATUS_KEY_AGENT_STATUSES = "agent_statuses"
STATUS_KEY_PENDING_COUNT = "pending_count"
STATUS_KEY_BLOCKED_COUNT = "blocked_count"
STATUS_KEY_PROVIDER_HEALTH = "provider_health"

LOGGER_NAME = "projectos.persistence"


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _write_atomically(path: Path, content: str) -> None:
    """Write content to a path by replacing it with a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(
        f"{TEMP_PREFIX}{path.name}.{uuid.uuid4().hex}{TEMP_SUFFIX}"
    )
    try:
        temporary_path.write_text(content, encoding=ENCODING)
        temporary_path.replace(path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file through atomic replacement."""
    existing_content = path.read_text(encoding=ENCODING) if path.exists() else EMPTY_TEXT
    _write_atomically(path, f"{existing_content}{content}")


class PersistenceManager:
    """Persist blocked and pending queue events as newline-delimited JSON."""

    def __init__(self, state_dir: Path) -> None:
        """Initialize persistence paths and create the state directory."""
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(LOGGER_NAME)

    def save_blocked_task(self, event: AgentEvent) -> None:
        """Append a blocked task event to durable state."""
        self._append_event(self._blocked_queue_path, event)

    def load_blocked_tasks(self) -> List[AgentEvent]:
        """Load blocked task events, skipping malformed lines."""
        return self._load_events(self._blocked_queue_path)

    def clear_blocked_task(self, correlation_id: str) -> None:
        """Remove blocked events matching a correlation identifier."""
        self._rewrite_excluding(
            self._blocked_queue_path,
            lambda event: self._correlation_id(event) == correlation_id,
        )

    def save_pending_event(self, event: AgentEvent) -> None:
        """Append a pending event to durable state."""
        self._append_event(self._pending_queue_path, event)

    def load_pending_events(self) -> List[AgentEvent]:
        """Load pending events, skipping malformed lines."""
        return self._load_events(self._pending_queue_path)

    def clear_pending_event(self, event_id: str) -> None:
        """Remove pending events matching an event identifier."""
        self._rewrite_excluding(
            self._pending_queue_path,
            lambda event: event.event_id == event_id,
        )

    def snapshot_status(
        self,
        agents: Dict[str, str],
        provider_health: Optional[Dict[str, bool]] = None,
    ) -> None:
        """Write a point-in-time runtime status snapshot."""
        status_payload = {
            STATUS_KEY_TIMESTAMP: _utc_timestamp(),
            STATUS_KEY_AGENT_STATUSES: agents,
            STATUS_KEY_PENDING_COUNT: len(self.load_pending_events()),
            STATUS_KEY_BLOCKED_COUNT: len(self.load_blocked_tasks()),
        }
        if provider_health is not None:
            status_payload[STATUS_KEY_PROVIDER_HEALTH] = provider_health
        _write_atomically(
            self._status_path,
            f"{json.dumps(status_payload, sort_keys=True)}{NEWLINE}",
        )

    @property
    def status_path(self) -> Path:
        """Return the persisted status snapshot path."""
        return self._status_path

    @property
    def _blocked_queue_path(self) -> Path:
        """Return the blocked queue path."""
        return self.state_dir / BLOCKED_QUEUE_FILE_NAME

    @property
    def _pending_queue_path(self) -> Path:
        """Return the pending queue path."""
        return self.state_dir / PENDING_QUEUE_FILE_NAME

    @property
    def _status_path(self) -> Path:
        """Return the status snapshot path."""
        return self.state_dir / STATUS_FILE_NAME

    def _append_event(self, path: Path, event: AgentEvent) -> None:
        """Append one serialized event to a queue file."""
        serialized_event = self._serialize_event(event)
        _append_atomically(path, f"{json.dumps(serialized_event, sort_keys=True)}{NEWLINE}")

    def _load_events(self, path: Path) -> List[AgentEvent]:
        """Load events from a newline-delimited JSON file."""
        if not path.exists():
            return []
        events: List[AgentEvent] = []
        for line in path.read_text(encoding=ENCODING).splitlines():
            if not line.strip():
                continue
            try:
                event_payload = json.loads(line)
                events.append(self._deserialize_event(event_payload))
            except Exception as error:
                self._logger.warning("Skipped malformed persisted event: %s", error)
        return events

    def _rewrite_excluding(
        self,
        path: Path,
        should_exclude: Any,
    ) -> None:
        """Rewrite a queue file while excluding selected events."""
        if not path.exists():
            return
        remaining_events = [
            event for event in self._load_events(path) if not should_exclude(event)
        ]
        rendered_events = EMPTY_TEXT.join(
            f"{json.dumps(self._serialize_event(event), sort_keys=True)}{NEWLINE}"
            for event in remaining_events
        )
        _write_atomically(path, rendered_events)

    def _serialize_event(self, event: AgentEvent) -> Mapping[str, Any]:
        """Serialize an AgentEvent using dataclass fields."""
        event_data = asdict(event)
        return self._json_safe(event_data)

    def _json_safe(self, value: Any) -> Any:
        """Convert dataclass output into JSON-compatible values."""
        if isinstance(value, EventType):
            return value.value
        if isinstance(value, EventPriority):
            return value.value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Mapping):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        return value

    def _deserialize_event(self, event_data: Mapping[str, Any]) -> AgentEvent:
        """Deserialize one JSON mapping into an AgentEvent."""
        if not isinstance(event_data, Mapping):
            raise ValueError("Persisted event must be a mapping.")

        event_type = EventType(str(event_data[EVENT_KEY_EVENT_TYPE]))
        priority = EventPriority(str(event_data.get(EVENT_KEY_PRIORITY, EventPriority.MEDIUM.value)))
        timestamp = datetime.fromisoformat(str(event_data[EVENT_KEY_TIMESTAMP]))
        payload = event_data.get(EVENT_KEY_PAYLOAD)
        if not isinstance(payload, Mapping):
            raise ValueError("Persisted event payload must be a mapping.")

        return AgentEvent(
            event_type=event_type,
            source_agent=str(event_data[EVENT_KEY_SOURCE_AGENT]),
            payload=dict(payload),
            event_id=str(event_data[EVENT_KEY_EVENT_ID]),
            correlation_id=self._optional_string(event_data.get(EVENT_KEY_CORRELATION_ID)),
            timestamp=timestamp,
            blocked_by=self._optional_string(event_data.get(EVENT_KEY_BLOCKED_BY)),
            priority=priority,
        )

    def _optional_string(self, value: Any) -> str | None:
        """Return a string value or None."""
        if value is None:
            return None
        return str(value)

    def _correlation_id(self, event: AgentEvent) -> str:
        """Return a stable event correlation identifier."""
        return event.correlation_id or event.event_id


__all__ = ["PersistenceManager"]
