"""Code Writing Agent implementation for ProjectOS."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Optional, TYPE_CHECKING

from core.base_agent import BaseAgent
from core.evaluation.static_analyzer import StaticAnalysisReport, StaticAnalyzer
from core.events import AgentEvent, AgentResult, EventType
from core.intelligence.collaboration import ConsultationType
from core.model_provider import ModelProvider
from core.observability.tracer import Tracer, SpanStatus

from core.safety import SafetyPolicy, SafetyResult

if TYPE_CHECKING:
    from core.intelligence.collaboration import CollaborationBroker
    from core.intelligence.context_retriever import ContextRetriever
    from core.intelligence.memory_manager import MemoryManager


AGENT_NAME = "code_writing"
ROLE_DESCRIPTION = "Python code implementation agent."
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]

ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

DECISIONS_LOG_NAME = "decisions.log"
MODEL_MAX_TOKENS = 8192

SYSTEM_PROMPT = (
    "You are a senior Python software engineer with strong principles.\n"
    "You write clean, well-structured, documented Python code.\n"
    "You follow these rules strictly:\n"
    "- Every function has a docstring\n"
    "- Every function has type hints\n"
    "- No hardcoded values - use config or environment\n"
    "- Write the simplest code that satisfies requirements\n"
    "- Output ONLY the code block, no explanation, no markdown fences"
)
CONTEXT_SYSTEM_PROMPT_TEMPLATE = (
    "{system_prompt}\n\n"
    "You have access to relevant codebase context:\n{context}"
)

PAYLOAD_KEY_ACCEPTANCE_CRITERIA = "acceptance_criteria"
PAYLOAD_KEY_AFFECTED_FILES = "affected_files"
PAYLOAD_KEY_EXISTING_CODE = "existing_code"
PAYLOAD_KEY_FILE_PATH = "file_path"
PAYLOAD_KEY_LINE_COUNT = "line_count"
PAYLOAD_KEY_ESTIMATED_COMPLEXITY = "estimated_complexity"
PAYLOAD_KEY_TASK_DESCRIPTION = "task_description"
PAYLOAD_KEY_TASK_ID = "task_id"

PROMPT_TASK_ID_LABEL = "Task ID:"
PROMPT_TASK_DESCRIPTION_LABEL = "Task description:"
PROMPT_ACCEPTANCE_LABEL = "Acceptance criteria:"
PROMPT_EXISTING_CODE_LABEL = "Existing code:"
PROMPT_ARCHITECTURE_GUIDANCE_LABEL = "Architecture guidance for this implementation:"
PROMPT_INSTRUCTION = "Return only the complete Python file content."
PROMPT_LIST_PREFIX = "- "
PROMPT_SECTION_SEPARATOR = "\n\n"
COMPLEX_TASK_KEYWORDS = (
    "auth",
    "security",
    "database",
    "migration",
    "architecture",
)
COMPLEX_TASK_COMPLEXITIES = frozenset({"L", "XL"})
TARGET_ARCHITECTURE_AGENT = "architecture"

DECISION_LOG_PREFIX = "["
DECISION_LOG_SEPARATOR = "] ["
DECISION_LOG_SUFFIX = "]\n"
DECISION_SUCCESS = "SUCCESS"
DECISION_FAILURE = "FAILURE"
DECISION_DIFF_PREVIEW = "DIFF_PREVIEW"
DECISION_WARNING = "WARNING"
DECISION_REASON_MISSING_PAYLOAD = "code writing event missing required payload"
DECISION_REASON_WRITTEN_TEMPLATE = "Wrote {line_count} lines to {file_path} for task {task_id}"
DECISION_REASON_SAFETY_BLOCKED_TEMPLATE = "safety policy blocked write to {file_path}: {reason}"
DECISION_REASON_SAFETY_WARNING_TEMPLATE = "safety policy warnings for {file_path}: {warnings}"
DECISION_REASON_STATIC_WARNING_TEMPLATE = (
    "static quality gate failed for {file_path}: {summary}"
)
DECISION_REASON_STATIC_FAILED_TEMPLATE = "static analysis failed for {file_path}: {error}"

OUTPUT_KEY_ERROR = "error"
OUTPUT_KEY_FILE_PATH = "file_path"
OUTPUT_KEY_LINE_COUNT = "line_count"
METADATA_KEY_STATIC_REPORT = "static_report"

MARKDOWN_FENCE = "```"
PYTHON_FENCE = "```python"
CODE_FENCE = "```code"
STATE_DIR_NAME = ".projectos_state"
STATIC_REPORTS_DIR_NAME = "static_analysis"
STATIC_REPORT_EXTENSION = ".json"
SAFE_FILENAME_REPLACEMENT = "_"


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""
    from datetime import datetime, timezone

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


class CodeWritingAgent(BaseAgent):
    """Agent that writes Python code from structured task events."""

    def __init__(
        self,
        model_provider: ModelProvider,
        logger: logging.Logger,
        project_root: Path | str = DEFAULT_PROJECT_ROOT,
        safety_policy: Optional[SafetyPolicy] = None,
        static_analyzer: Optional[StaticAnalyzer] = None,
        context_retriever: Optional["ContextRetriever"] = None,
        memory_manager: Optional["MemoryManager"] = None,
        collaboration_broker: Optional["CollaborationBroker"] = None,
        tracer: Optional[Tracer] = None,
    ) -> None:
        """Initialize CodeWritingAgent with model access and project paths."""
        super().__init__(
            AGENT_NAME,
            ROLE_DESCRIPTION,
            model_provider,
            logger,
            context_retriever=context_retriever,
            memory_manager=memory_manager,
            collaboration_broker=collaboration_broker,
        )
        self.project_root = Path(project_root)
        self.safety_policy = safety_policy
        self.static_analyzer = static_analyzer
        self.tracer = tracer

    def handle(self, event: AgentEvent) -> AgentResult:
        """Write code for an incoming task event and emit CODE_WRITTEN."""
        file_path_value = event.payload.get(PAYLOAD_KEY_FILE_PATH)
        span = self.tracer.start_span("code_writing.handle", component="code_writing",
            tags={"file_path": str(file_path_value) if file_path_value else "", "agent": self.name}) if self.tracer else None
        try:
            self.update_consultation_depth(event)
            payload_error = self._validate_payload(event.payload)
            if payload_error:
                res = self._failure_result(event, payload_error)
                if span:
                    span.finish(SpanStatus.OK)
                return res

            task_id = str(event.payload[PAYLOAD_KEY_TASK_ID])
            file_path = self._resolve_path(str(event.payload[PAYLOAD_KEY_FILE_PATH]))
            if span:
                span.tags["file_path"] = str(file_path)

            existing_code = self._existing_code(file_path, event.payload)
            architecture_guidance = self._architecture_guidance(
                event.payload,
                existing_code,
            )
            prompt = self._build_prompt(
                event.payload,
                existing_code,
                architecture_guidance,
            )
            context = self.get_context(
                task_description=str(event.payload.get(PAYLOAD_KEY_TASK_DESCRIPTION, EMPTY_TEXT)),
                file_path=str(file_path),
            )
            model_output = self.model_provider.complete(
                prompt,
                self._system_prompt(context),
                MODEL_MAX_TOKENS,
            )
            code = self._normalize_model_code(model_output)
            safety_result = self._validate_safe_write(event, file_path, code)
            if safety_result is not None and safety_result.diff_preview:
                self._log_decision(event, DECISION_DIFF_PREVIEW, safety_result.diff_preview)
            if safety_result is not None and not safety_result.allowed:
                res = self._safety_failure_result(event, file_path, safety_result)
                if span:
                    span.finish(SpanStatus.OK)
                return res
            escalation_reason = self._safety_warning_reason(file_path, safety_result)
            _write_atomically(file_path, code)

            line_count = self._line_count(code)
            reasoning = DECISION_REASON_WRITTEN_TEMPLATE.format(
                line_count=line_count,
                file_path=str(file_path),
                task_id=task_id,
            )
            self._log_decision(event, DECISION_SUCCESS, reasoning)
            static_report = self._run_static_analysis(event, file_path)
            static_report_path = self._write_static_report(event, static_report)
            static_escalation_reason = self._static_escalation_reason(
                event,
                static_report,
            )
            if static_escalation_reason is not None:
                escalation_reason = static_escalation_reason
            metadata = {}
            if static_report_path is not None:
                metadata[METADATA_KEY_STATIC_REPORT] = str(static_report_path)
            res = AgentResult(
                success=True,
                output={
                    OUTPUT_KEY_FILE_PATH: str(file_path),
                    OUTPUT_KEY_LINE_COUNT: line_count,
                },
                next_events=[self._code_written_event(event, file_path, line_count)],
                escalate=bool(escalation_reason),
                escalation_reason=escalation_reason,
                metadata=metadata,
            )
            if span:
                span.finish(SpanStatus.OK)
            return res
        except Exception as e:
            if span:
                span.finish(SpanStatus.ERROR, error=str(e))
            raise

    def _run_static_analysis(
        self,
        event: AgentEvent,
        file_path: Path,
    ) -> Optional[StaticAnalysisReport]:
        """Analyze a written file when a static analyzer is configured."""
        if self.static_analyzer is None:
            return None
        try:
            return self.static_analyzer.analyze(file_path)
        except Exception as error:
            reason = DECISION_REASON_STATIC_FAILED_TEMPLATE.format(
                file_path=str(file_path),
                error=error,
            )
            self._log_decision(event, DECISION_WARNING, reason)
            self.logger.warning(reason)
            return None

    def _write_static_report(
        self,
        event: AgentEvent,
        report: Optional[StaticAnalysisReport],
    ) -> Optional[Path]:
        """Persist a static analysis report and return its path."""
        if report is None:
            return None
        report_path = self._static_report_path(event, Path(report.file_path))
        rendered_report = json.dumps(
            asdict(report),
            sort_keys=True,
            indent=2,
            default=str,
        )
        _write_atomically(report_path, f"{rendered_report}{NEWLINE}")
        return report_path

    def _static_escalation_reason(
        self,
        event: AgentEvent,
        report: Optional[StaticAnalysisReport],
    ) -> Optional[str]:
        """Log failed static gates and return an escalation reason when needed."""
        if report is None:
            return None
        if report.passed_quality_gate and report.security.high_severity_count == 0:
            return None
        reason = DECISION_REASON_STATIC_WARNING_TEMPLATE.format(
            file_path=report.file_path,
            summary=report.summary,
        )
        if not report.passed_quality_gate:
            self._log_decision(event, DECISION_WARNING, reason)
        if report.security.high_severity_count > 0:
            return reason
        return None

    def _static_report_path(self, event: AgentEvent, file_path: Path) -> Path:
        """Return the persisted static report path for one generated file."""
        safe_stem = self._safe_report_stem(file_path)
        report_name = f"{safe_stem}-{event.event_id}{STATIC_REPORT_EXTENSION}"
        return (
            self.project_root
            / STATE_DIR_NAME
            / STATIC_REPORTS_DIR_NAME
            / report_name
        )

    def _safe_report_stem(self, file_path: Path) -> str:
        """Return a filesystem-safe report stem for a source path."""
        relative_path = self._relative_report_path(file_path)
        characters = [
            character if character.isalnum() else SAFE_FILENAME_REPLACEMENT
            for character in str(relative_path)
        ]
        return EMPTY_TEXT.join(characters).strip(SAFE_FILENAME_REPLACEMENT)

    def _relative_report_path(self, file_path: Path) -> Path:
        """Return file path relative to project root when possible."""
        try:
            return file_path.resolve().relative_to(self.project_root.resolve())
        except ValueError:
            return Path(file_path.name)

    def _validate_safe_write(
        self,
        event: AgentEvent,
        file_path: Path,
        code: str,
    ) -> Optional[SafetyResult]:
        """Return safety validation result when a policy is configured."""
        if self.safety_policy is None:
            return None
        result = self.safety_policy.validate_write(file_path, code)
        for warning in result.warnings:
            self.logger.warning(warning)
        return result

    def _safety_failure_result(
        self,
        event: AgentEvent,
        file_path: Path,
        safety_result: SafetyResult,
    ) -> AgentResult:
        """Log and return a failure result for blocked writes."""
        reason = DECISION_REASON_SAFETY_BLOCKED_TEMPLATE.format(
            file_path=str(file_path),
            reason=safety_result.reason,
        )
        self.logger.error(reason)
        return self._failure_result(event, reason)

    def _safety_warning_reason(
        self,
        file_path: Path,
        safety_result: Optional[SafetyResult],
    ) -> Optional[str]:
        """Return escalation reason for non-blocking safety warnings."""
        if safety_result is None or not safety_result.warnings:
            return None
        return DECISION_REASON_SAFETY_WARNING_TEMPLATE.format(
            file_path=str(file_path),
            warnings=", ".join(safety_result.warnings),
        )

    def _validate_payload(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Return an error reason when required payload fields are missing."""
        required_keys = (
            PAYLOAD_KEY_TASK_ID,
            PAYLOAD_KEY_FILE_PATH,
            PAYLOAD_KEY_TASK_DESCRIPTION,
            PAYLOAD_KEY_ACCEPTANCE_CRITERIA,
        )
        for required_key in required_keys:
            if required_key not in payload:
                return DECISION_REASON_MISSING_PAYLOAD
        if not isinstance(payload.get(PAYLOAD_KEY_FILE_PATH), str):
            return DECISION_REASON_MISSING_PAYLOAD
        if not isinstance(payload.get(PAYLOAD_KEY_TASK_DESCRIPTION), str):
            return DECISION_REASON_MISSING_PAYLOAD
        return None

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve a payload file path against the project root."""
        candidate_path = Path(file_path)
        if candidate_path.is_absolute():
            return candidate_path
        return self.project_root / candidate_path

    def _existing_code(self, file_path: Path, payload: Mapping[str, Any]) -> str:
        """Read existing file content before overwriting when present."""
        if file_path.exists():
            return file_path.read_text(encoding=ENCODING)
        existing_code = payload.get(PAYLOAD_KEY_EXISTING_CODE)
        if isinstance(existing_code, str):
            return existing_code
        return EMPTY_TEXT

    def _build_prompt(
        self,
        payload: Mapping[str, Any],
        existing_code: str,
        architecture_guidance: Optional[str] = None,
    ) -> str:
        """Build a code-generation prompt from task payload fields."""
        task_id = str(payload[PAYLOAD_KEY_TASK_ID])
        description = str(payload[PAYLOAD_KEY_TASK_DESCRIPTION]).strip()
        criteria = self._criteria_lines(payload.get(PAYLOAD_KEY_ACCEPTANCE_CRITERIA))
        prompt_parts = [
            f"{PROMPT_TASK_ID_LABEL} {task_id}",
            f"{PROMPT_TASK_DESCRIPTION_LABEL}\n{description}",
            f"{PROMPT_ACCEPTANCE_LABEL}\n{criteria}",
            f"{PROMPT_EXISTING_CODE_LABEL}\n{existing_code}",
        ]
        if architecture_guidance:
            prompt_parts.append(
                f"{PROMPT_ARCHITECTURE_GUIDANCE_LABEL}\n{architecture_guidance}"
            )
        prompt_parts.append(PROMPT_INSTRUCTION)
        return PROMPT_SECTION_SEPARATOR.join(prompt_parts)

    def _architecture_guidance(
        self,
        payload: Mapping[str, Any],
        existing_code: str,
    ) -> Optional[str]:
        """Return architecture guidance for complex implementation tasks."""
        task_description = str(payload.get(PAYLOAD_KEY_TASK_DESCRIPTION, EMPTY_TEXT))
        if not self._is_complex_task(payload, task_description):
            return None
        return self.consult(
            target_agent=TARGET_ARCHITECTURE_AGENT,
            question=f"Is this implementation approach appropriate? {task_description}",
            context=existing_code or EMPTY_TEXT,
            consultation_type=ConsultationType.ARCHITECTURE_REVIEW,
        )

    def _is_complex_task(
        self,
        payload: Mapping[str, Any],
        task_description: str,
    ) -> bool:
        """Return True when the implementation should request architecture review."""
        normalized_description = task_description.lower()
        if any(keyword in normalized_description for keyword in COMPLEX_TASK_KEYWORDS):
            return True
        estimated_complexity = payload.get(PAYLOAD_KEY_ESTIMATED_COMPLEXITY)
        if not isinstance(estimated_complexity, str):
            return False
        return estimated_complexity.strip().upper() in COMPLEX_TASK_COMPLEXITIES

    def _system_prompt(self, context: Optional[str]) -> str:
        """Return the writing system prompt with optional codebase context."""
        if not context:
            return SYSTEM_PROMPT
        return CONTEXT_SYSTEM_PROMPT_TEMPLATE.format(
            system_prompt=SYSTEM_PROMPT,
            context=context,
        )

    def _criteria_lines(self, value: Any) -> str:
        """Render acceptance criteria for the model prompt."""
        if isinstance(value, list):
            lines = [
                f"{PROMPT_LIST_PREFIX}{item}"
                for item in value
                if isinstance(item, str) and item.strip()
            ]
            return NEWLINE.join(lines)
        if isinstance(value, str):
            return value.strip()
        return EMPTY_TEXT

    def _normalize_model_code(self, model_output: str) -> str:
        """Return model code content with accidental fences removed."""
        stripped_output = model_output.strip()
        lowered_output = stripped_output.lower()
        if lowered_output.startswith(PYTHON_FENCE) or lowered_output.startswith(
            CODE_FENCE
        ):
            stripped_output = stripped_output.split(NEWLINE, 1)[1]
        elif stripped_output.startswith(MARKDOWN_FENCE):
            stripped_output = stripped_output[len(MARKDOWN_FENCE) :]
        if stripped_output.endswith(MARKDOWN_FENCE):
            stripped_output = stripped_output[: -len(MARKDOWN_FENCE)]
        return stripped_output.strip() + NEWLINE

    def _line_count(self, code: str) -> int:
        """Return the number of lines in generated code."""
        return len(code.splitlines())

    def _code_written_event(
        self,
        parent_event: AgentEvent,
        file_path: Path,
        line_count: int,
    ) -> AgentEvent:
        """Create a CODE_WRITTEN event for the generated file."""
        payload = dict(parent_event.payload)
        payload[PAYLOAD_KEY_FILE_PATH] = str(file_path)
        payload[PAYLOAD_KEY_AFFECTED_FILES] = [str(file_path)]
        payload[PAYLOAD_KEY_LINE_COUNT] = line_count
        return AgentEvent(
            event_type=EventType.CODE_WRITTEN,
            source_agent=self.name,
            payload=payload,
            correlation_id=parent_event.correlation_id or parent_event.event_id,
            priority=parent_event.priority,
        )

    def _failure_result(self, event: AgentEvent, reason: str) -> AgentResult:
        """Log and return a non-crashing failure result."""
        self._log_decision(event, DECISION_FAILURE, reason)
        return AgentResult(success=False, output={OUTPUT_KEY_ERROR: reason})

    def _log_decision(self, event: AgentEvent, outcome: str, reasoning: str) -> None:
        """Append one CodeWritingAgent decision to decisions.log."""
        decision_line = (
            f"{DECISION_LOG_PREFIX}{_utc_timestamp()}{DECISION_LOG_SEPARATOR}"
            f"{event.event_id}{DECISION_LOG_SEPARATOR}"
            f"{outcome}{DECISION_LOG_SEPARATOR}"
            f"{reasoning}{DECISION_LOG_SUFFIX}"
        )
        _append_atomically(self.project_root / DECISIONS_LOG_NAME, decision_line)
        self.log_decision(reasoning, outcome)


__all__ = ["CodeWritingAgent"]
