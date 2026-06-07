# TASK_46: Project Templates

## Engineering Context

When a new user runs ProjectOS on their project for the first time,
the agents have no context about what kind of project it is.
A data science project needs different review criteria than a web API.
A RAG pipeline needs different planning decomposition than a CLI tool.

Project templates solve this by pre-configuring ProjectOS for common
project types. A template sets:
- Which agents are most relevant
- What review criteria to emphasize  
- What planning patterns to use
- What quality gate thresholds make sense
- What to ignore (e.g. data files for DS projects)

## Pre-conditions
Read config/projectos.yaml, core/config_loader.py,
core/intelligence/semantic_router.py fully.
Read AGENTS.md.

## Deliverables

### 1. templates/ directory structure

templates/
├── README.md          (how to use templates)
├── ds_project/
│   ├── template.yaml  (config overrides for DS projects)
│   ├── AGENTS.md      (project-specific agent instructions)
│   └── .gitignore     (data files, notebooks, models)
├── rag_pipeline/
│   ├── template.yaml
│   ├── AGENTS.md
│   └── .gitignore
├── web_api/
│   ├── template.yaml
│   ├── AGENTS.md
│   └── .gitignore
└── cli_tool/
    ├── template.yaml
    ├── AGENTS.md
    └── .gitignore

### 2. templates/ds_project/template.yaml

```yaml
# ProjectOS Template: Data Science Project
name: ds_project
description: "For ML/DS projects with notebooks, datasets, and model training"

# Agent model overrides (DeepSeek for planning complex ML tasks)
agents:
  planning: deepseek-v3
  architecture: deepseek-v3

# Quality gate overrides (lower threshold — DS code is often exploratory)
quality_gates:
  code_writing:
    min_score: 0.55
    require_static: false  # notebooks don't need strict style

# Ignore patterns (don't index or trigger on data files)
ignore_patterns:
  - "*.csv"
  - "*.parquet"
  - "*.pkl"
  - "*.h5"
  - "*.joblib"
  - "data/"
  - "models/"
  - "notebooks/"
  - ".ipynb_checkpoints/"

# Routing examples specific to DS projects
routing_examples:
  - text: "train a machine learning model on dataset"
    category: planning
  - text: "feature engineering pipeline"
    category: planning
  - text: "model evaluation and metrics"
    category: code_review
  - text: "hyperparameter tuning configuration"
    category: architecture
```

### 3. templates/rag_pipeline/template.yaml

```yaml
name: rag_pipeline
description: "For RAG systems with vector stores, embeddings, and LLM pipelines"

agents:
  planning: deepseek-v3
  architecture: deepseek-v3

quality_gates:
  code_writing:
    min_score: 0.70
    block_security_high: true  # API keys and vector DB credentials

ignore_patterns:
  - "*.faiss"
  - "*.index"
  - "chroma_db/"
  - "vector_store/"
  - "embeddings/"
  - "*.bin"

routing_examples:
  - text: "chunk documents for vector store ingestion"
    category: planning
  - text: "embedding model configuration"
    category: architecture
  - text: "retrieval quality evaluation"
    category: code_review
  - text: "prompt template for RAG chain"
    category: code_writing
```

### 4. templates/web_api/template.yaml

```yaml
name: web_api
description: "For FastAPI/Flask REST APIs with routes, auth, and databases"

quality_gates:
  code_writing:
    min_score: 0.75
    block_security_high: true

ignore_patterns:
  - "migrations/"
  - "*.db"
  - "*.sqlite"
  - "static/"
  - "media/"

routing_examples:
  - text: "add authentication middleware"
    category: architecture
  - text: "database migration script"
    category: planning
  - text: "API endpoint rate limiting"
    category: code_writing
  - text: "request validation schema"
    category: code_writing
```

### 5. templates/cli_tool/template.yaml

```yaml
name: cli_tool
description: "For command-line tools with argument parsing and shell integration"

quality_gates:
  code_writing:
    min_score: 0.65
    require_static: true

ignore_patterns:
  - "dist/"
  - "build/"
  - "*.egg-info/"

routing_examples:
  - text: "add new CLI subcommand"
    category: planning
  - text: "shell completion support"
    category: code_writing
  - text: "argument validation logic"
    category: code_review
```

### 6. core/template_manager.py

class TemplateManager:
  TEMPLATES_DIR = Path("templates/")
  
  list_templates() -> List[Dict]:
    Reads all template.yaml files.
    Returns [{name, description, path}]
  
  apply_template(
    template_name: str,
    target_config: ProjectConfig
  ) -> ProjectConfig:
    Load template.yaml for template_name.
    Merge template overrides into target_config.
    Template values override config defaults.
    User values override template values.
    Return merged config.
  
  copy_template_files(
    template_name: str,
    target_dir: Path
  ) -> List[str]:
    Copy AGENTS.md and .gitignore to target_dir if not present.
    Never overwrite existing files.
    Return list of files copied.
  
  detect_project_type(project_path: Path) -> Optional[str]:
    Heuristic detection:
    If contains: requirements.txt + any of (sklearn, torch, pandas) 
      → "ds_project"
    If contains: any of (chromadb, faiss, langchain, llamaindex) 
      → "rag_pipeline"
    If contains: (fastapi, flask, django) in requirements 
      → "web_api"
    If contains: (click, typer, argparse) as main imports 
      → "cli_tool"
    Returns None if unknown.

### 7. New CLI command: projectos template

projectos template list
  Shows available templates with descriptions.

projectos template apply <name>
  Applies template to current project.
  Merges config, copies AGENTS.md if not present.
  Prints: "Template applied: [name]"

projectos template detect
  Runs detect_project_type() on current directory.
  Prints detected type or "Unknown project type"

### 8. Update install.py
After provider setup, add:
  "What type of project are you setting up ProjectOS for?"
  Show template list with numbers.
  Ask user to pick or press Enter to skip.
  If picked: apply_template() automatically.

### 9. tests/test_template_manager.py
All use tmp_path:
- test_list_templates_returns_all_four
- test_apply_template_merges_config
- test_apply_template_user_values_override_template
- test_copy_template_files_skips_existing
- test_detect_ds_project_from_requirements
- test_detect_rag_pipeline_from_requirements
- test_detect_unknown_returns_none

## Constraints
- templates/ directory is read-only at runtime
  (copying to user's project dir is write)
- Template application never deletes existing config values
- detect_project_type reads requirements.txt only (no AST parsing)
- Template AGENTS.md files are additive — appended to existing

## Verification
Full test suite. Write TASK_46_RESULT.md. Update tasks/README.md.
