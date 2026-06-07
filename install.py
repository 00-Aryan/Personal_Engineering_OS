#!/usr/bin/env python3
"""Installation script for ProjectOS."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Install and configure ProjectOS.")
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Run installation without interactive prompts.",
    )
    args = parser.parse_args()

    print("ProjectOS Installation Wizard")
    print("=============================")

    # 1. Sync dependencies with uv
    print("\n[1/4] Installing dependencies...")
    try:
        # Check if uv is available
        subprocess.run(["uv", "--version"], capture_output=True, check=True)
        # Use uv to sync dependencies
        print("Running: uv sync")
        subprocess.run(["uv", "sync"], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fall back to standard pip if uv is not installed
        print("uv is not available. Falling back to standard pip install...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], check=True)

    # 2. Create config/projectos.yaml if missing
    print("\n[2/4] Initializing configuration...")
    config_path = Path("config/projectos.yaml")
    if not config_path.exists():
        print(f"Creating default configuration at {config_path}...")
        try:
            from core.config_loader import ProjectConfig
            ProjectConfig.create_default(config_path)
        except ImportError:
            # Fallback if package is not in pythonpath yet
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from core.config_loader import ProjectConfig
            ProjectConfig.create_default(config_path)
    else:
        print(f"Configuration already exists at {config_path}")

    # 3. Create .env from .env.example if missing
    print("\n[3/4] Setting up environment variables...")
    env_path = Path(".env")
    env_example_path = Path(".env.example")
    
    # Write .env.example if missing
    if not env_example_path.exists():
        env_example_content = """# ProjectOS Provider Configuration
# Copy this file to .env and fill in your keys
# Never commit .env to git

# Gemini (free tier: 1M tokens/day)
# Get at: https://aistudio.google.com/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# OpenRouter (free models available)
# Get at: https://openrouter.ai/keys
OPENROUTER_API_KEY=your_openrouter_api_key_here

# Ollama (local, free, no key needed)
# Install: https://ollama.ai
OLLAMA_BASE_URL=http://localhost:11434
"""
        env_example_path.write_text(env_example_content, encoding="utf-8")
        
    if not env_path.exists():
        print(f"Copying {env_example_path} to {env_path}...")
        env_path.write_text(env_example_path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        print(f"Environment file already exists at {env_path}")

    # 4. Set up provider status
    print("\n[4/4] Detecting provider status...")
    setup_argv = ["--no-prompt"]
    if config_path.exists():
        setup_argv.extend(["--config", str(config_path)])
    
    # Import and runsetup_providers
    try:
        from scripts import setup_providers
        setup_providers.main(setup_argv)
    except Exception as e:
        print(f"Warning: failed to run provider setup check: {e}")

    print("\nProjectOS installed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
