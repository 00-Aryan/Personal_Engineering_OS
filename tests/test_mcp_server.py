"""Unit tests for the ProjectOS stdio MCP server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_server.server import MCPServer


JSONRPC_VERSION = "2.0"
METHOD_INITIALIZE = "initialize"
METHOD_TOOLS_LIST = "tools/list"
METHOD_TOOLS_CALL = "tools/call"
TOOL_PROJECTOS_STATUS = "projectos_status"
UNKNOWN_METHOD = "missing/method"
UNKNOWN_TOOL = "projectos_missing"
REQUEST_ID = 1
CLONE_AGENT = "clone"
MODEL_NAME = "fake-model"
PROVIDER_NAME = "openrouter"
PENDING_COUNT = 2
BLOCKED_COUNT = 1


def test_initialize_returns_server_info(tmp_path: Path) -> None:
    """Verify initialize returns MCP server metadata."""
    server = MCPServer(projectos_factory=lambda: FakeProjectOS(tmp_path))

    response = _request(server, METHOD_INITIALIZE)

    assert response["jsonrpc"] == JSONRPC_VERSION
    assert response["result"]["serverInfo"]["name"] == "projectos"
    assert "tools" in response["result"]["capabilities"]


def test_tools_list_returns_five_tools(tmp_path: Path) -> None:
    """Verify tools/list returns the five ProjectOS tools."""
    server = MCPServer(projectos_factory=lambda: FakeProjectOS(tmp_path))

    response = _request(server, METHOD_TOOLS_LIST)

    tools = response["result"]["tools"]
    assert len(tools) == 5
    assert {tool["name"] for tool in tools} == {
        "projectos_plan",
        "projectos_review",
        "projectos_status",
        "projectos_decisions",
        "projectos_approve",
    }


def test_tools_call_projectos_status(tmp_path: Path) -> None:
    """Verify tools/call returns status from mocked ProjectOS components."""
    server = MCPServer(projectos_factory=lambda: FakeProjectOS(tmp_path))

    response = _request(
        server,
        METHOD_TOOLS_CALL,
        {
            "name": TOOL_PROJECTOS_STATUS,
            "arguments": {},
        },
    )

    status = response["result"]["structuredContent"]
    assert status["agents"] == {CLONE_AGENT: MODEL_NAME}
    assert status["queue"] == {"pending": PENDING_COUNT, "blocked": BLOCKED_COUNT}
    assert status["providers"] == {PROVIDER_NAME: True}
    assert isinstance(status["uptime"], int)


def test_invalid_method_returns_error(tmp_path: Path) -> None:
    """Verify unknown JSON-RPC methods return method-not-found errors."""
    server = MCPServer(projectos_factory=lambda: FakeProjectOS(tmp_path))

    response = _request(server, UNKNOWN_METHOD)

    assert response["error"]["code"] == -32601
    assert response["error"]["message"] == "Method not found"


def test_unknown_tool_returns_error(tmp_path: Path) -> None:
    """Verify tools/call returns an error for unknown tool names."""
    server = MCPServer(projectos_factory=lambda: FakeProjectOS(tmp_path))

    response = _request(
        server,
        METHOD_TOOLS_CALL,
        {
            "name": UNKNOWN_TOOL,
            "arguments": {},
        },
    )

    assert response["error"]["code"] == -32000
    assert UNKNOWN_TOOL in response["error"]["message"]


def _request(
    server: MCPServer,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a JSON-RPC request to the server and parse the response."""
    request: dict[str, Any] = {
        "jsonrpc": JSONRPC_VERSION,
        "id": REQUEST_ID,
        "method": method,
    }
    if params is not None:
        request["params"] = params
    return json.loads(server.handle_message(json.dumps(request)))


class FakeProjectOS:
    """Minimal ProjectOS test double for MCP status tests."""

    def __init__(self, project_root: Path) -> None:
        """Initialize fake ProjectOS component attributes."""
        self.project_root = project_root
        self.providers = {CLONE_AGENT: FakeProvider()}
        self.task_queue = FakeTaskQueue()
        self.provider_health_monitor = FakeHealthMonitor()
        self.agent_registry = FakeAgentRegistry()


class FakeProvider:
    """Provider test double exposing a configured model name."""

    def get_model_name(self) -> str:
        """Return the fake model name."""
        return MODEL_NAME


class FakeTaskQueue:
    """TaskQueue test double exposing queue counts."""

    def get_pending_count(self) -> int:
        """Return a fixed pending count."""
        return PENDING_COUNT

    def get_blocked(self) -> list[object]:
        """Return fixed blocked placeholders."""
        return [object() for _index in range(BLOCKED_COUNT)]


class FakeHealthMonitor:
    """ProviderHealthMonitor test double exposing provider health."""

    def get_status(self) -> dict[str, bool]:
        """Return fixed provider health."""
        return {PROVIDER_NAME: True}


class FakeAgentRegistry:
    """AgentRegistry test double exposing registered agents."""

    def list_all(self) -> dict[str, object]:
        """Return fake registered agents."""
        return {CLONE_AGENT: object()}
