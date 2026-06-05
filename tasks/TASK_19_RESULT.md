# TASK_19_RESULT: Multi-Project Support

## Status
DONE

## Files Created
- core/project_config.py
- tests/test_project_registry.py

## Files Modified
- cli/main.py
- core/projectos.py
- core/trigger_system.py
- tasks/README.md

## Test Result
- Command: `UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest`
- Result: `118 passed in 1.03s`

## Deliverables Completed
- Added `ProjectConfig` with default state and model config path resolution.
- Added `ProjectRegistry` backed by global-style YAML config files.
- Added enabled-project listing, add, remove, and lookup behavior.
- Added `ProjectOS.from_project_config()`.
- Preserved existing single-project `ProjectOS` construction while allowing explicit project root, state dir, project name, and watch rules.
- Added isolated per-project state directories for ProjectOS instances created from project configs.
- Added `MultiProjectOS` for starting, stopping, and reporting status across enabled registered projects.
- Added configurable trigger watch and ignore patterns.
- Added `projectos projects list`, `projectos projects add`, and `projectos projects remove`.
- Added `projectos run --all` for multi-project mode.
- Added registry unit tests required by the task.

## Decisions Made
- `ProjectRegistry.list_projects()` returns enabled projects only, matching the required disabled-project test.
- `ProjectConfig.models_config` uses the project-local `config/models.yaml` when present and otherwise falls back to `~/.projectos/models.yaml`.
- Multi-project mode creates a separate `ProjectOS` instance per enabled project so model providers, queues, trigger systems, and state directories are isolated.
- Project-specific logger names and start/stop messages include the project name to provide project-prefixed logging context.
- Existing `projectos run` remains single-project mode, and `--all` is the only switch into registry-backed multi-project mode.

## Human Review
- Real multi-project startup requires each enabled project to have a valid project-local or global model config.
- Existing uncommitted files from prior task work remain in the worktree and were not reverted.

## Next Task Dependency Check
- TASK_20 can proceed.
