# TASK_61: Ollama Local Fallback + Model Parameter Tuning

## Engineering Context

When Gemini and OpenRouter are exhausted or unavailable,
ProjectOS must fall back to local Ollama models.

Equally important: every model call currently uses default
parameters (temperature, max_tokens). These are wrong for most tasks:
- Planning needs temperature=0.3 (focused, not creative)
- Code writing needs temperature=0.1 (precise, minimal variation)
- Architecture review needs temperature=0.7 (exploratory)
- Documentation needs temperature=0.2 (clear, consistent)

Tuning these parameters per agent will improve output quality
without changing the model.

## Pre-conditions
Read core/model_provider.py, providers/ollama_provider.py.
Read ALL agent files for their roles.
Read config/projectos.yaml.
Check Ollama availability: which ollama || echo "not installed"

## Deliverables

### 1. Update config/projectos.yaml — model parameters per agent

```yaml
model_parameters:
  clone:
    temperature: 0.2
    max_tokens: 500
    top_p: 0.9
  planning:
    temperature: 0.3
    max_tokens: 1500
    top_p: 0.85
  code_writing:
    temperature: 0.1
    max_tokens: 1000
    top_p: 0.95
  code_review:
    temperature: 0.2
    max_tokens: 800
    top_p: 0.9
  architecture:
    temperature: 0.7
    max_tokens: 1000
    top_p: 0.9
  test:
    temperature: 0.1
    max_tokens: 1000
    top_p: 0.95
  docs:
    temperature: 0.2
    max_tokens: 600
    top_p: 0.9
  project_intake:
    temperature: 0.4
    max_tokens: 2000
    top_p: 0.9

ollama:
  base_url: "http://localhost:11434"
  preferred_models:
    - llama3.2:1b      (lightest, fastest)
    - llama3.2:3b      (better quality, still fast)
    - deepseek-r1:1.5b (good for planning/architecture)
  fallback_model: llama3.2:1b
  timeout_seconds: 120
```

### 2. Update core/model_provider.py

Add model_params to complete() signature:
  complete(
    prompt: str,
    system_prompt: str,
    max_tokens: int = 1000,
    temperature: float = 0.3,
    top_p: float = 0.9,
    agent_name: Optional[str] = None,
    token_budget: Optional[TokenBudget] = None
  ) -> str:

Update all three providers to use temperature and top_p:
  GeminiProvider: generationConfig with temperature, maxOutputTokens
  OpenRouterProvider: temperature, max_tokens in request body
  OllamaProvider: options.temperature, options.num_predict

### 3. Update core/base_agent.py

Add method get_model_params() -> Dict:
  Read from config: model_parameters.{self.name}
  Return dict with temperature, max_tokens, top_p
  Default to {temperature: 0.3, max_tokens: 1000, top_p: 0.9}

Update all agent handle() methods:
  params = self.get_model_params()
  result = self.model_provider.complete(
    prompt=prompt,
    system_prompt=system_prompt,
    temperature=params["temperature"],
    max_tokens=params["max_tokens"],
    top_p=params["top_p"],
    agent_name=self.name
  )

### 4. Test and document Ollama setup

Create scripts/test_ollama.py:
  Check if Ollama is installed and running.
  If not: print installation instructions.
  If yes:
    Pull lightest model: ollama pull llama3.2:1b
    Send test prompt.
    Measure latency.
    Print: "Ollama working. Latency: {N}ms. Model: llama3.2:1b"
  
  Write to .projectos_state/ollama_status.json.

Create docs/OLLAMA_SETUP.md:
  Step-by-step Ollama setup for Ubuntu/Linux.
  What to expect with a laptop (no GPU).
  Which models are recommended for different hardware.
  How to make ProjectOS use Ollama only (/model command).

### 5. tests/test_model_parameters.py
  - test_temperature_passed_to_provider
  - test_agent_uses_configured_temperature
  - test_default_params_when_not_configured
  - test_ollama_provider_passes_temperature
  - test_conservative_mode_reduces_max_tokens

## Constraints
- temperature values must be between 0.0 and 1.0
- max_tokens must not exceed provider limits
  Gemini: 2048, OpenRouter: varies, Ollama: 2048
- All existing tests must still pass
  (update mock providers to accept temperature parameter)
- Ollama is optional — system works without it

## Verification
Full test suite (update mocks for new signature).
Write TASK_61_RESULT.md. Update tasks/README.md.
