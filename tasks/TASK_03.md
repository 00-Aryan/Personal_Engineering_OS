# TASK_03: Clone Agent — Decision Engine + Dispatcher

## Pre-conditions
Read ALL files in core/ before writing any code.
Verify BaseAgent, AgentEvent, AgentResult, EventType all import cleanly.

## Role
You are implementing the most critical component of ProjectOS.
The Clone Agent is the supervisor. It receives every event from every 
agent and the trigger system. It decides autonomously for routine work,
escalates for important decisions, and never blocks parallel work.

## Deliverables

### 1. core/clone_agent.py

Implement CloneAgent(BaseAgent) with these four internal systems:

**Decision Engine**
A method classify_decision(event: AgentEvent) -> DecisionCategory
DecisionCategory is an Enum with: AUTONOMOUS, ESCALATE, DEFER_PARALLEL

AUTONOMOUS (handle silently, log only):
- event_type in [DOCS_UPDATED, TESTS_DONE, REVIEW_DONE] 
  with no escalate flag
- payload contains keys: formatting, minor_refactor, docstring, 
  comment, status_update

ESCALATE (write to escalation queue, notify user):
- AgentResult.escalate is True
- payload contains keys: new_dependency, breaking_change, 
  delete_file, architecture_change
- event affects more than 3 files simultaneously (check payload 
  for affected_files list length)

DEFER_PARALLEL (queue task, find independent work, plan reconnect):
- event.blocked_by is not None
- Any PERMISSION_BLOCKED event type

**Dispatcher**
A method dispatch(event: AgentEvent) -> List[AgentEvent]
Maps event types to target agents:

CODE_CHANGED     → [code_review, test_agent, docs_agent] in parallel
NEW_FEATURE      → [planning_agent]
CODE_WRITTEN     → [code_review_agent, test_agent] in parallel
REVIEW_DONE      → Clone evaluates, routes fixes to code_writing_agent
ARCHITECTURE_Q   → [architecture_agent]
BACKLOG_CHANGED  → Clone classifies task type, routes to correct agent
PERMISSION_BLOCK → defer current task, dispatch independent tasks
MANUAL_TRIGGER   → route based on payload.target_agent field

**Escalation Protocol**
A method escalate(event, reason) -> None
- Appends to escalation_queue.md with timestamp, event_id, reason
- Never blocks. Fire and forget.
- Logs to decisions.log

**Parallel Task Manager**
A method handle_blocked(event: AgentEvent) -> List[AgentEvent]
- Logs blocked task with its correlation_id to blocked_tasks.md
- Finds events in queue with no blocked_by dependency
- Returns those independent events for immediate dispatch
- Writes reconnection plan to blocked_tasks.md:
  "When PERMISSION_GRANTED for X, resume task Y with correlation Z"

**handle() method**
Orchestrates all four systems:
1. classify_decision(event)
2. If ESCALATE → escalate(), return result with escalate=True
3. If DEFER_PARALLEL → handle_blocked(), dispatch independent work
4. If AUTONOMOUS → dispatch(event), log decision, return result
All decisions logged to decisions.log with format:
[ISO_TIMESTAMP] [event_id] [decision_category] [reasoning]

### 2. decisions.log
Create empty file at project root.
Clone writes every decision here. Never deletes entries.

### 3. escalation_queue.md
Create empty file at project root with header:
# Escalation Queue
Items requiring Aryan's attention.
Format: | timestamp | event_id | reason | status |

### 4. blocked_tasks.md  
Create empty file at project root with header:
# Blocked Tasks
Tasks deferred due to permissions or dependencies.
Format: | task_id | blocked_by | correlation_id | reconnect_plan |

### 5. tests/test_clone_agent.py
Write unit tests for:
- test_classify_autonomous: DOCS_UPDATED event → AUTONOMOUS
- test_classify_escalate: event with new_dependency → ESCALATE
- test_classify_defer: event with blocked_by set → DEFER_PARALLEL
- test_dispatch_code_changed: CODE_CHANGED → 3 target agents
- test_dispatch_backlog: BACKLOG_CHANGED → correct agent
- test_handle_blocked_finds_independent_work
- test_escalation_writes_to_queue
- test_decisions_logged_for_every_handle_call
All tests use mocked model providers. No real API calls.

## Constraints
- CloneAgent must never call model provider for routine dispatching
- Model provider only used when Clone needs to REASON about ambiguous events
- No external dependencies beyond what already exists in requirements.txt
- decisions.log must be append-only, never overwritten
- All file writes must be atomic (write to temp, rename)

## Verification
Run full test suite. Report total test count.
Import check: from core.clone_agent import CloneAgent

## Result Template
Write TASK_03_RESULT.md with:
- Files created
- Test count (total, not just new)
- Any design decisions Clone made that deviate from spec
- Anything that needs human review
