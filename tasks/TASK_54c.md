# TASK_54c: Wire Project Context into ProjectOS + CLI Commands

## Engineering Context

TASK_54a built the module. TASK_54b wired it into agents.
This final subtask has two jobs:

1. Initialize ProjectContextLoader in core/projectos.py and pass it
   to every agent at startup — so context injection works end-to-end.

2. Add two CLI commands so Aryan can inspect and initialize context
   from the terminal.

## Pre-conditions
Read TASK_54a_RESULT.md.
Read TASK_54b_RESULT.md.
Read core/projectos.py — specifically _initialize_agents() and __init__().
Read cli/main.py — specifically how existing command groups are structured.
Read AGENTS.md.

## Deliverables

### 1. Update core/projectos.py

Add import at top:
  from core.project_context import ProjectContextLoader

In __init__, after self.project_root is set:
  self.context_loader = ProjectContextLoader(self.project_root)

In _initialize_agents(), pass context_loader to every agent constructor:
  Each agent that accepts context_loader= should receive self.context_loader.
  Pattern: SomeAgent(..., context_loader=self.context_loader)

That's all for projectos.py — no other changes.

### 2. Add CLI commands to cli/main.py

Add a `context` command group with two subcommands.
Follow the exact same pattern as existing command groups in the file.

```
projectos context show
```
  Load ProjectContextLoader from the current working directory.
  If context loads successfully: print the formatted injection string.
  If no file found: print "No project context found."
  If parse error: print "Context file found but could not be parsed."

```
projectos context init
```
  Call ProjectContextLoader.create_template(Path("project_description.md")).
  Print "Created project_description.md — fill in the sections and re-run."
  If file already exists: print "project_description.md already exists." and exit.

### 3. tests/test_project_context.py — add two more tests

Add to the existing test file from TASK_54a:

- `test_base_agent_injects_context_into_prompt`
  Create a tmp ProjectContextLoader with a valid context file.
  Create a BaseAgent subclass with SYSTEM_PROMPT = "hello {project_context}".
  Call build_system_prompt(self.SYSTEM_PROMPT).
  Assert the result contains "PROJECT CONTEXT".

- `test_base_agent_handles_missing_context_loader`
  Create BaseAgent with context_loader=None.
  Call build_system_prompt("hello {project_context}").
  Assert result == "hello " (placeholder replaced with empty string).

## Constraints
- Do not change any agent files — only projectos.py and cli/main.py
- CLI commands must handle missing files gracefully (no tracebacks)
- context_loader is passed to agents but agents already handle None
  gracefully (from TASK_54b) — no further guard logic needed here

## Verification
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30
Manual smoke: uv run --no-sync projectos context show
Write TASK_54c_RESULT.md. Update tasks/README.md.
