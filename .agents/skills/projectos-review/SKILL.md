---
name: projectos-review
description: "Trigger ProjectOS code review on a file. Use when user says review this file, check this code, or analyze this."
---

# ProjectOS Review

Run ProjectOS code review on the specified file.

1. Identify the file path from context or ask user
2. Check if ProjectOS MCP server is connected
3. If connected: call projectos_review with file_path
4. If not connected:
   uv run --no-sync projectos review [file_path]
5. Display review results from reviews/ directory
6. Ask: "Should I fix the critical issues now?"
