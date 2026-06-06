"""Architecture Agent implementation for ProjectOS."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, TYPE_CHECKING

from core.base_agent import BaseAgent
from core.events import AgentEvent, AgentResult, EventType
from core.model_provider import ModelProvider

if TYPE_CHECKING:
    from core.intelligence.collaboration import CollaborationBroker
    from core.intelligence.memory_manager import MemoryManager


AGENT_NAME = "architecture"
ROLE_DESCRIPTION = "Architecture decision and ADR generation agent."
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]

ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

ADR_DIR = "docs/adr"
ADR_EXTENSION = ".md"
ADR_FILE_PREFIX = "ADR-"
ADR_SEQUENCE_WIDTH = 3
DEFAULT_SLUG = "architecture-decision"
MAX_SLUG_LENGTH = 80
DECISIONS_LOG_NAME = "decisions.log"

SYSTEM_PROMPT = (
    "You are a principal systems architect with 15 years of experience.\n"
    "You challenge design decisions before they are built.\n"
    "For every architecture question, output JSON with:\n"
    "decision_required (string),\n"
    "risks (list of strings),\n"
    "alternatives (list of {name, pros, cons}),\n"
    "recommendation (string),\n"
    "adr_content (full ADR markdown as string),\n"
    "confidence (HIGH/MEDIUM/LOW)"
)

MODEL_MAX_TOKENS = 8192

PAYLOAD_KEY_QUESTION = "question"
PAYLOAD_KEY_CONTEXT = "context"
PAYLOAD_KEY_AFFECTED_COMPONENTS = "affected_components"

PROMPT_QUESTION_LABEL = "Architecture question:"
PROMPT_CONTEXT_LABEL = "Context:"
PROMPT_AFFECTED_COMPONENTS_LABEL = "Affected components:"
PROMPT_INSTRUCTION = "Return valid JSON only."
PROMPT_SECTION_SEPARATOR = "\n\n"

MODEL_KEY_DECISION_REQUIRED = "decision_required"
MODEL_KEY_RISKS = "risks"
MODEL_KEY_ALTERNATIVES = "alternatives"
MODEL_KEY_NAME = "name"
MODEL_KEY_PROS = "pros"
MODEL_KEY_CONS = "cons"
MODEL_KEY_RECOMMENDATION = "recommendation"
MODEL_KEY_ADR_CONTENT = "adr_content"
MODEL_KEY_CONFIDENCE = "confidence"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
VALID_CONFIDENCE = frozenset(
    {
        CONFIDENCE_HIGH,
        CONFIDENCE_MEDIUM,
        CONFIDENCE_LOW,
    }
)

DECISION_LOG_PREFIX = "["
DECISION_LOG_SEPARATOR = "] ["
DECISION_LOG_SUFFIX = "]\n"
DECISION_SUCCESS = "SUCCESS"
DECISION_FAILURE = "FAILURE"
DECISION_REASON_WRITTEN = "architecture recommendation written to ADR"
DECISION_REASON_INVALID_EVENT = "architecture agent received unsupported event type"
DECISION_REASON_INVALID_PAYLOAD = "architecture question payload missing question"
DECISION_REASON_INVALID_JSON = "model returned invalid architecture JSON"
ESCALATION_REASON_LOW_CONFIDENCE = "low confidence architecture recommendation"
LOGGER_ERROR_FORMAT = "%s: %s"

OUTPUT_KEY_ADR_PATH = "adr_path"
OUTPUT_KEY_ALTERNATIVES = "alternatives"
OUTPUT_KEY_CONFIDENCE = "confidence"
OUTPUT_KEY_DECISION_REQUIRED = "decision_required"
OUTPUT_KEY_ERROR = "error"
OUTPUT_KEY_RECOMMENDATION = "recommendation"
OUTPUT_KEY_RISKS = "risks"


@dataclass
class ArchitectureAlternative:
    """One architecture alternative from a model response."""

    name: str
    pros: List[str]
    cons: List[str]


@dataclass
class ArchitectureDecision:
    """Structured architecture decision parsed from model JSON."""

    decision_required: str
    risks: List[str]
    alternatives: List[ArchitectureAlternative]
    recommendation: str
    adr_content: str
    confidence: str


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


class ArchitectureAgent(BaseAgent):
    """Agent that answers architecture questions and writes ADR files."""

    def __init__(
        self,
        model_provider: ModelProvider,
        logger: logging.Logger,
        project_root: Path | str = DEFAULT_PROJECT_ROOT,
        memory_manager: Optional["MemoryManager"] = None,
        collaboration_broker: Optional["CollaborationBroker"] = None,
    ) -> None:
        """Initialize ArchitectureAgent with model access and project paths."""
        super().__init__(
            AGENT_NAME,
            ROLE_DESCRIPTION,
            model_provider,
            logger,
            memory_manager=memory_manager,
            collaboration_broker=collaboration_broker,
        )
        self.project_root = Path(project_root)

    def handle(self, event: AgentEvent) -> AgentResult:
        """Handle ARCHITECTURE_QUESTION events and write ADR output."""
        if event.event_type is not EventType.ARCHITECTURE_QUESTION:
            return self._failure_result(event, DECISION_REASON_INVALID_EVENT)

        question = event.payload.get(PAYLOAD_KEY_QUESTION)
        if not isinstance(question, str) or not question.strip():
            return self._failure_result(event, DECISION_REASON_INVALID_PAYLOAD)

        prompt = self._build_prompt(event.payload, question.strip())
        model_output = self.model_provider.complete(
            prompt,
            SYSTEM_PROMPT,
            MODEL_MAX_TOKENS,
        )
        try:
            decision = self.parse_decision(model_output)
        except ValueError as error:
            self.logger.error(LOGGER_ERROR_FORMAT, DECISION_REASON_INVALID_JSON, error)
            return self._failure_result(event, DECISION_REASON_INVALID_JSON)

        adr_path = self.write_adr(decision)
        self._log_decision(event, DECISION_SUCCESS, DECISION_REASON_WRITTEN)
        return AgentResult(
            success=True,
            output=self._output(decision, adr_path),
            escalate=decision.confidence == CONFIDENCE_LOW,
            escalation_reason=(
                ESCALATION_REASON_LOW_CONFIDENCE
                if decision.confidence == CONFIDENCE_LOW
                else None
            ),
        )

    def parse_decision(self, model_output: str) -> ArchitectureDecision:
        """Parse model JSON output into an ArchitectureDecision."""
        try:
            parsed_output = json.loads(model_output)
        except json.JSONDecodeError as error:
            raise ValueError(str(error)) from error

        if not isinstance(parsed_output, Mapping):
            raise ValueError(DECISION_REASON_INVALID_JSON)

        confidence = self._required_string(parsed_output, MODEL_KEY_CONFIDENCE).upper()
        if confidence not in VALID_CONFIDENCE:
            raise ValueError(DECISION_REASON_INVALID_JSON)

        return ArchitectureDecision(
            decision_required=self._required_string(
                parsed_output,
                MODEL_KEY_DECISION_REQUIRED,
            ),
            risks=self._string_list(parsed_output.get(MODEL_KEY_RISKS)),
            alternatives=self._alternatives(parsed_output.get(MODEL_KEY_ALTERNATIVES)),
            recommendation=self._required_string(
                parsed_output,
                MODEL_KEY_RECOMMENDATION,
            ),
            adr_content=self._required_string(parsed_output, MODEL_KEY_ADR_CONTENT),
            confidence=confidence,
        )

    def write_adr(self, decision: ArchitectureDecision) -> Path:
        """Write the decision ADR markdown and return the created path."""
        adr_path = self._next_adr_path(decision.decision_required)
        content = decision.adr_content.rstrip() + NEWLINE
        _write_atomically(adr_path, content)
        return adr_path

    def _build_prompt(self, payload: Mapping[str, Any], question: str) -> str:
        """Build the model prompt from question, context, and components."""
        context_text = self._value_to_text(payload.get(PAYLOAD_KEY_CONTEXT))
        components = self._string_list(payload.get(PAYLOAD_KEY_AFFECTED_COMPONENTS))
        components_text = NEWLINE.join(components) if components else EMPTY_TEXT
        return PROMPT_SECTION_SEPARATOR.join(
            [
                f"{PROMPT_QUESTION_LABEL}\n{question}",
                f"{PROMPT_CONTEXT_LABEL}\n{context_text}",
                f"{PROMPT_AFFECTED_COMPONENTS_LABEL}\n{components_text}",
                PROMPT_INSTRUCTION,
            ]
        )

    def _value_to_text(self, value: Any) -> str:
        """Convert payload context into deterministic prompt text."""
        if value is None:
            return EMPTY_TEXT
        if isinstance(value, str):
            return value.strip()
        try:
            return json.dumps(value, sort_keys=True)
        except TypeError:
            return str(value)

    def _alternatives(self, value: Any) -> List[ArchitectureAlternative]:
        """Return validated architecture alternatives."""
        if not isinstance(value, list):
            raise ValueError(DECISION_REASON_INVALID_JSON)
        alternatives = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ValueError(DECISION_REASON_INVALID_JSON)
            alternatives.append(
                ArchitectureAlternative(
                    name=self._required_string(item, MODEL_KEY_NAME),
                    pros=self._string_list(item.get(MODEL_KEY_PROS)),
                    cons=self._string_list(item.get(MODEL_KEY_CONS)),
                )
            )
        return alternatives

    def _string_list(self, value: Any) -> List[str]:
        """Return a list of non-empty strings from a model or payload value."""
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if not isinstance(value, Sequence):
            return []
        return [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]

    def _required_string(self, item: Mapping[str, Any], key: str) -> str:
        """Return a required non-empty string field from a mapping."""
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(DECISION_REASON_INVALID_JSON)
        return value.strip()

    def _next_adr_path(self, decision_required: str) -> Path:
        """Return the next ADR path for a decision title."""
        adr_dir = self.project_root / ADR_DIR
        next_number = self._next_adr_number(adr_dir)
        slug = self._slug(decision_required)
        return adr_dir / (
            f"{ADR_FILE_PREFIX}{str(next_number).zfill(ADR_SEQUENCE_WIDTH)}"
            f"-{slug}{ADR_EXTENSION}"
        )

    def _next_adr_number(self, adr_dir: Path) -> int:
        """Return the next ADR sequence number for the ADR directory."""
        highest_number = 0
        if not adr_dir.exists():
            return 1
        for adr_path in adr_dir.glob(f"{ADR_FILE_PREFIX}*{ADR_EXTENSION}"):
            parts = adr_path.stem.split("-", 2)
            if len(parts) < 2 or not parts[1].isdigit():
                continue
            highest_number = max(highest_number, int(parts[1]))
        return highest_number + 1

    def _slug(self, value: str) -> str:
        """Return a filesystem-safe slug for an ADR filename."""
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        if not slug:
            return DEFAULT_SLUG
        return slug[:MAX_SLUG_LENGTH].strip("-") or DEFAULT_SLUG

    def _output(
        self,
        decision: ArchitectureDecision,
        adr_path: Path,
    ) -> Mapping[str, Any]:
        """Return the public result payload for a handled decision."""
        return {
            OUTPUT_KEY_DECISION_REQUIRED: decision.decision_required,
            OUTPUT_KEY_RISKS: decision.risks,
            OUTPUT_KEY_ALTERNATIVES: [
                asdict(alternative) for alternative in decision.alternatives
            ],
            OUTPUT_KEY_RECOMMENDATION: decision.recommendation,
            OUTPUT_KEY_CONFIDENCE: decision.confidence,
            OUTPUT_KEY_ADR_PATH: str(adr_path),
        }

    def _failure_result(self, event: AgentEvent, reason: str) -> AgentResult:
        """Log and return a non-crashing failure result."""
        self._log_decision(event, DECISION_FAILURE, reason)
        return AgentResult(success=False, output={OUTPUT_KEY_ERROR: reason})

    def _log_decision(self, event: AgentEvent, outcome: str, reasoning: str) -> None:
        """Append one ArchitectureAgent decision to decisions.log."""
        decision_line = (
            f"{DECISION_LOG_PREFIX}{_utc_timestamp()}{DECISION_LOG_SEPARATOR}"
            f"{event.event_id}{DECISION_LOG_SEPARATOR}"
            f"{outcome}{DECISION_LOG_SEPARATOR}"
            f"{reasoning}{DECISION_LOG_SUFFIX}"
        )
        _append_atomically(self.project_root / DECISIONS_LOG_NAME, decision_line)
        self.log_decision(reasoning, outcome)


__all__ = ["ArchitectureAgent", "ArchitectureAlternative", "ArchitectureDecision"]
