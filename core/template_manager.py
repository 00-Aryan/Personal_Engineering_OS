"""Template manager for ProjectOS project configurations."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from core.config_loader import ProjectConfig


class TemplateManager:
    """Manages ProjectOS templates, applying them and copying assets."""

    TEMPLATES_DIR = Path("templates/")

    @classmethod
    def list_templates(cls) -> List[Dict[str, Any]]:
        """Read all template.yaml files. Returns [{name, description, path}]."""
        templates = []
        if not cls.TEMPLATES_DIR.exists():
            return templates

        for subdir in cls.TEMPLATES_DIR.iterdir():
            if subdir.is_dir():
                yaml_path = subdir / "template.yaml"
                if yaml_path.exists():
                    try:
                        with yaml_path.open("r", encoding="utf-8") as f:
                            data = yaml.safe_load(f)
                        if isinstance(data, dict):
                            templates.append({
                                "name": data.get("name", subdir.name),
                                "description": data.get("description", ""),
                                "path": subdir.resolve()
                            })
                    except Exception:
                        pass
        return sorted(templates, key=lambda x: x["name"])

    @classmethod
    def apply_template(
        cls,
        template_name: str,
        target_config: ProjectConfig,
    ) -> ProjectConfig:
        """Load template.yaml for template_name.
        Merge template overrides into target_config.
        Template values override config defaults.
        User values override template values.
        Return merged config.
        """
        template_yaml_path = cls.TEMPLATES_DIR / template_name / "template.yaml"
        if not template_yaml_path.exists():
            raise FileNotFoundError(f"Template not found: {template_name}")

        with template_yaml_path.open("r", encoding="utf-8") as f:
            template_data = yaml.safe_load(f)

        if not isinstance(template_data, dict):
            raise ValueError("Template YAML must be a key-value mapping.")

        # Exclude name/description from merging into target_config
        overrides = {k: v for k, v in template_data.items() if k not in ("name", "description")}

        # Map template root-level ignore_patterns to project.ignore_patterns
        if "ignore_patterns" in overrides:
            if "project" not in target_config.raw_config:
                target_config.raw_config["project"] = {}
            if "ignore_patterns" not in target_config.raw_config["project"]:
                target_config.raw_config["project"]["ignore_patterns"] = []

            user_ignores = target_config.raw_config["project"]["ignore_patterns"]
            for item in overrides["ignore_patterns"]:
                if item not in user_ignores:
                    user_ignores.append(item)
            del overrides["ignore_patterns"]

        def merge_dicts(user_dict: dict, template_dict: dict) -> dict:
            for key, val in template_dict.items():
                if key not in user_dict:
                    user_dict[key] = val
                else:
                    if isinstance(user_dict[key], dict) and isinstance(val, dict):
                        merge_dicts(user_dict[key], val)
                    elif isinstance(user_dict[key], list) and isinstance(val, list):
                        merged_list = list(user_dict[key])
                        for item in val:
                            if item not in merged_list:
                                merged_list.append(item)
                        user_dict[key] = merged_list
            return user_dict

        # Merge overrides into raw_config
        merge_dicts(target_config.raw_config, overrides)

        # Re-initialize the project config with the merged raw_config
        target_config.__init__(
            target_config.raw_config,
            target_config.config_path,
            target_config.env,
        )
        return target_config

    @classmethod
    def copy_template_files(
        cls,
        template_name: str,
        target_dir: Path,
    ) -> List[str]:
        """Copy AGENTS.md and .gitignore to target_dir if not present.
        Never overwrite existing files.
        Return list of files copied.
        """
        source_dir = cls.TEMPLATES_DIR / template_name
        if not source_dir.exists():
            raise FileNotFoundError(f"Template directory not found: {template_name}")

        copied_files = []
        for filename in ("AGENTS.md", ".gitignore"):
            source_file = source_dir / filename
            if source_file.exists():
                target_file = target_dir / filename
                if filename == "AGENTS.md" and target_file.exists():
                    # Append content
                    with source_file.open("r", encoding="utf-8") as sf:
                        source_content = sf.read()
                    with target_file.open("a", encoding="utf-8") as tf:
                        tf.write("\n\n" + source_content)
                    copied_files.append(filename)
                elif not target_file.exists():
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(str(source_file), str(target_file))
                    copied_files.append(filename)
        return copied_files

    @classmethod
    def detect_project_type(cls, project_path: Path) -> Optional[str]:
        """Heuristic detection of project type from requirements.txt only."""
        req_path = project_path / "requirements.txt"
        if not req_path.exists():
            return None

        try:
            content = req_path.read_text(encoding="utf-8").lower()
        except Exception:
            return None

        if any(lib in content for lib in ("sklearn", "scikit-learn", "torch", "pandas")):
            return "ds_project"
        if any(lib in content for lib in ("chromadb", "faiss", "langchain", "llamaindex", "llama-index")):
            return "rag_pipeline"
        if any(lib in content for lib in ("fastapi", "flask", "django")):
            return "web_api"
        if any(lib in content for lib in ("click", "typer", "argparse")):
            return "cli_tool"
        return None
