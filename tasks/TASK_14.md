# TASK_14: Safety Policies for Code Writes

## Problem
CodeWritingAgent writes to any path in payload without validation.
A bad model response or malicious event could overwrite critical files.
No diff preview exists before overwrite. No path allowlist enforced.

## Pre-conditions
Read agents/code_writing_agent.py and core/events.py fully.

## Deliverables

### 1. core/safety.py

class SafetyPolicy:
  __init__(
    allowed_dirs: List[Path],
    protected_files: List[Path],
    max_file_size_bytes: int = 100_000,
    require_diff_preview: bool = True
  )
  
  validate_write(file_path: Path, content: str) -> SafetyResult
  
  SafetyResult is a dataclass:
    allowed: bool
    reason: str
    diff_preview: Optional[str]  (unified diff vs existing file)
    warnings: List[str]
  
  Rules (all must pass for allowed=True):
  1. file_path must be inside one of allowed_dirs
  2. file_path must not be in protected_files
  3. len(content.encode()) must not exceed max_file_size_bytes
  4. If file exists and content removes >50% of lines → warning
  5. If file is in core/ → always generate diff_preview

class DefaultSafetyPolicy(SafetyPolicy):
  Preconfigured with:
  allowed_dirs: [agents/, tests/, docs/, reviews/]
  protected_files: [core/base_agent.py, core/events.py, 
                    core/model_provider.py, config/models.yaml,
                    AGENTS.md]
  require_diff_preview: True for core/, False for others

### 2. Update agents/code_writing_agent.py
  Accept safety_policy: Optional[SafetyPolicy] = None param.
  Before any file write:
    result = safety_policy.validate_write(path, content)
    If not result.allowed → log reason, return AgentResult(success=False)
    If result.warnings → log warnings, continue but escalate=True
    If result.diff_preview → log diff to decisions.log

### 3. Update core/projectos.py
  Initialize DefaultSafetyPolicy.
  Pass to CodeWritingAgent on init.

### 4. tests/test_safety.py
  - test_write_to_allowed_dir_passes
  - test_write_outside_allowed_dir_blocked
  - test_write_to_protected_file_blocked
  - test_oversized_content_blocked
  - test_large_deletion_generates_warning
  - test_core_file_generates_diff_preview
  - test_nonexistent_file_no_diff_generated
  - test_default_policy_blocks_core_base_agent

## Constraints
- SafetyPolicy must be injectable (not hardcoded in agent)
- diff_preview uses difflib.unified_diff (stdlib only)
- Tests use tmp_path — no real project files touched
- Never raise from validate_write — always return SafetyResult

## Verification
Full test suite. Write TASK_14_RESULT.md. Update tasks/README.md.
