# TASK_08: Task Queue + CLI

## Deliverables

### 1. core/task_queue.py

Implement TaskQueue for parallel, non-blocking execution:

class TaskQueue:
  __init__(max_workers=4)
  submit(event, target_agent) → submits to ThreadPoolExecutor
  submit_batch(events_agents pairs) → submits all simultaneously  
  get_pending_count() → int
  get_blocked() → List[AgentEvent]
  unblock(correlation_id) → resumes deferred task
  shutdown(wait=True)

Rules:
- Uses concurrent.futures.ThreadPoolExecutor internally
- Blocked tasks stored in dict keyed by correlation_id
- unblock() resubmits with same event + PERMISSION_GRANTED context
- Never raises exception to caller — log and continue

### 2. cli/main.py

Use Click library. Implement these commands exactly:

projectos status
  → shows all agents, their current model (from config), 
     pending tasks count, last activity timestamp

projectos model <agent_name> <model_name>
  → updates config/models.yaml
  → prints confirmation: "Agent [name] now uses [model]"
  → no restart required

projectos approve
  → reads escalation_queue.md
  → shows pending items interactively
  → marks item as APPROVED or REJECTED in the file

projectos backlog
  → prints backlog.md to terminal with color coding:
    HIGH=red, MEDIUM=yellow, LOW=green

projectos review <file_path>
  → manually triggers CODE_CHANGED event for that file
  → submits to task queue immediately

projectos run
  → starts daemon: trigger system + clone agent + task queue
  → runs until Ctrl+C
  → graceful shutdown on SIGINT

### 3. requirements.txt
Add: click>=8.0.0

### 4. tests/test_cli.py
Use click.testing.CliRunner:
- test_status_command_runs
- test_model_command_updates_config
- test_backlog_command_prints_markdown
- test_review_command_emits_event

## Verification
Full suite. CLI help command works: python3 -m cli.main --help

## Result Template → TASK_08_RESULT.md
