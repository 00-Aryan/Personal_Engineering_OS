# TASK_04: Planning Agent

## Pre-conditions
Read core/base_agent.py, core/events.py, core/clone_agent.py, 
config/models.yaml before writing any code.

## Role
You are a Staff Engineer implementing the Planning Agent.
This agent receives a feature idea or task description and converts 
it into a structured, actionable backlog. It must think like a 
senior product + engineering hybrid.

## Deliverables

### 1. agents/planning_agent.py

Implement PlanningAgent(BaseAgent):

**System Prompt for Model**
The model receives this system context on every call:
"You are a senior staff engineer and product strategist.
You receive a feature description and must decompose it into 
engineering tasks. Output must be valid JSON only, no markdown.
Each task must have: id, title, type (feature/bug/refactor/test/docs),
priority (HIGH/MEDIUM/LOW), estimated_complexity (S/M/L/XL),
dependencies (list of task ids), acceptance_criteria (list of strings),
agent_assignment (which agent should execute this),
blocked_by (null or description of blocker)."

**handle() method**
Input: AgentEvent with event_type=NEW_FEATURE or MANUAL_TRIGGER
payload must contain: description (str), project_context (str, optional)

Process:
1. Build prompt from payload.description
2. Call model_provider.complete() 
3. Parse JSON response into list of Task dataclasses
4. Write tasks to backlog.md in structured markdown
5. Emit BACKLOG_CHANGED event for each new task
6. Return AgentResult with task list in output

**Task dataclass** (define in agents/planning_agent.py):
id, title, type, priority, complexity, dependencies, 
acceptance_criteria, agent_assignment, blocked_by, created_at, status

**backlog.md format**:
# ProjectOS Backlog
Last updated: [timestamp]

## HIGH Priority
### [task_id] [title]
- Type: [type]
- Complexity: [complexity]  
- Agent: [agent_assignment]
- Acceptance: [criteria as checklist]
- Dependencies: [list]
- Status: [PENDING/IN_PROGRESS/DONE/BLOCKED]

### 2. tests/test_planning_agent.py
Tests using mocked model provider returning valid JSON:
- test_handle_new_feature_creates_backlog
- test_backlog_md_written_correctly
- test_task_json_parse_valid
- test_task_json_parse_invalid_graceful (malformed JSON → log error, 
  return failure result, do not crash)
- test_emits_backlog_changed_event

## Constraints
- If model returns invalid JSON, log error and return 
  AgentResult(success=False) — never crash
- backlog.md is appended, never overwritten (new tasks added)
- Task IDs must be deterministic: PLAN-[YYYYMMDD]-[sequence_number]
- Never hardcode model name — always read from config/models.yaml

## Verification
Full test suite must pass. Report total count.

## Result Template → TASK_04_RESULT.md
