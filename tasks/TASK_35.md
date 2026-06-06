# TASK_35: Cost Tracker + Provider Economics

## Engineering Context

TASK_34 tracks token counts. This task tracks cost in real currency,
per provider, per agent, per task — and makes provider-switching
decisions based on economics, not just availability.

Current state: ProjectOS uses free models. That's the right choice
now. But "free" has limits:
- Gemini free tier: 1500 requests/minute, 1M tokens/minute
- OpenRouter free models: rate-limited, may add latency
- DeepSeek: has both free and paid tiers

When you eventually use paid APIs (or run a benchmark for clients),
you need to know: "This code review session cost ₹12. This planning
task cost ₹3."

Cost tracking also enables the "optimizer" pattern: automatically
route simple tasks to cheap models and complex tasks to expensive ones.

## Pre-conditions
Read core/observability/token_budget.py from TASK_34.
Read core/model_provider.py, config/models.yaml.
Read core/intelligence/fallback_router.py from TASK_15.

## Deliverables

### 1. core/observability/cost_tracker.py

@dataclass
class ProviderPricing:
  provider_name: str
  model_name: str
  input_cost_per_1k_tokens: float  (USD)
  output_cost_per_1k_tokens: float  (USD)
  free_tier_input_tokens_per_day: int  (0 = no free tier)
  free_tier_output_tokens_per_day: int  (0 = no free tier)
  currency: str = "USD"
  
  def is_free_tier(self, input_tokens: int, output_tokens: int,
                   used_today: int) -> bool:
    Returns True if this call would be covered by free tier.

PROVIDER_PRICING_CATALOG = {
  "gemini-flash": ProviderPricing(
    provider_name="gemini",
    model_name="gemini-1.5-flash",
    input_cost_per_1k_tokens=0.0,
    output_cost_per_1k_tokens=0.0,
    free_tier_input_tokens_per_day=1_000_000,
    free_tier_output_tokens_per_day=1_000_000
  ),
  "deepseek-v3": ProviderPricing(
    provider_name="openrouter",
    model_name="deepseek/deepseek-chat",
    input_cost_per_1k_tokens=0.00014,
    output_cost_per_1k_tokens=0.00028,
    free_tier_input_tokens_per_day=0,
    free_tier_output_tokens_per_day=0
  ),
  "openrouter-free": ProviderPricing(
    provider_name="openrouter",
    model_name="various-free",
    input_cost_per_1k_tokens=0.0,
    output_cost_per_1k_tokens=0.0,
    free_tier_input_tokens_per_day=500_000,
    free_tier_output_tokens_per_day=500_000
  ),
  "ollama-local": ProviderPricing(
    provider_name="ollama",
    model_name="local",
    input_cost_per_1k_tokens=0.0,
    output_cost_per_1k_tokens=0.0,
    free_tier_input_tokens_per_day=999_999_999,
    free_tier_output_tokens_per_day=999_999_999
  )
}

@dataclass
class CostRecord:
  record_id: str
  timestamp: datetime
  agent_name: str
  provider: str
  model: str
  input_tokens: int
  output_tokens: int
  cost_usd: float
  cost_inr: float  (cost_usd * 83.5, configurable exchange rate)
  is_free_tier: bool
  trace_id: Optional[str]
  task_id: Optional[str]

class CostTracker:
  __init__(
    state_dir: Path,
    usd_to_inr: float = 83.5,
    pricing_catalog: Optional[Dict] = None
  )
  
  record(
    agent_name: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None
  ) -> CostRecord:
    Look up pricing from catalog.
    Compute cost (0.0 if free tier).
    Append to costs.jsonl atomically.
    Return CostRecord.
  
  get_daily_cost(date: Optional[date] = None) -> Dict:
    Returns:
    {
      "total_usd": float,
      "total_inr": float,
      "by_agent": {agent_name: {"usd": float, "inr": float}},
      "by_provider": {provider: {"usd": float, "inr": float}},
      "free_tier_calls": int,
      "paid_calls": int
    }
  
  get_task_cost(task_id: str) -> Dict:
    Returns total cost for all model calls in a task.
  
  get_monthly_projection(days_of_data: int = 7) -> Dict:
    Projects monthly cost from last N days average.
    Returns: {projected_usd, projected_inr, confidence: "low/medium/high"}
    confidence = "low" if days_of_data < 3, "high" if >= 14.
  
  recommend_model_swap(agent_name: str) -> Optional[str]:
    If agent cost > threshold AND ollama available → recommend ollama
    If agent cost > threshold AND cheaper model exists → recommend it
    Returns recommendation string or None.

### 2. Update config/models.yaml
  Add pricing section:
  pricing:
    usd_to_inr: 83.5
    alert_threshold_daily_inr: 100
    alert_threshold_monthly_inr: 2000

### 3. Update core/projectos.py
  Initialize CostTracker.
  Pass to model providers (alongside token_budget).
  After each model call: cost_tracker.record(...).

### 4. New CLI command: projectos cost
  projectos cost today
    Shows today's cost breakdown.
    Format:
    Today's Usage
    Agent          Calls  Tokens   Cost (₹)  Free Tier
    code_review    12     14,200   ₹0.00     ✓ Yes
    planning       3      2,100    ₹0.00     ✓ Yes
    Total: ₹0.00 | Projected monthly: ₹0.00
  
  projectos cost week
    Last 7 days breakdown with daily chart (ASCII bar chart).
  
  projectos cost optimize
    Shows model swap recommendations based on usage patterns.

### 5. tests/test_observability/test_cost_tracker.py
  - test_free_tier_records_zero_cost
  - test_paid_tier_computes_correct_cost
  - test_inr_conversion_applied
  - test_get_daily_cost_aggregates_correctly
  - test_get_task_cost_sums_all_calls
  - test_monthly_projection_low_confidence_under_3_days
  - test_costs_jsonl_append_only
  - test_recommend_model_swap_suggests_ollama (mock health check)

## Constraints
- costs.jsonl is append-only
- Exchange rate is configurable, not hardcoded
- CostTracker never raises — logs errors, records zero cost on failure
- Provider catalog must be extensible (add new providers without code change)
- Free tier calculation is conservative (undercount free, never over)

## Verification
Full test suite. Write TASK_35_RESULT.md. Update tasks/README.md.
