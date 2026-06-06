# ProjectOS — Agent Instructions

## Architecture Rules (Never Violate)
- All model calls go through core/model_provider.py ONLY
- Every agent inherits from core/base_agent.py
- Every decision is logged to decisions.log
- No hardcoded model names — always read from config/models.yaml
- Atomic file writes only (write to temp, rename)
- decisions.log is append-only, never overwritten

## Before Writing Any Code
1. Read all files in core/ first
2. Read the relevant TASK_XX.md completely
3. Read existing tests to understand patterns
4. Check CONTRADICTIONS.md for resolved decisions

## Task Execution Protocol
- Read tasks/README.md to find next PENDING task
- Execute exactly as specified, no scope creep
- Write TASK_XX_RESULT.md when done
- Update tasks/README.md status
- Run full test suite before marking DONE:
  UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest

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
