"""Code Review Agent implementation for ProjectOS."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, TYPE_CHECKING

from core.base_agent import BaseAgent
from core.project_context import ProjectContextLoader
from core.events import AgentEvent, AgentResult, EventType
from core.git_manager import GitManager
from core.model_provider import ModelProvider
from core.observability.tracer import Tracer, SpanStatus


if TYPE_CHECKING:
    from core.intelligence.collaboration import CollaborationBroker
    from core.intelligence.context_retriever import ContextRetriever
    from core.intelligence.memory_manager import MemoryManager


AGENT_NAME = "code_review"
ROLE_DESCRIPTION = "Strict Python code review agent."
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]

ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
SPACE = " "
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

BACKLOG_FILE_NAME = "backlog.md"
DECISIONS_LOG_NAME = "decisions.log"
REVIEWS_DIR_NAME = "reviews"
GITKEEP_FILE_NAME = ".gitkeep"
MODEL_MAX_TOKENS = 8192

# Global SYSTEM_PROMPT removed (defined as class attribute instead)
CONTEXT_SYSTEM_PROMPT_TEMPLATE = (
    "{system_prompt}\n\n"
    "You have access to relevant codebase context:\n{context}"
)
MEMORY_SYSTEM_PROMPT_TEMPLATE = (
    "{system_prompt}\n\n"
    "You have reviewed similar code before:\n{memories}"
)

PAYLOAD_KEY_FILE_PATH = "file_path"
PAYLOAD_KEY_TASK_ID = "task_id"
PAYLOAD_KEY_TASK_DESCRIPTION = "task_description"
PAYLOAD_KEY_AFFECTED_FILES = "affected_files"
PAYLOAD_KEY_REVIEW_REPORT = "review_report"
PAYLOAD_KEY_ISSUES = "issues"
PAYLOAD_KEY_TOTAL_ISSUES = "total_issues"
PAYLOAD_KEY_CRITICAL_COUNT = "critical_count"

MODEL_KEY_SEVERITY = "severity"
MODEL_KEY_CATEGORY = "category"
MODEL_KEY_LINE_NUMBER = "line_number"
MODEL_KEY_DESCRIPTION = "description"
MODEL_KEY_SUGGESTED_FIX = "suggested_fix"

PROMPT_FILE_PATH_LABEL = "File path:"
PROMPT_TASK_ID_LABEL = "Task ID:"
PROMPT_CODE_LABEL = "Code:"
PROMPT_SECTION_SEPARATOR = "\n\n"

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
SEVERITIES = (SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW)
VALID_SEVERITIES = frozenset(SEVERITIES)

CATEGORY_SECURITY = "security"
CATEGORY_LOGIC = "logic"
CATEGORY_PERFORMANCE = "performance"
CATEGORY_STYLE = "style"
CATEGORY_TEST_COVERAGE = "test_coverage"
CATEGORY_DOCS = "docs"
DEFAULT_CATEGORY = CATEGORY_LOGIC
VALID_CATEGORIES = frozenset(
    {
        CATEGORY_SECURITY,
        CATEGORY_LOGIC,
        CATEGORY_PERFORMANCE,
        CATEGORY_STYLE,
        CATEGORY_TEST_COVERAGE,
        CATEGORY_DOCS,
    }
)

REPORT_TITLE_TEMPLATE = "# Code Review: {filename}"
REPORT_TIMESTAMP_LABEL = "Timestamp:"
REPORT_TASK_LABEL = "Task:"
REPORT_MODEL_LABEL = "Model:"
REPORT_ISSUES_HEADING_TEMPLATE = "## {severity} Issues"
REPORT_SUMMARY_HEADING = "## Summary"
REPORT_TOTAL_TEMPLATE = "Total issues: {total} | Blockers: {blockers}"
REPORT_NO_ISSUES = "- None"
REPORT_LINE_TEMPLATE = "- Line {line_number}: [{category}] {description}"
REPORT_NO_LINE_TEMPLATE = "- [line unknown]: [{category}] {description}"
REPORT_FIX_TEMPLATE = "  Suggested fix: {suggested_fix}"
REPORT_FILE_SUFFIX = "_review.md"
REPORT_TIMESTAMP_SEPARATOR = "_"
REPORT_SAFE_COLON = "-"
REPORT_SAFE_DOT = "-"
TASK_ID_NOT_AVAILABLE = "N/A"
MODEL_NAME_UNKNOWN = "unknown"

DECISION_LOG_PREFIX = "["
DECISION_LOG_SEPARATOR = "] ["
DECISION_LOG_SUFFIX = "]\n"
DECISION_SUCCESS = "SUCCESS"
DECISION_FAILURE = "FAILURE"
DECISION_REASON_REVIEWED_TEMPLATE = (
    "Reviewed {file_path}; total issues {total_issues}; blockers {blockers}"
)
DECISION_REASON_MISSING_PAYLOAD = "code review event missing required payload"
DECISION_REASON_FILE_NOT_FOUND = "code review target file not found"
DECISION_REASON_INVALID_JSON = "model returned invalid review JSON"
DECISION_REASON_UNSUPPORTED_EVENT = "code review received unsupported event type"
DECISION_REASON_COMMIT_SKIPPED_CRITICAL = "commit skipped: critical issues found"
DECISION_REASON_COMMIT_CREATED_TEMPLATE = "auto-commit created for {file_path}: {commit_hash}"
DECISION_REASON_COMMIT_SKIPPED_TEMPLATE = "auto-commit skipped for {file_path}"
ESCALATION_REASON_CRITICAL = "critical code review issues found"
LOGGER_ERROR_FORMAT = "%s: %s"
COMMIT_MESSAGE_TEMPLATE = "projectos: auto-review passed \u2014 {filename} {summary}"
COMMIT_SUMMARY_TEMPLATE = "issues-{total_issues}-blockers-{blockers}"

OUTPUT_KEY_ERROR = "error"
OUTPUT_KEY_ISSUES = "issues"
OUTPUT_KEY_REPORT_PATH = "report_path"

BACKLOG_TASK_HEADING_PREFIX = "### ["
BACKLOG_TASK_HEADING_SUFFIX = "]"
BACKLOG_STATUS_PREFIX = "- Status:"
BACKLOG_STATUS_DONE = "DONE"
BACKLOG_STATUS_BLOCKED = "BLOCKED"


@dataclass
class ReviewIssue:
    """Structured issue returned by the Code Review Agent."""

    severity: str
    category: str
    line_number: Optional[int]
    description: str
    suggested_fix: str


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _safe_timestamp() -> str:
    """Return a filesystem-safe UTC timestamp."""
    return (
        _utc_timestamp()
        .replace(":", REPORT_SAFE_COLON)
        .replace(".", REPORT_SAFE_DOT)
    )


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


def _write_new_file_atomically(path: Path, content: str) -> None:
    """Write a new immutable file and fail if the destination exists."""
    if path.exists():
        raise FileExistsError(str(path))
    _write_atomically(path, content)


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file while preserving existing content."""
    existing_content = path.read_text(encoding=ENCODING) if path.exists() else EMPTY_TEXT
    _write_atomically(path, f"{existing_content}{content}")


