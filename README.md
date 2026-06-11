# ProjectOS

Autonomous multi-agent system that manages your software projects while you focus on other work.

[![CI Status](https://github.com/00-Aryan/Personal_Engineering_OS/actions/workflows/ci.yml/badge.svg)](https://github.com/00-Aryan/Personal_Engineering_OS/actions)
[![Version](https://img.shields.io/github/v/release/00-Aryan/Personal_Engineering_OS?label=version)](https://github.com/00-Aryan/Personal_Engineering_OS/releases)
[![License](https://img.shields.io/github/license/00-Aryan/Personal_Engineering_OS)](https://github.com/00-Aryan/Personal_Engineering_OS/blob/main/LICENSE)

## What It Does

ProjectOS handles the lifecycle of software tasks. You create a backlog of features by editing a `project_description.md` file in your repository. The coordinator analyzes your requests, plans the execution steps, and dispatches tasks to specialized agents. The system works autonomously in the background, making code changes, writing tests, and updating project documentation.

You stay in control without leaving your workflow. Important updates, code modifications, or planned operations are buffered and sent to your Telegram chat. You can review proposals, approve next steps, or request revisions on the fly. Because the system runs entirely on your local machine, your source files and keys remain private.

## How It Works

```text
  [project_description.md]
              │
              ▼
    [Morning Telegram Brief] ──(You Approve/Instruct)──┐
              ▲                                        │
              │                                        ▼
    [Evening Telegram Digest] ◄──(Agents Execute)──────┘
```

The system cycles through a daily workflow:
1. **Morning Telegram Brief**: Summarizes pending plans, blocked items, and requests your approval.
2. **User Instructions**: You approve tasks or provide text feedback directly inside the chat.
3. **Agent Loop**: The orchestrator wakes up, coordinates agents to modify files, and runs tests.
4. **Evening Telegram Digest**: Sends a summary of completed tasks and the updated status of your project.

## Quick Start

1. **Clone the repository:**
   ```bash
   git clone https://github.com/00-Aryan/Personal_Engineering_OS
   cd Personal_Engineering_OS
   ```

2. **Install dependencies:**
   ```bash
   python install.py
   ```

3. **Configure API credentials:**
   Add your model provider API key to the generated `.env` file:
   ```bash
   echo "GEMINI_API_KEY=your_api_key_here" >> .env
   ```

4. **Start the daemon:**
   ```bash
   uv run projectos run --dashboard
   ```

## Daily Workflow

Your interaction with the system happens primarily via Telegram. When the daemon is active, it messages you every morning with status updates and awaits your confirmation before modifying code.

Here is an example morning brief:
```text
🌅 ProjectOS Morning Brief

Active Project: my-web-api
📋 Pending your approval: 2
🔒 Blocked tasks: 0

Use /status for full details.
```

### Telegram Commands
You can control the background daemon by sending these commands in the chat:
- `/status` — View current system status and model assignments.
- `/approve <id>` — Approve a pending task plan for execution.
- `/reject <id>` — Reject a proposed task plan.
- `/brief` — Manually trigger the morning project update.
- `/digest` — Request the evening summary of completed work.
- `/pause` — Suspend background file monitoring and execution.
- `/resume` — Resume background file monitoring.

## Agents

| Agent | Role | What it produces |
| :--- | :--- | :--- |
| `clone` | Workspace coordinator | Event routing and task scheduling |
| `planning` | Backlog engineer | Actionable task lists from prompts |
| `code_writing` | Software developer | Source file changes and features |
| `code_review` | Quality reviewer | Code reviews and security audits |
| `architecture` | Systems designer | Architecture records (ADRs) |
| `test` | Verification engineer | Unit tests and execution verification |
| `docs` | Technical writer | Markdown guides and documentation |

## Project Templates

| Template | Best for | Key differences |
| :--- | :--- | :--- |
| `ds_project` | Data Science & ML | Pre-configured for data scripts, notebooks, and models |
| `rag_pipeline` | Retrieval AI | Includes vector indexers and LLM context chains |
| `web_api` | Backend APIs | Ready for FastAPI and backend route validation |
| `cli_tool` | CLI Applications | Formatted for click subcommands and terminal utilities |

## Configuration

Set environment variables in `.env`:
- `GEMINI_API_KEY` or `OPENROUTER_API_KEY` for cloud models.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for chat integration.

Adjust orchestration options in `config/projectos.yaml`:
```yaml
rate_limit:
  requests_per_minute: 60
token_budget:
  daily_max_usd: 5.0
```

For advanced settings, refer to the [docs/CONTRIBUTING.md](file:///home/aryan/June-2026/Personal_Engineering%20_OS/docs/CONTRIBUTING.md) guide.

## CLI Reference

| Command | Description |
| :--- | :--- |
| `uv run projectos status` | Show current provider health and agent assignments |
| `uv run projectos run` | Start the local orchestrator and monitor files |
| `uv run projectos model <agent> <model>` | Update the model used by a specific agent |
| `uv run projectos approve` | Interactively approve pending backlog tasks |
| `uv run projectos backlog` | Display the backlog tasks with priority colors |

## Honest Limitations

ProjectOS has several design boundaries:
- **No secure sandbox**: Generated code and tests run directly on the host machine.
- **Mocked test validation**: The automated test suite uses mocks and does not evaluate real LLM output quality.
- **No data rotation**: Traces and JSONL log files grow indefinitely.
- **Single-machine design**: Project state is saved locally and cannot be synchronized across multiple hosts.
- **No web interface**: Interactivity is limited to the terminal and Telegram commands.
- **Provider limits**: Using free tiers of cloud APIs may result in rate-limit throttling.

For details, view [KNOWN_LIMITATIONS.md](file:///home/aryan/June-2026/Personal_Engineering%20_OS/KNOWN_LIMITATIONS.md).

## What's Coming Next

The following additions are planned (not built yet):
- 🔜 **Isolated Docker runner** for executing tests inside containers.
- 🔜 **Multi-project web interface** for status monitoring.
- 🔜 **GitHub App integration** to review pull requests.
- **VS Code extension** to view agent feedback inside the editor.

For details, view [FUTURE_SCOPE.md](file:///home/aryan/June-2026/Personal_Engineering%20_OS/FUTURE_SCOPE.md).

## Contributing

We welcome contributions to improve the system. Please read our [CONTRIBUTING.md](file:///home/aryan/June-2026/Personal_Engineering%20_OS/docs/CONTRIBUTING.md) file to understand the development standards and PR submission process.

## License

[MIT License](file:///home/aryan/June-2026/Personal_Engineering%20_OS/LICENSE)
