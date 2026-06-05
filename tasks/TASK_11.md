# TASK_11: Durable Queue Persistence

## Problem
Queue state is in memory only. Blocked and pending tasks are lost 
on process exit. ProjectOS cannot resume work after restart.

## Pre-conditions
Read core/task_queue.py, core/clone_agent.py, core/events.py fully.

## Deliverables

### 1. core/persistence.py

class PersistenceManager:
  __init__(state_dir: Path)
  
  save_blocked_task(event: AgentEvent) -> None
    Appends to state_dir/blocked_queue.json as newline-delimited JSON.
    Each line: full AgentEvent serialized with dataclasses.asdict().
    Write is atomic: write to .tmp, rename.
  
  load_blocked_tasks() -> List[AgentEvent]
    Reads blocked_queue.json, deserializes each line.
    Skips and logs malformed lines — never crashes.
    Returns empty list if file does not exist.
  
  clear_blocked_task(correlation_id: str) -> None
    Rewrites file excluding entries matching correlation_id.
    Atomic write.
  
  save_pending_event(event: AgentEvent) -> None
    Appends to state_dir/pending_queue.json (same format).
  
  load_pending_events() -> List[AgentEvent]
    Same pattern as blocked.
  
  clear_pending_event(event_id: str) -> None
    Rewrites file excluding entries matching event_id.
  
  snapshot_status(agents: Dict[str, str]) -> None
    Writes state_dir/last_status.json:
    {timestamp, agent_statuses, pending_count, blocked_count}

### 2. Update core/task_queue.py
  Add persistence_manager: Optional[PersistenceManager] = None param.
  On submit() → save_pending_event() if manager present.
  On task complete → clear_pending_event().
  On block → save_blocked_task() if manager present.
  On unblock → clear_blocked_task().

### 3. Update core/projectos.py
  Init PersistenceManager(state_dir=Path(".projectos_state")).
  Pass to TaskQueue.
  On start() → load_pending_events() and resubmit each to queue.
  On start() → load_blocked_tasks() and restore to blocked dict.
  Log how many tasks were restored on startup.

### 4. Update cli/main.py
  projectos status command: read last_status.json if exists,
  show last_seen timestamp, pending count, blocked count.

### 5. tests/test_persistence.py
  - test_save_and_load_blocked_task
  - test_clear_blocked_task_removes_only_matching
  - test_load_returns_empty_for_missing_file
  - test_malformed_line_skipped_not_crashed
  - test_save_and_load_pending_event
  - test_snapshot_status_writes_json
  - test_restart_restores_blocked_tasks (integration: save, 
    create new PersistenceManager, load, verify same event)

## Constraints
- state_dir must be created automatically if missing
- All writes atomic (tmp + rename)
- Never import TaskQueue from persistence (no circular imports)
- Use only stdlib: json, pathlib, dataclasses, uuid, datetime

## Verification
Full test suite. Import check: from core.persistence import PersistenceManager
Write TASK_11_RESULT.md. Update tasks/README.md.
