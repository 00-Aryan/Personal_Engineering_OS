"""Tests for the AGY and Codex plugin packaging."""

from __future__ import annotations

import json
import pathlib
import yaml


def test_plugin_yaml_valid_schema() -> None:
    """Verify that .agents/plugin.yaml exists and has required manifest fields."""
    plugin_yaml = pathlib.Path(".agents/plugin.yaml")
    assert plugin_yaml.exists()

    with plugin_yaml.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert isinstance(data, dict)
    for field in ("name", "version", "description", "author", "skills", "mcp_servers", "workflows"):
        assert field in data
    assert data["name"] == "projectos"
    assert isinstance(data["skills"], list)
    assert isinstance(data["workflows"], list)
    assert isinstance(data["mcp_servers"], list)


def test_codex_plugin_json_valid_schema() -> None:
    """Verify that .codex/plugin.json exists and has required config fields."""
    plugin_json = pathlib.Path(".codex/plugin.json")
    assert plugin_json.exists()

    with plugin_json.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, dict)
    for field in ("name", "version", "description", "skills", "mcp"):
        assert field in data
    assert data["name"] == "projectos"
    assert isinstance(data["skills"], list)
    assert isinstance(data["mcp"], dict)


def test_all_skills_referenced_exist() -> None:
    """Verify that all skills listed in plugin manifests actually exist on disk."""
    # Check .agents/plugin.yaml skills
    with pathlib.Path(".agents/plugin.yaml").open("r", encoding="utf-8") as f:
        agy_data = yaml.safe_load(f)
    for skill_path in agy_data["skills"]:
        # The skills path should be relative to workspace root (e.g. .agents/skills/projectos-plan)
        skill_dir = pathlib.Path(skill_path)
        assert skill_dir.exists(), f"Skill directory does not exist: {skill_path}"
        assert (skill_dir / "SKILL.md").exists(), f"SKILL.md missing under: {skill_path}"

    # Check .codex/plugin.json skills
    with pathlib.Path(".codex/plugin.json").open("r", encoding="utf-8") as f:
        codex_data = json.load(f)
    for skill_path in codex_data["skills"]:
        skill_dir = pathlib.Path(skill_path)
        assert skill_dir.exists(), f"Skill directory does not exist: {skill_path}"
        assert (skill_dir / "SKILL.md").exists(), f"SKILL.md missing under: {skill_path}"


def test_all_workflows_referenced_exist() -> None:
    """Verify that all workflows listed in .agents/plugin.yaml actually exist on disk."""
    with pathlib.Path(".agents/plugin.yaml").open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for wf_path in data["workflows"]:
        path = pathlib.Path(wf_path)
        assert path.exists(), f"Workflow file does not exist: {wf_path}"


def test_package_script_creates_dist_dir() -> None:
    """Verify that dist/ directory contains generated package archive and manifest."""
    dist_dir = pathlib.Path("dist")
    assert dist_dir.exists()
    
    # Check if tarball and manifest are present
    tarball = next(dist_dir.glob("projectos-plugin-v*.tar.gz"), None)
    manifest = next(dist_dir.glob("projectos-plugin-v*-manifest.json"), None)

    assert tarball is not None, "tar.gz plugin archive missing in dist/"
    assert manifest is not None, "manifest.json missing in dist/"


def test_manifest_json_has_required_fields() -> None:
    """Verify packaged manifest file has required installation metadata."""
    dist_dir = pathlib.Path("dist")
    manifest_file = next(dist_dir.glob("projectos-plugin-v*-manifest.json"), None)
    assert manifest_file is not None

    with manifest_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, dict)
    for field in ("name", "version", "files", "install_command", "mcp_tools"):
        assert field in data, f"Required field '{field}' missing in packaged manifest"
    assert data["name"] == "projectos"
    assert isinstance(data["files"], list)
    assert len(data["files"]) > 0
    # Make sure install.py is in the archive file list
    assert any("install.py" in f for f in data["files"])
