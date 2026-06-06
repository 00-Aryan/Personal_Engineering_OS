---
name: run-task
description: Execute the next PENDING task from tasks/README.md
---

1. Read tasks/README.md — identify the first task marked PENDING
2. Read AGENTS.md completely before touching any code
3. Read the full TASK_XX.md file for that task
4. Read ALL referenced files in core/, agents/, core/evaluation/, 
   core/intelligence/, core/observability/ before writing anything
5. Execute every deliverable in the task file exactly as specified
6. Run test suite: UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 
   uv run --no-sync pytest
7. Write TASK_XX_RESULT.md with full detail
8. Update tasks/README.md — mark task DONE
9. Stop. Do not start the next task automatically.
10. Print: "TASK_XX COMPLETE — [test count] tests passing"