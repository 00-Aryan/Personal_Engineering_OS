# TASK_20: Open Source Preparation

## Purpose
Make this repository presentable, installable, and contributable
by other developers. This is the bridge to option C from vision.

## Pre-conditions
Read README.md, all docs/, pyproject.toml, requirements.txt fully.

## Deliverables

### 1. Update pyproject.toml
  Add proper metadata:
  name = "projectos"
  version = "0.2.0"
  description = "Personal Engineering OS — autonomous multi-agent 
                 system for software project management"
  authors = [{name = "Aryan Kumar", 
              email = "22f2000697@ds.study.iitm.ac.in"}]
  license = {text = "MIT"}
  readme = "README.md"
  
  Add scripts entry point:
  [project.scripts]
  projectos = "cli.main:cli"

### 2. LICENSE
  Create MIT LICENSE file with Aryan Kumar as copyright holder.
  Year: 2026.

### 3. CONTRIBUTING.md
  Sections:
  - How to add a new agent (reference BaseAgent, 4 steps)
  - How to add a new model provider (reference ModelProvider)
  - Running tests (uv run --no-sync pytest)
  - Code standards (docstrings, type hints, no hardcoded values)
  - PR checklist (tests pass, AGENTS.md not modified, result file)

### 4. .github/workflows/ci.yml
  GitHub Actions workflow:
  name: CI
  Triggers: push to main, pull_request
  Jobs:
    test:
      runs-on: ubuntu-latest
      steps:
        - checkout
        - setup Python 3.12
        - install uv
        - uv pip install -e ".[dev]"
        - run pytest with coverage
        - upload coverage report

### 5. Update README.md
  Add badges at top:
  - CI status badge (GitHub Actions)
  - Python version badge (3.12+)
  - License badge (MIT)
  
  Add section: "Roadmap"
  List TASK_21+ as future items.
  
  Add section: "Philosophy"
  3 paragraphs on why this was built, what problem it solves,
  what it will never do (scope boundaries from docs/).

### 6. docs/ARCHITECTURE_DECISIONS.md
  One-page summary of every ADR written during month 1.
  Table: ADR number, title, decision, status (accepted/superseded).

### 7. smoke_test.py
  Add --ci flag: runs all assertions, exits 0 on pass, 1 on fail.
  Already works this way — just add argparse with --ci flag 
  that prints "CI SMOKE: PASSED" for clean CI log parsing.

### 8. tests/test_open_source_hygiene.py
  - test_license_file_exists
  - test_contributing_md_exists
  - test_pyproject_has_version
  - test_pyproject_has_description
  - test_readme_has_quickstart_section
  - test_all_agents_importable
  - test_smoke_test_exits_zero (subprocess.run smoke_test.py --ci)

## Constraints
- Do not change any agent logic
- Do not add new dependencies beyond what already exists
- CI workflow must use free GitHub Actions minutes only

## Verification
Full test suite including hygiene tests.
Write TASK_20_RESULT.md. Update tasks/README.md.
Final line must read: ProjectOS v0.2.0 — ready for open source.
