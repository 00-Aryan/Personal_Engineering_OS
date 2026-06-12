---
name: run-next-task
description: "Run the next PENDING task in ProjectOS tasks/README.md. Use when user says run next task, continue, next task, or run task."
---

# Run Next Task

1. **Short Preflight Only**:
   - Read `tasks/README.md` to find the first PENDING task.
   - Read that `tasks/TASK_XX.md` completely.
   - Read `AGENTS.md` for all architectural rules.
   - Inspect only the files explicitly listed in the task's Pre-conditions or directly relevant implementation files. Do not perform broad repository scans.
   - **No Full Test Suite Before Edits**: Do not run the full test suite before editing unless explicitly required. Only run targeted reproduction/failing commands if needed.

2. **Strict File Scope**:
   - Execute the task exactly as specified, focusing on the declared file scope.
   - **Stop if File Scope Expands**: If a task declares one-file or specific-file scope and you determine additional files must be modified, stop immediately and write to `tasks/TASK_XX_RESULT.md`:
     `TASK BLOCKED: required changes exceed declared scope.`
     Do not silently modify extra files.

3. **Checkpoint Result File Early**:
   - **Create Result File Before Risky Validation**: Create or update `tasks/TASK_XX_RESULT.md` before running any command expected to take longer than 30 seconds.
   - The partial/initial result must include:
     - task status: `IN_PROGRESS`
     - files changed so far
     - validation pending
     - exact commands planned next
   - **Mandatory Checkpoint After Implementation**: After code edits are completed and before long validation runs, update the result file to include:
     ```
     Implementation completed.
     Files changed:
     - <file>
     Validation pending.
     ```
     This ensures timeouts do not leave the system without a reliable handoff.

4. **Explicit Timeouts for Long Commands**:
   - Any command that may run longer than 30 seconds must be wrapped in `timeout`. Do not run unbounded validation commands.
   - Examples:
     `timeout 120s UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30`
     `timeout 120s python -m cli.main intake-smoke --project-root ~/June-2026/TenderIQ --timeout-seconds 90`

5. **Handling Blockers**:
   - **Stop After First Major Blocker**: If a live command reveals a major blocker, document it and stop. Do not expand the task into a larger multi-system fix. Write the result file reflecting the block/failure.

6. **Avoid Background Commands**:
   - Avoid background test or run commands unless absolutely necessary.
   - If used, you must collect output, terminate if stale, and record the outcome in the result file.

7. **Final Response and Status Update**:
   - Run the final validation command with explicit timeout.
   - Write the final `tasks/TASK_XX_RESULT.md`.
   - Update `tasks/README.md` to mark the task as `DONE` (or `BLOCKED` / `FAILED` if appropriate).
   - Report a clear summary including:
     - Task status: `COMPLETE`, `BLOCKED`, or `FAILED`
     - Files changed
     - Validation commands run and pass/fail result
     - Result file path
     - Whether user action is needed

## CRITICAL: Result File Location
- CORRECT: `tasks/TASK_XX_RESULT.md`
- WRONG: `TASK_XX_RESULT.md` (project root)
- If you wrote to root by mistake: `mv TASK_XX_RESULT.md tasks/`
