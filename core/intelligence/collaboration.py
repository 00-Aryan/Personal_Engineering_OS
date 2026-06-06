"""Agent-to-agent consultation broker for ProjectOS."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Mapping, Optional

from core.events import AgentEvent, AgentResult, EventType


ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

COLLABORATION_LOG_NAME = "collaboration.jsonl"
CONSULTATION_TIMEOUT_SECONDS = 30.0
DEFAULT_CONFIDENCE = 0.7
FAILURE_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0
MIN_CONFIDENCE = 0.0
PERCENT_MULTIPLIER = 100.0

PAYLOAD_KEY_CONSULTATION = "consultation"
PAYLOAD_KEY_QUESTION = "question"
PAYLOAD_KEY_CONTEXT = "context"
PAYLOAD_KEY_MAX_TOKENS = "max_tokens"
PAYLOAD_KEY_DEPTH = "depth"

OUTPUT_KEY_ANSWER = "answer"
OUTPUT_KEY_CONFIDENCE = "confidence"
OUTPUT_KEY_RECOMMENDED_ACTION = "recommended_action"
OUTPUT_KEY_RECOMMENDATION = "recommendation"
OUTPUT_KEY_RESPONSE = "response"
OUTPUT_KEY_ERROR = "error"

AGENT_CLONE = "clone"
AGENT_CLONE_ALIAS = "clone_agent"

LOG_KEY_TIMESTAMP = "timestamp"
LOG_KEY_CONSULTATION_ID = "consultation_id"
LOG_KEY_REQUESTING_AGENT = "requesting_agent"
LOG_KEY_TARGET_AGENT = "target_agent"
LOG_KEY_RESPONDING_AGENT = "responding_agent"
LOG_KEY_CONSULTATION_TYPE = "consultation_type"
LOG_KEY_QUESTION = "question"
LOG_KEY_ANSWER = "answer"
LOG_KEY_CONFIDENCE = "confidence"
LOG_KEY_RECOMMENDED_ACTION = "recommended_action"
LOG_KEY_DURATION_MS = "duration_ms"
LOG_KEY_DEPTH = "depth"


class ConsultationType(Enum):
    """Supported reasons for agent-to-agent consultation."""

    ARCHITECTURE_REVIEW = "architecture_review"
    FEASIBILITY_CHECK = "feasibility_check"
    PATTERN_VALIDATION = "pattern_validation"
    CODE_VERIFICATION = "code_verification"
    PLAN_REVIEW = "plan_review"


@dataclass
class ConsultationRequest:
    """One synchronous consultation request between two agents."""

    requesting_agent: str
    target_agent: str
    consultation_type: ConsultationType
    question: str
    context: str
    max_tokens: int = 500
    depth: int = 0
    consultation_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class ConsultationResult:
    """Structured result returned from a consultation."""

    consultation_id: str
    responding_agent: str
    answer: str
    confidence: float
    recommended_action: Optional[str]
    duration_ms: int
    depth: int


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
        with os.fdopen(file_descriptor, FILE_WRITE_MODE, encoding=ENCODING) as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file using ProjectOS atomic-write semantics."""
    existing_content = path.read_text(encoding=ENCODING) if path.exists() else EMPTY_TEXT
    _write_atomically(path, f"{existing_content}{content}")


