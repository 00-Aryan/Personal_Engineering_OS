"""Configuration loader and validator for the consolidated master config."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
import yaml


def load_env(env_path: Path) -> Dict[str, str]:
    """Manually parse .env file to avoid dependencies, setting values in os.environ."""
    env_vars = {}
    if env_path.exists():
        try:
            content = env_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    # Strip optional quotes
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    env_vars[key] = val
                    os.environ[key] = val
        except Exception:
            pass
    return env_vars


def adapt_to_legacy_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt the master projectos.yaml config format to the legacy models.yaml format."""
    # Check if this is already a legacy format config
    if "providers" in raw_config and any(k in ("gemini", "openrouter", "ollama") for k in raw_config["providers"]):
        return raw_config

    legacy_providers = {
        "gemini": {
            "api_key_env": "GEMINI_API_KEY",
            "completion_url_template": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            "stream_url_template": "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={api_key}",
            "default_model": "gemini-1.5-flash"
        },
        "openrouter": {
            "api_key_env": "OPENROUTER_API_KEY",
            "completion_url": "https://openrouter.ai/api/v1/chat/completions",
            "stream_url": "https://openrouter.ai/api/v1/chat/completions",
            "default_model": "deepseek/deepseek-chat"
        },
        "ollama": {
            "completion_url": "http://localhost:11434/api/generate",
            "stream_url": "http://localhost:11434/api/generate",
            "default_model": "llama3"
        }
    }

    # Overwrite default provider details with specific values from raw_config["providers"] if present
    providers_sec = raw_config.get("providers", {})
    for k, prov in providers_sec.items():
        if not isinstance(prov, dict):
            continue
        p_type = prov.get("type")
        if p_type in legacy_providers:
            if "model" in prov:
                legacy_providers[p_type]["default_model"] = prov["model"]
            if "api_key_env" in prov:
                legacy_providers[p_type]["api_key_env"] = prov["api_key_env"]
            if "base_url_env" in prov:
                base_url = os.environ.get(prov["base_url_env"], prov.get("base_url_default", "http://localhost:11434"))
                legacy_providers[p_type]["completion_url"] = f"{base_url}/api/generate"
                legacy_providers[p_type]["stream_url"] = f"{base_url}/api/generate"
            elif "base_url_default" in prov:
                base_url = prov["base_url_default"]
                legacy_providers[p_type]["completion_url"] = f"{base_url}/api/generate"
                legacy_providers[p_type]["stream_url"] = f"{base_url}/api/generate"

    # Build legacy agents section
    legacy_agents = {}
    agents_sec = raw_config.get("agents", {})
    for agent_name, prov_name in agents_sec.items():
        prov_info = providers_sec.get(prov_name, {})
        if isinstance(prov_info, dict):
            p_type = prov_info.get("type", "gemini" if "gemini" in prov_name else "openrouter")
            p_model = prov_info.get("model", prov_name)

            tb_config = raw_config.get("token_budgets", {}).get(agent_name, {})
            legacy_agents[agent_name] = {
                "provider": p_type,
                "model": p_model,
            }
            if tb_config:
                legacy_agents[agent_name]["token_budget"] = {
                    "soft_limit_per_call": tb_config.get("soft", 2000),
                    "hard_limit_per_call": tb_config.get("hard", 4000),
                    "daily_limit": tb_config.get("daily", 50000),
                }

    # Build legacy fallback_chain
    legacy_fallbacks = {}
    fallbacks_sec = raw_config.get("fallbacks", {})
    for agent_name, chain in fallbacks_sec.items():
        if isinstance(chain, list):
            legacy_fallbacks[agent_name] = []
            for item in chain:
                legacy_fallbacks[agent_name].append(item)

    # Build pricing
    costs_sec = raw_config.get("costs", {})
    alerts_sec = raw_config.get("alerts", {})
    legacy_pricing = {
        "usd_to_inr": costs_sec.get("usd_to_inr", 83.5),
        "alert_threshold_daily_inr": alerts_sec.get("daily_cost_inr_threshold", 100.0),
        "alert_threshold_monthly_inr": alerts_sec.get("monthly_cost_inr_threshold", 2000.0),
    }

    return {
        "providers": legacy_providers,
        "agents": legacy_agents,
        "fallback_chain": legacy_fallbacks,
        "pricing": legacy_pricing,
        "model_parameters": raw_config.get("model_parameters", {}),
        "ollama": raw_config.get("ollama", {}),
    }


