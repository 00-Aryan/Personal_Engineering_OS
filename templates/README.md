# ProjectOS Templates

This directory contains pre-configured project templates to help set up ProjectOS for specific workflows:

- **ds_project**: For Data Science/ML projects with notebooks and data assets.
- **rag_pipeline**: For RAG applications with vector databases and LLM chains.
- **web_api**: For backend REST APIs (FastAPI, Flask, Django).
- **cli_tool**: For command-line applications.

Each template contains:
- `template.yaml`: Configuration overrides (agents, quality gates, ignore patterns, semantic routing examples).
- `AGENTS.md`: Custom agent prompts and context rules.
- `.gitignore`: Additions to prevent ProjectOS from indexing temporary/data files.