class CollaborationBroker:
    """Manage bounded synchronous consultations between registered agents."""

    def __init__(
        self,
        agent_registry: Any,
        log_path: Path,
        max_depth: int = 1,
        timeout_seconds: float = CONSULTATION_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the broker with an agent registry and audit log path."""
        self.agent_registry = agent_registry
        self.log_path = Path(log_path)
        self.max_depth = max_depth
        self.timeout_seconds = timeout_seconds

    def consult(self, request: ConsultationRequest) -> ConsultationResult:
        """Run one bounded consultation and return a structured result."""
        start_time = perf_counter()
        validation_error = self._validation_error(request)
        if validation_error is not None:
            result = self._failure_result(request, validation_error, start_time)
            self._log_consultation(request, result)
            return result

        try:
            target_agent = self.agent_registry.get(request.target_agent)
        except KeyError:
            result = self._failure_result(
                request,
                f"Consultation target not registered: {request.target_agent}",
                start_time,
            )
            self._log_consultation(request, result)
            return result

        event = self._consultation_event(request)
        agent_result = self._call_target_with_timeout(target_agent, event)
        if agent_result is None:
            result = self._failure_result(
                request,
                "Consultation timed out",
                start_time,
            )
            self._log_consultation(request, result)
            return result

        answer, confidence, recommended_action = self._extract_answer(agent_result.output)
        result = ConsultationResult(
            consultation_id=request.consultation_id,
            responding_agent=request.target_agent,
            answer=answer,
            confidence=confidence,
            recommended_action=recommended_action,
            duration_ms=self._duration_ms(start_time),
            depth=request.depth,
        )
        self._log_consultation(request, result)
        return result

    def get_collaboration_stats(self) -> Dict[str, Any]:
        """Return aggregate collaboration statistics from the JSONL log."""
        records = self._log_records()
        total = len(records)
        if total == 0:
            return {
                "total_consultations": 0,
                "by_type": {},
                "by_requesting_agent": {},
                "avg_duration_ms": 0,
                "depth_1_pct": 0.0,
            }

        durations = [int(record.get(LOG_KEY_DURATION_MS, 0)) for record in records]
        depth_one_count = sum(
            1 for record in records if int(record.get(LOG_KEY_DEPTH, 0)) >= 1
        )
        return {
            "total_consultations": total,
            "by_type": self._count_by(records, LOG_KEY_CONSULTATION_TYPE),
            "by_requesting_agent": self._count_by(records, LOG_KEY_REQUESTING_AGENT),
            "avg_duration_ms": int(sum(durations) / total),
            "depth_1_pct": (depth_one_count / total) * PERCENT_MULTIPLIER,
        }

    def _validation_error(self, request: ConsultationRequest) -> Optional[str]:
        """Return a validation error message or None when the request is allowed."""
        if request.depth >= self.max_depth:
            return "Consultation depth limit reached"
        if request.requesting_agent == request.target_agent:
            return "Consultation rejected: agents cannot consult themselves"
        if request.target_agent in {AGENT_CLONE, AGENT_CLONE_ALIAS}:
            return "Consultation rejected: clone cannot be a target"
        return None

    def _consultation_event(self, request: ConsultationRequest) -> AgentEvent:
        """Build the event sent to the consulted target agent."""
        return AgentEvent(
            event_type=EventType.MANUAL_TRIGGER,
            source_agent=request.requesting_agent,
            payload={
                PAYLOAD_KEY_CONSULTATION: True,
                PAYLOAD_KEY_QUESTION: request.question,
                PAYLOAD_KEY_CONTEXT: request.context,
                PAYLOAD_KEY_MAX_TOKENS: request.max_tokens,
                PAYLOAD_KEY_DEPTH: request.depth + 1,
            },
        )

    def _call_target_with_timeout(
        self,
        target_agent: Any,
        event: AgentEvent,
    ) -> Optional[AgentResult]:
        """Call an agent without blocking indefinitely."""
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(target_agent.handle, event)
        try:
            result = future.result(timeout=self.timeout_seconds)
            executor.shutdown(wait=False, cancel_futures=True)
            return result if isinstance(result, AgentResult) else None
        except TimeoutError:
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            return None
        except Exception as error:
            executor.shutdown(wait=False, cancel_futures=True)
            return AgentResult(success=False, output={OUTPUT_KEY_ERROR: str(error)})

    def _extract_answer(self, output: Any) -> tuple[str, float, Optional[str]]:
        """Extract answer, confidence, and action from agent output."""
        parsed_output = self._parsed_output(output)
        if isinstance(parsed_output, Mapping):
            answer = self._answer_from_mapping(parsed_output)
            confidence = self._confidence_from_mapping(parsed_output)
            recommended_action = self._optional_string(
                parsed_output.get(OUTPUT_KEY_RECOMMENDED_ACTION)
            )
            return answer, confidence, recommended_action
        return str(output), DEFAULT_CONFIDENCE, None

    def _parsed_output(self, output: Any) -> Any:
        """Return JSON-decoded string output when possible."""
        if not isinstance(output, str):
            return output
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return output

    def _answer_from_mapping(self, output: Mapping[str, Any]) -> str:
        """Return the best answer-like value from structured output."""
        for key in (
            OUTPUT_KEY_ANSWER,
            OUTPUT_KEY_RECOMMENDATION,
            OUTPUT_KEY_RESPONSE,
            OUTPUT_KEY_ERROR,
        ):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(dict(output), sort_keys=True)

    def _confidence_from_mapping(self, output: Mapping[str, Any]) -> float:
        """Return a normalized confidence value from structured output."""
        value = output.get(OUTPUT_KEY_CONFIDENCE)
        if isinstance(value, (int, float)):
            return max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, float(value)))
        if isinstance(value, str):
            try:
                parsed_value = float(value)
            except ValueError:
                return DEFAULT_CONFIDENCE
            return max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, parsed_value))
        return DEFAULT_CONFIDENCE

    def _optional_string(self, value: Any) -> Optional[str]:
        """Return a trimmed string or None."""
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _failure_result(
        self,
        request: ConsultationRequest,
        answer: str,
        start_time: float,
    ) -> ConsultationResult:
        """Return a non-crashing failed consultation result."""
        return ConsultationResult(
            consultation_id=request.consultation_id,
            responding_agent=request.target_agent,
            answer=answer,
            confidence=FAILURE_CONFIDENCE,
            recommended_action=None,
            duration_ms=self._duration_ms(start_time),
            depth=request.depth,
        )

    def _log_consultation(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> None:
        """Append one consultation record to collaboration.jsonl."""
        record = {
            LOG_KEY_TIMESTAMP: _utc_timestamp(),
            LOG_KEY_CONSULTATION_ID: request.consultation_id,
            LOG_KEY_REQUESTING_AGENT: request.requesting_agent,
            LOG_KEY_TARGET_AGENT: request.target_agent,
            LOG_KEY_RESPONDING_AGENT: result.responding_agent,
            LOG_KEY_CONSULTATION_TYPE: request.consultation_type.value,
            LOG_KEY_QUESTION: request.question,
            LOG_KEY_ANSWER: result.answer,
            LOG_KEY_CONFIDENCE: result.confidence,
            LOG_KEY_RECOMMENDED_ACTION: result.recommended_action,
            LOG_KEY_DURATION_MS: result.duration_ms,
            LOG_KEY_DEPTH: result.depth,
        }
        _append_atomically(
            self.log_path,
            f"{json.dumps(record, sort_keys=True)}{NEWLINE}",
        )

    def _log_records(self) -> list[Mapping[str, Any]]:
        """Return valid JSON records from the collaboration log."""
        if not self.log_path.exists():
            return []
        records: list[Mapping[str, Any]] = []
        for line in self.log_path.read_text(encoding=ENCODING).splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, Mapping):
                records.append(record)
        return records

    def _count_by(
        self,
        records: list[Mapping[str, Any]],
        key: str,
    ) -> dict[str, int]:
        """Count records by one JSON key."""
        counts: dict[str, int] = {}
        for record in records:
            value = str(record.get(key, EMPTY_TEXT))
            if not value:
                continue
            counts[value] = counts.get(value, 0) + 1
        return counts

    def _duration_ms(self, start_time: float) -> int:
        """Return elapsed milliseconds since start_time."""
        return int((perf_counter() - start_time) * 1000)


__all__ = [
    "COLLABORATION_LOG_NAME",
    "CollaborationBroker",
    "ConsultationRequest",
    "ConsultationResult",
    "ConsultationType",
]
