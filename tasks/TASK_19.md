# TASK_19: Multi-Project Support

## Purpose
Point ProjectOS at any repo, not just current directory.
Watch multiple projects simultaneously from one daemon.

## Pre-conditions
Read core/projectos.py, core/trigger_system.py, 
core/persistence.py fully.

## Deliverables

### 1. core/project_config.py

@dataclass
class ProjectConfig:
  name: str
  root_path: Path
  watch_patterns: List[str]  (e.g. ["*.py", "*.md"])
  ignore_patterns: List[str] (e.g. ["__pycache__", ".git", ".venv"])
  state_dir: Path  (defaults to root_path / ".projectos_state")
  models_config: Path (defaults to root_path / "config/models.yaml",
                       falls back to global ~/.projectos/models.yaml)
  enabled: bool = True

class ProjectRegistry:
  __init__(config_path: Path)  (reads ~/.projectos/projects.yaml)
  
  list_projects() -> List[ProjectConfig]
  add_project(config: ProjectConfig) -> None
  remove_project(name: str) -> None
  get_project(name: str) -> Optional[ProjectConfig]

### 2. Update core/projectos.py
  Add @classmethod from_project_config(cls, config: ProjectConfig)
  Existing __init__ becomes single-project mode.
  
class MultiProjectOS:
  __init__(registry: ProjectRegistry)
  start() → starts one ProjectOS instance per enabled project
             each in its own thread with its own state dir
  stop() → stops all instances cleanly
  status() -> Dict[str, Dict] (project name → status dict)

### 3. Update cli/main.py
  projectos projects list
    → shows all registered projects with status
  
  projectos projects add --name myproject --path /path/to/repo
    → adds to ~/.projectos/projects.yaml
  
  projectos projects remove --name myproject
    → removes from registry
  
  projectos run --all
    → starts MultiProjectOS (all enabled projects)
  
  projectos run (no flag)
    → existing behavior: single project at current dir

### 4. tests/test_project_registry.py
  Use tmp_path:
  - test_add_and_list_project
  - test_remove_project
  - test_get_project_returns_none_for_missing
  - test_disabled_project_not_in_list
  - test_config_file_created_if_missing

## Constraints
- Each project has fully isolated state (separate state_dir)
- Projects do not share model providers (each loads own config)
- Multi-project mode logs with project name prefix
- Global config dir: ~/.projectos/

## Verification
Full test suite. Write TASK_19_RESULT.md. Update tasks/README.md.
