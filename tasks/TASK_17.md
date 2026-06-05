# TASK_17: Rich Terminal Dashboard

## Purpose
Replace bare CLI output with a live terminal dashboard showing
all agent activity, queue status, and decisions in real time.

## Pre-conditions
Read cli/main.py, core/task_queue.py, core/decision_log.py fully.
Add rich to requirements.txt before writing any code.

## Deliverables

### 1. Add dependency
  uv add rich
  Add to requirements.txt: rich>=13.0.0

### 2. cli/dashboard.py

class Dashboard:
  __init__(
    task_queue: TaskQueue,
    decision_logger: DecisionLogger,
    persistence_manager: PersistenceManager,
    health_monitor: ProviderHealthMonitor,
    refresh_interval: float = 1.0
  )
  
  run() → starts Rich Live display, refreshes every interval
  stop() → clean shutdown
  
  Layout (using Rich Layout and Table):
  
  ┌─ ProjectOS Dashboard ──────────────────────────────┐
  │ Status: RUNNING | Uptime: 00:04:32 | Tasks: 3      │
  ├─ Agents ──────────────────┬─ Providers ────────────┤
  │ clone      ACTIVE         │ gemini-flash  ✓ Healthy │
  │ planning   IDLE           │ openrouter    ✓ Healthy │
  │ code_write WORKING        │ ollama        ✗ Down    │
  │ code_review IDLE          │                        │
  ├─ Queue ───────────────────┴────────────────────────┤
  │ Pending: 2  Blocked: 1  Completed today: 14        │
  ├─ Recent Decisions (last 5) ────────────────────────┤
  │ 12:04:01 clone AUTONOMOUS  code_review dispatched  │
  │ 12:03:58 clone ESCALATE    new_dependency detected │
  └────────────────────────────────────────────────────┘

### 3. Update cli/main.py
  projectos run command: 
    Add --dashboard flag.
    If --dashboard: start Dashboard alongside ProjectOS.
    Default: existing plain log output.

### 4. tests/test_dashboard.py
  Test without rendering (unit test logic only):
  - test_dashboard_initializes_without_error
  - test_dashboard_stop_does_not_raise
  - test_layout_data_fetched_from_components

## Constraints
- Dashboard must not block agent execution
- Runs in separate thread
- If rich is not installed → projectos run works without dashboard
  (graceful degradation)

## Verification
Full test suite. Write TASK_17_RESULT.md. Update tasks/README.md.
