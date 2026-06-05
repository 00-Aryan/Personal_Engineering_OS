# TASK_18: Expose ProjectOS as MCP Server

## Purpose
Make ProjectOS agents callable from Codex, Claude Code, and any
MCP-compatible client. This is the bridge to the open-source ecosystem.

## Pre-conditions
Read core/projectos.py, core/agent_registry.py, core/events.py fully.
Read MCP protocol basics: tools have name, description, inputSchema.

## Deliverables

### 1. mcp_server/server.py

Implement a stdio MCP server using only stdlib (no MCP SDK).
MCP protocol: JSON-RPC 2.0 over stdin/stdout.

Expose these tools:

tool: projectos_plan
  description: "Submit a feature idea to ProjectOS Planning Agent"
  input: {description: string, project_context: string (optional)}
  Returns: task list as JSON

tool: projectos_review
  description: "Trigger code review on a file"
  input: {file_path: string}
  Returns: review report path and issue count

tool: projectos_status
  description: "Get current ProjectOS status"
  input: {}
  Returns: {agents, queue, providers, uptime}

tool: projectos_decisions
  description: "Query recent decisions"
  input: {limit: int (default 10), agent: string (optional)}
  Returns: list of decision records

tool: projectos_approve
  description: "Approve or reject an escalation"
  input: {event_id: string, approved: bool, reason: string}
  Returns: confirmation

Implementation:
  Read JSON-RPC from stdin line by line.
  Handle: initialize, tools/list, tools/call
  Route tools/call to appropriate ProjectOS component.
  Write JSON-RPC response to stdout.
  All errors return proper JSON-RPC error responses.

### 2. mcp_server/__init__.py (empty)

### 3. Update codex config instructions in README.md
  Add section: "Use as MCP Server"
  codex mcp add projectos -- uv run --no-sync python -m mcp_server.server

### 4. tests/test_mcp_server.py
  Test JSON-RPC handling with mocked ProjectOS:
  - test_initialize_returns_server_info
  - test_tools_list_returns_five_tools
  - test_tools_call_projectos_status
  - test_invalid_method_returns_error
  - test_unknown_tool_returns_error

## Constraints
- No external MCP SDK dependency
- Server must handle malformed JSON gracefully
- All tool handlers must have 30 second timeout
- stdio only — no HTTP server

## Verification
Full test suite. Write TASK_18_RESULT.md. Update tasks/README.md.
