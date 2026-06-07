#!/usr/bin/env python3
"""One-Command Install + Setup Wizard for ProjectOS."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import signal
import subprocess
import sys


def check_python_version() -> None:
    """Check Python version >= 3.10. If not: print clear error, exit 1."""
    if sys.version_info < (3, 10):
        print(
            "Error: ProjectOS requires Python 3.10 or newer.",
            file=sys.stderr,
        )
        print(
            f"Your current Python version is {sys.version}.",
            file=sys.stderr,
        )
        sys.exit(1)


def timeout_handler(signum: int, frame: object) -> None:
    """Signal handler that raises TimeoutError on SIGALRM."""
    raise TimeoutError()


def input_with_timeout(prompt: str, timeout: int = 30) -> str:
    """Get input from the user with a hard timeout using signal.alarm."""
    if not hasattr(signal, "alarm"):
        # Non-Unix platforms
        try:
            return input(prompt)
        except (KeyboardInterrupt, EOFError):
            print()
            return ""

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)
    try:
        val = input(prompt)
        signal.alarm(0)
        return val
    except TimeoutError:
        print("\n[Timeout] No input received within 30 seconds. Skipping.")
        return ""
    except (KeyboardInterrupt, EOFError):
        print()
        signal.alarm(0)
        return ""
    finally:
        signal.alarm(0)


def check_and_install_uv(no_prompt: bool) -> str | None:
    """Check if uv is installed, and offer auto-installation if not."""
    # Check Windows limitations first
    if sys.platform == "win32" or os.name == "nt":
        print(
            "Error: install.py is not supported on Windows.",
            file=sys.stderr,
        )
        print("Please install dependencies manually using uv:", file=sys.stderr)
        print(
            '  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"',
            file=sys.stderr,
        )
        print('  uv pip install -e ".[dev]"', file=sys.stderr)
        sys.exit(1)

    uv_path = shutil.which("uv")
    if not uv_path:
        # Check common local install locations
        home = pathlib.Path.home()
        for candidate in [home / ".local/bin/uv", home / ".cargo/bin/uv"]:
            if candidate.exists() and os.access(candidate, os.X_OK):
                uv_path = str(candidate)
                os.environ["PATH"] = f"{candidate.parent}:{os.environ.get('PATH', '')}"
                break

    if uv_path:
        return uv_path

    print("uv package manager not found.")
    print("ProjectOS uses uv for fast, reliable dependency management.")
    print("Installation command: curl -LsSf https://astral.sh/uv/install.sh | sh")

    if no_prompt:
        print(
            "Error: Running in non-interactive mode but uv is not installed.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Would you like to auto-install uv now? (y/n): ", end="", flush=True)
    choice = input_with_timeout("", 30).strip().lower()

    if choice in ("y", "yes"):
        print("Installing uv...")
        try:
            subprocess.run(
                "curl -LsSf https://astral.sh/uv/install.sh | sh",
                shell=True,
                check=True,
            )
            # Add installed paths to os.environ["PATH"]
            home = pathlib.Path.home()
            for candidate in [home / ".local/bin", home / ".cargo/bin"]:
                if candidate.exists():
                    os.environ["PATH"] = f"{candidate}:{os.environ.get('PATH', '')}"

            uv_path = shutil.which("uv")
            if not uv_path:
                for candidate in [home / ".local/bin/uv", home / ".cargo/bin/uv"]:
                    if candidate.exists():
                        uv_path = str(candidate)
                        os.environ["PATH"] = f"{candidate.parent}:{os.environ.get('PATH', '')}"
                        break

            if not uv_path:
                print(
                    "Error: uv was installed but could not be located in PATH.",
                    file=sys.stderr,
                )
                sys.exit(1)

            print(f"uv installed successfully at: {uv_path}")
            return uv_path
        except subprocess.CalledProcessError as e:
            print(f"Error: uv installation failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("uv installation skipped. Cannot proceed without uv.", file=sys.stderr)
        sys.exit(1)


def install_dependencies(uv_path: str | None) -> None:
    """Run uv pip install -e ".[dev]" showing progress."""
    print("Installing ProjectOS dependencies...")
    cmd_uv = uv_path or "uv"
    try:
        subprocess.run([cmd_uv, "pip", "install", "-e", ".[dev]"], check=True)
        print("Dependencies installed successfully.")
    except subprocess.CalledProcessError as e:
        print("\nError: Dependency installation failed.", file=sys.stderr)
        print("Troubleshooting steps:", file=sys.stderr)
        print("1. Ensure your internet connection is active.", file=sys.stderr)
        print(
            '2. Try running "uv pip install -e \".[dev]\"" manually to see detailed errors.',
            file=sys.stderr,
        )
        print("3. Check if your Python environment is corrupted.", file=sys.stderr)
        sys.exit(1)


def check_and_create_config() -> None:
    """Check if config/projectos.yaml exists. If not, copy from example (uncommenting)."""
    config_path = pathlib.Path("config/projectos.yaml")
    config_example_path = pathlib.Path("config/projectos.yaml.example")

    if not config_path.exists():
        print("Creating config/projectos.yaml from config/projectos.yaml.example...")
        if not config_example_path.exists():
            print(
                "Error: config/projectos.yaml.example not found.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Uncomment lines to create a valid yaml config
        with config_example_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        uncommented_lines = []
        for line in lines:
            if (
                line.startswith("# Copy this file")
                or line.startswith("# Then edit")
                or line.startswith("# ProjectOS Configuration")
                or not line.strip()
            ):
                uncommented_lines.append(line)
            elif line.startswith("# "):
                uncommented_lines.append(line[2:])
            elif line.startswith("#"):
                uncommented_lines.append(line[1:])
            else:
                uncommented_lines.append(line)

        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as f:
            f.writelines(uncommented_lines)


def configure_env(no_prompt: bool) -> None:
    """Check if .env exists. If not: run interactive provider setup or default setup."""
    env_path = pathlib.Path(".env")
    if env_path.exists():
        return

    keys: dict[str, str] = {}

    if not no_prompt:
        print("Let's configure your AI providers.")
        print("You need at least one to use ProjectOS.")

        providers = [
            {
                "name": "Gemini",
                "env_var": "GEMINI_API_KEY",
                "desc": "Google's flagship model family, highly capable and fast.",
                "where": "https://aistudio.google.com/apikey",
                "cost": "Free tier available (1M tokens/day), pay-as-you-go thereafter",
            },
            {
                "name": "OpenRouter",
                "env_var": "OPENROUTER_API_KEY",
                "desc": "A unified API to access DeepSeek-V3, Llama, and other top models.",
                "where": "https://openrouter.ai/keys",
                "cost": "Free models available, paid models are extremely low cost",
            },
            {
                "name": "Ollama",
                "env_var": "OLLAMA_API_KEY",
                "desc": "Run open-source models (like Llama 3, DeepSeek-R1) locally.",
                "where": "No key required, runs on your local machine. Download from https://ollama.ai",
                "cost": "100% Free (runs locally on your hardware)",
            },
        ]

        for p in providers:
            print(f"\n--- {p['name']} ---")
            print(f"Description: {p['desc']}")
            print(f"Where to get key: {p['where']}")
            print(f"Cost: {p['cost']}")
            prompt_str = f"Enter your {p['name']} API key (or press Enter to skip): "
            key_val = input_with_timeout(prompt_str, 30).strip()
            if key_val:
                keys[p["env_var"]] = key_val

        if not keys:
            print("\nWarning: No API keys provided. ProjectOS will be configured for mock mode.")
    else:
        # Default mock mode setup
        pass

    # Write .env file
    content = [
        "# ProjectOS Provider Configuration",
        "# Generated by install.py",
        "",
    ]
    for key in ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_API_KEY"]:
        if key in keys:
            content.append(f"{key}={keys[key]}")
        else:
            content.append(f"# {key}=")

    # Always write OLLAMA_BASE_URL by default
    content.append("OLLAMA_BASE_URL=http://localhost:11434")

    env_path.write_text("\n".join(content) + "\n", encoding="utf-8")


def run_provider_setup() -> None:
    """Run: python scripts/setup_providers.py --no-prompt showing provider status table."""
    print("\nValidating provider configurations...")
    try:
        subprocess.run(
            [sys.executable, "scripts/setup_providers.py", "--no-prompt"],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Warning: Provider setup validation script failed: {e}", file=sys.stderr)


def run_pytest(uv_path: str | None) -> None:
    """Run: uv run --no-sync pytest tests/ -q --timeout=30 -x showing pass/fail."""
    print("\nRunning test suite to verify installation...")
    cmd_uv = uv_path or "uv"
    cmd = [cmd_uv, "run", "--no-sync", "pytest", "tests/", "-q", "--timeout=30", "-x"]
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = "/tmp/uv-cache"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    res = subprocess.run(cmd, env=env)
    if res.returncode != 0:
        print("\nInstallation may have issues.")
    else:
        print("\nAll tests passed successfully.")


def print_success() -> None:
    """Print the final success ASCII banner."""
    print("╔══════════════════════════════════╗")
    print("║  ProjectOS installed             ║")
    print("║  Run: projectos run              ║")
    print("║  Help: projectos --help          ║")
    print("║  Docs: docs/                     ║")
    print("╚══════════════════════════════════╝")


def main() -> None:
    """Main execution of the installer."""
    parser = argparse.ArgumentParser(description="Install ProjectOS and dependencies.")
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Run installation without user interaction using defaults.",
    )
    args = parser.parse_args()

    check_python_version()
    uv_path = check_and_install_uv(args.no_prompt)
    install_dependencies(uv_path)
    check_create_example_yaml_if_needed()
    check_and_create_config()
    configure_env(args.no_prompt)
    run_provider_setup()
    choose_project_template(args.no_prompt, uv_path)
    run_pytest(uv_path)
    print_success()


def choose_project_template(no_prompt: bool, uv_path: str | None) -> None:
    """Prompt the user to select a project template and apply it."""
    templates_dir = pathlib.Path("templates")
    templates = []
    if templates_dir.exists():
        for subdir in templates_dir.iterdir():
            if subdir.is_dir():
                yaml_path = subdir / "template.yaml"
                if yaml_path.exists():
                    try:
                        name = subdir.name
                        desc = ""
                        with yaml_path.open("r", encoding="utf-8") as f:
                            for line in f:
                                if line.strip().startswith("name:"):
                                    name = line.split(":", 1)[1].strip().strip('"').strip("'")
                                elif line.strip().startswith("description:"):
                                    desc = line.split(":", 1)[1].strip().strip('"').strip("'")
                        templates.append((name, desc))
                    except Exception:
                        pass
    templates.sort()

    if not templates:
        return

    if no_prompt:
        return

    print("\nWhat type of project are you setting up ProjectOS for?")
    for i, (name, desc) in enumerate(templates, 1):
        print(f"  [{i}] {name} - {desc}")
    print("  [Enter] Skip template setup")

    choice_str = input_with_timeout("Enter the number of your choice: ", 30).strip()
    if choice_str.isdigit():
        idx = int(choice_str) - 1
        if 0 <= idx < len(templates):
            chosen_name = templates[idx][0]
            print(f"Applying template '{chosen_name}'...")
            try:
                cmd_uv = uv_path or "uv"
                subprocess.run(
                    [cmd_uv, "run", "--no-sync", "projectos", "template", "apply", chosen_name],
                    check=True,
                )
                print(f"Template '{chosen_name}' applied successfully.")
            except subprocess.CalledProcessError as e:
                print(f"Error: Failed to apply template: {e}", file=sys.stderr)



def check_create_example_yaml_if_needed() -> None:
    """Verify config/projectos.yaml.example is present, otherwise create it."""
    example_path = pathlib.Path("config/projectos.yaml.example")
    if not example_path.exists():
        # Just in case, create it (should already be done by previous step)
        config_path = pathlib.Path("config/projectos.yaml")
        if config_path.exists():
            content = config_path.read_text(encoding="utf-8")
            commented = []
            for line in content.splitlines():
                if line.startswith("#") or not line.strip():
                    commented.append(line)
                else:
                    commented.append(f"# {line}")
            example_path.parent.mkdir(parents=True, exist_ok=True)
            example_path.write_text(
                "# ProjectOS Configuration\n"
                "# Copy this file: cp config/projectos.yaml.example config/projectos.yaml\n"
                "# Then edit values for your setup.\n\n" + "\n".join(commented) + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
