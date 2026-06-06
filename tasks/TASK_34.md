# TASK_34: Token Budget Manager

## Engineering Context

Every model call costs tokens. ProjectOS currently has no visibility
into token usage and no way to prevent runaway costs.

Problems this creates right now:
- CodeReviewAgent reviewing a 500-line file injects 2000 tokens of
  codebase context + 500 tokens of memories + the file itself =
  potential 4000-token prompt with no ceiling
- Consultation chains where Agent A asks Agent B which asks a model
  can double token usage per event with no visibility
- When free tier limits are hit, agents fail silently with no
  actionable error message

Token budget management is a production requirement for any system
that makes LLM calls. This task implements it properly.

## Pre-conditions
Read core/model_provider.py, core/intelligence/context_retriever.py,
core/intelligence/memory_manager.py, core/base_agent.py.
Read all agent files for their current prompt construction.

## Deliverables

### 1. core/observability/token_budget.py

@dataclass
class TokenUsageRecord:
  record_id: str  (UUID)
  timestamp: datetime
  agent_name: str
  operation: str  (e.g., "model_call", "embedding", "context_injection")
  provider: str
  prompt_tokens: int
  completion_tokens: int
  total_tokens: int
  estimated_cost_usd: float  (0.0 for free models)
  trace_id: Optional[str]
  event_id: Optional[str]

class TokenBudget:
  """
  Per-agent token budgets with hard limits and soft warnings.
  
  Budget levels:
  - soft_limit: warn when exceeded, continue
  - hard_limit: block call, return error result
  - daily_limit: cumulative limit per agent per day
  
  Token estimation (no tokenizer dependency):
  - Use len(text) // 4 as approximation (GPT-style 4 chars/token)
  - This is an estimate, not exact — acceptable for budget management
  """
  
  __init__(
    state_dir: Path,
    budgets: Optional[Dict[str, Dict]] = None
  )
  
  DEFAULT_BUDGETS = {
    "code_review": {
      "soft_limit_per_call": 3000,
      "hard_limit_per_call": 6000,
      "daily_limit": 100000
    },
    "code_writing": {
      "soft_limit_per_call": 3000,
      "hard_limit_per_call": 6000,
      "daily_limit": 100000
    },
    "planning": {
      "soft_limit_per_call": 2000,
      "hard_limit_per_call": 4000,
      "daily_limit": 50000
    },
    "architecture": {
      "soft_limit_per_call": 2000,
      "hard_limit_per_call": 4000,
      "daily_limit": 30000
    },
    "test": {
      "soft_limit_per_call": 3000,
      "hard_limit_per_call": 6000,
      "daily_limit": 80000
    },
    "docs": {
      "soft_limit_per_call": 1500,
      "hard_limit_per_call": 3000,
      "daily_limit": 40000
    },
    "clone": {
      "soft_limit_per_call": 1000,
      "hard_limit_per_call": 2000,
      "daily_limit": 200000
    },
    "default": {
      "soft_limit_per_call": 2000,
      "hard_limit_per_call": 4000,
      "daily_limit": 50000
    }
  }
  
  check_and_record(
    agent_name: str,
    prompt: str,
    operation: str = "model_call"
  ) -> BudgetCheckResult:
    Estimate tokens from prompt length.
    Check against soft and hard limits.
    Check daily cumulative usage.
    Return BudgetCheckResult.
  
  record_completion(
    agent_name: str,
    completion: str,
    trace_id: Optional[str] = None,
    event_id: Optional[str] = None
  ) -> TokenUsageRecord:
    Estimate completion tokens.
    Append to token_usage.jsonl.
    Update daily counter.
    Return record.
  
  @dataclass
  class BudgetCheckResult:
    allowed: bool
    estimated_tokens: int
    soft_limit_exceeded: bool
    hard_limit_exceeded: bool
    daily_limit_exceeded: bool
    warning_message: Optional[str]
    daily_used_today: int
    daily_limit: int
  
  get_daily_usage(agent_name: str, date: Optional[date] = None) -> int:
    Returns total tokens used by agent on given date (default today).
    Reads from token_usage.jsonl, filters by date.
  
  get_usage_summary(days: int = 7) -> Dict:
    Returns per-agent token usage over last N days.
    Format: {agent_name: {total_tokens, total_calls, avg_per_call,
                          daily_breakdown: {date: tokens}}}
  
  trim_context_to_budget(
    context: str,
    budget_remaining: int
  ) -> str:
    Trims context string to fit within token budget.
    Removes from the end of the context (lowest-relevance chunks
    are appended last by ContextRetriever).

### 2. Update core/model_provider.py
  All complete() methods:
    Before call: log estimated prompt tokens to budget.
    After call: log completion tokens to budget.
    Method signature update:
    complete(prompt, system_prompt, max_tokens,
             agent_name: Optional[str] = None,
             token_budget: Optional[TokenBudget] = None) -> str:
    
    If token_budget provided:
      check = token_budget.check_and_record(agent_name, prompt+system_prompt)
      If check.hard_limit_exceeded:
        Return "TOKEN_BUDGET_EXCEEDED: [warning_message]"
        Do not make API call.
      If check.soft_limit_exceeded:
        Log warning to decisions.log
    
    After completion: token_budget.record_completion(agent_name, result)

### 3. Update core/intelligence/context_retriever.py
  retrieve_for_task():
    Accept token_budget: Optional[TokenBudget] = None
    After assembling context:
      If token_budget:
        budget_for_context = token_budget.DEFAULT_BUDGETS.get(
          agent_name, DEFAULT_BUDGETS["default"])["hard_limit_per_call"] // 3
        formatted_context = token_budget.trim_context_to_budget(
          retrieval_context.formatted_context, budget_for_context)

### 4. Update core/projectos.py
  Initialize TokenBudget.
  Pass to all model providers and context retrievers.

### 5. New CLI command: projectos tokens
  projectos tokens usage
    Shows token usage summary for last 7 days per agent.
    Format:
    Agent          Today    7-day avg  Daily limit  Status
    code_review    1,240    980        100,000      ✓ OK
    planning       450      320        50,000       ✓ OK
  
  projectos tokens budget --agent code_review --hard-limit 8000
    Updates budget for one agent in config.
  
  projectos tokens reset --agent code_review
    Resets daily counter for agent (for testing).

### 6. tests/test_observability/test_token_budget.py
  - test_check_allows_under_soft_limit
  - test_check_warns_over_soft_limit
  - test_check_blocks_over_hard_limit
  - test_daily_limit_blocks_when_exceeded
  - test_record_completion_persists_to_jsonl
  - test_get_daily_usage_accurate
  - test_usage_summary_spans_multiple_days
  - test_trim_context_fits_within_budget
  - test_trim_context_empty_returns_empty
  - test_hard_limit_prevents_api_call (mock provider)

## Constraints
- Token estimation uses len // 4 always — no tokenizer imports
- Hard limit enforcement must never raise — return error string
- token_usage.jsonl is append-only
- Budget check must add < 1ms overhead
- Daily counter resets at midnight UTC

## Verification
Full test suite. Write TASK_34_RESULT.md. Update tasks/README.md.
