---
name: projectos-plan
description: "Submit a feature idea to ProjectOS Planning Agent. Use when user says plan this feature, create tasks for, or break down this idea."
---

# ProjectOS Plan

Submit a feature description to ProjectOS Planning Agent.

1. Check if ProjectOS MCP server is connected via /mcp
2. If connected: call projectos_plan tool with the description
3. If not connected: run locally:
   uv run --no-sync projectos /plan "[description]"
4. Display the generated task breakdown
5. Ask: "Should I add these to backlog.md?"
