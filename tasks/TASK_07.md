# TASK_07: Architecture Agent + Trigger System

## Deliverables

### 1. agents/architecture_agent.py

Implement ArchitectureAgent(BaseAgent):

**System Prompt**:
"You are a principal systems architect with 15 years of experience.
You challenge design decisions before they are built.
For every architecture question, output JSON with:
decision_required (string),
risks (list of strings),
alternatives (list of {name, pros, cons}),
recommendation (string),
adr_content (full ADR markdown as string),
confidence (HIGH/MEDIUM/LOW)"

**handle() method**
Input: ARCHITECTURE_QUESTION event
payload: question, context, affected_components

Process:
1. Call model with question + context
2. Parse JSON response
3. Write ADR to docs/adr/ADR-[auto_number]-[slug].md
4. If confidence=LOW → escalate=True
5. Emit result with recommendation

### 2. core/trigger_system.py

Implement TriggerSystem using watchdog library.

Class TriggerSystem:
  __init__(watch_dir, event_dispatcher)
  start() → starts background file watcher thread
  stop() → clean shutdown
  
Internal FileChangeHandler(FileSystemEventHandler):
  on_modified(event):
    - Ignore: __pycache__, .pyc, .git, test files
    - For .py files → create AgentEvent(CODE_CHANGED)
      payload: file_path, modified_at
    - Put event on dispatcher queue immediately
    - Never block

Event dispatcher is a simple queue.Queue passed in at init.
TriggerSystem does NOT dispatch to agents directly.
Clone Agent reads from the queue.

### 3. tests/test_trigger_system.py
- test_py_file_change_emits_code_changed_event
- test_pycache_ignored
- test_test_files_not_triggered (files starting with test_)
- test_stop_cleans_up_watcher_thread
Use tmp_path pytest fixture, create real temp files.

### 4. requirements.txt
Add: watchdog>=3.0.0

## Verification
Full test suite. pip install watchdog before running.
Import check: from core.trigger_system import TriggerSystem

## Result Template → TASK_07_RESULT.md
