---
name: projectos-status
description: "Check ProjectOS system status. Use when user asks about agent status, what is running, or system health."
---

# ProjectOS Status

Show current ProjectOS system status.

1. If MCP connected: call projectos_status tool
2. If not: uv run --no-sync projectos status
3. Display: agents, providers, queue, last activity
