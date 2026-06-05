"""Stdlib-only stdio MCP server for ProjectOS tools."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from core.decision_log import DecisionLogger
from core.events import AgentEvent, EventType
from core.projectos import ProjectOS


JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "projectos"
SERVER_VERSION = "0.1.0"
SOURCE_AGENT = "mcp_server"
DEFAULT_CONFIG_PATH = Path("config/models.yaml")
TOOL_TIMEOUT_SECONDS = 30
ENCODING = "utf-8"
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"
EMPTY_TEXT = ""

METHOD_INITIALIZE = "initialize"
METHOD_TOOLS_LIST = "tools/list"
METHOD_TOOLS_CALL = "tools/call"

PARAM_NAME = "name"
PARAM_ARGUMENTS = "arguments"
PARAM_DESCRIPTION = "description"
PARAM_PROJECT_CONTEXT = "project_context"
PARAM_FILE_PATH = "file_path"
PARAM_LIMIT = "limit"
PARAM_AGENT = "agent"
PARAM_EVENT_ID = "event_id"
PARAM_APPROVED = "approved"
PARAM_REASON = "reason"

TOOL_PROJECTOS_PLAN = "projectos_plan"
TOOL_PROJECTOS_REVIEW = "projectos_review"
TOOL_PROJECTOS_STATUS = "projectos_status"
TOOL_PROJECTOS_DECISIONS = "projectos_decisions"
TOOL_PROJECTOS_APPROVE = "projectos_approve"

AGENT_PLANNING = "planning"
AGENT_PLANNING_ALIAS = "planning_agent"
AGENT_CODE_REVIEW = "code_review"
AGENT_CODE_REVIEW_ALIAS = "code_review_agent"

KEY_TASKS = "tasks"
KEY_REPORT_PATH = "report_path"
KEY_ISSUES = "issues"
KEY_ISSUE_COUNT = "issue_count"
KEY_AGENTS = "agents"
KEY_QUEUE = "queue"
KEY_PROVIDERS = "providers"
KEY_UPTIME = "uptime"
KEY_PENDING = "pending"
KEY_BLOCKED = "blocked"
KEY_APPROVED = "approved"
KEY_UPDATED = "updated"
KEY_STATUS = "status"
KEY_JSONRPC = "jsonrpc"
KEY_ID = "id"
KEY_METHOD = "method"
KEY_PARAMS = "params"
KEY_RESULT = "result"
KEY_ERROR = "error"
KEY_CODE = "code"
KEY_MESSAGE = "message"
KEY_DATA = "data"
KEY_TOOLS = "tools"
KEY_PROTOCOL_VERSION = "protocolVersion"
KEY_SERVER_INFO = "serverInfo"
KEY_NAME = "name"
KEY_VERSION = "version"
KEY_CAPABILITIES = "capabilities"
KEY_CONTENT = "content"
KEY_TYPE = "type"
KEY_TEXT = "text"
KEY_STRUCTURED_CONTENT = "structuredContent"
KEY_IS_ERROR = "isError"
KEY_INPUT_SCHEMA = "inputSchema"
KEY_PROPERTIES = "properties"
KEY_REQUIRED = "required"
KEY_ADDITIONAL_PROPERTIES = "additionalProperties"
KEY_DEFAULT = "default"

STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_MISSING = "MISSING"

ESCALATION_QUEUE_NAME = "escalation_queue.md"
DECISIONS_LOG_NAME = "decisions.log"
DECISION_APPROVAL_CATEGORY = "MCP_APPROVAL"
DECISION_OUTCOME_TEMPLATE = "{status} escalation {event_id}"

ERROR_PARSE = -32700
ERROR_INVALID_REQUEST = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL = -32603
ERROR_TOOL = -32000
ERROR_TIMEOUT = -32001

MESSAGE_PARSE_ERROR = "Parse error"
MESSAGE_INVALID_REQUEST = "Invalid request"
MESSAGE_METHOD_NOT_FOUND = "Method not found"
MESSAGE_INVALID_PARAMS = "Invalid params"
MESSAGE_UNKNOWN_TOOL = "Unknown tool"
MESSAGE_TOOL_TIMEOUT = "Tool handler timed out"

TYPE_OBJECT = "object"
TYPE_STRING = "string"
TYPE_INTEGER = "integer"
TYPE_BOOLEAN = "boolean"
TYPE_ARRAY = "array"
TYPE_TEXT = "text"

ProjectOSFactory = Callable[[], Any]


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


def _append_text(path: Path, content: str) -> None:
    """Append text using OS append semantics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded_content = content.encode(ENCODING)
    file_descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o644,
    )
    try:
        os.write(file_descriptor, encoded_content)
    finally:
        os.close(file_descriptor)


