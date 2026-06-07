#!/usr/bin/env python3
"""Package ProjectOS as a distributable plugin archive."""

from __future__ import annotations

import json
import os
import pathlib
import tarfile
import yaml


def main() -> None:
    # 1. Read .agents/plugin.yaml for metadata
    plugin_yaml_path = pathlib.Path(".agents/plugin.yaml")
    if not plugin_yaml_path.exists():
        print("Error: .agents/plugin.yaml not found.")
        return

    with plugin_yaml_path.open("r", encoding="utf-8") as f:
        metadata = yaml.safe_load(f)

    name = metadata.get("name", "projectos")
    version = metadata.get("version", "0.4.0")

    # 2. Create dist/ directory
    dist_dir = pathlib.Path("dist")
    dist_dir.mkdir(exist_ok=True)

    # 3. Bundle files
    tar_filename = f"projectos-plugin-v{version}.tar.gz"
    tar_path = dist_dir / tar_filename

    # Paths to bundle
    bundle_paths = [
        pathlib.Path(".agents/skills"),
        pathlib.Path(".agents/workflows"),
        pathlib.Path("mcp_server"),
        pathlib.Path("config/projectos.yaml.example"),
        pathlib.Path("install.py"),
        pathlib.Path("README.md"),
    ]

    all_files: list[str] = []

    with tarfile.open(tar_path, "w:gz") as tar:
        for p in bundle_paths:
            if not p.exists():
                print(f"Warning: Bundled path {p} does not exist.")
                continue

            if p.is_dir():
                for root, dirs, files in os.walk(p):
                    # Sort dirs and files to be deterministic
                    dirs.sort()
                    files.sort()
                    for file in files:
                        filepath = pathlib.Path(root) / file
                        # Skip __pycache__ or temporary files
                        if "__pycache__" in filepath.parts or filepath.name.endswith(".pyc"):
                            continue
                        rel_path = filepath
                        tar.add(filepath, arcname=str(rel_path))
                        all_files.append(str(rel_path))
            else:
                rel_path = p
                tar.add(p, arcname=str(rel_path))
                all_files.append(str(rel_path))

    all_files.sort()

    # 5. Write dist/projectos-plugin-v{version}-manifest.json
    manifest = {
        "name": name,
        "version": version,
        "files": all_files,
        "install_command": "python install.py",
        "mcp_tools": ["projectos_plan", "projectos_review", "projectos_status"],
    }

    manifest_filename = f"projectos-plugin-v{version}-manifest.json"
    manifest_path = dist_dir / manifest_filename

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    # 6. Print success
    print(f"Plugin packaged: dist/{tar_filename}")
    print("\nInstall Instructions:")
    print("AGY:")
    print(f"  agy plugin install dist/{tar_filename}")
    print("\nCodex:")
    print(f"  codex plugin install dist/{tar_filename}")
    print("\nMCP Server (any client):")
    print("  uv run --no-sync python -m mcp_server.server")


if __name__ == "__main__":
    main()