class ProjectConfig:
    """Single source of truth for all ProjectOS configuration."""

    def __init__(self, raw_config: Dict[str, Any], config_path: Path, env: Dict[str, str]) -> None:
        """Initialize ProjectConfig from raw dictionary, path, and environment dictionary."""
        self.raw_config = raw_config
        self.config_path = config_path
        self.env = env

        self.version = str(raw_config.get("version", "0.3.0"))

        # Project properties
        proj = raw_config.get("project", {})
        self.project_name = str(proj.get("name", "my-project"))
        self.project_root = Path(proj.get("root", ".")).resolve()
        self.state_dir = Path(proj.get("state_dir", ".projectos_state")).resolve()
        self.watch_patterns = list(proj.get("watch_patterns", ["*.py"]))
        self.ignore_patterns = list(proj.get("ignore_patterns", ["__pycache__", ".venv", ".git", "test_*"]))

        # Providers properties
        self.providers = raw_config.get("providers", {})

        # Agents properties
        self.agents = raw_config.get("agents", {})

        # Fallbacks properties
        self.fallbacks = raw_config.get("fallbacks", {})

        # Token budgets properties
        self.token_budgets = raw_config.get("token_budgets", {})

        # Quality gates properties
        self.quality_gates = raw_config.get("quality_gates", {})

        # Circuit breakers properties
        cb = raw_config.get("circuit_breakers", {})
        self.circuit_breaker_failure_threshold = int(cb.get("failure_threshold", 5))
        self.circuit_breaker_recovery_timeout_seconds = int(cb.get("recovery_timeout_seconds", 60))
        self.circuit_breaker_minimum_open_duration = float(cb.get("minimum_open_duration", 30.0))
        self.circuit_breaker_consecutive_success_threshold = int(cb.get("consecutive_success_threshold", 3))

        # Alerts properties
        al = raw_config.get("alerts", {})
        self.alert_daily_cost_inr_threshold = float(al.get("daily_cost_inr_threshold", 100.0))
        self.alert_monthly_cost_inr_threshold = float(al.get("monthly_cost_inr_threshold", 2000.0))
        self.alert_quality_score_minimum = float(al.get("quality_score_minimum", 0.60))
        self.alert_blocked_queue_max = int(al.get("blocked_queue_max", 10))
        self.alert_evaluation_failure_rate_max = float(al.get("evaluation_failure_rate_max", 0.30))

        # Cost tracking properties
        costs = raw_config.get("costs", {})
        self.usd_to_inr = float(costs.get("usd_to_inr", 83.5))

        # Validation properties
        validation = raw_config.get("validation", {})
        self.validation_max_new_file_lines = int(validation.get("max_new_file_lines", 150))
        self.validation_max_size_ratio = float(validation.get("max_size_ratio", 2.5))

        # Model parameter and Ollama configurations
        self.model_parameters = raw_config.get("model_parameters", {})
        self.ollama = raw_config.get("ollama", {})

    @classmethod
    def load(cls, config_path: Path = Path("config/projectos.yaml"),
            env_file: Path = Path(".env")) -> ProjectConfig:
        """Load YAML config and .env file, validating presence."""
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        env = load_env(env_file)

        with config_path.open("r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)

        if not isinstance(raw_config, dict):
            raise ValueError("Configuration must be a key-value mapping")

        return cls(raw_config, config_path, env)

    @classmethod
    def create_default(cls, output_path: Path) -> None:
        """Write the default config above to output_path."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        default_yaml = """# ProjectOS Master Configuration
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

# --- Validation ---
validation:
  max_new_file_lines: 150
  max_size_ratio: 2.5
"""
        output_path.write_text(default_yaml, encoding="utf-8")

    def validate(self) -> List[str]:
        """Validate all configuration sections, returning a list of validation errors."""
        errors = []

        # 1. Project validation
        if not self.raw_config.get("project"):
            errors.append("Missing 'project' section")
        else:
            proj = self.raw_config["project"]
            if not proj.get("name"):
                errors.append("Missing project name in 'project.name'")
            if not proj.get("root"):
                errors.append("Missing project root path in 'project.root'")

        # 2. Providers validation
        providers_sec = self.raw_config.get("providers", {})
        if not providers_sec:
            errors.append("Missing 'providers' section")
        else:
            default_provider = providers_sec.get("default")
            if not default_provider:
                errors.append("Missing 'providers.default' configuration")
            elif default_provider not in providers_sec:
                errors.append(f"Default provider '{default_provider}' is not defined in providers")

            for k, prov in providers_sec.items():
                if k == "default":
                    continue
                if not isinstance(prov, dict):
                    errors.append(f"Provider '{k}' configuration must be a mapping")
                    continue
                p_type = prov.get("type")
                if not p_type:
                    errors.append(f"Provider '{k}' is missing 'type'")
                elif p_type not in ("gemini", "openrouter", "ollama"):
                    errors.append(f"Provider '{k}' has invalid type '{p_type}'. Must be gemini, openrouter, or ollama")

                if not prov.get("model"):
                    errors.append(f"Provider '{k}' is missing 'model'")

                # api key check if env is set
                api_key_env = prov.get("api_key_env")
                if api_key_env:
                    if not os.environ.get(api_key_env):
                        errors.append(f"Environment variable '{api_key_env}' for provider '{k}' is not set")
                elif p_type in ("gemini", "openrouter"):
                    errors.append(f"Provider '{k}' of type '{p_type}' requires 'api_key_env'")

        # 3. Agents validation
        agents_sec = self.raw_config.get("agents", {})
        required_agents = {"clone", "planning", "code_writing", "code_review", "architecture", "test", "docs"}
        for agent in required_agents:
            assigned = agents_sec.get(agent)
            if not assigned:
                errors.append(f"Agent '{agent}' is not assigned to any provider in 'agents'")
            elif assigned not in providers_sec:
                errors.append(f"Agent '{agent}' is assigned to undefined provider '{assigned}'")

        # 4. Fallbacks validation
        fallbacks_sec = self.raw_config.get("fallbacks", {})
        for agent, chain in fallbacks_sec.items():
            if not isinstance(chain, list):
                errors.append(f"Fallback chain for '{agent}' must be a list")
                continue
            for p_key in chain:
                if p_key not in providers_sec:
                    errors.append(f"Fallback provider '{p_key}' in '{agent}' chain is not defined")

        # 5. Token budgets validation
        budgets_sec = self.raw_config.get("token_budgets", {})
        for agent, b in budgets_sec.items():
            if not isinstance(b, dict):
                errors.append(f"Token budget for '{agent}' must be a mapping")
                continue
            for limit_name in ("soft", "hard", "daily"):
                if limit_name not in b:
                    errors.append(f"Token budget for '{agent}' is missing '{limit_name}'")
                elif not isinstance(b[limit_name], int) or b[limit_name] <= 0:
                    errors.append(f"Token budget '{limit_name}' for '{agent}' must be a positive integer")
            if "soft" in b and "hard" in b:
                if isinstance(b["soft"], int) and isinstance(b["hard"], int) and b["soft"] > b["hard"]:
                    errors.append(f"Token budget 'soft' limit must be less than or equal to 'hard' limit for '{agent}'")

        # 6. Quality gates validation
        gates_sec = self.raw_config.get("quality_gates", {})
        for agent, gate in gates_sec.items():
            if not isinstance(gate, dict):
                errors.append(f"Quality gate for '{agent}' must be a mapping")
                continue
            min_score = gate.get("min_score")
            if min_score is not None:
                if not isinstance(min_score, (int, float)) or not (0.0 <= min_score <= 1.0):
                    errors.append(f"Quality gate 'min_score' for '{agent}' must be a number between 0 and 1")

        # 7. Circuit breakers validation
        cb = self.raw_config.get("circuit_breakers", {})
        if cb:
            if "failure_threshold" in cb:
                ft = cb["failure_threshold"]
                if not isinstance(ft, int) or ft <= 0:
                    errors.append("Circuit breaker 'failure_threshold' must be a positive integer")
            if "recovery_timeout_seconds" in cb:
                rt = cb["recovery_timeout_seconds"]
                if not isinstance(rt, int) or rt <= 0:
                    errors.append("Circuit breaker 'recovery_timeout_seconds' must be a positive integer")
            if "minimum_open_duration" in cb:
                mod = cb["minimum_open_duration"]
                if not isinstance(mod, (int, float)) or mod < 0:
                    errors.append("Circuit breaker 'minimum_open_duration' must be a non-negative number")
            if "consecutive_success_threshold" in cb:
                cst = cb["consecutive_success_threshold"]
                if not isinstance(cst, int) or cst <= 0:
                    errors.append("Circuit breaker 'consecutive_success_threshold' must be a positive integer")

        # 8. Alerts validation
        al = self.raw_config.get("alerts", {})
        if al:
            for k, val in al.items():
                if not isinstance(val, (int, float)) or val < 0:
                    errors.append(f"Alert setting '{k}' must be a positive number")

        # 9. Costs validation
        costs = self.raw_config.get("costs", {})
        if costs:
            if "usd_to_inr" in costs:
                u2i = costs["usd_to_inr"]
                if not isinstance(u2i, (int, float)) or u2i <= 0:
                    errors.append("Cost setting 'usd_to_inr' must be a positive number")

        # 10. Validation settings validation
        val_sec = self.raw_config.get("validation", {})
        if val_sec:
            if "max_new_file_lines" in val_sec:
                mnfl = val_sec["max_new_file_lines"]
                if not isinstance(mnfl, int) or mnfl <= 0:
                    errors.append("Validation 'max_new_file_lines' must be a positive integer")
            if "max_size_ratio" in val_sec:
                msr = val_sec["max_size_ratio"]
                if not isinstance(msr, (int, float)) or msr <= 0:
                    errors.append("Validation 'max_size_ratio' must be a positive number")

        return errors
