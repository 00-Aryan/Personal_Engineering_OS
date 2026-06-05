# TASK_17_RESULT: Rich Terminal Dashboard

## Status
DONE

## Files Created
- cli/dashboard.py
- tests/test_dashboard.py

## Files Modified
- cli/main.py
- requirements.txt
- pyproject.toml
- tasks/README.md

## Test Result
- Command: `UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest`
- Result: `108 passed in 1.18s`

## Deliverables Completed
- Added `rich>=13.0.0` to `requirements.txt`.
- Added `rich>=13.0.0` to `pyproject.toml` because `uv add rich` could not complete in the network-restricted sandbox.
- Added `Dashboard` with a non-blocking daemon thread, stop event, and clean shutdown.
- Added Rich `Layout`, `Panel`, `Table`, and `Live` rendering with graceful fallback when Rich is unavailable.
- Added dashboard data collection for agent statuses, provider health, queue counts, completed-today count, and recent decisions.
- Added `projectos run --dashboard` to start the dashboard alongside the existing ProjectOS runtime.
- Preserved existing plain `projectos run` output by default.
- Added dashboard unit tests that avoid rendering and validate component data fetching.

## Decisions Made
- Dashboard rendering is optional at import and runtime so ProjectOS commands still work when Rich is not installed.
- `Dashboard.run()` starts the Rich live display on a daemon thread to keep agent execution non-blocking.
- Agent rows use persisted runtime status when available and fall back to live queue activity otherwise.
- Completed-today is derived from same-day decision records because no separate completed task counter exists yet.

## Human Review
- `uv add rich` was attempted twice. The first attempt failed due a read-only default uv cache, and the retry with `UV_CACHE_DIR=/tmp/uv-cache` failed because external network access is unavailable.
- `uv.lock` was not updated for Rich because dependency resolution could not reach PyPI.
- Existing uncommitted files from prior task work remain in the worktree and were not reverted.

## Next Task Dependency Check
- TASK_18 can proceed after Rich is resolved or installed in an environment with package access.
