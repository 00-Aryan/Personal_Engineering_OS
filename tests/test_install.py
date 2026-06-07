"""Tests for the install.py installer script."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import install


def test_python_version_check_passes_on_current_version() -> None:
    """Verify that Python version check passes on Python >= 3.10."""
    with patch("sys.version_info", (3, 11, 2)):
        # Should not raise SystemExit
        install.check_python_version()


def test_python_version_check_fails_on_old_version() -> None:
    """Verify that Python version check fails on Python < 3.10."""
    with patch("sys.version_info", (3, 9, 5)):
        with pytest.raises(SystemExit) as exc_info:
            install.check_python_version()
        assert exc_info.value.code == 1


def test_uv_check_returns_path_when_installed() -> None:
    """Verify uv_check returns path if uv is already in PATH."""
    with patch("shutil.which", return_value="/usr/local/bin/uv"):
        path = install.check_and_install_uv(no_prompt=True)
        assert path == "/usr/local/bin/uv"


def test_env_file_created_from_example(tmp_path: Path) -> None:
    """Verify that .env is created and written properly."""
    env_file = tmp_path / ".env"
    with patch("pathlib.Path.exists", return_value=False), \
         patch("pathlib.Path.write_text") as mock_write:
        # We need env_path inside configure_env to be our tmp_path / ".env"
        # Let's mock pathlib.Path.exists and write_text directly.
        # To make it simple, we patch Path in install module.
        with patch("install.pathlib.Path") as MockPath:
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = False
            MockPath.return_value = mock_path_instance

            install.configure_env(no_prompt=True)

            mock_path_instance.write_text.assert_called_once()
            # Ensure OLLAMA_BASE_URL is in written content
            written_content = mock_path_instance.write_text.call_args[0][0]
            assert "OLLAMA_BASE_URL=http://localhost:11434" in written_content


def test_config_yaml_created_from_example(tmp_path: Path) -> None:
    """Verify config/projectos.yaml is copied and uncommented if it does not exist."""
    config_path = tmp_path / "projectos.yaml"
    example_path = tmp_path / "projectos.yaml.example"

    example_content = """# ProjectOS Configuration
# Copy this file: cp config/projectos.yaml.example config/projectos.yaml
# Then edit values for your setup.

# version: "0.3.0"
# project:
#   name: "my-project"
"""
    example_path.write_text(example_content, encoding="utf-8")

    # Patch Path inside install to resolve to our temp paths
    with patch("install.pathlib.Path") as MockPath:
        def path_side_effect(path_str):
            if path_str == "config/projectos.yaml":
                return config_path
            if path_str == "config/projectos.yaml.example":
                return example_path
            return Path(path_str)

        MockPath.side_effect = path_side_effect

        install.check_and_create_config()

        assert config_path.exists()
        written = config_path.read_text(encoding="utf-8")
        assert "version: \"0.3.0\"" in written
        assert "project:" in written
        # The header comments should still have the leading hash
        assert "# ProjectOS Configuration" in written


def test_installer_success_message_printed(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify installer prints success message correctly."""
    install.print_success()
    captured = capsys.readouterr()
    assert "ProjectOS installed" in captured.out
    assert "Run: projectos run" in captured.out
