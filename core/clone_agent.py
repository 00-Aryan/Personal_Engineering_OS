"""Clone Agent supervisor implementation for ProjectOS."""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, List, Mapping, Optional, Sequence, TYPE_CHECKING

from core.base_agent import BaseAgent
from core.decision_log import DecisionLogger
from core.evaluation.base_evaluator import EvaluationResult
from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.quality_gate import GateDecision, QualityGate
from core.evaluation.regression_detector import RegressionDetector
from core.evaluation.schema_validator import SchemaValidator, ValidationResult
from core.events import AgentEvent, AgentResult, EventType
from core.model_provider import ModelProvider

if TYPE_CHECKING:
    from core.intelligence.collaboration import CollaborationBroker
    from core.intelligence.memory_manager import MemoryManager
    from core.intelligence.semantic_router import SemanticRouter


AGENT_NAME = "clone"
ROLE_DESCRIPTION = "ProjectOS supervisor and event dispatcher."
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]

ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
SPACE = " "
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

DECISIONS_LOG_NAME = "decisions.log"
ESCALATION_QUEUE_NAME = "escalation_queue.md"
BLOCKED_TASKS_NAME = "blocked_tasks.md"

ESCALATION_QUEUE_HEADER = (
    "# Escalation Queue\n"
    "Items requiring Aryan's attention.\n"
    "Format: | timestamp | event_id | reason | status |\n"
)
BLOCKED_TASKS_HEADER = (
    "# Blocked Tasks\n"
    "Tasks deferred due to permissions or dependencies.\n"
    "Format: | task_id | blocked_by | correlation_id | reconnect_plan |\n"
)

PAYLOAD_KEY_AFFECTED_FILES = "affected_files"
PAYLOAD_KEY_AGENT_RESULT = "agent_result"
PAYLOAD_KEY_CATEGORY = "category"
PAYLOAD_KEY_DECISION_CATEGORY = "decision_category"
PAYLOAD_KEY_ESCALATE = "escalate"
PAYLOAD_KEY_FILE_PATH = "file_path"
PAYLOAD_KEY_KIND = "kind"
PAYLOAD_KEY_ORIGINAL_EVENT_ID = "original_event_id"
PAYLOAD_KEY_PERMISSION_RESUMED = "permission_resumed"
PAYLOAD_KEY_REASON = "reason"
PAYLOAD_KEY_RESULT = "result"
PAYLOAD_KEY_TARGET_AGENT = "target_agent"
PAYLOAD_KEY_TASK_TYPE = "task_type"
PAYLOAD_KEY_WORK_ITEM_TYPE = "work_item_type"

PAYLOAD_KEY_FORMATTING = "formatting"
PAYLOAD_KEY_MINOR_REFACTOR = "minor_refactor"
PAYLOAD_KEY_DOCSTRING = "docstring"
PAYLOAD_KEY_COMMENT = "comment"
PAYLOAD_KEY_STATUS_UPDATE = "status_update"

PAYLOAD_KEY_NEW_DEPENDENCY = "new_dependency"
PAYLOAD_KEY_BREAKING_CHANGE = "breaking_change"
PAYLOAD_KEY_DELETE_FILE = "delete_file"
PAYLOAD_KEY_ARCHITECTURE_CHANGE = "architecture_change"

TARGET_ARCHITECTURE_AGENT = "architecture_agent"
TARGET_CODE_REVIEW = "code_review"
TARGET_CODE_REVIEW_AGENT = "code_review_agent"
TARGET_CODE_WRITING_AGENT = "code_writing_agent"
TARGET_DOCS_AGENT = "docs_agent"
TARGET_PLANNING_AGENT = "planning_agent"
TARGET_TEST_AGENT = "test_agent"

SEMANTIC_TARGET_ALIASES = {
    "planning": TARGET_PLANNING_AGENT,
    "code_writing": TARGET_CODE_WRITING_AGENT,
    "code_review": TARGET_CODE_REVIEW_AGENT,
    "architecture": TARGET_ARCHITECTURE_AGENT,
    "test": TARGET_TEST_AGENT,
    "docs": TARGET_DOCS_AGENT,
}

