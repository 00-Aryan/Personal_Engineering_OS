"""Check if Ollama is installed, running, pull llama3.2:1b, test it, measure latency, and log status."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import requests

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.model_provider import OllamaProvider


def _hard_timeout(signum: Any, frame: Any) -> None:
    """Handle hard script timeout."""
    print("OLLAMA TEST: FAILED: Wall clock timeout reached")
    sys.exit(1)


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    state_dir = project_root / ".projectos_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    status_file = state_dir / "ollama_status.json"

    # 1. Check if ollama is installed
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        print("Ollama is not installed.")
        print("To install Ollama, run:")
        print("  curl -fsSL https://ollama.com/install.sh | sh")
        print("For other platforms, visit: https://ollama.com")
        status_data = {
            "status": "not_installed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error": "Ollama executable not found in PATH"
        }
        status_file.write_text(json.dumps(status_data, indent=2), encoding="utf-8")
        return 1

    # 2. Check if Ollama is running
    base_url = "http://localhost:11434"
    config_path = project_root / "config" / "projectos.yaml"
    if config_path.exists():
        try:
            import yaml
            with config_path.open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                if isinstance(cfg, dict):
                    ollama_cfg = cfg.get("ollama", {})
                    if isinstance(ollama_cfg, dict) and "base_url" in ollama_cfg:
                        base_url = ollama_cfg["base_url"]
        except Exception:
            pass

    # Override with env var if present
    env_base_url = os.environ.get("OLLAMA_BASE_URL")
    if env_base_url:
        base_url = env_base_url

    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        is_running = response.status_code == 200
    except Exception as e:
        is_running = False
        error_msg = str(e)

    if not is_running:
        print("Ollama is not running.")
        print(f"Failed to connect to Ollama base URL: {base_url}")
        print("To start Ollama:")
        print("  systemctl start ollama (or run 'ollama serve' in a terminal)")
        status_data = {
            "status": "not_running",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error": f"Failed to connect to Ollama at {base_url}"
        }
        status_file.write_text(json.dumps(status_data, indent=2), encoding="utf-8")
        return 1

    # 3. Pull lightest model
    target_model = "llama3.2:1b"
    print(f"Pulling model {target_model}...")
    try:
        subprocess.run(["ollama", "pull", target_model], check=True)
    except Exception as e:
        print(f"Failed to pull model {target_model}: {e}")
        status_data = {
            "status": "pull_failed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error": f"Failed to pull model: {e}"
        }
        status_file.write_text(json.dumps(status_data, indent=2), encoding="utf-8")
        return 1

    # 4. Send test prompt and measure latency
    print("Sending test prompt...")
    try:
        provider = OllamaProvider(config_path=config_path)
        provider._model_name = target_model
        
        start_time = time.perf_counter()
        response_text = provider.complete(
            prompt="Hello, reply with one word: 'hello'.",
            system_prompt="You are a helpful assistant.",
            max_tokens=10,
            temperature=0.1,
            top_p=0.9
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        
        print(f"Ollama response: '{response_text.strip()}'")
        print(f"Ollama working. Latency: {latency_ms}ms. Model: {target_model}")
        
        status_data = {
            "status": "working",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": target_model,
            "latency_ms": latency_ms
        }
        temp_file = status_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(status_data, indent=2), encoding="utf-8")
        temp_file.replace(status_file)
        
    except Exception as e:
        print(f"Failed to complete test prompt: {e}")
        status_data = {
            "status": "test_failed",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error": f"Test prompt failed: {e}"
        }
        status_file.write_text(json.dumps(status_data, indent=2), encoding="utf-8")
        return 1

    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, _hard_timeout)
    signal.alarm(120)
    sys.exit(main())
