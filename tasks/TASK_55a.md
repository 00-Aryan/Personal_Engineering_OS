# TASK_55a: PreWriteValidator — Core Module + Tests

## Engineering Context

Before any agent writes a file, output must pass three checks:
1. Syntax valid Python (ast.parse)
2. Size not excessive (relative to original or absolute for new files)
3. Content relevant to the task description (keyword heuristic)

This subtask builds only the validator module and its tests.
No agent files are touched here.

TASK_55b wires it into CodeWritingAgent.
TASK_55c adds the token budget conservative mode.

## Pre-conditions
Read AGENTS.md.
Read core/evaluation/quality_gate.py (understand existing validation patterns).

That is all. Do NOT read agent files in this task.

## Deliverables

### 1. core/pre_write_validator.py

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import ast

STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "have",
    "will", "your", "are", "not", "but", "been", "has", "into",
}

@dataclass
class ValidationResult:
    valid: bool
    reason: str          # empty string if valid
    check_name: str      # "syntax" | "size" | "size_ratio" | "relevance" | ""
    original_size: int   # lines in original file, 0 if new
    output_size: int     # lines in proposed output
    action: str          # "WRITE" | "DISCARD" | "RETRY_ONCE"

class PreWriteValidator:
    """
    Validates agent output before any file is written.

    Three checks run in order (fail-fast):
    1. Syntax   — Python files only; SyntaxError → RETRY_ONCE
    2. Size     — new file > MAX_NEW_FILE_LINES or ratio > MAX_SIZE_RATIO → DISCARD
    3. Relevance — keyword match rate < 0.20 → DISCARD

    No model calls. Pure logic only. Must complete in < 50ms.
    Limits are configurable; defaults match config/projectos.yaml validation: section.
    """

    MAX_NEW_FILE_LINES: int = 150
    MAX_SIZE_RATIO: float = 2.5

    def __init__(
        self,
        max_new_file_lines: int = 150,
        max_size_ratio: float = 2.5,
    ) -> None: ...

    def validate(
        self,
        proposed_content: str,
        task_description: str,
        target_file_path: str,
        existing_content: Optional[str] = None,
    ) -> ValidationResult: ...

    def retry_with_constraint(
        self,
        original_prompt: str,
        validation_result: ValidationResult,
        task_description: str = "",
    ) -> str:
        """
        Return a modified prompt that constrains the model based on
        what check failed.  Does NOT make any model call.
        """
        ...
```

Implementation rules:

**validate() — check 1 (syntax):**
- Only runs when `target_file_path.endswith(".py")`
- `ast.parse(proposed_content)` — on `SyntaxError` return:
  `ValidationResult(valid=False, reason="Syntax error: {e}", check_name="syntax", action="RETRY_ONCE", ...)`

**validate() — check 2 (size):**
- `output_lines = len(proposed_content.splitlines())`
- If `existing_content is None`:
  - If `output_lines > self.max_new_file_lines` → DISCARD, check_name="size"
- Else:
  - `ratio = output_lines / max(len(existing_content.splitlines()), 1)`
  - If `ratio > self.max_size_ratio` → DISCARD, check_name="size_ratio"

**validate() — check 3 (relevance):**
- Extract key nouns: `task_description.lower().split()`, filter `STOPWORDS`, keep words `len > 4`
- If `len(key_nouns) < 2`: skip check (too vague)
- `match_rate = sum(1 for n in key_nouns if n in proposed_content.lower()) / len(key_nouns)`
- If `match_rate < 0.20` → DISCARD, check_name="relevance"

All checks pass → `ValidationResult(valid=True, check_name="", reason="", action="WRITE", ...)`

**retry_with_constraint():**
- `syntax`: append `"\n\nCRITICAL: Previous output had syntax error: {reason}. Output valid Python only."`
- `size` or `size_ratio`: append `"\n\nCRITICAL: Output must be under {max_new_file_lines} lines. Be concise."`
- `relevance`: append `"\n\nCRITICAL: Output must specifically address: {task_description}. Stay focused."`

### 2. Add to config/projectos.yaml

Under a new top-level `validation:` section:
```yaml
validation:
  max_new_file_lines: 150
  max_size_ratio: 2.5
```

### 3. tests/test_pre_write_validator.py

Nine tests — no mocking needed (pure logic):

- `test_valid_python_passes_syntax_check`
- `test_invalid_python_fails_syntax_check` — action must be RETRY_ONCE
- `test_new_file_over_150_lines_discarded` — action must be DISCARD
- `test_existing_file_size_ratio_discarded` — 3x original → DISCARD
- `test_relevant_output_passes_relevance_check`
- `test_irrelevant_output_fails_relevance_check` — action must be DISCARD
- `test_vague_task_skips_relevance_check` — task with < 2 key nouns passes
- `test_non_python_file_skips_syntax_check` — .md file with invalid Python passes syntax
- `test_retry_prompt_includes_failure_reason`

## Constraints
- `core/pre_write_validator.py` must be under 100 lines
- No new dependencies — stdlib only (ast, dataclasses)
- Do NOT touch any agent files in this task
- DISCARD action never triggers a retry — that logic is in the agent (TASK_55b)

## Verification
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest tests/test_pre_write_validator.py -q --timeout=30
Then full suite: UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30
Write TASK_55a_RESULT.md. Update tasks/README.md.
