"""Documentation Agent implementation for ProjectOS."""

from __future__ import annotations

import ast
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, TYPE_CHECKING

from core.base_agent import BaseAgent
from core.events import AgentEvent, AgentResult, EventType
from core.model_provider import ModelProvider

if TYPE_CHECKING:
    from core.intelligence.collaboration import CollaborationBroker
    from core.intelligence.memory_manager import MemoryManager


AGENT_NAME = "docs"
ROLE_DESCRIPTION = "Code and README documentation update agent."
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]

ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

DECISIONS_LOG_NAME = "decisions.log"
README_FILE_NAME = "README.md"
MODEL_MAX_TOKENS = 8192

SYSTEM_PROMPT = (
    "You are a technical writer and senior engineer.\n"
    "You update documentation to reflect code changes.\n"
    "Rules:\n"
    "- Never remove existing documentation\n"
    "- Add docstrings to any function missing them\n"
    "- Update README sections that reference changed code\n"
    "- Output ONLY the updated file content, no explanation"
)

PAYLOAD_KEY_ADDED_DOCSTRINGS = "added_docstrings"
PAYLOAD_KEY_FILE_PATH = "file_path"
PAYLOAD_KEY_README_SECTIONS = "readme_sections"
PAYLOAD_KEY_README_UPDATED = "readme_updated"
PAYLOAD_KEY_SOURCE_FILE = "source_file"
PAYLOAD_KEY_TASK_ID = "task_id"

PROMPT_FILE_PATH_LABEL = "File path:"
PROMPT_TASK_ID_LABEL = "Task ID:"
PROMPT_MISSING_DOCSTRINGS_LABEL = "Functions missing docstrings:"
PROMPT_SOURCE_LABEL = "Current source file:"
PROMPT_README_LABEL = "Current README:"
PROMPT_README_SECTIONS_LABEL = "README sections to update:"
PROMPT_INSTRUCTION = "Return only the complete updated file content."
PROMPT_SECTION_SEPARATOR = "\n\n"
PROMPT_LIST_SEPARATOR = ", "

DECISION_LOG_PREFIX = "["
DECISION_LOG_SEPARATOR = "] ["
DECISION_LOG_SUFFIX = "]\n"
DECISION_SUCCESS = "SUCCESS"
DECISION_FAILURE = "FAILURE"
DECISION_REASON_UPDATED_TEMPLATE = (
    "Updated docs for {file_path}, added {added_count} docstrings"
)
DECISION_REASON_MISSING_PAYLOAD = "docs agent event missing file_path"
DECISION_REASON_FILE_NOT_FOUND = "docs agent source file not found"
DECISION_REASON_UNSUPPORTED_EVENT = "docs agent received unsupported event type"
DECISION_REASON_REMOVED_EXISTING_DOCS = "model removed existing documentation"

OUTPUT_KEY_ADDED_DOCSTRINGS = "added_docstrings"
OUTPUT_KEY_ERROR = "error"
OUTPUT_KEY_FILE_PATH = "file_path"
OUTPUT_KEY_README_UPDATED = "readme_updated"

MARKDOWN_FENCE = "```"
PYTHON_FENCE = "```python"
CODE_FENCE = "```code"


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


