# TASK_62: README Overhaul + KNOWN_LIMITATIONS.md + FUTURE_SCOPE.md

## Engineering Context

The current README describes the system to someone who already
knows how it was built. It needs to describe the system to a
developer who just found it on GitHub and has 60 seconds to decide
if it's worth their time.

Three documents needed:
1. README.md — what it is, how to use it, honest limitations
2. KNOWN_LIMITATIONS.md — every real limitation, documented clearly
3. FUTURE_SCOPE.md — what's planned but not built, honestly labeled

## Pre-conditions
Read ENTIRE current README.md.
Read docs/PRODUCTION_READINESS.md.
Read docs/PROJECT_SUMMARY.md.
Read docs/FAQ.md.
Read all TASK result files for accurate metrics.
Read AGENTS.md.

## Deliverables

### 1. Rewrite README.md

Structure (in this exact order):

ProjectOS

Autonomous multi-agent system that manages your software projects
while you focus on other work.

[CI badge] [version badge] [license badge]

**What It Does**
[2 paragraphs — plain language, no jargon]
[Explains: you create project_description.md, ProjectOS plans and executes in phases, you approve via Telegram, it works autonomously]

**How It Works**
[ASCII diagram showing the daily workflow]
[Morning Telegram brief → you approve/instruct → agents work → evening digest]

**Quick Start**
[4 steps: clone, install, add API key, run]

**Daily Workflow**
[What your interaction looks like day-to-day]
[Morning brief example, Telegram commands reference]

**Agents**
[Table: Agent | Role | What it produces]

**Project Templates**
[Table: Template | Best for | Key differences]

**Configuration**
[What to set in .env and config/projectos.yaml]
[Only the essential settings — link to full docs for rest]

**CLI Reference**
[Table: Command | Description]
[Telegram Commands section]

**Honest Limitations**
[5-7 bullet points — specific, not vague]
[Link to KNOWN_LIMITATIONS.md for full list]

**What's Coming Next**
[3-4 items from FUTURE_SCOPE.md]
[Clearly labeled as "not built yet"]

**Contributing**
[2 sentences + link to CONTRIBUTING.md]

**License**
[MIT]

Rules:
- Maximum 700 words in body text
- No mention of task files, phases, internal build process
- No mention of AGY, Codex CLI, or how it was built
- Every number cited must be verifiable (from test count, etc.)
- KNOWN LIMITATIONS section must not be hidden or minimized

### 2. KNOWN_LIMITATIONS.md

```markdown
# Known Limitations

These are real limitations of the current version.
They are documented here so users know what to expect.

## Security
- **No true sandbox**: Generated code and tests run on your host machine. 
  AST scanning provides basic protection but is not foolproof.
  Do not run ProjectOS on projects containing sensitive credentials
  without reviewing generated code first.

## Model Quality
- **All tests use mocked providers**: The test suite validates structure
  and wiring, not output quality. Real model output quality varies.
- **Quality gates are heuristic**: The LLM-as-judge evaluator uses
  another model to grade output. This can have errors.

## Infrastructure  
- **JSONL files grow indefinitely**: Log files are append-only and
  not rotated. Long-running deployments should periodically archive
  .projectos_state/ files.
- **Single-machine only**: All state is local. No sync across machines.
- **No web UI**: Terminal and Telegram only.

## Model Providers
- **Gemini free tier limits**: 1500 requests/minute, 1M tokens/day.
  Heavy usage will hit limits.
- **Ollama requires local hardware**: CPU-only inference is slow.
  Expect 30-120 seconds per completion on a laptop without GPU.

## Platform
- **Linux and macOS only**: Windows support is untested.
- **Python 3.10+ required**: Older Python versions not supported.

## Current Phase
- **Phase 9 features experimental**: Project intake, phase management,
  and Telegram integration are new in v0.6.0 and may have rough edges.
  Report issues at: [GitHub Issues link]
```

### 3. FUTURE_SCOPE.md

```markdown
# Future Scope

These features are planned but NOT built yet.
Items marked 🔜 are in active development.

## Near Term
🔜 Docker sandbox for safe test execution
🔜 Multi-project web dashboard
🔜 GitHub App integration (auto-review on PRs)
🔜 Voice notifications via Telegram voice messages

## Medium Term  
- VS Code extension
- Multi-user support (team projects)
- Custom agent definition (define agents in YAML, no Python)
- Webhook triggers (Slack, Linear, Jira integration)

## Long Term
- Self-improving agents (learn from your feedback over time)
- Cloud deployment option
- Mobile app for project management
- Enterprise features (audit logs, SSO, role-based access)

## Not Planning to Build
- General-purpose AI assistant (not the goal)
- Code generation IDE (use Cursor or VS Code for that)
- Replacing code review from humans (augmenting, not replacing)
```

### 4. tests/test_documentation.py updates
  - test_readme_under_700_words_body
  - test_known_limitations_file_exists
  - test_future_scope_file_exists
  - test_readme_has_honest_limitations_section
  - test_readme_does_not_mention_internal_build_process
  - test_readme_has_telegram_commands_section

## Constraints
- README body text must be under 700 words (headings excluded)
- KNOWN_LIMITATIONS.md must list at least 8 specific limitations
- FUTURE_SCOPE.md must clearly label items as NOT YET BUILT
- README must not use words: "revolutionary", "game-changing",
  "seamlessly", "powerful", "robust", "cutting-edge"

## Verification
Full test suite. Write TASK_62_RESULT.md. Update tasks/README.md.
Mark Phase 9 as COMPLETE in tasks/PHASES.md.