TASK_TYPE_ARCHITECTURE = "architecture"
TASK_TYPE_CODE = "code"
TASK_TYPE_DOCS = "docs"
TASK_TYPE_DOCUMENTATION = "documentation"
TASK_TYPE_FEATURE = "feature"
TASK_TYPE_IMPLEMENTATION = "implementation"
TASK_TYPE_PLAN = "plan"
TASK_TYPE_PLANNING = "planning"
TASK_TYPE_REVIEW = "review"
TASK_TYPE_TEST = "test"
TASK_TYPE_TESTS = "tests"

DECISION_REASON_PERMISSION_BLOCKED = "permission or dependency block defers work"
DECISION_REASON_RESULT_ESCALATED = "agent result requested escalation"
DECISION_REASON_HIGH_RISK_PAYLOAD = "payload contains high-risk change marker"
DECISION_REASON_FILE_SPAN = "event affects more than three files"
DECISION_REASON_ROUTINE_EVENT = "routine event can be handled autonomously"
DECISION_REASON_ROUTINE_PAYLOAD = "payload contains routine work marker"
DECISION_REASON_DEFAULT_AUTONOMOUS = "no escalation or dependency signal detected"
DECISION_REASON_PERMISSION_GRANTED = "permission grant resumes blocked work"
DECISION_REASON_SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
DECISION_REASON_SCHEMA_WARNING_TEMPLATE = (
    "schema validation failed for {agent_name}: missing={missing_fields}; "
    "type_errors={type_errors}"
)
DECISION_REASON_GATE_TEMPLATE = "quality_gate {decision}: {reasons}"
DECISION_REASON_GATE_PASS = "quality_gate PASS"
DECISION_REASON_GATE_BLOCK = "quality_gate BLOCK"
DECISION_REASON_GATE_ESCALATE = "quality_gate ESCALATE"

LOG_STATUS_PENDING = "PENDING"
LOG_TABLE_SEPARATOR = " | "
LOG_ROW_PREFIX = "| "
LOG_ROW_SUFFIX = " |\n"
DECISION_LOG_PREFIX = "["
DECISION_LOG_SEPARATOR = "] ["
DECISION_LOG_SUFFIX = "]\n"
RECONNECT_PLAN_TEMPLATE = (
    "When PERMISSION_GRANTED for {blocked_by}, resume task {task_id} "
    "with correlation {correlation_id}"
)

MAX_AUTONOMOUS_FILE_COUNT = 3

AUTONOMOUS_EVENT_TYPES = frozenset(
    {
        EventType.DOCS_UPDATED,
        EventType.TESTS_DONE,
        EventType.REVIEW_DONE,
    }
)
AUTONOMOUS_PAYLOAD_KEYS = frozenset(
    {
        PAYLOAD_KEY_FORMATTING,
        PAYLOAD_KEY_MINOR_REFACTOR,
        PAYLOAD_KEY_DOCSTRING,
        PAYLOAD_KEY_COMMENT,
        PAYLOAD_KEY_STATUS_UPDATE,
    }
)
ESCALATION_PAYLOAD_KEYS = frozenset(
    {
        PAYLOAD_KEY_NEW_DEPENDENCY,
        PAYLOAD_KEY_BREAKING_CHANGE,
        PAYLOAD_KEY_DELETE_FILE,
        PAYLOAD_KEY_ARCHITECTURE_CHANGE,
    }
)
BACKLOG_TYPE_TARGETS = {
    TASK_TYPE_ARCHITECTURE: TARGET_ARCHITECTURE_AGENT,
    TASK_TYPE_CODE: TARGET_CODE_WRITING_AGENT,
    TASK_TYPE_DOCS: TARGET_DOCS_AGENT,
    TASK_TYPE_DOCUMENTATION: TARGET_DOCS_AGENT,
    TASK_TYPE_FEATURE: TARGET_PLANNING_AGENT,
    TASK_TYPE_IMPLEMENTATION: TARGET_CODE_WRITING_AGENT,
    TASK_TYPE_PLAN: TARGET_PLANNING_AGENT,
    TASK_TYPE_PLANNING: TARGET_PLANNING_AGENT,
    TASK_TYPE_REVIEW: TARGET_CODE_REVIEW_AGENT,
    TASK_TYPE_TEST: TARGET_TEST_AGENT,
    TASK_TYPE_TESTS: TARGET_TEST_AGENT,
}
BACKLOG_CLASSIFICATION_KEYS = (
    PAYLOAD_KEY_TASK_TYPE,
    PAYLOAD_KEY_WORK_ITEM_TYPE,
    PAYLOAD_KEY_CATEGORY,
    PAYLOAD_KEY_KIND,
)