class DocsAgent(BaseAgent):
    """Agent that updates source docstrings and related README content."""

    def __init__(
        self,
        model_provider: ModelProvider,
        logger: logging.Logger,
        project_root: Path | str = DEFAULT_PROJECT_ROOT,
        memory_manager: Optional["MemoryManager"] = None,
        collaboration_broker: Optional["CollaborationBroker"] = None,
    ) -> None:
        """Initialize DocsAgent with model access and project paths."""
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
        """Update documentation for supported events."""
        if event.event_type not in (
            EventType.TESTS_DONE,
            EventType.CODE_WRITTEN,
            EventType.DOCS_UPDATED,
        ):
            return self._failure_result(event, DECISION_REASON_UNSUPPORTED_EVENT)

        file_path_value = self._file_path_value(event.payload)
        if not file_path_value:
            return self._failure_result(event, DECISION_REASON_MISSING_PAYLOAD)

        source_path = self._resolve_path(file_path_value)
        if not source_path.exists():
            return self._failure_result(event, DECISION_REASON_FILE_NOT_FOUND)

        original_source = source_path.read_text(encoding=ENCODING)
        missing_before = self._missing_docstring_functions(original_source)
        existing_docstrings = self._existing_docstrings(original_source)
        prompt = self._build_source_prompt(event.payload, source_path, original_source, missing_before)
        model_output = self.model_provider.complete(
            prompt,
            SYSTEM_PROMPT,
            MODEL_MAX_TOKENS,
        )
        updated_source = self._normalize_model_content(model_output)
        if not self._preserves_existing_docstrings(updated_source, existing_docstrings):
            self.logger.error(DECISION_REASON_REMOVED_EXISTING_DOCS)
            updated_source = original_source
        _write_atomically(source_path, updated_source)

        missing_after = self._missing_docstring_functions(updated_source)
        added_count = max(len(missing_before) - len(missing_after), 0)
        readme_updated = self._update_readme_if_requested(event.payload, source_path)
        reasoning = DECISION_REASON_UPDATED_TEMPLATE.format(
            file_path=str(source_path),
            added_count=added_count,
        )
        self._log_decision(event, DECISION_SUCCESS, reasoning)
        return AgentResult(
            success=True,
            output={
                OUTPUT_KEY_FILE_PATH: str(source_path),
                OUTPUT_KEY_ADDED_DOCSTRINGS: added_count,
                OUTPUT_KEY_README_UPDATED: readme_updated,
            },
            next_events=[
                self._docs_updated_event(event, source_path, added_count, readme_updated)
            ],
        )

    def _file_path_value(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Return a source file path from supported payload keys."""
        file_path = payload.get(PAYLOAD_KEY_FILE_PATH)
        if isinstance(file_path, str) and file_path:
            return file_path
        source_file = payload.get(PAYLOAD_KEY_SOURCE_FILE)
        if isinstance(source_file, str) and source_file:
            return source_file
        return None

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve a payload file path against the project root."""
        candidate_path = Path(file_path)
        if candidate_path.is_absolute():
            return candidate_path
        return self.project_root / candidate_path

    def _build_source_prompt(
        self,
        payload: Mapping[str, Any],
        source_path: Path,
        source_code: str,
        missing_functions: Iterable[str],
    ) -> str:
        """Build the source-documentation prompt for the model."""
        task_id = payload.get(PAYLOAD_KEY_TASK_ID)
        task_id_text = str(task_id) if task_id is not None else EMPTY_TEXT
        missing_text = PROMPT_LIST_SEPARATOR.join(missing_functions)
        return PROMPT_SECTION_SEPARATOR.join(
            [
                f"{PROMPT_FILE_PATH_LABEL} {source_path}",
                f"{PROMPT_TASK_ID_LABEL} {task_id_text}",
                f"{PROMPT_MISSING_DOCSTRINGS_LABEL} {missing_text}",
                f"{PROMPT_SOURCE_LABEL}\n{source_code}",
                PROMPT_INSTRUCTION,
            ]
        )

    def _missing_docstring_functions(self, source_code: str) -> List[str]:
        """Return function names missing docstrings in source code."""
        try:
            syntax_tree = ast.parse(source_code)
        except SyntaxError:
            return []
        missing_names = []
        for node in ast.walk(syntax_tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if ast.get_docstring(node) is None:
                    missing_names.append(node.name)
        return missing_names

    def _existing_docstrings(self, source_code: str) -> List[str]:
        """Return existing function docstrings from source code."""
        try:
            syntax_tree = ast.parse(source_code)
        except SyntaxError:
            return []
        docstrings = []
        for node in ast.walk(syntax_tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                docstring = ast.get_docstring(node)
                if docstring:
                    docstrings.append(docstring)
        return docstrings

    def _preserves_existing_docstrings(
        self,
        updated_source: str,
        existing_docstrings: Iterable[str],
    ) -> bool:
        """Return whether updated source still contains existing docstrings."""
        return all(docstring in updated_source for docstring in existing_docstrings)

    def _normalize_model_content(self, model_output: str) -> str:
        """Normalize model file content before writing."""
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

    def _update_readme_if_requested(
        self,
        payload: Mapping[str, Any],
        source_path: Path,
    ) -> bool:
        """Update README.md when sections are explicitly requested."""
        readme_sections = payload.get(PAYLOAD_KEY_README_SECTIONS)
        if not isinstance(readme_sections, list) or not readme_sections:
            return False
        readme_path = self.project_root / README_FILE_NAME
        if not readme_path.exists():
            return False
        original_readme = readme_path.read_text(encoding=ENCODING)
        updated_readme = self.model_provider.complete(
            self._build_readme_prompt(source_path, original_readme, readme_sections),
            SYSTEM_PROMPT,
            MODEL_MAX_TOKENS,
        ).strip()
        if original_readme not in updated_readme:
            updated_readme = f"{original_readme.rstrip()}{NEWLINE}{NEWLINE}{updated_readme}"
        _write_atomically(readme_path, updated_readme.rstrip() + NEWLINE)
        return True

    def _build_readme_prompt(
        self,
        source_path: Path,
        readme_content: str,
        readme_sections: Iterable[Any],
    ) -> str:
        """Build a README-update prompt for the model."""
        section_text = PROMPT_LIST_SEPARATOR.join(
            str(section) for section in readme_sections if isinstance(section, str)
        )
        return PROMPT_SECTION_SEPARATOR.join(
            [
                f"{PROMPT_FILE_PATH_LABEL} {source_path}",
                f"{PROMPT_README_SECTIONS_LABEL} {section_text}",
                f"{PROMPT_README_LABEL}\n{readme_content}",
                PROMPT_INSTRUCTION,
            ]
        )

    def _docs_updated_event(
        self,
        parent_event: AgentEvent,
        source_path: Path,
        added_count: int,
        readme_updated: bool,
    ) -> AgentEvent:
        """Create a DOCS_UPDATED event for completed documentation work."""
        return AgentEvent(
            event_type=EventType.DOCS_UPDATED,
            source_agent=self.name,
            payload={
                PAYLOAD_KEY_FILE_PATH: str(source_path),
                PAYLOAD_KEY_ADDED_DOCSTRINGS: added_count,
                PAYLOAD_KEY_README_UPDATED: readme_updated,
            },
            correlation_id=parent_event.correlation_id or parent_event.event_id,
            priority=parent_event.priority,
        )

    def _failure_result(self, event: AgentEvent, reason: str) -> AgentResult:
        """Log and return a non-crashing failure result."""
        self._log_decision(event, DECISION_FAILURE, reason)
        return AgentResult(success=False, output={OUTPUT_KEY_ERROR: reason})

    def _log_decision(self, event: AgentEvent, outcome: str, reasoning: str) -> None:
        """Append one DocsAgent decision to decisions.log."""
        decision_line = (
            f"{DECISION_LOG_PREFIX}{_utc_timestamp()}{DECISION_LOG_SEPARATOR}"
            f"{event.event_id}{DECISION_LOG_SEPARATOR}"
            f"{outcome}{DECISION_LOG_SEPARATOR}"
            f"{reasoning}{DECISION_LOG_SUFFIX}"
        )
        _append_atomically(self.project_root / DECISIONS_LOG_NAME, decision_line)
        self.log_decision(reasoning, outcome)


__all__ = ["DocsAgent"]
