# ProjectOS

ProjectOS is an autonomous agent coordinator for software repositories. It automatically monitors codebases, performs code reviews, updates documentation, runs tests, and coordinates planning, all within your local environment.

## Quick Start

1. **Install dependencies**:
   ```bash
   uv sync
   ```
2. **Configure your environment variables** in a `.env` file (copied from `.env.example`):
   ```env
   GEMINI_API_KEY="your_api_key_here"
   OPENROUTER_API_KEY="your_api_key_here"
   ```
3. **Verify setup**:
   ```bash
   uv run projectos config validate
   ```
4. **Run the daemon**:
   ```bash
   uv run projectos run
   ```

## Agent Roster

ProjectOS coordinates the following engineering agents to maintain repository standards:

| Agent | Responsibility | Primary Trigger |
| --- | --- | --- |
| `clone` | Supervisor, coordinator, and event router | Incoming change events |
| `planning` | Translates feature requirements into structured backlog tasks | Feature requests |
| `code_writing` | Implements changes based on backlog tasks | Backlog updates |
| `code_review` | Reviews code changes and writes reports under `reviews/` | File modifications |
| `architecture` | Answers system queries and creates ADRs | Architecture questions |
| `test` | Generates and runs pytest verification suites | File modifications |
| `docs` | Automatically updates documentation and inline comments | Successful code reviews |

## CLI Commands

Manage the system using the `projectos` CLI:

| Command | Purpose |
| --- | --- |
| `projectos status` | Displays configured models and latest activities. |
| `projectos run` | Starts the local background monitoring loop. |
| `projectos review <file>` | Triggers a manual review event for a specific file. |
| `projectos quality status` | Reports per-agent evaluation scores and regressions. |
| `projectos quality baseline` | Displays saved model-versioned quality baselines. |
| `projectos gate status` | Shows quality gate pass/block history. |
| `projectos gate override <id>` | Bypasses a blocked gate decision with a reason. |
| `projectos benchmark run` | Runs quality benchmarks and records results. |
| `projectos audit` | Generates a quality audit report. |

## Use as MCP Server

ProjectOS can run as a Model Context Protocol (MCP) server for compatible client applications:

```bash
codex mcp add projectos -- uv run --no-sync python -m mcp_server.server
```

## Swap A Model

Swap agent model assignments using the CLI:

```bash
uv run projectos model planning deepseek-v3
```

This modifies `config/projectos.yaml` to dynamically redirect agent requests to the new provider or model.

## Known Limitations

- **Local Scope**: Runs entirely in your local terminal process.
- **Review Dependency**: Automatic writes require human approval and local key validation.
- **Python Native**: Core tools are optimized for Python structures.
