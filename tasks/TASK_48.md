# TASK_48: External-Audience README + Demo Preparation

## Engineering Context

The current README is written for Aryan. It assumes the reader
knows what AGY is, knows what the task queue system is, knows
the project history.

A developer on GitHub finding this project cold has none of that
context. They need to understand in 30 seconds:
1. What does this do?
2. Why would I use it?
3. How do I start?

This task rewrites the external-facing documentation and prepares
everything needed for a public launch.

## Pre-conditions
Read current README.md fully.
Read docs/architecture/SYSTEM_OVERVIEW.md.
Read docs/PRODUCTION_READINESS.md.
Read CONTRIBUTING.md.

## Deliverables

### 1. Rewrite README.md for external audience

Structure:
ProjectOS — Personal Engineering OS
[One-line description]
[3 badges: CI, version, license]
What It Does
[2 paragraphs — no jargon, explains the value]
Demo
[ASCII animation or description of what happens when you run it]
Quick Start
[3 steps using install.py]
How It Works
[ASCII architecture diagram]
[One sentence per agent]
Agent Roster
[Table: Agent | What it does | When it runs]

Rules for the rewrite:
- No mention of "task queue", "TASK_XX files", "AGY", Claude
- No internal implementation details
- No mention of the build process (phases, tasks, etc.)
- Write as if this is a finished product someone else built
- Maximum 600 words in the main body
- Every section must add value — cut anything decorative

### 2. docs/DEMO_SCRIPT.md

A reproducible demo anyone can run:

```markdown
# ProjectOS Demo

## Setup (2 minutes)
1. Clone and install
2. Set GEMINI_API_KEY
3. Point at any Python project

## Demo Sequence (5 minutes)

### Step 1: Index the project
projectos index rebuild
[Expected output: N files indexed]

### Step 2: Trigger a code review  
projectos review src/main.py
[Expected output: review report with issues]

### Step 3: View decisions
projectos decisions --tail 5
[Expected output: 5 recent agent decisions]

### Step 4: Check quality metrics
projectos quality status
[Expected output: per-agent quality scores]

### Step 5: Run the daemon
projectos run --dashboard
[Expected output: live terminal dashboard]
```

### 3. docs/FAQ.md

Answer the 8 most likely questions from a new user:
1. Does it work without an API key?
2. How much does it cost to run?
3. Can it modify my files without asking?
4. What languages does it support?
5. How is this different from GitHub Copilot?
6. Can I use it with an existing project?
7. Does it work offline?
8. Is my code sent to the cloud?

### 4. .github/ISSUE_TEMPLATE/bug_report.md

Standard GitHub issue template for bug reports.

### 5. .github/ISSUE_TEMPLATE/feature_request.md

Standard GitHub issue template for feature requests.

### 6. .github/PULL_REQUEST_TEMPLATE.md

Standard PR template with checklist:
- Tests added
- AGENTS.md not modified without reason
- No hardcoded values
- Documentation updated

### 7. tests/test_documentation.py
- test_readme_under_800_lines
- test_readme_has_quick_start_section
- test_readme_has_agent_roster_section
- test_faq_has_eight_questions
- test_demo_script_exists
- test_issue_templates_exist
- test_pr_template_exists

## Constraints
- README must not mention internal build process
- FAQ must be honest about limitations
- Demo script must work with only Gemini free tier
- All GitHub templates use standard markdown

## Verification
Full test suite passes.
Write TASK_48_RESULT.md. Update tasks/README.md.
