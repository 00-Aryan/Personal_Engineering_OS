---
name: run-next-task
description: "Run the next PENDING task in ProjectOS tasks/README.md. Use when user says run next task, continue, next task, or run task."
---

# Run Next Task

1. Read tasks/README.md — find the first PENDING task
2. Read that TASK_XX.md completely
3. Read AGENTS.md for all architectural rules
4. Read all existing code in core/ and agents/ before writing anything
5. Execute the task exactly as specified
6. Run full test suite: PYTHONDONTWRITEBYTECODE=1 uv run pytest
7. Write TASK_XX_RESULT.md with: files created, test count, decisions made
8. Update tasks/README.md — mark task DONE
9. Stop and report summary
