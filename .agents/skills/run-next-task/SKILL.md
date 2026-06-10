---
name: run-next-task
description: "Run the next PENDING task in ProjectOS tasks/README.md. Use when user says run next task, continue, next task, or run task."
---

# Run Next Task

1. Read tasks/README.md — find the first PENDING task
2. Read that TASK_XX.md completely
3. Read AGENTS.md for all architectural rules
4. Read ONLY the files explicitly listed in the task's Pre-conditions section
5. Execute the task exactly as specified
6. Run full test suite: UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30
7. Write result file to tasks/TASK_XX_RESULT.md — NEVER to the project root
8. Update tasks/README.md — mark task DONE
9. Stop and report summary

## CRITICAL: Result File Location
- CORRECT: tasks/TASK_55b_RESULT.md
- WRONG:   TASK_55b_RESULT.md  (project root)
- If you wrote to root by mistake: mv TASK_XX_RESULT.md tasks/
