# TASK_43: Configuration Consolidation

## Engineering Context

ProjectOS currently has configuration scattered across:
- config/models.yaml (model assignments)
- .env / environment variables (API keys)
- core/observability/token_budget.py (DEFAULT_BUDGETS hardcoded)
- core/observability/cost_tracker.py (PROVIDER_PRICING_CATALOG hardcoded)
- core/evaluation/quality_gate.py (DEFAULT_POLICIES hardcoded)
- core/intelligence/semantic_router.py (DEFAULT_ROUTING_EXAMPLES hardcoded)
- core/observability/circuit_breaker.py (thresholds hardcoded)

A new user installing ProjectOS needs to touch 6+ files to configure
the system. That's too much friction. This task consolidates all
configuration into one place.

## Pre-conditions
Read ALL files listed above completely before writing any code.
Read docs/external_project_report.md for configuration pain points
discovered during real-world testing.

## Deliverables

### 1. config/projectos.yaml (new master config file)

```yaml
# ProjectOS Master Configuration
# Edit this file to configure your installation.
# Run: projectos config validate to check for errors.

version: "0.3.0"

# --- Project ---
project:
  name: "my-project"
  root: "."
  state_dir: ".projectos_state"
  watch_patterns: ["*.py"]
  ignore_patterns: ["__pycache__", ".venv", ".git", "test_*"]

# --- Providers ---
providers:
  default: gemini-flash
  
  gemini-flash:
    type: gemini
    model: gemini-1.5-flash
    api_key_env: GEMINI_API_KEY
    
  deepseek-v3:
    type: openrouter
    model: deepseek/deepseek-chat
    api_key_env: OPENROUTER_API_KEY
    
  ollama-local:
    type: ollama
    model: llama3
    base_url_env: OLLAMA_BASE_URL
    base_url_default: http://localhost:11434

# --- Agent Model Assignments ---
agents:
  clone:        gemini-flash
  planning:     deepseek-v3
  code_writing: gemini-flash
  code_review:  gemini-flash
  architecture: deepseek-v3
  test:         gemini-flash
  docs:         gemini-flash

# --- Fallback Chains ---
fallbacks:
  planning:     [deepseek-v3, gemini-flash, ollama-local]
  code_writing: [gemini-flash, ollama-local]
  code_review:  [gemini-flash, ollama-local]

# --- Token Budgets ---
token_budgets:
  code_review:   {soft: 3000, hard: 6000, daily: 100000}
  code_writing:  {soft: 3000, hard: 6000, daily: 100000}
  planning:      {soft: 2000, hard: 4000, daily: 50000}
  architecture:  {soft: 2000, hard: 4000, daily: 30000}
  test:          {soft: 3000, hard: 6000, daily: 80000}
  docs:          {soft: 1500, hard: 3000, daily: 40000}
  clone:         {soft: 1000, hard: 2000, daily: 200000}

# --- Quality Gates ---
quality_gates:
  code_writing:
    min_score: 0.65
    require_llm_eval: true
    require_static: true
    block_security_high: true
    block_regression: true
  code_review:
    min_score: 0.70
    require_llm_eval: true
    require_static: false
    block_regression: true
  planning:
    min_score: 0.60
    require_llm_eval: true

# --- Circuit Breakers ---
circuit_breakers:
  failure_threshold: 5
  recovery_timeout_seconds: 60

# --- Alerts ---
alerts:
  daily_cost_inr_threshold: 100
  monthly_cost_inr_threshold: 2000
  quality_score_minimum: 0.60
  blocked_queue_max: 10
  evaluation_failure_rate_max: 0.30

# --- Cost Tracking ---
costs:
  usd_to_inr: 83.5
```

### 2. core/config_loader.py

class ProjectConfig:
  """Single source of truth for all ProjectOS configuration."""
  
  @classmethod
  def load(cls, config_path: Path = Path("config/projectos.yaml"),
           env_file: Path = Path(".env")) -> ProjectConfig:
    Load YAML config.
    Load .env file (python-dotenv or manual parse).
    Validate all required fields present.
    Return populated ProjectConfig.
  
  @classmethod
  def create_default(cls, output_path: Path) -> None:
    Write the default config above to output_path.
    Used by setup wizard.
  
  def validate(self) -> List[str]:
    Returns list of validation errors.
    Empty list = valid config.
  
  # Properties for every config section
  # Used throughout codebase instead of hardcoded defaults

### 3. Update core/projectos.py
  Replace all hardcoded defaults with ProjectConfig.load().
  Pass config values to:
    - TokenBudget (from token_budgets section)
    - QualityGate (from quality_gates section)
    - CircuitBreaker (from circuit_breakers section)
    - AlertManager (from alerts section)
    - CostTracker (from costs section)
  
  ProjectOS.__init__ signature becomes:
    __init__(config_path: Path = Path("config/projectos.yaml"))

### 4. New CLI command: projectos config
  projectos config show
    Pretty-prints current config from projectos.yaml.
  
  projectos config validate
    Runs ProjectConfig.validate(), prints errors or "Config valid".
  
  projectos config init
    Creates config/projectos.yaml if missing.
    Prompts for provider API keys interactively.
    Writes .env file.

### 5. Remove hardcoded defaults from:
  - core/observability/token_budget.py (move to config)
  - core/observability/cost_tracker.py (move to config)
  - core/evaluation/quality_gate.py (move to config)
  - core/observability/circuit_breaker.py (move to config)
  Keep DEFAULT_* constants as fallback only when no config loaded.

### 6. tests/test_config_loader.py
  All use tmp_path:
  - test_load_valid_config
  - test_validate_catches_missing_required_fields
  - test_create_default_writes_valid_yaml
  - test_env_file_loaded_for_api_keys
  - test_config_provides_token_budget_values
  - test_config_provides_quality_gate_values
  - test_missing_config_file_raises_clear_error

## Constraints
- config/projectos.yaml must be valid YAML at all times
- ProjectConfig.load() must never crash on missing optional fields
  (use defaults from the DEFAULT_* constants)
- All existing tests must pass — do not break mocked configurations
- config/models.yaml remains for backward compat but is deprecated
  (print warning when loaded if projectos.yaml exists)

## Verification
Full test suite passes.
projectos config validate exits 0.
Write TASK_43_RESULT.md. Update tasks/README.md.
