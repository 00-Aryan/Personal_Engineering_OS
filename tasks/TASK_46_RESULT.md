# TASK_46 RESULT: Project Templates

## Files Created or Modified

### Created
- [core/template_manager.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/template_manager.py) (Manages project templates, listing templates, applying overrides recursively with user preservation, appending `AGENTS.md` and copying `.gitignore`, and detecting project types heuristically from `requirements.txt`)
- [tests/test_template_manager.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/tests/test_template_manager.py) (Test suite for template manager operations)
- `templates/` directory containing:
  - [templates/README.md](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/README.md) (Explanation of templates and structure)
  - `ds_project/`: [template.yaml](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/ds_project/template.yaml), [AGENTS.md](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/ds_project/AGENTS.md), [.gitignore](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/ds_project/.gitignore)
  - `rag_pipeline/`: [template.yaml](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/rag_pipeline/template.yaml), [AGENTS.md](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/rag_pipeline/AGENTS.md), [.gitignore](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/rag_pipeline/.gitignore)
  - `web_api/`: [template.yaml](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/web_api/template.yaml), [AGENTS.md](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/web_api/AGENTS.md), [.gitignore](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/web_api/.gitignore)
  - `cli_tool/`: [template.yaml](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/cli_tool/template.yaml), [AGENTS.md](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/cli_tool/AGENTS.md), [.gitignore](file:///home/aryan/June-2026/Personal_Engineering%20_OS/templates/cli_tool/.gitignore)

### Modified
- [cli/main.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/cli/main.py) (Implemented `projectos template list`, `projectos template apply <name>`, and `projectos template detect` subcommands)
- [install.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/install.py) (Integrated template prompt after provider setup using a subprocess CLI call for robust execution)

## Test Count and Verification

- **Tests passed**: 375 tests (including 7 new template-specific tests).
- **Run command**:
  ```bash
  UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest
  ```
- **CLI Commands Verification**:
  - `uv run --no-sync projectos template list` shows all 4 templates and descriptions.
  - `uv run --no-sync projectos template detect` heuristically checks `requirements.txt` and returns the type.
  - `uv run --no-sync projectos template apply ds_project` merges settings into config/projectos.yaml, appends AGENTS.md, and creates `.gitignore`.

## Decisions Made and Rationale
1. **Root-Level `ignore_patterns` Mapping**: The templates specify `ignore_patterns` at the root of `template.yaml`, but the master config stores them under `project.ignore_patterns`. Added explicit mapping in `TemplateManager.apply_template` to merge them under the correct key.
2. **Subprocess Call in installer**: Using `uv run --no-sync projectos template apply chosen_name` in the installer ensures it runs with clean imports and dependencies without needing PyYAML loaded in the host python process.
3. **Additive `AGENTS.md`**: Implemented automatic appending of custom instructions if `AGENTS.md` already exists, ensuring template guidelines are layered on top of existing repository instruction files instead of discarding them.

## Flagged for Human Review
- None.
