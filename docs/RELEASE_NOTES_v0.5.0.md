# ProjectOS v0.5.0 Release Notes

## What's New
- One-command install via `install.py`
- Project templates: `ds_project`, `rag_pipeline`, `web_api`, `cli_tool`
- AGY and Codex plugin packaging
- External-audience README and documentation
- GitHub issue and PR templates

## Improvements
- Integrated configuration consolidation (`projectos.yaml`) replacing `models.yaml`.
- Fixed environment isolation leaks in test suites.
- Reduced overall test suite duration.
- Enhanced robustness of semantic routing fallback paths.

## Known Limitations
- Runs entirely in your local process; no distributed durable queue.
- Model outputs are parsed defensively, but lack absolute correctness guarantees.
- Requires valid API keys configured in `.env` for advanced cloud agent actions.

## Upgrade from v0.4.0
- Delete `config/models.yaml` (deprecated).
- Run `python install.py` to generate the new `config/projectos.yaml` configuration.
