# TASK_09: Integration — Wire Everything Through Clone

## This Is The Most Important Task

## Pre-conditions
Read ALL files in core/ and agents/ before writing any code.
Every component exists as a stub or full implementation.
This task connects them.

## Deliverables

### 1. core/agent_registry.py

class AgentRegistry:
  Holds all agent instances keyed by name.
  Provides get(agent_name) → BaseAgent
  Provides register(name, agent_instance)
  Provides list_all() → Dict[str, BaseAgent]

### 2. core/projectos.py (Main Orchestrator)

class ProjectOS:
  __init__(config_path="config/models.yaml"):
    - Load config
    - Initialize all providers from config
    - Initialize all 6 agents with correct providers
    - Register all agents in AgentRegistry
    - Initialize CloneAgent with registry reference
    - Initialize TriggerSystem watching current directory
    - Initialize TaskQueue(max_workers=4)

  start():
    - Start TriggerSystem
    - Start background thread reading from trigger queue
    - For each event from queue → clone_agent.handle(event)
    - Clone dispatches to task queue
    - Run until stop() called

  stop():
    - Graceful shutdown: TriggerSystem, TaskQueue, log final status

### 3. Update core/clone_agent.py
Add agent_registry parameter to __init__
Update dispatch() to get actual agent instances from registry
Submit dispatched events to task_queue, not just return list

### 4. Update cli/main.py
projectos run command → instantiate ProjectOS, call start()

### 5. tests/test_integration.py
Full integration test (mocked model providers):
- test_code_change_triggers_review_and_tests:
  Create temp .py file, modify it, verify CODE_CHANGED event 
  flows through Clone → CodeReview + TestAgent run in parallel
- test_blocked_task_resumes_after_permission:
  Emit PERMISSION_BLOCKED event, verify independent work starts,
  emit PERMISSION_GRANTED, verify blocked task resumes
- test_full_feature_flow:
  MANUAL_TRIGGER with new feature → Planning → backlog.md created 
  → BACKLOG_CHANGED → Clone routes to CodeWriting

## Constraints
- All model calls mocked in integration tests
- Real file system used (tmp_path)
- No test should take more than 10 seconds

## Verification
Full test suite including integration tests.
python3 -c "from core.projectos import ProjectOS; print('OK')"

## Result Template → TASK_09_RESULT.md
