# TASK_54a: Project Context — Core Module + Tests

## Engineering Context

Every agent currently uses generic prompts that produce generic output.
This subtask builds only the data layer: the module that reads a
project_description.md file and produces a structured ProjectContext.

No agents are touched here. No wiring. No CLI.
Just the module and its tests.

TASK_54b wires it into agents.
TASK_54c wires it into projectos.py and adds CLI commands.

## Pre-conditions
Read core/base_agent.py (understand how agents use system prompts).
Read core/config_loader.py (understand config patterns in this codebase).
Read AGENTS.md.

## Deliverables

### 1. core/project_context.py

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

@dataclass
class ProjectContext:
    project_name: str
    description: str
    tech_stack: List[str]
    primary_language: str
    domain: str
    key_files: List[str]
    conventions: List[str]
    constraints: List[str]
    context_file_path: str

CONTEXT_FILENAMES = [
    "project_description.md",
    "project_context.md",
    ".projectos/context.md",
]

WORD_LIMIT = 2000

class ProjectContextLoader:
    """
    Loads project context from a markdown file in the project root.

    Supported filenames (checked in order):
      project_description.md
      project_context.md
      .projectos/context.md

    Expected markdown format:
      # Project Name
      ## Description
      ## Tech Stack
      ## Domain
      ## Key Files
      ## Conventions
      ## Constraints
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def load(self) -> Optional[ProjectContext]:
        """Parse the first found context file. Return None on any error."""
        ...

    def create_template(self, output_path: Path) -> None:
        """Write a blank project_description.md template to output_path."""
        ...

    @staticmethod
    def to_system_prompt_injection(context: ProjectContext) -> str:
        """Return a formatted block for injection into agent system prompts."""
        ...
```

Implementation rules:
- `load()` NEVER raises — return None on any parse error or missing file
- If context file word count exceeds WORD_LIMIT, truncate to first WORD_LIMIT words before parsing
- Parse each `## Section` header into the matching dataclass field
- Tech Stack, Key Files, Conventions, Constraints are lists (one item per `- ` bullet)
- primary_language = first item in tech_stack (empty string if none)
- `to_system_prompt_injection` output format:

```
--- PROJECT CONTEXT ---
Project: {project_name}
Domain: {domain}
Tech Stack: {tech_stack joined by ", "}
Key Files: {key_files joined by ", "}
Conventions: {conventions joined by " | "}
Constraints: {constraints joined by " | "}
--- END CONTEXT ---
```

### 2. tests/test_project_context.py

All tests use pytest `tmp_path` fixture. No mocking needed — pure file I/O.

- `test_load_returns_none_when_no_file`
- `test_load_parses_description_section`
- `test_load_parses_tech_stack_list`
- `test_load_returns_none_on_malformed_file`
- `test_to_system_prompt_injection_format`
- `test_create_template_writes_valid_file`
- `test_load_finds_project_context_md_filename`
- `test_load_truncates_files_over_word_limit`

## Constraints
- `core/project_context.py` must be under 120 lines
- No new dependencies — stdlib only (pathlib, dataclasses, re)
- Do NOT touch any agent files or base_agent.py in this task
- Do NOT touch core/projectos.py in this task

## Verification
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest tests/test_project_context.py -q --timeout=30
Then run full suite to confirm no regressions:
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30
Write TASK_54a_RESULT.md. Update tasks/README.md.
