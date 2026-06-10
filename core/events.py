"""Shared event and result types for ProjectOS agents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional


class EventType(Enum):
    """Enumerates source-defined events handled by ProjectOS agents."""

    CODE_CHANGED = "CODE_CHANGED"
    NEW_FEATURE = "NEW_FEATURE"
    CODE_WRITTEN = "CODE_WRITTEN"
    REVIEW_DONE = "REVIEW_DONE"
    TESTS_DONE = "TESTS_DONE"
    DOCS_UPDATED = "DOCS_UPDATED"
    BACKLOG_CHANGED = "BACKLOG_CHANGED"
    PERMISSION_BLOCKED = "PERMISSION_BLOCKED"
    PERMISSION_GRANTED = "PERMISSION_GRANTED"
    ARCHITECTURE_QUESTION = "ARCHITECTURE_QUESTION"
    MANUAL_TRIGGER = "MANUAL_TRIGGER"
    NEW_PROJECT = "NEW_PROJECT"
    PLAN_APPROVED = "PLAN_APPROVED"
    PHASE_COMPLETE = "PHASE_COMPLETE"


class EventPriority(Enum):
    """Enumerates supported agent event priorities."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class AgentEvent:
    """Represents an event delivered to an agent."""

    event_type: EventType
    source_agent: str
    payload: Mapping[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    blocked_by: Optional[str] = None
    priority: EventPriority = EventPriority.MEDIUM


@dataclass
class AgentResult:
    """Represents the result produced by an agent after handling an event."""

    success: bool
    output: Any
    next_events: List[AgentEvent] = field(default_factory=list)
    escalate: bool = False
    escalation_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
