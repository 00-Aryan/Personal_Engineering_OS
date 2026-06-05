# ProjectOS

## What ProjectOS Is

ProjectOS is a local Python orchestration prototype for coordinating multiple engineering agents around a repository. It watches for code changes, routes events through a Clone supervisor, sends work to specialized agents, records decisions in `decisions.log`, and writes artifacts such as review reports, generated tests, backlog entries, ADRs, blocked-task records, and escalation records.

The system is honest infrastructure, not a production autonomous engineer. It has mocked-provider test coverage and deterministic orchestration paths, but real model quality, safety review, and operational resilience still depend on configured providers, local environment setup, and human review of escalations.

## Architecture

```text
                         +----------------------+
                         | config/models.yaml   |
                         | provider + model map |
                         +----------+-----------+
                                    |
                                    v
+-------------+       +-------------+-------------+       +----------------+
| file change | ----> | TriggerSystem             | ----> | event queue    |
+-------------+       | emits CODE_CHANGED        |       +-------+--------+
                      +---------------------------+               |
                                                                  v
                                                        +---------+---------+
                                                        | Clone Agent       |
                                                        | decision engine   |
                                                        +----+----+----+----+
                                                             |    |    |
                 +-------------------------------------------+    |    +-----------------------------------+
                 |                                                |                                        |
                 v                                                v                                        v
       +---------+---------+                           +----------+----------+                    +---------+---------+
       | Planning Agent   |                           | Code Review Agent   |                    | Test Agent       |
       +---------+---------+                           +----------+----------+                    +---------+---------+
                 |                                                |                                        |
                 v                                                v                                        v
       +---------+---------+                           +----------+----------+                    +---------+---------+
       | Code Writing     |                           | Architecture Agent  |                    | Docs Agent       |
       | Agent            |                           +---------------------+                    +------------------+
       +------------------+
```

## Agent Roster

| Name | Role | Trigger | Model |
| --- | --- | --- | --- |
| `clone` | Supervisor, decision engine, dispatcher, escalation and blocked-task recorder | All submitted events through `ProjectOS.submit_event()` or trigger queue | `gemini-flash` via `gemini` |
| `planning` | Converts feature descriptions into structured backlog tasks | `NEW_FEATURE`, targeted `MANUAL_TRIGGER` | `deepseek-v3` via `openrouter` |
| `code_writing` | Writes Python files from structured backlog task payloads | `BACKLOG_CHANGED` routed to `code_writing_agent` | `openrouter-free` via `openrouter` |
| `code_review` | Reviews changed or written Python files and writes reports in `reviews/` | `CODE_CHANGED`, `CODE_WRITTEN` | `openrouter-free` via `openrouter` |
| `architecture` | Answers architecture questions and writes ADRs | `ARCHITECTURE_QUESTION`, architecture backlog work | `deepseek-v3` via `openrouter` |
| `test` | Generates pytest files and runs pytest for changed code | `CODE_CHANGED`, `CODE_WRITTEN` | `openrouter-free` via `openrouter` |
| `docs` | Updates source documentation and optionally README content | `CODE_WRITTEN`, `TESTS_DONE`, `DOCS_UPDATED` | `gemini-flash` via `gemini` |

## Quick Start

1. Install dependencies:

```bash
uv sync
```

2. Configure model provider environment variables for the providers you use:

```bash
export OPENROUTER_API_KEY="..."
export GEMINI_API_KEY="..."
```

3. Check configured agents:

```bash
uv run projectos status
```

4. Run the daemon:

```bash
uv run projectos run
```

5. Manually submit a review:

```bash
uv run projectos review core/base_agent.py
```

For test-only verification without live model calls, run:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest
```

## CLI Commands

| Command | Purpose |
| --- | --- |
| `projectos status` | Prints configured agent models, pending task count, and latest decision-log activity. |
| `projectos model AGENT_NAME MODEL_NAME` | Updates one agent model in `config/models.yaml`. |
| `projectos approve` | Iterates pending rows in `escalation_queue.md` and marks them approved or rejected. |
| `projectos backlog` | Prints `backlog.md` with priority coloring. |
| `projectos review FILE_PATH` | Submits a manual `CODE_CHANGED` event for one file. |
| `projectos run` | Starts the trigger system and background ProjectOS event loop until interrupted. |

## Swap A Model With `/model`

The implemented CLI command is `projectos model AGENT_NAME MODEL_NAME`. If using a slash-command wrapper, `/model planning deepseek-v3` should map to:

```bash
uv run projectos model planning deepseek-v3
```

This edits only `config/models.yaml`; agents read their model assignment through `core/model_provider.py` when providers are initialized.

## Add A New Agent

1. Create `agents/new_agent.py` with a class that inherits from `core.base_agent.BaseAgent` and implements `handle(self, event: AgentEvent) -> AgentResult`.

2. Add the agent to `config/models.yaml` under `agents:` with a `provider` and `model`, and ensure any model calls go through `core/model_provider.py`.

3. Register the agent in `core/projectos.py`, then add Clone dispatch rules in `core/clone_agent.py` for the event type or backlog category that should target it.

## `config/models.yaml` Reference

`providers` defines provider connection settings:

| Key | Meaning |
| --- | --- |
| `api_key_env` | Environment variable read for provider API credentials. |
| `completion_url` | Fixed completion endpoint for OpenRouter or Ollama-style providers. |
| `stream_url` | Fixed streaming endpoint. |
| `completion_url_template` | Template endpoint for providers that require model and key interpolation. |
| `stream_url_template` | Streaming template endpoint. |
| `default_model` | Provider-level fallback model when no agent-specific model is requested. |

`agents` maps each ProjectOS agent to a provider and model:

```yaml
agents:
  clone:
    provider: gemini
    model: gemini-flash
```

No agent should hardcode model names. Change models through `config/models.yaml` or `projectos model`.

## Known Limitations

- The daemon is local-process only; there is no durable external queue or multi-process coordination.
- Model outputs are parsed defensively, but there is no semantic guarantee that generated code, tests, docs, or ADRs are correct.
- The manual `review` CLI command submits to a lightweight target unless wired with the full ProjectOS runtime.
- `decisions.log` is append-only at the content level through temp-file replacement, not an OS-level append-only file.
- Provider calls require valid local environment variables, except mocked tests and local Ollama-style use cases.

## Contributing

Contribution rules are intentionally minimal for now: preserve the architecture rules in `AGENTS.md`, add tests with any behavioral change, keep all model access behind `core/model_provider.py`, and do not introduce an agent framework.
