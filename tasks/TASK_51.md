# TASK_51: GitHub Repository Polish

## Engineering Context

When a developer lands on github.com/00-Aryan/Personal_Engineering_OS
they see the repository page before they read the README.
The repository page includes: description, topics, social preview,
and the file structure visible in the file browser.

This task polishes everything visible on the GitHub repository page
and ensures the repository follows GitHub community standards that
increase discoverability and trust.

## Pre-conditions
Read README.md, CONTRIBUTING.md, docs/FAQ.md.
Read pyproject.toml for current version and description.

## Deliverables

### 1. Update repository metadata file

Create .github/repository.yaml (documents intended GitHub settings
— must be applied manually on GitHub.com):

```yaml
# Apply these settings at:
# github.com/00-Aryan/Personal_Engineering_OS/settings

name: Personal_Engineering_OS
description: "🤖 Autonomous multi-agent system that engineers your software projects while you study. 7 specialized AI agents, quality gates, and real-time observability."

topics:
  - ai-agents
  - llm
  - python
  - developer-tools
  - autonomous-agents
  - gemini
  - openrouter
  - multi-agent
  - code-review
  - software-engineering

website: ""  # Add later if landing page created

# Features to enable:
issues: true
projects: false
wiki: false
discussions: false  # Enable after first users
```

### 2. Create docs/social_preview_text.md

Text for social preview image (manually created on Canva):
ProjectOS
Personal Engineering OS
7 AI agents that engineer your
software projects while you study.

Code review  • Test generation
Planning     • Documentation
Architecture • Observability

github.com/00-Aryan/Personal_Engineering_OS

### 3. Verify and update SECURITY.md

```markdown
# Security Policy

## Supported Versions
| Version | Supported |
|---------|-----------|
| 0.5.x   | ✅ Yes    |
| < 0.5   | ❌ No     |

## Reporting a Vulnerability

Please do NOT open a public GitHub issue for security vulnerabilities.

Email: 22f2000697@ds.study.iitm.ac.in
Subject: [SECURITY] ProjectOS vulnerability report

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You will receive a response within 72 hours.
```

### 4. Verify GitHub Actions CI badge works

Read README.md badge line.
Verify format:
  ![CI](https://github.com/00-Aryan/Personal_Engineering_OS/
  actions/workflows/ci.yml/badge.svg)

If badge URL is wrong: fix it.

### 5. Create docs/CHANGELOG.md

```markdown
# Changelog

All notable changes to ProjectOS are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com).

## [0.5.0] — 2026-06-XX
### Added
- One-command install via install.py
- Project templates: ds_project, rag_pipeline, web_api, cli_tool
- AGY and Codex plugin packaging
- External-audience README and documentation
- GitHub issue and PR templates

## [0.4.0] — 2026-06-XX
### Added
- Production observability: tracing, token budgets, cost tracking
- Circuit breakers and rate limiters for all providers
- Alerting and anomaly detection
- 100% production readiness score

## [0.3.0] — 2026-06-XX
### Added
- Evaluation & Quality: LLM-as-judge, schema validation
- Regression detection with baselines
- Quality gate enforcement
- Agent Intelligence: RAG, memory, semantic routing

## [0.2.0] — 2026-06-XX
### Added
- Open source preparation: LICENSE, CONTRIBUTING, CI
- GitHub Actions pipeline

## [0.1.0] — 2026-06-XX
### Added
- Initial release: 7 agents, task queue, CLI
```

Fill actual dates from git log:
  git log --format="%h %ad %s" --date=short | grep "feat:"

### 6. tests/test_repository_hygiene.py
- test_security_md_exists
- test_changelog_md_exists
- test_repository_yaml_exists
- test_github_actions_ci_yml_exists
- test_license_file_exists
- test_readme_has_ci_badge
- test_all_issue_templates_exist

## Constraints
- .github/repository.yaml is documentation only (applied manually)
- CHANGELOG.md dates must come from git log (not invented)
- SECURITY.md email must match pyproject.toml author email

## Verification
Full test suite passes.
Write TASK_51_RESULT.md. Update tasks/README.md.
