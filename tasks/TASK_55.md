# TASK_55: Pre-Write Validator + Token Protection

## Engineering Context

Aryan's biggest concern: garbage output burning tokens.

Current system: agent writes → quality gate evaluates → maybe escalate
Problem: tokens already burned, file already written

This task reverses that: validate → if valid write → if invalid discard

Three types of garbage to catch:
1. Syntax invalid Python (ast.parse fails)
2. Scope creep (output > 2x original or > 150 lines for new file)
3. Task mismatch (output is clearly unrelated to task description)

Rule 3 is the most important. If PlanningAgent was asked to "add a
health check endpoint" and returns a complete authentication system —
that's hallucinated scope. Discard immediately.

## Pre-conditions
Read agents/code_writing_agent.py, agents/docs_agent.py,
agents/test_agent.py completely.
Read core/evaluation/quality_gate.py.
Read AGENTS.md.

## Deliverables

### 1. core/pre_write_validator.py

@dataclass
class ValidationResult:
  valid: bool
  reason: str  (empty string if valid)
  check_name: str  (which check failed)
  original_size: int  (lines in original file, 0 if new)
  output_size: int  (lines in proposed output)
  action: str  (WRITE, DISCARD, RETRY_ONCE)

class PreWriteValidator:
  """
  Validates agent output BEFORE any file is written.
  
  Three checks in order (fail-fast):
  1. Syntax check (for Python files only)
  2. Size check (output must be reasonable relative to task)
  3. Relevance check (output must relate to task description)
  """
  
  MAX_NEW_FILE_LINES = 150
  MAX_SIZE_RATIO = 2.5  (output can't be 2.5x larger than original)
  
  __init__(
    max_new_file_lines: int = 150,
    max_size_ratio: float = 2.5
  )
  
  validate(
    proposed_content: str,
    task_description: str,
    target_file_path: str,
    existing_content: Optional[str] = None
  ) -> ValidationResult:
  
  CHECK 1 — Syntax (Python files only):
    If target_file_path.endswith(".py"):
      Try ast.parse(proposed_content)
      On SyntaxError → ValidationResult(valid=False, 
        reason="Syntax error: {error}", 
        check_name="syntax",
        action="RETRY_ONCE")
  
  CHECK 2 — Size:
    output_lines = len(proposed_content.splitlines())
    If existing_content is None:
      If output_lines > MAX_NEW_FILE_LINES:
        Return ValidationResult(valid=False,
          reason=f"Output {output_lines} lines exceeds {MAX_NEW_FILE_LINES} limit",
          check_name="size",
          action="DISCARD")
    Else:
      original_lines = len(existing_content.splitlines())
      ratio = output_lines / max(original_lines, 1)
      If ratio > MAX_SIZE_RATIO:
        Return ValidationResult(valid=False,
          reason=f"Output {ratio:.1f}x larger than original",
          check_name="size_ratio",
          action="DISCARD")
  
  CHECK 3 — Relevance:
    Extract key nouns from task_description (split, lowercase, 
    filter stopwords, keep words > 4 chars).
    
    If len(key_nouns) < 2: skip relevance check (too vague to check)
    
    For each key_noun:
      Check if noun appears in proposed_content (case-insensitive)
    
    match_rate = matching_nouns / total_key_nouns
    If match_rate < 0.20:  (less than 20% of task keywords appear)
      Return ValidationResult(valid=False,
        reason=f"Output may not match task: {match_rate:.0%} keyword match",
        check_name="relevance",
        action="DISCARD")
  
  All checks pass → ValidationResult(valid=True, action="WRITE")
  
  retry_with_constraint(
    original_prompt: str,
    validation_result: ValidationResult
  ) -> str:
    Builds a constrained retry prompt based on what failed:
    
    If syntax:
      f"{original_prompt}\n\nCRITICAL: Previous output had syntax error: 
        {validation_result.reason}. Output valid Python only."
    
    If size:
      f"{original_prompt}\n\nCRITICAL: Output must be under 
        {self.MAX_NEW_FILE_LINES} lines. Be concise."
    
    If relevance:
      f"{original_prompt}\n\nCRITICAL: Output must specifically address: 
        {task_description}. Stay focused."

### 2. Update agents/code_writing_agent.py

In handle():
  After model returns output:
  
  validator = PreWriteValidator()
  result = validator.validate(
    proposed_content=model_output,
    task_description=event.payload.get("task_description", ""),
    target_file_path=event.payload.get("file_path", ""),
    existing_content=existing_file_content
  )
  
  If result.action == "WRITE":
    Proceed with file write (existing behavior)
  
  If result.action == "RETRY_ONCE":
    Log: "Pre-write validation failed: {result.reason}. Retrying once."
    retry_prompt = validator.retry_with_constraint(original_prompt, result)
    retry_output = self.model_provider.complete(retry_prompt, ...)
    
    retry_result = validator.validate(retry_output, ...)
    If retry_result.action == "WRITE":
      Write the retry output
    Else:
      DO NOT write anything
      Log: "Retry also failed validation. Task discarded."
      Return AgentResult(
        success=False,
        output={"validation_failed": True, "reason": retry_result.reason},
        escalate=True,
        escalation_reason=f"Output failed validation twice: {retry_result.reason}"
      )
  
  If result.action == "DISCARD":
    DO NOT write anything
    DO NOT retry (size/relevance issues need human review)
    Log: "Output discarded: {result.reason}"
    Return AgentResult(
      success=False,
      output={"discarded": True, "reason": result.reason},
      escalate=True,
      escalation_reason=f"Output discarded: {result.reason}"
    )

### 3. Daily token budget alert

Add to core/observability/token_budget.py:

  check_daily_threshold_alert(
    agent_name: str,
    threshold_pct: float = 0.60
  ) -> Optional[str]:
    usage_today = get_daily_usage(agent_name)
    daily_limit = get_budget(agent_name)["daily"]
    pct_used = usage_today / daily_limit
    If pct_used >= threshold_pct:
      Return (
        f"⚠️ Token alert: {agent_name} used {pct_used:.0%} of daily budget. "
        f"Running in conservative mode (reduced context, shorter outputs)."
      )
    Return None
  
  conservative_mode_active(agent_name: str) -> bool:
    Returns True if agent is above 60% daily usage.

Add conservative mode to CodeWritingAgent and CodeReviewAgent:
  If token_budget.conservative_mode_active(self.name):
    Reduce max_context_tokens by 50%
    Set max_tokens completion to 500 instead of 1000
    Log: "Conservative mode active for {self.name}"

### 4. tests/test_pre_write_validator.py
  - test_valid_python_passes_syntax_check
  - test_invalid_python_fails_syntax_check
  - test_new_file_over_150_lines_discarded
  - test_existing_file_2x_ratio_discarded
  - test_relevant_output_passes_relevance_check
  - test_irrelevant_output_fails_relevance_check
  - test_retry_prompt_includes_failure_reason
  - test_vague_task_skips_relevance_check
  - test_non_python_file_skips_syntax_check
  - test_code_writing_agent_discards_on_validation_failure
  - test_code_writing_agent_retries_on_syntax_error
  - test_conservative_mode_reduces_token_limits

## Constraints
- PreWriteValidator NEVER makes model calls — pure logic only
- Relevance check is heuristic only — false positives acceptable,
  false negatives are not (better to flag than to miss garbage)
- DISCARD action never retries — only RETRY_ONCE retries
- Total validation time must be < 50ms (pure Python, no I/O)
- Keep MAX_NEW_FILE_LINES and MAX_SIZE_RATIO configurable via
  config/projectos.yaml under new section: validation:

## Verification
Full test suite. Write TASK_55_RESULT.md. Update tasks/README.md.
