import os
import tempfile
from pathlib import Path
import pytest
import yaml

from core.config_loader import ProjectConfig


def test_load_valid_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        config_file = tmp_path / "projectos.yaml"
        ProjectConfig.create_default(config_file)
        
        # Load it
        config = ProjectConfig.load(config_file)
        assert config.version == "0.3.0"
        assert config.project_name == "my-project"
        assert len(config.watch_patterns) > 0
        assert len(config.providers) > 0


def test_validate_catches_missing_required_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        config_file = tmp_path / "projectos.yaml"
        
        # Write config missing fields
        bad_config = {
            "version": "0.3.0",
            "project": {
                # missing name
                "root": "."
            },
            "providers": {
                "default": "gemini-flash"
                # missing gemini-flash definition
            }
        }
        config_file.write_text(yaml.safe_dump(bad_config), encoding="utf-8")
        
        config = ProjectConfig.load(config_file)
        errors = config.validate()
        assert len(errors) > 0
        assert any("name" in e for e in errors)
        assert any("gemini-flash" in e for e in errors)


def test_create_default_writes_valid_yaml():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        config_file = tmp_path / "projectos.yaml"
        ProjectConfig.create_default(config_file)
        
        assert config_file.exists()
        # Parse it
        with config_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert data.get("version") == "0.3.0"


def test_env_file_loaded_for_api_keys():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        config_file = tmp_path / "projectos.yaml"
        ProjectConfig.create_default(config_file)
        
        env_file = tmp_path / ".env"
        env_file.write_text("GEMINI_API_KEY=test_gemini_key_123\nOPENROUTER_API_KEY=test_openrouter_key_456", encoding="utf-8")
        
        # Clear environment vars if set
        old_gemini = os.environ.get("GEMINI_API_KEY")
        old_or = os.environ.get("OPENROUTER_API_KEY")
        if "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]
        if "OPENROUTER_API_KEY" in os.environ:
            del os.environ["OPENROUTER_API_KEY"]
            
        try:
            config = ProjectConfig.load(config_file, env_file=env_file)
            assert os.environ.get("GEMINI_API_KEY") == "test_gemini_key_123"
            assert os.environ.get("OPENROUTER_API_KEY") == "test_openrouter_key_456"
        finally:
            # Restore environment
            if old_gemini:
                os.environ["GEMINI_API_KEY"] = old_gemini
            elif "GEMINI_API_KEY" in os.environ:
                del os.environ["GEMINI_API_KEY"]
            if old_or:
                os.environ["OPENROUTER_API_KEY"] = old_or
            elif "OPENROUTER_API_KEY" in os.environ:
                del os.environ["OPENROUTER_API_KEY"]


def test_config_provides_token_budget_values():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        config_file = tmp_path / "projectos.yaml"
        ProjectConfig.create_default(config_file)
        
        config = ProjectConfig.load(config_file)
        assert "planning" in config.token_budgets
        assert config.token_budgets["planning"]["soft"] == 2000
        assert config.token_budgets["planning"]["hard"] == 4000
        assert config.token_budgets["planning"]["daily"] == 50000


def test_config_provides_quality_gate_values():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        config_file = tmp_path / "projectos.yaml"
        ProjectConfig.create_default(config_file)
        
        config = ProjectConfig.load(config_file)
        assert "code_writing" in config.quality_gates
        assert config.quality_gates["code_writing"]["min_score"] == 0.65
        assert config.quality_gates["code_writing"]["require_llm_eval"] is True


def test_missing_config_file_raises_clear_error():
    non_existent = Path("non_existent_directory_123/config.yaml")
    with pytest.raises(FileNotFoundError) as exc_info:
        ProjectConfig.load(non_existent)
    assert "Config file not found" in str(exc_info.value)