class DecisionCategory(Enum):
    """Decision categories used by the Clone Agent supervisor."""

    AUTONOMOUS = "AUTONOMOUS"
    ESCALATE = "ESCALATE"
    DEFER_PARALLEL = "DEFER_PARALLEL"


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _write_atomically(path: Path, content: str) -> None:
    """Write content to a path by replacing it with a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{TEMP_PREFIX}{path.name}.",
        suffix=TEMP_SUFFIX,
        dir=str(path.parent),
    )
    try:
        with os.fdopen(
            file_descriptor,
            FILE_WRITE_MODE,
            encoding=ENCODING,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file while preserving existing content."""
    existing_content = path.read_text(encoding=ENCODING) if path.exists() else EMPTY_TEXT
    _write_atomically(path, f"{existing_content}{content}")


def _sanitize_table_value(value: str) -> str:
    """Return text that is safe to place in a markdown table cell."""
    return value.replace("|", "/").replace(NEWLINE, SPACE)


class CloneAgent(BaseAgent):
    """Supervisor agent that classifies events and dispatches agent work."""

    def __init__(
        self,
        model_provider: ModelProvider,
        logger: logging.Logger,
        project_root: Path | str = DEFAULT_PROJECT_ROOT,
        queued_events: Optional[Iterable[AgentEvent]] = None,
        agent_registry: Optional[Any] = None,
        task_queue: Optional[Any] = None,
        schema_validator: Optional[SchemaValidator] = None,
        regression_detector: Optional[RegressionDetector] = None,
        evaluation_store: Optional[EvaluationStore] = None,
        quality_gate: Optional[QualityGate] = None,
        memory_manager: Optional["MemoryManager"] = None,
        semantic_router: Optional["SemanticRouter"] = None,
        collaboration_broker: Optional["CollaborationBroker"] = None,
    ) -> None:
        """Initialize CloneAgent state and required project log files."""
        super().__init__(
            AGENT_NAME,
            ROLE_DESCRIPTION,
            model_provider,
            logger,
            memory_manager=memory_manager,
            collaboration_broker=collaboration_broker,
        )
        self.project_root = Path(project_root)
        self.event_queue = list(queued_events or [])
        self.blocked_events: List[AgentEvent] = []
        self.agent_registry = agent_registry
        self.task_queue = task_queue
        self.schema_validator = schema_validator
        self.regression_detector = regression_detector
        self.evaluation_store = evaluation_store
        self.quality_gate = quality_gate
        self.semantic_router = semantic_router
        self.decision_logger = DecisionLogger(self.project_root)
        self._ensure_project_files()

    def classify_decision(self, event: AgentEvent) -> DecisionCategory:
        """Classify an incoming event into a Clone decision category."""
        if self.semantic_router is not None:
            return self._semantic_decision_category(event)
        return self._keyword_decision_category(event)

    def _keyword_decision_category(self, event: AgentEvent) -> DecisionCategory:
        """Classify an event using the legacy keyword and event-type rules."""
        if self._should_defer(event):
            return DecisionCategory.DEFER_PARALLEL
        if self._should_escalate(event):
            return DecisionCategory.ESCALATE
        if self._is_routine_event(event) or self._has_any_payload_key(
            event.payload,
            AUTONOMOUS_PAYLOAD_KEYS,
        ):
            return DecisionCategory.AUTONOMOUS
        return DecisionCategory.AUTONOMOUS

    def _semantic_decision_category(self, event: AgentEvent) -> DecisionCategory:
        """Classify an event with semantic routing and keyword fallback."""
        decision = self.semantic_router.route(self._event_description(event))
        self.logger.info(
            "Semantic route method=%s confidence=%.2f nearest=%s category=%s",
            decision.routing_method,
            decision.confidence,
            decision.nearest_example,
            decision.category,
        )
        if decision.routing_method == "keyword_fallback":
            self.logger.warning("Semantic confidence low, used keyword fallback")
        try:
            return DecisionCategory(decision.category)
        except ValueError:
            return self._keyword_decision_category(event)

    def dispatch(self, event: AgentEvent) -> List[AgentEvent]:
        """Create and optionally submit child events for responsible agents."""
        next_events = [
            self._targeted_event(event, target_agent)
            for target_agent in self._dispatch_targets(event)
        ]
        self._submit_dispatched_events(next_events)
        return next_events

    def escalate(
        self,
        event: AgentEvent,
        reason: str,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Append an event to the escalation queue and decision log."""
        timestamp = _utc_timestamp()
        safe_reason = _sanitize_table_value(reason)
        row = self._markdown_row(
            [timestamp, event.event_id, safe_reason, LOG_STATUS_PENDING]
        )
        _append_atomically(self._escalation_queue_path, row)
        self._log_decision(event, DecisionCategory.ESCALATE, reason, duration_ms)
        self.logger.warning(row.strip())

    def handle_blocked(self, event: AgentEvent) -> List[AgentEvent]:
        """Record a blocked event and return independent queued events."""
        self.blocked_events.append(event)
        blocked_by = self._blocked_by_value(event)
        correlation_id = self._correlation_id(event)
        reconnect_plan = RECONNECT_PLAN_TEMPLATE.format(
            blocked_by=blocked_by,
            task_id=event.event_id,
            correlation_id=correlation_id,
        )
        row = self._markdown_row(
            [
                event.event_id,
                blocked_by,
                correlation_id,
                reconnect_plan,
            ]
        )
        _append_atomically(self._blocked_tasks_path, row)

        independent_events = [
            queued_event
            for queued_event in self.event_queue
            if queued_event.blocked_by is None
        ]
        self.event_queue = [
            queued_event
            for queued_event in self.event_queue
            if queued_event.blocked_by is not None
        ]
        return independent_events

    def handle(self, event: AgentEvent) -> AgentResult:
        """Classify, log, and dispatch a Clone Agent event."""
        started_at = perf_counter()
        if event.event_type is EventType.PERMISSION_GRANTED:
            return self._handle_permission_granted(
                event,
                self._duration_ms(started_at),
            )

        decision_category = self.classify_decision(event)
        reasoning = self._decision_reason(event, decision_category)

        if decision_category is DecisionCategory.ESCALATE:
            self.escalate(event, reasoning, self._duration_ms(started_at))
            return AgentResult(
                success=True,
                output=self._result_output(decision_category, reasoning),
                escalate=True,
                escalation_reason=reasoning,
            )

        if decision_category is DecisionCategory.DEFER_PARALLEL:
            self._submit_blocked_event(event)
            independent_events = self.handle_blocked(event)
            next_events = self._dispatch_independent_events(independent_events)
            self._log_decision(
                event,
                decision_category,
                reasoning,
                self._duration_ms(started_at),
            )
            return AgentResult(
                success=True,
                output=self._result_output(decision_category, reasoning),
                next_events=next_events,
            )

        next_events = self.dispatch(event)
        self._log_decision(
            event,
            decision_category,
            reasoning,
            self._duration_ms(started_at),
        )
        return AgentResult(
            success=True,
            output=self._result_output(decision_category, reasoning),
            next_events=next_events,
        )

    def process_agent_result(
        self,
        result: AgentResult,
        agent_name: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> AgentResult:
        """Apply optional evaluator hooks to a worker AgentResult."""
        if not isinstance(result.output, dict):
            return result
        resolved_agent_name = agent_name or self._agent_name_for_result(result)
        resolved_event_id = event_id or self._event_id_for_result(result)
        if (
            self.schema_validator is not None
            and self.schema_validator.has_schema(resolved_agent_name)
        ):
            validation = self.schema_validator.validate(
                resolved_agent_name,
                result.output,
            )
            if not validation.valid:
                self._handle_schema_validation_failure(
                    result,
                    resolved_agent_name,
                    resolved_event_id,
                    validation,
                )
        if self.quality_gate is None:
            return result
        self._apply_quality_gate(
            result,
            resolved_agent_name,
            resolved_event_id,
        )
        return result

    def _apply_quality_gate(
        self,
        result: AgentResult,
        agent_name: str,
        event_id: str,
    ) -> None:
        """Evaluate and apply quality gate decisions to an agent result."""
        if self.quality_gate is None:
            return
        gate_result = self.quality_gate.evaluate(
            result,
            agent_name,
            llm_evaluation=self._llm_evaluation(result),
            file_path=self._result_file_path(result),
            model_version=self._model_version(result),
        )
        gate_event = AgentEvent(
            event_type=EventType.MANUAL_TRIGGER,
            source_agent=agent_name,
            payload={},
            event_id=event_id,
        )
        if gate_result.decision is GateDecision.BLOCK:
            result.next_events = []
            result.escalate = True
            result.escalation_reason = DECISION_REASON_GATE_BLOCK
            self.escalate(gate_event, self._gate_reason(gate_result))
            return
        if gate_result.decision is GateDecision.ESCALATE:
            result.escalate = True
            result.escalation_reason = DECISION_REASON_GATE_ESCALATE
            self.escalate(gate_event, self._gate_reason(gate_result))
            return
        self._log_decision(
            gate_event,
            DecisionCategory.AUTONOMOUS,
            DECISION_REASON_GATE_PASS,
        )

    @property
    def _decisions_log_path(self) -> Path:
        """Return the decisions log path."""
        return self.project_root / DECISIONS_LOG_NAME

    @property
    def _escalation_queue_path(self) -> Path:
        """Return the escalation queue path."""
        return self.project_root / ESCALATION_QUEUE_NAME

    @property
    def _blocked_tasks_path(self) -> Path:
        """Return the blocked tasks path."""
        return self.project_root / BLOCKED_TASKS_NAME

    def _ensure_project_files(self) -> None:
        """Create required Clone Agent persistence files if absent."""
        self._ensure_file(self._decisions_log_path, EMPTY_TEXT)
        self._ensure_file(self._escalation_queue_path, ESCALATION_QUEUE_HEADER)
        self._ensure_file(self._blocked_tasks_path, BLOCKED_TASKS_HEADER)

    def _ensure_file(self, path: Path, initial_content: str) -> None:
        """Create a file atomically when it does not already exist."""
        if not path.exists():
            _write_atomically(path, initial_content)

    def _should_defer(self, event: AgentEvent) -> bool:
        """Return whether an event should be deferred for parallel work."""
        return (
            event.blocked_by is not None
            or event.event_type is EventType.PERMISSION_BLOCKED
        )

    def _should_escalate(self, event: AgentEvent) -> bool:
        """Return whether an event requires human escalation."""
        return (
            self._payload_result_escalates(event.payload)
            or self._has_any_payload_key(event.payload, ESCALATION_PAYLOAD_KEYS)
            or self._affected_file_count(event.payload) > MAX_AUTONOMOUS_FILE_COUNT
        )

    def _is_routine_event(self, event: AgentEvent) -> bool:
        """Return whether an event type is routine without escalation."""
        return (
            event.event_type in AUTONOMOUS_EVENT_TYPES
            and not self._payload_result_escalates(event.payload)
            and not bool(event.payload.get(PAYLOAD_KEY_ESCALATE))
        )

    def _has_any_payload_key(
        self,
        payload: Mapping[str, Any],
        keys: Iterable[str],
    ) -> bool:
        """Return whether the payload contains any of the provided keys."""
        return any(key in payload for key in keys)

    def _payload_result_escalates(self, payload: Mapping[str, Any]) -> bool:
        """Return whether payload carries an escalating AgentResult."""
        if bool(payload.get(PAYLOAD_KEY_ESCALATE)):
            return True
        for result_key in (PAYLOAD_KEY_AGENT_RESULT, PAYLOAD_KEY_RESULT):
            result = payload.get(result_key)
            if isinstance(result, AgentResult) and result.escalate:
                return True
        return False

    def _affected_file_count(self, payload: Mapping[str, Any]) -> int:
        """Return the number of affected files declared by a payload."""
        affected_files = payload.get(PAYLOAD_KEY_AFFECTED_FILES)
        if isinstance(affected_files, Sequence) and not isinstance(
            affected_files,
            str,
        ):
            return len(affected_files)
        return 0

    def _dispatch_targets(self, event: AgentEvent) -> List[str]:
        """Return target agent names for a dispatchable event."""
        explicit_targets = self._explicit_dispatch_targets(event)
        if self.semantic_router is not None and (
            event.event_type is EventType.MANUAL_TRIGGER or not explicit_targets
        ):
            semantic_targets = self._semantic_dispatch_targets(event)
            if semantic_targets:
                return semantic_targets
        return explicit_targets

    def _explicit_dispatch_targets(self, event: AgentEvent) -> List[str]:
        """Return dispatch targets from legacy explicit routing rules."""
        if event.event_type is EventType.CODE_CHANGED:
            return [TARGET_CODE_REVIEW, TARGET_TEST_AGENT, TARGET_DOCS_AGENT]
        if event.event_type is EventType.NEW_FEATURE:
            return [TARGET_PLANNING_AGENT]
        if event.event_type is EventType.CODE_WRITTEN:
            return [TARGET_CODE_REVIEW_AGENT, TARGET_TEST_AGENT]
        if event.event_type is EventType.REVIEW_DONE:
            return [TARGET_CODE_WRITING_AGENT]
        if event.event_type is EventType.ARCHITECTURE_QUESTION:
            return [TARGET_ARCHITECTURE_AGENT]
        if event.event_type is EventType.BACKLOG_CHANGED:
            return [self._target_for_backlog(event.payload)]
        if event.event_type is EventType.MANUAL_TRIGGER:
            return self._manual_trigger_targets(event.payload)
        return []

    def _semantic_dispatch_targets(self, event: AgentEvent) -> List[str]:
        """Return semantic-router dispatch targets for an event."""
        if self.semantic_router is None:
            return []
        decision = self.semantic_router.route(self._event_description(event))
        target_agent = SEMANTIC_TARGET_ALIASES.get(decision.category)
        if target_agent is None:
            return []
        self.logger.info(
            "Semantic dispatch method=%s confidence=%.2f nearest=%s target=%s",
            decision.routing_method,
            decision.confidence,
            decision.nearest_example,
            target_agent,
        )
        return [target_agent]

    def _target_for_backlog(self, payload: Mapping[str, Any]) -> str:
        """Classify a backlog payload and return the target agent."""
        explicit_target = payload.get(PAYLOAD_KEY_TARGET_AGENT)
        if isinstance(explicit_target, str) and explicit_target:
            return explicit_target
        for key in BACKLOG_CLASSIFICATION_KEYS:
            task_type = payload.get(key)
            if isinstance(task_type, str):
                normalized_task_type = task_type.strip().lower()
                target = BACKLOG_TYPE_TARGETS.get(normalized_task_type)
                if target:
                    return target
        return TARGET_PLANNING_AGENT

    def _manual_trigger_targets(self, payload: Mapping[str, Any]) -> List[str]:
        """Return manual trigger targets from payload metadata."""
        target_agent = payload.get(PAYLOAD_KEY_TARGET_AGENT)
        if isinstance(target_agent, str) and target_agent:
            return [target_agent]
        return []

    def _targeted_event(self, event: AgentEvent, target_agent: str) -> AgentEvent:
        """Create a child event carrying routing metadata for a target."""
        payload = dict(event.payload)
        payload[PAYLOAD_KEY_TARGET_AGENT] = target_agent
        payload[PAYLOAD_KEY_ORIGINAL_EVENT_ID] = event.event_id
        return AgentEvent(
            event_type=event.event_type,
            source_agent=self.name,
            payload=payload,
            correlation_id=self._correlation_id(event),
            blocked_by=event.blocked_by,
            priority=event.priority,
        )

    def _dispatch_independent_events(
        self,
        independent_events: Iterable[AgentEvent],
    ) -> List[AgentEvent]:
        """Dispatch all independent events returned by the blocked handler."""
        next_events: List[AgentEvent] = []
        for independent_event in independent_events:
            next_events.extend(self.dispatch(independent_event))
        return next_events

    def _decision_reason(
        self,
        event: AgentEvent,
        decision_category: DecisionCategory,
    ) -> str:
        """Return the audit reasoning string for a Clone decision."""
        if decision_category is DecisionCategory.DEFER_PARALLEL:
            return DECISION_REASON_PERMISSION_BLOCKED
        if decision_category is DecisionCategory.ESCALATE:
            if self._payload_result_escalates(event.payload):
                return DECISION_REASON_RESULT_ESCALATED
            if self._affected_file_count(event.payload) > MAX_AUTONOMOUS_FILE_COUNT:
                return DECISION_REASON_FILE_SPAN
            return DECISION_REASON_HIGH_RISK_PAYLOAD
        if self._is_routine_event(event):
            return DECISION_REASON_ROUTINE_EVENT
        if self._has_any_payload_key(event.payload, AUTONOMOUS_PAYLOAD_KEYS):
            return DECISION_REASON_ROUTINE_PAYLOAD
        return DECISION_REASON_DEFAULT_AUTONOMOUS

    def _result_output(
        self,
        decision_category: DecisionCategory,
        reasoning: str,
    ) -> Mapping[str, str]:
        """Build a structured result payload for Clone handle calls."""
        return {
            PAYLOAD_KEY_DECISION_CATEGORY: decision_category.value,
            PAYLOAD_KEY_REASON: reasoning,
        }

    def _submit_dispatched_events(self, next_events: Iterable[AgentEvent]) -> None:
        """Submit dispatched child events to registered target agents."""
        if self.agent_registry is None or self.task_queue is None:
            return
        for next_event in next_events:
            target_agent_name = next_event.payload.get(PAYLOAD_KEY_TARGET_AGENT)
            if not isinstance(target_agent_name, str) or not target_agent_name:
                continue
            try:
                target_agent = self.agent_registry.get(target_agent_name)
                self.task_queue.submit(next_event, target_agent)
            except Exception as error:
                self.logger.exception("Clone dispatch failed: %s", error)

    def _submit_blocked_event(self, event: AgentEvent) -> None:
        """Store a blocked targeted event in the task queue when possible."""
        if self.agent_registry is None or self.task_queue is None:
            return
        target_agent_name = event.payload.get(PAYLOAD_KEY_TARGET_AGENT)
        if not isinstance(target_agent_name, str) or not target_agent_name:
            return
        try:
            target_agent = self.agent_registry.get(target_agent_name)
            self.task_queue.submit(event, target_agent)
        except Exception as error:
            self.logger.exception("Clone blocked submit failed: %s", error)

    def _handle_permission_granted(
        self,
        event: AgentEvent,
        duration_ms: Optional[int] = None,
    ) -> AgentResult:
        """Resume a task queue item for a permission grant event."""
        resumed = False
        if self.task_queue is not None:
            resumed = self.task_queue.unblock(self._correlation_id(event)) is not None
        self._log_decision(
            event,
            DecisionCategory.AUTONOMOUS,
            DECISION_REASON_PERMISSION_GRANTED,
            duration_ms,
        )
        return AgentResult(
            success=True,
            output={
                PAYLOAD_KEY_DECISION_CATEGORY: DecisionCategory.AUTONOMOUS.value,
                PAYLOAD_KEY_REASON: DECISION_REASON_PERMISSION_GRANTED,
                PAYLOAD_KEY_PERMISSION_RESUMED: resumed,
            },
        )

    def _handle_schema_validation_failure(
        self,
        result: AgentResult,
        agent_name: str,
        event_id: str,
        validation: ValidationResult,
    ) -> None:
        """Flag a result and append schema validation failure escalation."""
        result.escalate = True
        result.escalation_reason = DECISION_REASON_SCHEMA_VALIDATION_FAILED
        warning = DECISION_REASON_SCHEMA_WARNING_TEMPLATE.format(
            agent_name=agent_name,
            missing_fields=validation.missing_fields,
            type_errors=validation.type_errors,
        )
        self.logger.warning(warning)
        validation_event = AgentEvent(
            event_type=EventType.MANUAL_TRIGGER,
            source_agent=agent_name,
            payload={},
            event_id=event_id,
        )
        self.escalate(validation_event, DECISION_REASON_SCHEMA_VALIDATION_FAILED)

    def _llm_evaluation(self, result: AgentResult) -> Optional[EvaluationResult]:
        """Return an attached LLM evaluation when present."""
        value = result.metadata.get("llm_evaluation")
        if isinstance(value, EvaluationResult):
            return value
        return None

    def _result_file_path(self, result: AgentResult) -> Optional[Path]:
        """Return a file path from result output or emitted event payload."""
        output_file_path = result.output.get(PAYLOAD_KEY_FILE_PATH)
        if isinstance(output_file_path, str) and output_file_path:
            return Path(output_file_path)
        for next_event in result.next_events:
            next_file_path = next_event.payload.get(PAYLOAD_KEY_FILE_PATH)
            if isinstance(next_file_path, str) and next_file_path:
                return Path(next_file_path)
        return None

    def _model_version(self, result: AgentResult) -> Optional[str]:
        """Return an attached model version for regression checks."""
        value = result.metadata.get("model_version")
        if isinstance(value, str) and value:
            return value
        return None

    def _gate_reason(self, gate_result: Any) -> str:
        """Return a compact quality gate reason for decisions.log."""
        reasons = gate_result.blocking_reasons or gate_result.warnings
        rendered_reasons = ", ".join(reasons) if reasons else gate_result.decision.value
        return DECISION_REASON_GATE_TEMPLATE.format(
            decision=gate_result.decision.value,
            reasons=rendered_reasons,
        )

    def _agent_name_for_result(self, result: AgentResult) -> str:
        """Infer the producing agent from result events when possible."""
        if result.next_events:
            source_agent = result.next_events[0].source_agent
            if isinstance(source_agent, str) and source_agent:
                return source_agent
        return EMPTY_TEXT

    def _event_id_for_result(self, result: AgentResult) -> str:
        """Infer an event identifier from result events when possible."""
        if result.next_events:
            next_event = result.next_events[0]
            return next_event.correlation_id or next_event.event_id
        return DECISION_REASON_SCHEMA_VALIDATION_FAILED

    def _correlation_id(self, event: AgentEvent) -> str:
        """Return an event correlation identifier, falling back to event ID."""
        return event.correlation_id or event.event_id

    def _blocked_by_value(self, event: AgentEvent) -> str:
        """Return the dependency marker responsible for blocking an event."""
        return event.blocked_by or event.event_type.value

    def _markdown_row(self, values: Iterable[str]) -> str:
        """Format values as a markdown table row."""
        safe_values = [_sanitize_table_value(value) for value in values]
        return f"{LOG_ROW_PREFIX}{LOG_TABLE_SEPARATOR.join(safe_values)}{LOG_ROW_SUFFIX}"

    def _log_decision(
        self,
        event: AgentEvent,
        decision_category: DecisionCategory,
        reasoning: str,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Append one Clone decision to decisions.log."""
        timestamp = _utc_timestamp()
        decision_line = (
            f"{DECISION_LOG_PREFIX}{timestamp}{DECISION_LOG_SEPARATOR}"
            f"{event.event_id}{DECISION_LOG_SEPARATOR}"
            f"{decision_category.value}{DECISION_LOG_SEPARATOR}"
            f"{reasoning}{DECISION_LOG_SUFFIX}"
        )
        _append_atomically(self._decisions_log_path, decision_line)
        self.decision_logger.log(
            event_id=event.event_id,
            correlation_id=event.correlation_id,
            agent_name=self.name,
            decision_category=decision_category.value,
            reasoning=reasoning,
            outcome=decision_category.value,
            escalated=decision_category is DecisionCategory.ESCALATE,
            duration_ms=duration_ms,
        )
        self.log_decision(reasoning, decision_category.value)

    def _duration_ms(self, started_at: float) -> int:
        """Return elapsed milliseconds from a monotonic start time."""
        return int((perf_counter() - started_at) * 1000)

    def _event_description(self, event: AgentEvent) -> str:
        """Return a compact event description for semantic routing."""
        return f"{event.event_type.value}: {str(event.payload)[:200]}"


__all__ = ["CloneAgent", "DecisionCategory"]