class ToolExecutionError(RuntimeError):
    """Raised when an MCP tool cannot complete successfully."""


class MCPServer:
    """Handle JSON-RPC MCP requests for ProjectOS over stdio."""

    def __init__(
        self,
        projectos_factory: Optional[ProjectOSFactory] = None,
        project_root: Path | str = Path("."),
    ) -> None:
        """Initialize the server with lazy ProjectOS construction."""
        self.project_root = Path(project_root)
        self._projectos_factory = projectos_factory or self._default_projectos
        self._projectos: Any = None
        self._started_at = time.monotonic()
        self._tool_handlers: dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any] | list[Any]]] = {
            TOOL_PROJECTOS_PLAN: self._tool_projectos_plan,
            TOOL_PROJECTOS_REVIEW: self._tool_projectos_review,
            TOOL_PROJECTOS_STATUS: self._tool_projectos_status,
            TOOL_PROJECTOS_DECISIONS: self._tool_projectos_decisions,
            TOOL_PROJECTOS_APPROVE: self._tool_projectos_approve,
        }

    def handle_message(self, raw_message: str) -> str:
        """Return one JSON-RPC response for a raw input line."""
        try:
            request = json.loads(raw_message)
        except json.JSONDecodeError:
            return self._encode(self._error(None, ERROR_PARSE, MESSAGE_PARSE_ERROR))

        if not isinstance(request, Mapping):
            return self._encode(
                self._error(None, ERROR_INVALID_REQUEST, MESSAGE_INVALID_REQUEST)
            )

        request_id = request.get(KEY_ID)
        method = request.get(KEY_METHOD)
        if not isinstance(method, str):
            return self._encode(
                self._error(request_id, ERROR_INVALID_REQUEST, MESSAGE_INVALID_REQUEST)
            )

        try:
            result = self._dispatch(method, request.get(KEY_PARAMS))
        except ToolExecutionError as error:
            return self._encode(self._error(request_id, ERROR_TOOL, str(error)))
        except TimeoutError:
            return self._encode(self._error(request_id, ERROR_TIMEOUT, MESSAGE_TOOL_TIMEOUT))
        except ValueError as error:
            return self._encode(self._error(request_id, ERROR_INVALID_PARAMS, str(error)))
        except Exception as error:
            return self._encode(self._error(request_id, ERROR_INTERNAL, str(error)))

        if result is None:
            return self._encode(
                self._error(request_id, ERROR_METHOD_NOT_FOUND, MESSAGE_METHOD_NOT_FOUND)
            )
        return self._encode(self._success(request_id, result))

    def serve_forever(self) -> None:
        """Read JSON-RPC lines from stdin and write responses to stdout."""
        for raw_line in sys.stdin:
            if not raw_line.strip():
                continue
            response = self.handle_message(raw_line)
            sys.stdout.write(f"{response}{NEWLINE}")
            sys.stdout.flush()

    def _dispatch(self, method: str, params: Any) -> Optional[Mapping[str, Any]]:
        """Dispatch a JSON-RPC method to a result mapping."""
        if method == METHOD_INITIALIZE:
            return self._initialize_result()
        if method == METHOD_TOOLS_LIST:
            return {KEY_TOOLS: self._tool_definitions()}
        if method == METHOD_TOOLS_CALL:
            return self._call_tool(params)
        return None

    def _initialize_result(self) -> Mapping[str, Any]:
        """Return MCP initialize server metadata."""
        return {
            KEY_PROTOCOL_VERSION: PROTOCOL_VERSION,
            KEY_SERVER_INFO: {
                KEY_NAME: SERVER_NAME,
                KEY_VERSION: SERVER_VERSION,
            },
            KEY_CAPABILITIES: {
                KEY_TOOLS: {},
            },
        }

    def _call_tool(self, params: Any) -> Mapping[str, Any]:
        """Call one MCP tool with timeout protection."""
        if not isinstance(params, Mapping):
            raise ValueError(MESSAGE_INVALID_PARAMS)
        tool_name = params.get(PARAM_NAME)
        if not isinstance(tool_name, str):
            raise ValueError(MESSAGE_INVALID_PARAMS)
        arguments = params.get(PARAM_ARGUMENTS, {})
        if not isinstance(arguments, Mapping):
            raise ValueError(MESSAGE_INVALID_PARAMS)
        handler = self._tool_handlers.get(tool_name)
        if handler is None:
            raise ToolExecutionError(f"{MESSAGE_UNKNOWN_TOOL}: {tool_name}")

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(handler, dict(arguments))
            result = future.result(timeout=TOOL_TIMEOUT_SECONDS)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return self._tool_result(result)

    def _tool_result(self, result: Mapping[str, Any] | list[Any]) -> Mapping[str, Any]:
        """Return an MCP tools/call compatible result."""
        return {
            KEY_CONTENT: [
                {
                    KEY_TYPE: TYPE_TEXT,
                    KEY_TEXT: json.dumps(result, sort_keys=True),
                }
            ],
            KEY_STRUCTURED_CONTENT: result,
            KEY_IS_ERROR: False,
        }

    def _tool_projectos_plan(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Submit a feature idea to the ProjectOS Planning Agent."""
        description = self._required_string(arguments, PARAM_DESCRIPTION)
        payload: dict[str, Any] = {PARAM_DESCRIPTION: description}
        project_context = arguments.get(PARAM_PROJECT_CONTEXT)
        if isinstance(project_context, str) and project_context:
            payload[PARAM_PROJECT_CONTEXT] = project_context
        result = self._agent_handle(
            AGENT_PLANNING,
            AGENT_PLANNING_ALIAS,
            AgentEvent(
                event_type=EventType.MANUAL_TRIGGER,
                source_agent=SOURCE_AGENT,
                payload=payload,
            ),
        )
        output = self._result_output(result)
        tasks = output.get(KEY_TASKS, output)
        return {KEY_TASKS: tasks}

    def _tool_projectos_review(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Trigger code review on a file."""
        file_path = self._required_string(arguments, PARAM_FILE_PATH)
        result = self._agent_handle(
            AGENT_CODE_REVIEW,
            AGENT_CODE_REVIEW_ALIAS,
            AgentEvent(
                event_type=EventType.CODE_CHANGED,
                source_agent=SOURCE_AGENT,
                payload={PARAM_FILE_PATH: file_path},
            ),
        )
        output = self._result_output(result)
        issues = output.get(KEY_ISSUES, [])
        issue_count = len(issues) if isinstance(issues, list) else 0
        return {
            KEY_REPORT_PATH: output.get(KEY_REPORT_PATH),
            KEY_ISSUE_COUNT: issue_count,
            KEY_ISSUES: issues,
        }

    def _tool_projectos_status(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Get current ProjectOS status."""
        self._ensure_no_arguments(arguments)
        project_os = self._project_os()
        return {
            KEY_AGENTS: self._agents_status(project_os),
            KEY_QUEUE: self._queue_status(project_os),
            KEY_PROVIDERS: self._provider_status(project_os),
            KEY_UPTIME: self._uptime_seconds(),
        }

    def _tool_projectos_decisions(
        self,
        arguments: Mapping[str, Any],
    ) -> list[Mapping[str, Any]]:
        """Query recent ProjectOS decisions."""
        limit = self._limit(arguments.get(PARAM_LIMIT))
        agent_name = arguments.get(PARAM_AGENT)
        if agent_name is not None and not isinstance(agent_name, str):
            raise ValueError(MESSAGE_INVALID_PARAMS)
        project_root = self._active_project_root()
        return DecisionLogger(project_root).query(agent_name=agent_name, limit=limit)

    def _tool_projectos_approve(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Approve or reject an escalation queue item."""
        event_id = self._required_string(arguments, PARAM_EVENT_ID)
        approved = arguments.get(PARAM_APPROVED)
        if not isinstance(approved, bool):
            raise ValueError(MESSAGE_INVALID_PARAMS)
        reason = self._required_string(arguments, PARAM_REASON)
        updated = self._update_escalation_queue(event_id, approved)
        status = STATUS_APPROVED if approved else STATUS_REJECTED
        self._log_approval_decision(event_id, status, reason)
        return {
            PARAM_EVENT_ID: event_id,
            KEY_APPROVED: approved,
            PARAM_REASON: reason,
            KEY_UPDATED: updated,
            KEY_STATUS: status if updated else STATUS_MISSING,
        }

    def _agent_handle(
        self,
        primary_name: str,
        alias_name: str,
        event: AgentEvent,
    ) -> Any:
        """Run a registered ProjectOS agent for one event."""
        project_os = self._project_os()
        registry = getattr(project_os, "agent_registry", None)
        if registry is None:
            raise ToolExecutionError("ProjectOS agent registry unavailable")
        for agent_name in (primary_name, alias_name):
            try:
                agent = registry.get(agent_name)
                return agent.handle(event)
            except KeyError:
                continue
        raise ToolExecutionError(f"ProjectOS agent unavailable: {primary_name}")

    def _result_output(self, result: Any) -> Mapping[str, Any]:
        """Return an AgentResult output mapping or raise a tool error."""
        if not bool(getattr(result, "success", False)):
            output = getattr(result, "output", {})
            raise ToolExecutionError(json.dumps(output, sort_keys=True))
        output = getattr(result, "output", {})
        return output if isinstance(output, Mapping) else {"result": output}

    def _agents_status(self, project_os: Any) -> Mapping[str, Any]:
        """Return current agent metadata for status output."""
        providers = getattr(project_os, "providers", None)
        if isinstance(providers, Mapping):
            return {
                str(agent_name): self._model_name(provider)
                for agent_name, provider in providers.items()
            }
        registry = getattr(project_os, "agent_registry", None)
        if registry is not None:
            try:
                return {str(name): "registered" for name in registry.list_all()}
            except Exception:
                return {}
        return {}

    def _queue_status(self, project_os: Any) -> Mapping[str, int]:
        """Return pending and blocked queue counts."""
        task_queue = getattr(project_os, "task_queue", None)
        if task_queue is None:
            return {KEY_PENDING: 0, KEY_BLOCKED: 0}
        return {
            KEY_PENDING: int(task_queue.get_pending_count()),
            KEY_BLOCKED: len(task_queue.get_blocked()),
        }

    def _provider_status(self, project_os: Any) -> Mapping[str, bool]:
        """Return provider health status from the monitor."""
        monitor = getattr(project_os, "provider_health_monitor", None)
        if monitor is None:
            return {}
        status = monitor.get_status()
        return {
            str(provider_name): bool(healthy)
            for provider_name, healthy in status.items()
        }

    def _model_name(self, provider: Any) -> str:
        """Return a provider model name with a stable fallback."""
        try:
            return str(provider.get_model_name())
        except Exception:
            return str(provider)

    def _project_os(self) -> Any:
        """Return the cached ProjectOS runtime."""
        if self._projectos is None:
            self._projectos = self._projectos_factory()
        return self._projectos

    def _default_projectos(self) -> ProjectOS:
        """Create a default ProjectOS runtime from config/models.yaml."""
        config_path = self.project_root / DEFAULT_CONFIG_PATH
        return ProjectOS(config_path)

    def _active_project_root(self) -> Path:
        """Return the active project root from ProjectOS or the server."""
        if self._projectos is None:
            return self.project_root
        project_root = getattr(self._projectos, "project_root", self.project_root)
        return Path(project_root)

    def _update_escalation_queue(self, event_id: str, approved: bool) -> bool:
        """Update the matching escalation queue row status."""
        queue_path = self._active_project_root() / ESCALATION_QUEUE_NAME
        if not queue_path.exists():
            return False
        lines = queue_path.read_text(encoding=ENCODING).splitlines()
        updated_lines = []
        updated = False
        target_status = STATUS_APPROVED if approved else STATUS_REJECTED
        for line in lines:
            cells = self._markdown_cells(line)
            if len(cells) >= 4 and cells[1] == event_id:
                cells[-1] = target_status
                updated_lines.append(self._markdown_row(cells))
                updated = True
            else:
                updated_lines.append(line)
        if updated:
            _write_atomically(queue_path, NEWLINE.join(updated_lines) + NEWLINE)
        return updated

    def _log_approval_decision(self, event_id: str, status: str, reason: str) -> None:
        """Append an MCP approval decision to decisions.log."""
        project_root = self._active_project_root()
        outcome = DECISION_OUTCOME_TEMPLATE.format(status=status, event_id=event_id)
        line = f"[{SOURCE_AGENT}] [{DECISION_APPROVAL_CATEGORY}] [{outcome}] {reason}{NEWLINE}"
        _append_text(project_root / DECISIONS_LOG_NAME, line)

    def _markdown_cells(self, line: str) -> list[str]:
        """Return markdown table cells from a row line."""
        stripped_line = line.strip()
        if not stripped_line.startswith("|") or not stripped_line.endswith("|"):
            return []
        return [cell.strip() for cell in stripped_line.strip("|").split("|")]

    def _markdown_row(self, cells: list[str]) -> str:
        """Return one markdown table row from cell values."""
        return f"| {' | '.join(cells)} |"

    def _required_string(self, values: Mapping[str, Any], key: str) -> str:
        """Return a required non-empty string argument."""
        value = values.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(MESSAGE_INVALID_PARAMS)
        return value.strip()

    def _limit(self, value: Any) -> int:
        """Return a safe decision query limit."""
        if value is None:
            return 10
        if not isinstance(value, int) or value <= 0:
            raise ValueError(MESSAGE_INVALID_PARAMS)
        return value

    def _ensure_no_arguments(self, arguments: Mapping[str, Any]) -> None:
        """Validate that a tool received no arguments."""
        if arguments:
            raise ValueError(MESSAGE_INVALID_PARAMS)

    def _uptime_seconds(self) -> int:
        """Return server uptime in whole seconds."""
        return int(time.monotonic() - self._started_at)

    def _tool_definitions(self) -> list[Mapping[str, Any]]:
        """Return MCP tool definitions with JSON schemas."""
        return [
            self._tool_definition(
                TOOL_PROJECTOS_PLAN,
                "Submit a feature idea to ProjectOS Planning Agent",
                {
                    PARAM_DESCRIPTION: {KEY_TYPE: TYPE_STRING},
                    PARAM_PROJECT_CONTEXT: {KEY_TYPE: TYPE_STRING},
                },
                [PARAM_DESCRIPTION],
            ),
            self._tool_definition(
                TOOL_PROJECTOS_REVIEW,
                "Trigger code review on a file",
                {PARAM_FILE_PATH: {KEY_TYPE: TYPE_STRING}},
                [PARAM_FILE_PATH],
            ),
            self._tool_definition(
                TOOL_PROJECTOS_STATUS,
                "Get current ProjectOS status",
                {},
                [],
            ),
            self._tool_definition(
                TOOL_PROJECTOS_DECISIONS,
                "Query recent decisions",
                {
                    PARAM_LIMIT: {KEY_TYPE: TYPE_INTEGER, KEY_DEFAULT: 10},
                    PARAM_AGENT: {KEY_TYPE: TYPE_STRING},
                },
                [],
            ),
            self._tool_definition(
                TOOL_PROJECTOS_APPROVE,
                "Approve or reject an escalation",
                {
                    PARAM_EVENT_ID: {KEY_TYPE: TYPE_STRING},
                    PARAM_APPROVED: {KEY_TYPE: TYPE_BOOLEAN},
                    PARAM_REASON: {KEY_TYPE: TYPE_STRING},
                },
                [PARAM_EVENT_ID, PARAM_APPROVED, PARAM_REASON],
            ),
        ]

    def _tool_definition(
        self,
        name: str,
        description: str,
        properties: Mapping[str, Mapping[str, Any]],
        required: list[str],
    ) -> Mapping[str, Any]:
        """Return one MCP tool definition."""
        return {
            KEY_NAME: name,
            PARAM_DESCRIPTION: description,
            KEY_INPUT_SCHEMA: {
                KEY_TYPE: TYPE_OBJECT,
                KEY_PROPERTIES: properties,
                KEY_REQUIRED: required,
                KEY_ADDITIONAL_PROPERTIES: False,
            },
        }

    def _success(self, request_id: Any, result: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a JSON-RPC success response."""
        return {
            KEY_JSONRPC: JSONRPC_VERSION,
            KEY_ID: request_id,
            KEY_RESULT: result,
        }

    def _error(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Optional[Any] = None,
    ) -> Mapping[str, Any]:
        """Return a JSON-RPC error response."""
        error: dict[str, Any] = {
            KEY_CODE: code,
            KEY_MESSAGE: message,
        }
        if data is not None:
            error[KEY_DATA] = data
        return {
            KEY_JSONRPC: JSONRPC_VERSION,
            KEY_ID: request_id,
            KEY_ERROR: error,
        }

    def _encode(self, payload: Mapping[str, Any]) -> str:
        """Encode one JSON-RPC response."""
        return json.dumps(payload, sort_keys=True)


def main() -> None:
    """Run the ProjectOS MCP server over stdio."""
    MCPServer().serve_forever()


if __name__ == "__main__":
    main()
