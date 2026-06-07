"""Run a bounded live provider smoke test for ProjectOS."""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from scripts.provider_setup import (
    CONFIG_PATH,
    ENV_PATH,
    PROVIDER_STATUS_PATH,
    available_provider_names,
    first_agent_for_provider,
    load_env_file,
    load_model_config,
    load_provider_status,
    provider_class_name,
)


SMOKE_PROMPT = "Reply with exactly: PROJECTOS_LIVE_TEST_OK"
SMOKE_SYSTEM_PROMPT = "You are a smoke test. Keep the response short."
MAX_TOKENS = 32


def main(argv: Sequence[str] | None = None) -> int:
    """Run live smoke checks for providers marked available."""
    parser = argparse.ArgumentParser(description="Run ProjectOS live provider smoke.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--env-file", type=Path, default=ENV_PATH)
    parser.add_argument("--status-file", type=Path, default=PROVIDER_STATUS_PATH)
    args = parser.parse_args(argv)

    load_env_file(args.env_file)
    if not args.status_file.exists():
        setup_result = subprocess.run(
            [
                sys.executable,
                "scripts/setup_providers.py",
                "--no-prompt",
                "--config",
                str(args.config),
                "--env-file",
                str(args.env_file),
                "--status-file",
                str(args.status_file),
            ],
            check=False,
            text=True,
        )
        if setup_result.returncode != 0:
            print("Provider setup failed; skipping live smoke.")
            return 0

    status = load_provider_status(args.status_file)
    provider_names = available_provider_names(status)
    if not provider_names:
        print("LIVE SMOKE SKIPPED: No providers configured")
        print("No available providers; skipping live smoke.")
        return 0

    config = load_model_config(args.config)
    failures: list[str] = []
    results: dict[str, dict[str, Any]] = {}
    
    for provider_name in provider_names:
        try:
            output, latency_ms, tokens_used = _run_provider_smoke(provider_name, config, args.config, args.status_file.parent)
            if "PROJECTOS_LIVE_TEST_OK" not in output:
                failures.append(f"{provider_name} returned {output}")
                print(f"{provider_name}: live smoke failed - Expected 'PROJECTOS_LIVE_TEST_OK', got '{output}'")
            else:
                results[provider_name] = {
                    "latency_ms": latency_ms,
                    "tokens_used": tokens_used,
                    "provider_name": provider_name
                }
                print(f"{provider_name}: live smoke ok - Latency: {latency_ms}ms, Tokens: {tokens_used}")
        except Exception as error:
            failures.append(f"{provider_name}: {error}")
            print(f"{provider_name}: live smoke failed - {error}")

    # Write results to .projectos_state/live_smoke_results.json
    results_path = args.status_file.parent / "live_smoke_results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    if failures:
        print(f"LIVE SMOKE FAILED: {failures[0]}")
        return 1
        
    print(f"LIVE SMOKE PASSED: {len(results)} providers verified")
    return 0


def _run_provider_smoke(
    provider_name: str,
    config: dict[str, Any],
    config_path: Path,
    state_dir: Path,
) -> tuple[str, int, int]:
    """Run one live completion and return (output, latency_ms, tokens_used)."""
    from core.observability.token_budget import TokenBudget
    tb = TokenBudget(state_dir)
    
    model_provider = importlib.import_module("core.model_provider")
    provider_class = getattr(model_provider, provider_class_name(provider_name))
    agent_name = first_agent_for_provider(config, provider_name)
    provider = provider_class(agent_name, config_path, token_budget=tb)
    
    start_time = time.perf_counter()
    output = str(provider.complete(SMOKE_PROMPT, SMOKE_SYSTEM_PROMPT, MAX_TOKENS))
    end_time = time.perf_counter()
    latency_ms = int((end_time - start_time) * 1000)
    
    # Calculate estimated tokens_used as fallback
    tokens_used = (len(SMOKE_PROMPT + SMOKE_SYSTEM_PROMPT) + len(output)) // 4
    
    # Try reading the actual tokens used from token budget log
    if tb.log_path.exists():
        try:
            with open(tb.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if lines:
                    for line in reversed(lines):
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if data.get("provider") == provider_name or data.get("agent_name") == agent_name:
                            tokens_used = data.get("total_tokens", tokens_used)
                            break
        except Exception:
            pass
            
    return output, latency_ms, tokens_used


if __name__ == "__main__":
    raise SystemExit(main())
