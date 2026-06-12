# ProjectOS — Agent Instructions

## Architecture Rules (Never Violate)
- All model calls go through core/model_provider.py ONLY
- Every agent inherits from core/base_agent.py
- Every decision is logged to decisions.log
- No hardcoded model names — always read from config/models.yaml
- Atomic file writes only (write to temp, rename)
- decisions.log is append-only, never overwritten

## Before Writing Any Code
1. Inspect ONLY the target task file, `AGENTS.md`, and directly relevant implementation files. Do NOT perform broad repository scans unless the task explicitly requires it.
2. Read the relevant TASK_XX.md completely.
3. Read existing tests to understand patterns.
4. Check CONTRADICTIONS.md for resolved decisions.
5. **No Full Test Suite Before Edits**: Do NOT run the full test suite before editing unless explicitly required. Only run targeted reproduction/failing commands if needed.

## Task Execution Protocol
- Read tasks/README.md to find next PENDING task.
- Execute exactly as specified, no scope creep.
- **Strict File Scope**: If a task declares a specific file scope and additional files must be modified, stop immediately and write to `tasks/TASK_XX_RESULT.md`:
  `TASK BLOCKED: required changes exceed declared scope.`
  Do NOT silently modify extra files.
- **Early Checkpoints**: Create or update `tasks/TASK_XX_RESULT.md` (with status `IN_PROGRESS`) BEFORE running any command expected to run longer than 30 seconds.
- **Mandatory Checkpoint After Implementation**: After code edits are completed and before long validation, update the result file to include:
  ```
  Implementation completed.
  Files changed:
  - <file>
  Validation pending.
  ```
- **Explicit Timeout Wrappers**: Any command running longer than 30 seconds must be wrapped in `timeout <seconds>` (e.g. `timeout 120s`). No unbounded validation commands.
- **Stop After First Blocker**: If a command reveals a major blocker, document it and stop. Do NOT turn one task into a larger multi-system fix.
- **Avoid Background Commands**: Avoid background runs unless necessary. If used, collect output, terminate if stale, and record the outcome in the result file.
- Write final `tasks/TASK_XX_RESULT.md` when done.
- Update tasks/README.md status.
- Run full test suite before marking DONE:
  timeout 120s UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -q --timeout=30

## Code Standards
- Every function: docstring + type hints
- Zero hardcoded strings
- Tests written immediately after implementation
- Import checks must pass before task is complete

## Intelligence Components (Phase 4)

### Before any agent call, the following context is assembled:
1. Codebase context: retrieved via CodeIndexer + ContextRetriever
2. Memory context: recalled via MemoryManager
3. Routing: classified via SemanticRouter

### Test command for intelligence components:
UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 \
uv run --no-sync python scripts/intelligence_smoke.py

### Never do in intelligence components:
- Hard-code routing rules without adding semantic examples
- Add synchronous model calls to memory storage (async or skip)
- Exceed consultation depth > 1
- Store raw model outputs as memories without distillation

## Never Do
- Skip writing the RESULT file
- Start next task without completing current one
- Add dependencies not in task specification
- Use LangChain, CrewAI, or any agent framework

## Script Safety Rules (Added Phase 6)
- NEVER call ProjectOS.start() from any script — it blocks forever
- NEVER call run_for_duration() without signal.alarm() hard timeout
- ALL scripts must have signal.alarm(N) wall clock timeout
- ALL scripts must exit with sys.exit(0) or sys.exit(1) — never hang
- Profile/benchmark scripts use direct component calls, not daemon start

## Test Performance Rules
- No single test may take > 10 seconds
- Tests that call scripts/ must use subprocess timeout=30
- Never call ProjectOS.start() or run_for_duration() in tests

## Result File Location (CRITICAL — Never Violate)
- ALL TASK_XX_RESULT.md files MUST be written to tasks/TASK_XX_RESULT.md
- NEVER write result files to the project root directory
- Correct: tasks/TASK_55b_RESULT.md
- Wrong:   TASK_55b_RESULT.md (root)
- If you wrote to root by mistake: mv TASK_XX_RESULT.md tasks/
