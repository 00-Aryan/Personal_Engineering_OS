# TASK_45: One-Command Install + Setup Wizard

## Engineering Context

A new developer finding ProjectOS on GitHub should be able to go from
zero to running in under 10 minutes. Right now that is not possible.

The install experience is:
1. Clone repo
2. Read README to find setup instructions
3. Install uv manually if not present
4. Run uv pip install -e ".[dev]"
5. Copy .env.example to .env
6. Fill in API keys manually
7. Edit config/projectos.yaml manually
8. Hope it works

That is 8 steps with multiple failure points. This task reduces it to 3:
1. Clone repo
2. python install.py
3. projectos run

## Pre-conditions
Read README.md, config/projectos.yaml, core/config_loader.py,
scripts/setup_providers.py fully before writing any code.
Read AGENTS.md for all constraints.

## Deliverables

### 1. install.py (project root)

Single-file installer that works with only stdlib.
No dependencies required to run install.py itself.

Steps in order:
1. Check Python version >= 3.10. If not: print clear error, exit 1.

2. Check if uv is installed (shutil.which("uv")).
   If not: print install instructions for uv, ask user Y/N to auto-install.
   Auto-install: curl -LsSf https://astral.sh/uv/install.sh | sh
   On Windows: print manual instructions, exit 1.

3. Run: uv pip install -e ".[dev]"
   Show progress. On failure: print error with troubleshooting steps.

4. Check if config/projectos.yaml exists.
   If not: copy from config/projectos.yaml.example (create this file).

5. Check if .env exists.
   If not: run interactive provider setup:
     Print: "Let's configure your AI providers."
     Print: "You need at least one to use ProjectOS."
     For each provider (Gemini, OpenRouter, Ollama):
       Print: provider description + where to get key + cost
       Ask: "Enter your [Provider] API key (or press Enter to skip):"
       If provided: write to .env
     If no keys provided: print warning, configure for mock mode.

6. Run: python scripts/setup_providers.py --no-prompt
   Show provider status table.

7. Run: uv run --no-sync pytest tests/ -q --timeout=30 -x
   Show pass/fail. On failure: print "Installation may have issues."
   Do NOT exit 1 on test failure — installation continues.

8. Print success message:
   ╔══════════════════════════════════╗
   ║  ProjectOS installed             ║
   ║  Run: projectos run              ║
   ║  Help: projectos --help          ║
   ║  Docs: docs/                     ║
   ╚══════════════════════════════════╝

### 2. config/projectos.yaml.example

Copy of config/projectos.yaml with all values as comments showing defaults.
Used when user doesn't have a config yet.
Header comment:
  # ProjectOS Configuration
  # Copy this file: cp config/projectos.yaml.example config/projectos.yaml
  # Then edit values for your setup.

### 3. Update README.md

Replace existing Quick Start section with:

## Quick Start

```bash
git clone https://github.com/00-Aryan/Personal_Engineering_OS
cd Personal_Engineering_OS
python install.py
```

That's it. The installer handles dependencies, configuration, and
provider setup interactively.

### Manual Setup
For advanced configuration, see [docs/CONTRIBUTING.md].

### 4. Makefile (project root)

Simple make targets for common operations:

```makefile
.PHONY: install test run lint clean

install:
	python install.py

test:
	UV_CACHE_DIR=/tmp/uv-cache uv run --no-sync pytest -q --timeout=30

run:
	uv run --no-sync projectos run

lint:
	uv run --no-sync python -m py_compile core/*.py agents/*.py

clean:
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf .projectos_state/traces.jsonl
	rm -rf .projectos_state/decisions.jsonl

status:
	uv run --no-sync projectos status

config:
	uv run --no-sync projectos config show
```

### 5. tests/test_install.py

No actual installation in tests — test the installer logic only:
- test_python_version_check_passes_on_current_version
- test_python_version_check_fails_on_old_version (mock sys.version)
- test_uv_check_returns_path_when_installed (mock shutil.which)
- test_env_file_created_from_example
- test_config_yaml_created_from_example
- test_installer_success_message_printed (mock all steps)

## Constraints
- install.py uses stdlib only — no imports that require installation
- install.py works on Linux and macOS (Windows: print limitations)
- Interactive prompts have 30 second timeout (use signal.alarm)
- Non-interactive mode: python install.py --no-prompt
  Uses all defaults, skips API key prompts
- Never hardcode API keys in install.py

## Verification
python install.py --no-prompt (must complete without hanging)
Full test suite passes.
Write TASK_45_RESULT.md. Update tasks/README.md.
