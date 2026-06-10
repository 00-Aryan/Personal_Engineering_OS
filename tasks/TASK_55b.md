# TASK_55b: Wire PreWriteValidator into CodeWritingAgent

## Engineering Context

TASK_55a built PreWriteValidator.
This task wires it into CodeWritingAgent so garbage output is
caught before any file is written.

Only ONE agent file is touched: agents/code_writing_agent.py.

## Pre-conditions
Read TASK_55a_RESULT.md (confirms PreWriteValidator API).
Read agents/code_writing_agent.py fully.
Read core/events.py (need valid EventType values for tests).
Read tests/test_code_agents.py (understand existing mock/event patterns).
Read AGENTS.md.

## Deliverables

### 1. Update agents/code_writing_agent.py

Add import at the top:
  from core.pre_write_validator import PreWriteValidator

In `handle()`, after the model returns output and before any file write:

```python
validator = PreWriteValidator()
existing_content = Path(target_file_path).read_text() if Path(target_file_path).exists() else None
result = validator.validate(
    proposed_content=model_output,
    task_description=event.payload.get("task_description", ""),
    target_file_path=event.payload.get("file_path", ""),
    existing_content=existing_content,
)

if result.action == "RETRY_ONCE":
    self.logger.warning(f"Pre-write validation failed: {result.reason}. Retrying once.")
    retry_prompt = validator.retry_with_constraint(original_prompt, result,
                       task_description=event.payload.get("task_description", ""))
    model_output = self.model_provider.complete(retry_prompt, system_prompt=system_prompt, ...)
    result = validator.validate(model_output, ...)
    if result.action != "WRITE":
        self.logger.error("Retry also failed validation. Task discarded.")
        return AgentResult(
            success=False,
            output={"validation_failed": True, "reason": result.reason},
            escalate=True,
            escalation_reason=f"Output failed validation twice: {result.reason}",
        )

if result.action == "DISCARD":
    self.logger.warning(f"Output discarded: {result.reason}")
    return AgentResult(
        success=False,
        output={"discarded": True, "reason": result.reason},
        escalate=True,
        escalation_reason=f"Output discarded: {result.reason}",
    )

# result.action == "WRITE" — proceed with existing file write logic
```

### 2. tests/test_pre_write_validator.py — add agent integration tests

Add three more tests to the existing file:

- `test_code_writing_agent_proceeds_on_valid_output`
  Mock model to return valid Python. Assert file write is called.

- `test_code_writing_agent_discards_on_validation_failure`
  Mock model to return output with only 5% keyword match.
  Assert AgentResult.success == False and escalate == True.

- `test_code_writing_agent_retries_on_syntax_error`
  Mock model: first call returns invalid Python, second call returns valid Python.
  Assert file write IS called (retry succeeded).

## Constraints
- Only touch agents/code_writing_agent.py and tests/test_pre_write_validator.py
- The RETRY_ONCE path makes exactly one additional model call — no more
- The DISCARD path makes zero additional model calls
- All existing tests must still pass

## Verification
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30
Write TASK_55b_RESULT.md. Update tasks/README.md.
