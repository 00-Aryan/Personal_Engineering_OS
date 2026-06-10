# TASK_55c: Token Budget Conservative Mode

## Engineering Context

When an agent has used ≥ 60% of its daily token budget, it should
automatically reduce context size and output length to stretch the
remaining budget through the day.

This task adds that behaviour to the token budget manager and wires
it into CodeWritingAgent and CodeReviewAgent.

## Pre-conditions
Read TASK_55b_RESULT.md.
Read core/observability/token_budget.py fully.
Read agents/code_writing_agent.py (after TASK_55b changes).
Read agents/code_review_agent.py.
Read AGENTS.md.

## Deliverables

### 1. Add two methods to core/observability/token_budget.py

```python
def check_daily_threshold_alert(
    self,
    agent_name: str,
    threshold_pct: float = 0.60,
) -> Optional[str]:
    """
    Return a warning string if agent has used >= threshold_pct of its
    daily budget, otherwise return None.
    """
    usage = self.get_daily_usage(agent_name)
    budget = self.get_budget(agent_name).get("daily", 0)
    if budget == 0:
        return None
    pct = usage / budget
    if pct >= threshold_pct:
        return (
            f"⚠️ Token alert: {agent_name} used {pct:.0%} of daily budget. "
            f"Running in conservative mode (reduced context, shorter outputs)."
        )
    return None

def conservative_mode_active(self, agent_name: str) -> bool:
    """Return True if agent is at or above 60% daily budget usage."""
    return self.check_daily_threshold_alert(agent_name) is not None
```

### 2. Update agents/code_writing_agent.py

At the start of `handle()`, before building context:

```python
if self.token_budget and self.token_budget.conservative_mode_active(self.name):
    self.logger.info(f"Conservative mode active for {self.name}")
    max_context_tokens = max_context_tokens // 2
    completion_max_tokens = 500
else:
    completion_max_tokens = 1000
```

Use `completion_max_tokens` when calling `model_provider.complete()`.

### 3. Update agents/code_review_agent.py

Same pattern as above — add conservative mode check at the start
of `handle()` and use `completion_max_tokens` in the model call.

### 4. tests/test_observability/test_token_budget.py — add tests

Add to existing test file:

- `test_conservative_mode_inactive_below_threshold`
  Set daily usage to 50% of budget. Assert `conservative_mode_active` returns False.

- `test_conservative_mode_active_at_threshold`
  Set daily usage to 60% of budget. Assert `conservative_mode_active` returns True.

- `test_check_daily_threshold_alert_returns_string`
  Set usage to 70%. Assert return value is a non-empty string containing "conservative".

- `test_conservative_mode_reduces_token_limits`
  Mock token_budget on CodeWritingAgent at 65% usage.
  Assert model call uses max_tokens=500.

## Constraints
- Only touch token_budget.py, code_writing_agent.py, code_review_agent.py,
  and the token budget test file
- conservative_mode_active uses the existing get_daily_usage / get_budget
  methods — do not add new storage
- If self.token_budget is None on an agent: skip the check silently

## Verification
UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30
Write TASK_55c_RESULT.md. Update tasks/README.md.
