"""Project registry configuration for multi-project ProjectOS."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional

import yaml


ENCODING = "utf-8"
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"
GLOBAL_CONFIG_DIR_NAME = ".projectos"
PROJECTS_CONFIG_NAME = "projects.yaml"
MODELS_CONFIG_NAME = "models.yaml"
CONFIG_DIR_NAME = "config"
STATE_DIR_NAME = ".projectos_state"

DEFAULT_WATCH_PATTERNS = ["*.py", "*.md"]
DEFAULT_IGNORE_PATTERNS = ["__pycache__", ".git", ".venv"]

KEY_PROJECTS = "projects"
KEY_NAME = "name"
KEY_ROOT_PATH = "root_path"
KEY_WATCH_PATTERNS = "watch_patterns"
KEY_IGNORE_PATTERNS = "ignore_patterns"
KEY_STATE_DIR = "state_dir"
KEY_MODELS_CONFIG = "models_config"
KEY_ENABLED = "enabled"


def _write_atomically(path: Path, content: str) -> None:
    """Write content to a path by replacing it with a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{TEMP_PREFIX}{path.name}.",
        suffix=TEMP_SUFFIX,
        dir=str(path.parent),
    )
    try:
        with os.fdopen(
            file_descriptor,
            FILE_WRITE_MODE,
            encoding=ENCODING,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def default_projects_config_path() -> Path:
    """Return the default global projects registry path."""
    return Path.home() / GLOBAL_CONFIG_DIR_NAME / PROJECTS_CONFIG_NAME


def global_models_config_path() -> Path:
    """Return the default global model config path."""
    return Path.home() / GLOBAL_CONFIG_DIR_NAME / MODELS_CONFIG_NAME


@dataclass
class ProjectConfig:
    """Configuration for one ProjectOS-managed repository."""

    name: str
    root_path: Path
    watch_patterns: List[str]
    ignore_patterns: List[str]
    state_dir: Optional[Path] = None
    models_config: Optional[Path] = None
    enabled: bool = True

    def __post_init__(self) -> None:
        """Normalize paths and fill derived defaults."""
        self.root_path = Path(self.root_path).expanduser().resolve()
        self.watch_patterns = list(self.watch_patterns or DEFAULT_WATCH_PATTERNS)
        self.ignore_patterns = list(self.ignore_patterns or DEFAULT_IGNORE_PATTERNS)
        self.state_dir = (
            Path(self.state_dir).expanduser().resolve()
            if self.state_dir is not None
            else self.root_path / STATE_DIR_NAME
        )
        self.models_config = (
            Path(self.models_config).expanduser().resolve()
            if self.models_config is not None
            else self._default_models_config(self.root_path)
        )

    @classmethod
    def create(
        cls,
        name: str,
        root_path: Path | str,
        watch_patterns: Optional[List[str]] = None,
        ignore_patterns: Optional[List[str]] = None,
        state_dir: Optional[Path | str] = None,
        models_config: Optional[Path | str] = None,
        enabled: bool = True,
    ) -> "ProjectConfig":
        """Create a ProjectConfig with default paths resolved from root_path."""
        resolved_root = Path(root_path).expanduser().resolve()
        return cls(
            name=name,
            root_path=resolved_root,
            watch_patterns=list(watch_patterns or DEFAULT_WATCH_PATTERNS),
            ignore_patterns=list(ignore_patterns or DEFAULT_IGNORE_PATTERNS),
            state_dir=Path(state_dir) if state_dir is not None else None,
            models_config=Path(models_config) if models_config is not None else None,
            enabled=enabled,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProjectConfig":
        """Deserialize a ProjectConfig from a mapping."""
        name = str(value[KEY_NAME])
        root_path = Path(str(value[KEY_ROOT_PATH])).expanduser().resolve()
        return cls.create(
            name=name,
            root_path=root_path,
            watch_patterns=cls._string_list(
                value.get(KEY_WATCH_PATTERNS),
                DEFAULT_WATCH_PATTERNS,
            ),
            ignore_patterns=cls._string_list(
                value.get(KEY_IGNORE_PATTERNS),
                DEFAULT_IGNORE_PATTERNS,
            ),
            state_dir=value.get(KEY_STATE_DIR),
            models_config=value.get(KEY_MODELS_CONFIG),
            enabled=bool(value.get(KEY_ENABLED, True)),
        )

    def to_mapping(self) -> Mapping[str, Any]:
        """Serialize this project config to a YAML-safe mapping."""
        return {
            KEY_NAME: self.name,
            KEY_ROOT_PATH: str(self.root_path),
            KEY_WATCH_PATTERNS: list(self.watch_patterns),
            KEY_IGNORE_PATTERNS: list(self.ignore_patterns),
            KEY_STATE_DIR: str(self.state_dir),
            KEY_MODELS_CONFIG: str(self.models_config),
            KEY_ENABLED: self.enabled,
        }

    @staticmethod
    def _default_models_config(root_path: Path) -> Path:
        """Return the project model config or global fallback path."""
        project_models = root_path / CONFIG_DIR_NAME / MODELS_CONFIG_NAME
        if project_models.exists():
            return project_models
        return global_models_config_path()

    @staticmethod
    def _string_list(value: Any, default: List[str]) -> List[str]:
        """Return a list of strings from a value or a default list."""
        if not isinstance(value, list):
            return list(default)
        return [str(item) for item in value if isinstance(item, str)]


class ProjectRegistry:
    """Persist and query ProjectOS project registrations."""

    def __init__(self, config_path: Path | str = default_projects_config_path()) -> None:
        """Initialize the project registry, creating the config file if missing."""
        self.config_path = Path(config_path).expanduser()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self._write_projects([])

    def list_projects(self) -> List[ProjectConfig]:
        """Return enabled registered project configs."""
        return [project for project in self._read_projects() if project.enabled]

    def add_project(self, config: ProjectConfig) -> None:
        """Add or replace one project config by name."""
        projects = [
            project for project in self._read_projects() if project.name != config.name
        ]
        projects.append(config)
        self._write_projects(projects)

    def remove_project(self, name: str) -> None:
        """Remove one project config by name."""
        projects = [project for project in self._read_projects() if project.name != name]
        self._write_projects(projects)

    def get_project(self, name: str) -> Optional[ProjectConfig]:
        """Return an enabled project by name, or None when missing."""
        for project in self.list_projects():
            if project.name == name:
                return project
        return None

    def _read_projects(self) -> List[ProjectConfig]:
        """Read all project configs, including disabled ones."""
        payload = self._read_payload()
        projects = payload.get(KEY_PROJECTS, [])
        if not isinstance(projects, list):
            return []
        configs = []
        for project in projects:
            if isinstance(project, Mapping):
                configs.append(ProjectConfig.from_mapping(project))
        return configs

    def _read_payload(self) -> Mapping[str, Any]:
        """Read the registry YAML payload."""
        if not self.config_path.exists():
            return {KEY_PROJECTS: []}
        payload = yaml.safe_load(self.config_path.read_text(encoding=ENCODING))
        return payload if isinstance(payload, Mapping) else {KEY_PROJECTS: []}

    def _write_projects(self, projects: List[ProjectConfig]) -> None:
        """Write project configs atomically."""
        payload = {KEY_PROJECTS: [project.to_mapping() for project in projects]}
        rendered = yaml.safe_dump(payload, sort_keys=False)
        _write_atomically(self.config_path, rendered)


__all__ = [
    "ProjectConfig",
    "ProjectRegistry",
    "default_projects_config_path",
    "global_models_config_path",
]