class CodeReviewAgent(BaseAgent):
    """Agent that reviews code and emits REVIEW_DONE events."""

    SYSTEM_PROMPT = """You are a principal engineer doing code review.
You are strict, specific, and direct.

ALWAYS:
- Reference exact line numbers for every issue
- Provide a specific fix for every issue you raise
- Categorize severity: CRITICAL / HIGH / MEDIUM / LOW
- Review specifically for the project's tech stack

NEVER:
- Raise issues without suggested fixes
- Flag style issues as CRITICAL or HIGH
- Praise — only issues
- Review code outside the specified file

Output: JSON array only. Empty array if no issues.
[{"severity": "HIGH", "line": 42, "issue": "...", "fix": "..."}]
{project_context}"""

    def __init__(
        self,
        model_provider: ModelProvider,
        logger: logging.Logger,
        project_root: Path | str = DEFAULT_PROJECT_ROOT,
        git_manager: Optional[GitManager] = None,
        context_retriever: Optional["ContextRetriever"] = None,
        memory_manager: Optional["MemoryManager"] = None,
        collaboration_broker: Optional["CollaborationBroker"] = None,
        tracer: Optional[Tracer] = None,
        context_loader: Optional[ProjectContextLoader] = None,
    ) -> None:
        """Initialize CodeReviewAgent with model access and review paths."""
        super().__init__(
            AGENT_NAME,
            ROLE_DESCRIPTION,
            model_provider,
            logger,
            context_retriever=context_retriever,
            memory_manager=memory_manager,
            collaboration_broker=collaboration_broker,
            context_loader=context_loader,
        )
        self.project_root = Path(project_root)
        self.git_manager = git_manager
        self.tracer = tracer
        self._ensure_reviews_dir()

    @property
    def token_budget(self) -> Optional[Any]:
        """Get the token budget manager from model provider."""
        return getattr(self.model_provider, "token_budget", None)

    def handle(self, event: AgentEvent) -> AgentResult:
        """Review a changed or written code file."""
        file_path_value = self._file_path_value(event.payload)
        span = self.tracer.start_span("code_review.handle", component="code_review",
            tags={"file_path": str(file_path_value) if file_path_value else "", "agent": self.name}) if self.tracer else None
        try:
            if event.event_type not in (EventType.CODE_WRITTEN, EventType.CODE_CHANGED):
                res = self._failure_result(event, DECISION_REASON_UNSUPPORTED_EVENT)
                if span:
                    span.finish(SpanStatus.OK)
                return res

            if not file_path_value:
                res = self._failure_result(event, DECISION_REASON_MISSING_PAYLOAD)
                if span:
                    span.finish(SpanStatus.OK)
                return res

            file_path = self._resolve_path(file_path_value)
            if span:
                span.tags["file_path"] = str(file_path)

            if not file_path.exists():
                res = self._failure_result(event, DECISION_REASON_FILE_NOT_FOUND)
                if span:
                    span.finish(SpanStatus.OK)
                return res

            code = file_path.read_text(encoding=ENCODING)
            task_id = self._task_id(event.payload)

            params = self.get_model_params()
            original_max_context_tokens = None
            if self.token_budget and self.token_budget.conservative_mode_active(self.name):
                self.logger.info(f"Conservative mode active for {self.name}")
                if self.context_retriever:
                    original_max_context_tokens = self.context_retriever.max_context_tokens
                    self.context_retriever.max_context_tokens = original_max_context_tokens // 2

            try:
                memories = self.recall_relevant(query=f"review {file_path}", k=3)
                context = self.get_context(
                    task_description=self._task_description(event.payload),
                    file_path=str(file_path),
                )
                prompt = self._build_prompt(file_path, task_id, code)
                system_prompt = self.build_system_prompt(self.SYSTEM_PROMPT)
                if context:
                    system_prompt = CONTEXT_SYSTEM_PROMPT_TEMPLATE.format(
                        system_prompt=system_prompt,
                        context=context,
                    )
                if memories:
                    system_prompt = MEMORY_SYSTEM_PROMPT_TEMPLATE.format(
                        system_prompt=system_prompt,
                        memories=memories,
                    )
                model_output = self.model_provider.complete(
                    prompt,
                    system_prompt,
                    params["max_tokens"],
                    temperature=params["temperature"],
                    top_p=params["top_p"],
                    agent_name=self.name,
                )
            finally:
                if original_max_context_tokens is not None and self.context_retriever:
                    self.context_retriever.max_context_tokens = original_max_context_tokens
            try:
                issues = self.parse_issues(model_output)
            except ValueError as error:
                self.logger.error(LOGGER_ERROR_FORMAT, DECISION_REASON_INVALID_JSON, error)
                res = self._failure_result(event, DECISION_REASON_INVALID_JSON)
                if span:
                    span.finish(SpanStatus.OK)
                return res

            blocker_count = self._blocker_count(issues)
            report_path = self._write_review_report(file_path, task_id, issues)
            if task_id:
                self._update_backlog_task_status(
                    task_id,
                    BACKLOG_STATUS_BLOCKED if blocker_count else BACKLOG_STATUS_DONE,
                )
            reasoning = DECISION_REASON_REVIEWED_TEMPLATE.format(
                file_path=str(file_path),
                total_issues=len(issues),
                blockers=blocker_count,
            )
            self._auto_commit_reviewed_file(file_path, len(issues), blocker_count)
            self._log_decision(event, DECISION_SUCCESS, reasoning)
            self.remember(
                decision=f"Reviewed {file_path}",
                context=f"File: {file_path}",
                outcome=f"Found {len(issues)} issues",
                quality_score=None,
            )
            res = AgentResult(
                success=True,
                output={
                    OUTPUT_KEY_ISSUES: [asdict(issue) for issue in issues],
                    OUTPUT_KEY_REPORT_PATH: str(report_path),
                },
                next_events=[
                    self._review_done_event(event, file_path, task_id, issues, report_path)
                ],
                escalate=bool(blocker_count),
                escalation_reason=ESCALATION_REASON_CRITICAL if blocker_count else None,
            )
            if span:
                span.finish(SpanStatus.OK)
            return res
        except Exception as e:
            if span:
                span.finish(SpanStatus.ERROR, error=str(e))
            raise

    def parse_issues(self, model_output: str) -> List[ReviewIssue]:
        """Parse model JSON output into review issues."""
        try:
            parsed_output = json.loads(model_output)
        except json.JSONDecodeError as error:
            raise ValueError(str(error)) from error
        if not isinstance(parsed_output, list):
            raise ValueError(DECISION_REASON_INVALID_JSON)
        return [self._issue_from_item(item) for item in parsed_output]

    def _issue_from_item(self, item: Any) -> ReviewIssue:
        """Convert one parsed issue mapping into a ReviewIssue."""
        if not isinstance(item, Mapping):
            raise ValueError(DECISION_REASON_INVALID_JSON)
        return ReviewIssue(
            severity=self._severity(item.get(MODEL_KEY_SEVERITY)),
            category=self._category(item.get(MODEL_KEY_CATEGORY)),
            line_number=self._line_number(item.get(MODEL_KEY_LINE_NUMBER)),
            description=self._required_string(item.get(MODEL_KEY_DESCRIPTION)),
            suggested_fix=self._required_string(item.get(MODEL_KEY_SUGGESTED_FIX)),
        )

    def _ensure_reviews_dir(self) -> None:
        """Create the reviews directory and .gitkeep file if absent."""
        self._reviews_dir.mkdir(parents=True, exist_ok=True)
        gitkeep_path = self._reviews_dir / GITKEEP_FILE_NAME
        if not gitkeep_path.exists():
            _write_atomically(gitkeep_path, EMPTY_TEXT)

    @property
    def _reviews_dir(self) -> Path:
        """Return the reviews directory path."""
        return self.project_root / REVIEWS_DIR_NAME

    @property
    def _backlog_path(self) -> Path:
        """Return the backlog path."""
        return self.project_root / BACKLOG_FILE_NAME

    def _file_path_value(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Return a review file path from payload metadata."""
        file_path = payload.get(PAYLOAD_KEY_FILE_PATH)
        if isinstance(file_path, str) and file_path:
            return file_path
        affected_files = payload.get(PAYLOAD_KEY_AFFECTED_FILES)
        if isinstance(affected_files, Sequence) and not isinstance(
            affected_files,
            str,
        ):
            for affected_file in affected_files:
                if isinstance(affected_file, str) and affected_file:
                    return affected_file
        return None

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve a payload file path against the project root."""
        candidate_path = Path(file_path)
        if candidate_path.is_absolute():
            return candidate_path
        return self.project_root / candidate_path

    def _task_id(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Return an optional task ID from event payload."""
        task_id = payload.get(PAYLOAD_KEY_TASK_ID)
        if isinstance(task_id, str) and task_id.strip():
            return task_id.strip()
        return None

    def _task_description(self, payload: Mapping[str, Any]) -> str:
        """Return task description text for codebase context retrieval."""
        task_description = payload.get(PAYLOAD_KEY_TASK_DESCRIPTION)
        if isinstance(task_description, str):
            return task_description.strip()
        task_id = self._task_id(payload)
        return task_id or EMPTY_TEXT


    def _build_prompt(
        self,
        file_path: Path,
        task_id: Optional[str],
        code: str,
    ) -> str:
        """Build a code-review prompt from file content."""
        return PROMPT_SECTION_SEPARATOR.join(
            [
                f"{PROMPT_FILE_PATH_LABEL} {file_path}",
                f"{PROMPT_TASK_ID_LABEL} {task_id or TASK_ID_NOT_AVAILABLE}",
                f"{PROMPT_CODE_LABEL}\n{code}",
            ]
        )

    def _severity(self, value: Any) -> str:
        """Normalize issue severity."""
        if isinstance(value, str) and value.strip().upper() in VALID_SEVERITIES:
            return value.strip().upper()
        return SEVERITY_MEDIUM

    def _category(self, value: Any) -> str:
        """Normalize issue category."""
        if isinstance(value, str) and value.strip().lower() in VALID_CATEGORIES:
            return value.strip().lower()
        return DEFAULT_CATEGORY

    def _line_number(self, value: Any) -> Optional[int]:
        """Normalize a line number value."""
        if value is None:
            return None
        if isinstance(value, int) and value > 0:
            return value
        return None

    def _required_string(self, value: Any) -> str:
        """Return a required non-empty issue string or raise ValueError."""
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError(DECISION_REASON_INVALID_JSON)

    def _blocker_count(self, issues: Sequence[ReviewIssue]) -> int:
        """Return the number of critical review issues."""
        return sum(1 for issue in issues if issue.severity == SEVERITY_CRITICAL)

    def _write_review_report(
        self,
        file_path: Path,
        task_id: Optional[str],
        issues: Sequence[ReviewIssue],
    ) -> Path:
        """Write an immutable markdown review report."""
        report_path = self._review_report_path(file_path)
        _write_new_file_atomically(
            report_path,
            self._render_report(file_path, task_id, issues),
        )
        return report_path

    def _review_report_path(self, file_path: Path) -> Path:
        """Return the next review report path for a file."""
        report_name = (
            f"{file_path.name}{REPORT_TIMESTAMP_SEPARATOR}{_safe_timestamp()}"
            f"{REPORT_FILE_SUFFIX}"
        )
        return self._reviews_dir / report_name

    def _render_report(
        self,
        file_path: Path,
        task_id: Optional[str],
        issues: Sequence[ReviewIssue],
    ) -> str:
        """Render review issues in the required markdown report format."""
        lines = [
            REPORT_TITLE_TEMPLATE.format(filename=file_path.name),
            f"{REPORT_TIMESTAMP_LABEL} {_utc_timestamp()}",
            f"{REPORT_TASK_LABEL} {task_id or TASK_ID_NOT_AVAILABLE}",
            f"{REPORT_MODEL_LABEL} {self._model_name()}",
            EMPTY_TEXT,
        ]
        for severity in SEVERITIES:
            lines.extend(self._render_severity_section(severity, issues))
        lines.extend(
            [
                REPORT_SUMMARY_HEADING,
                REPORT_TOTAL_TEMPLATE.format(
                    total=len(issues),
                    blockers=self._blocker_count(issues),
                ),
            ]
        )
        return NEWLINE.join(lines) + NEWLINE

    def _model_name(self) -> str:
        """Return the configured model name for the report."""
        model_name = self.model_provider.get_model_name()
        if isinstance(model_name, str) and model_name:
            return model_name
        return MODEL_NAME_UNKNOWN

    def _render_severity_section(
        self,
        severity: str,
        issues: Sequence[ReviewIssue],
    ) -> List[str]:
        """Render one severity section for the review report."""
        section_lines = [REPORT_ISSUES_HEADING_TEMPLATE.format(severity=severity)]
        severity_issues = [issue for issue in issues if issue.severity == severity]
        if not severity_issues:
            section_lines.extend([REPORT_NO_ISSUES, EMPTY_TEXT])
            return section_lines
        for issue in severity_issues:
            section_lines.extend(self._render_issue(issue))
        section_lines.append(EMPTY_TEXT)
        return section_lines

    def _render_issue(self, issue: ReviewIssue) -> List[str]:
        """Render one issue in markdown."""
        if issue.line_number is None:
            issue_line = REPORT_NO_LINE_TEMPLATE.format(
                category=issue.category,
                description=issue.description,
            )
        else:
            issue_line = REPORT_LINE_TEMPLATE.format(
                line_number=issue.line_number,
                category=issue.category,
                description=issue.description,
            )
        return [
            issue_line,
            REPORT_FIX_TEMPLATE.format(suggested_fix=issue.suggested_fix),
        ]

    def _review_done_event(
        self,
        parent_event: AgentEvent,
        file_path: Path,
        task_id: Optional[str],
        issues: Sequence[ReviewIssue],
        report_path: Path,
    ) -> AgentEvent:
        """Create a REVIEW_DONE event for completed code review."""
        critical_count = self._blocker_count(issues)
        payload = {
            PAYLOAD_KEY_FILE_PATH: str(file_path),
            PAYLOAD_KEY_TASK_ID: task_id,
            PAYLOAD_KEY_REVIEW_REPORT: str(report_path),
            PAYLOAD_KEY_ISSUES: [asdict(issue) for issue in issues],
            PAYLOAD_KEY_TOTAL_ISSUES: len(issues),
            PAYLOAD_KEY_CRITICAL_COUNT: critical_count,
        }
        return AgentEvent(
            event_type=EventType.REVIEW_DONE,
            source_agent=self.name,
            payload=payload,
            correlation_id=parent_event.correlation_id or parent_event.event_id,
            priority=parent_event.priority,
        )

    def _update_backlog_task_status(self, task_id: str, status: str) -> None:
        """Update a generated backlog task status when backlog.md exists."""
        if not self._backlog_path.exists():
            return
        lines = self._backlog_path.read_text(encoding=ENCODING).splitlines()
        updated_lines = self._updated_backlog_lines(lines, task_id, status)
        if updated_lines != lines:
            _write_atomically(self._backlog_path, NEWLINE.join(updated_lines) + NEWLINE)

    def _updated_backlog_lines(
        self,
        lines: Sequence[str],
        task_id: str,
        status: str,
    ) -> List[str]:
        """Return backlog lines with one task status replaced."""
        updated_lines = list(lines)
        target_heading = f"{BACKLOG_TASK_HEADING_PREFIX}{task_id}{BACKLOG_TASK_HEADING_SUFFIX}"
        inside_target_task = False
        for index, line in enumerate(updated_lines):
            if line.startswith(BACKLOG_TASK_HEADING_PREFIX):
                inside_target_task = target_heading in line
                continue
            if inside_target_task and line.startswith(BACKLOG_STATUS_PREFIX):
                updated_lines[index] = f"{BACKLOG_STATUS_PREFIX} {status}"
                return updated_lines
        return updated_lines

    def _auto_commit_reviewed_file(
        self,
        file_path: Path,
        total_issues: int,
        blocker_count: int,
    ) -> None:
        """Auto-commit a reviewed file when review has no critical blockers."""
        if blocker_count:
            self.logger.info(DECISION_REASON_COMMIT_SKIPPED_CRITICAL)
            return
        if self.git_manager is None:
            return

        staged = self.git_manager.stage_file(file_path)
        if not staged:
            self.logger.info(
                DECISION_REASON_COMMIT_SKIPPED_TEMPLATE.format(
                    file_path=str(file_path),
                )
            )
            return

        commit_hash = self.git_manager.commit(
            COMMIT_MESSAGE_TEMPLATE.format(
                filename=file_path.name,
                summary=COMMIT_SUMMARY_TEMPLATE.format(
                    total_issues=total_issues,
                    blockers=blocker_count,
                ),
            )
        )
        if commit_hash is None:
            self.logger.info(
                DECISION_REASON_COMMIT_SKIPPED_TEMPLATE.format(
                    file_path=str(file_path),
                )
            )
            return
        self.logger.info(
            DECISION_REASON_COMMIT_CREATED_TEMPLATE.format(
                file_path=str(file_path),
                commit_hash=commit_hash,
            )
        )

    def _failure_result(self, event: AgentEvent, reason: str) -> AgentResult:
        """Log and return a non-crashing failure result."""
        self._log_decision(event, DECISION_FAILURE, reason)
        return AgentResult(success=False, output={OUTPUT_KEY_ERROR: reason})

    def _log_decision(self, event: AgentEvent, outcome: str, reasoning: str) -> None:
        """Append one CodeReviewAgent decision to decisions.log."""
        decision_line = (
            f"{DECISION_LOG_PREFIX}{_utc_timestamp()}{DECISION_LOG_SEPARATOR}"
            f"{event.event_id}{DECISION_LOG_SEPARATOR}"
            f"{outcome}{DECISION_LOG_SEPARATOR}"
            f"{reasoning}{DECISION_LOG_SUFFIX}"
        )
        _append_atomically(self.project_root / DECISIONS_LOG_NAME, decision_line)
        self.log_decision(reasoning, outcome)


__all__ = ["CodeReviewAgent", "ReviewIssue"]
