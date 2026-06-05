"""Benchmark configured ProjectOS model assignments.

This script intentionally stays out of production imports. It is a manual
utility for comparing configured models when real provider credentials exist.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Type

import yaml

from core.model_provider import (
    GeminiProvider,
    ModelProvider,
    ModelProviderConfigError,
    OllamaProvider,
    OpenRouterProvider,
)


CONFIG_PATH = Path("config/models.yaml")
BENCHMARK_OUTPUT_PATH = Path("docs/benchmark_results.md")
RUNS_PER_MODEL = 3
APPROX_TOKEN_DIVISOR = 4
AUTH_ERROR_MARKERS = ("api key", "environment variable", "401", "403", "auth")

TASKS = {
    "planning": "Add user authentication to a Flask app",
    "code_review": "Review core/base_agent.py for correctness and risks.",
    "code_writing": "Write a function to parse JSON safely",
}

PROVIDER_BY_NAME: Dict[str, Type[ModelProvider]] = {
    "openrouter": OpenRouterProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


def main() -> None:
    """Run the benchmark and write markdown results."""
    config = _load_config(CONFIG_PATH)
    rows: List[Dict[str, Any]] = []
    for agent_name, prompt in TASKS.items():
        for model_name in _models_for_agent(config, agent_name):
            rows.append(_benchmark_model(config, agent_name, model_name, prompt))

    _write_results(rows)
    _print_summary(rows)


def _load_config(config_path: Path) -> Mapping[str, Any]:
    """Load the benchmark model configuration."""
    with config_path.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, Mapping):
        raise RuntimeError("config/models.yaml must be a mapping")
    return config


def _models_for_agent(config: Mapping[str, Any], agent_name: str) -> List[str]:
    """Return fallback-chain models for an agent, or its direct model."""
    fallback_chain = config.get("fallback_chain")
    if isinstance(fallback_chain, Mapping):
        models = fallback_chain.get(agent_name)
        if isinstance(models, list):
            return [model for model in models if isinstance(model, str)]

    agents = config.get("agents")
    if isinstance(agents, Mapping):
        agent_config = agents.get(agent_name)
        if isinstance(agent_config, Mapping):
            model = agent_config.get("model")
            if isinstance(model, str):
                return [model]
    return []


def _benchmark_model(
    config: Mapping[str, Any],
    agent_name: str,
    model_name: str,
    prompt: str,
) -> Dict[str, Any]:
    """Benchmark one model with repeated completions."""
    provider = _provider_for_model(config, agent_name, model_name)
    latencies: List[float] = []
    output_lengths: List[int] = []
    successes = 0
    skipped_reason: Optional[str] = None

    for _ in range(RUNS_PER_MODEL):
        started_at = time.perf_counter()
        try:
            output = provider.complete(prompt, "ProjectOS benchmark task.", 512)
        except Exception as error:
            if _is_auth_error(error):
                skipped_reason = "skipped: no API key"
                break
            skipped_reason = f"failed: {error}"
            continue
        latencies.append((time.perf_counter() - started_at) * 1000)
        output_lengths.append(max(len(output) // APPROX_TOKEN_DIVISOR, 0))
        if output.strip():
            successes += 1

    return {
        "agent": agent_name,
        "model": model_name,
        "latency_ms": _average(latencies),
        "output_len": _average(output_lengths),
        "success_rate": successes / RUNS_PER_MODEL,
        "status": skipped_reason or "ok",
    }


def _provider_for_model(
    config: Mapping[str, Any],
    agent_name: str,
    model_name: str,
) -> ModelProvider:
    """Create a provider for a model and override its configured model name."""
    provider_name = _provider_name_for_model(config, agent_name, model_name)
    provider_class = PROVIDER_BY_NAME[provider_name]
    provider = provider_class(None, CONFIG_PATH)
    provider._model_name = model_name
    return provider


def _provider_name_for_model(
    config: Mapping[str, Any],
    agent_name: str,
    model_name: str,
) -> str:
    """Infer provider name from model naming and agent defaults."""
    if model_name.startswith("ollama-"):
        return "ollama"
    if "gemini" in model_name:
        return "gemini"
    agents = config.get("agents")
    if isinstance(agents, Mapping):
        agent_config = agents.get(agent_name)
        if isinstance(agent_config, Mapping):
            provider = agent_config.get("provider")
            if provider in PROVIDER_BY_NAME:
                return str(provider)
    return "openrouter"


def _is_auth_error(error: Exception) -> bool:
    """Return whether an exception indicates missing credentials."""
    if isinstance(error, ModelProviderConfigError):
        return True
    error_text = str(error).lower()
    return any(marker in error_text for marker in AUTH_ERROR_MARKERS)


def _average(values: Iterable[float]) -> float:
    """Return an average value, or zero for no samples."""
    values_list = list(values)
    if not values_list:
        return 0.0
    return sum(values_list) / len(values_list)


def _write_results(rows: List[Mapping[str, Any]]) -> None:
    """Write benchmark results as a markdown table atomically."""
    lines = [
        "# ProjectOS Model Benchmark Results",
        "",
        "| Agent | Model | Latency ms | Output Len | Success Rate | Status |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {agent} | {model} | {latency_ms:.0f} | {output_len:.0f} | "
            "{success_rate:.2f} | {status} |".format(**row)
        )
    content = "\n".join(lines) + "\n"
    BENCHMARK_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{BENCHMARK_OUTPUT_PATH.name}.",
        suffix=".tmp",
        dir=str(BENCHMARK_OUTPUT_PATH.parent),
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, BENCHMARK_OUTPUT_PATH)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _print_summary(rows: List[Mapping[str, Any]]) -> None:
    """Print recommended model per benchmarked agent."""
    print("Recommended models:")
    for agent_name in TASKS:
        agent_rows = [row for row in rows if row["agent"] == agent_name]
        if not agent_rows:
            continue
        best = sorted(
            agent_rows,
            key=lambda row: (-float(row["success_rate"]), float(row["latency_ms"])),
        )[0]
        print(f"- {agent_name}: {best['model']} ({best['status']})")


if __name__ == "__main__":
    main()
