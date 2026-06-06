# ProjectOS

[![CI](https://github.com/00-Aryan/Personal_Engineering_OS/actions/workflows/ci.yml/badge.svg)](https://github.com/00-Aryan/Personal_Engineering_OS/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## What ProjectOS Is

ProjectOS is a local Python orchestration prototype for coordinating multiple engineering agents around a repository. It watches for code changes, routes events through a Clone supervisor, sends work to specialized agents, records decisions in `decisions.log`, and writes artifacts such as review reports, generated tests, backlog entries, ADRs, blocked-task records, and escalation records.

The system is honest infrastructure, not a production autonomous engineer. It has mocked-provider test coverage and deterministic orchestration paths, but real model quality, safety review, and operational resilience still depend on configured providers, local environment setup, and human review of escalations.

## Philosophy

ProjectOS was built because a single developer cannot always hold planning, implementation, review, architecture, testing, and documentation contexts at the same time. The goal is to keep routine engineering work moving while Aryan focuses on academic work, project direction, and higher-leverage decisions.

The system solves for continuity. It gives each engineering responsibility a named agent, routes every event through a Clone supervisor, records why decisions were made, and keeps blocked work from stopping unrelated progress. Its job is not to replace engineering judgment; its job is to preserve context, enforce standards, and make handoffs explicit.

ProjectOS will not become an unbounded autonomous product in version 1. It is scoped to Aryan's personal projects, single-machine deployment, Python-first workflows, configured model providers, and human escalation for important architecture, dependency, and breaking-change decisions. Multi-user support, enterprise features, self-modifying agents, and a web dashboard remain out of scope for the current version.

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

## Phase 3: Evaluation & Quality

ProjectOS now has an evaluation subsystem that scores agent outputs before downstream work continues. Agent results can be schema-validated, judged by a configured LLM evaluator, checked with deterministic static analysis, compared against rolling regression baselines, and enforced through an append-only quality gate with human override support.

```text
Agent Output -> Schema Validation -> LLM Judge -> Static Analysis
                                                   |
                                                   v
                         File Written <- Quality Gate (PASS/BLOCK)
```

View current quality metrics:

```bash
uv run projectos quality status
```

Run the mocked benchmark suite:

```bash
uv run projectos benchmark run
```

Generate a quality audit report:

```bash
uv run projectos audit --days 7
```

## Agent Intelligence (Phase 4)

ProjectOS agents are context-aware through three mechanisms:

**Codebase RAG**: Before acting, agents retrieve relevant code from an indexed vector store of your repository.

**Agent Memory**: Agents accumulate episodic, semantic, and procedural memories that improve output quality over time.

**Semantic Routing**: Clone classifies events using embedding similarity rather than keyword matching.

**Agent Collaboration**: Agents consult each other for complex tasks, bounded by depth limits to prevent cascades.

```text
Incoming Event
     |
     v
SemanticRouter (classify + route)
     |
     v
ContextRetriever (fetch relevant code)
+ MemoryManager (recall past experience)
     |
     v
Agent (informed model call)
     |
     v
CollaborationBroker (consult if needed)
     |
     v
Quality Gate (evaluate output)
     |
     v
MemoryManager.learn_from_evaluation() (store learnings)
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
| `projectos quality status` | Shows per-agent evaluation scores and regression state. |
| `projectos quality baseline` | Lists stored model-versioned quality baselines. |
| `projectos gate status` | Shows quality gate block rates and recent decisions. |
| `projectos gate override EVENT_ID --reason TEXT` | Appends a human BYPASS decision for a blocked gate result. |
| `projectos benchmark run` | Runs the mocked quality benchmark suite and writes benchmark history. |
| `projectos benchmark history` | Prints the last ten benchmark runs. |
| `projectos audit --days N` | Prints a human-readable quality audit report. |
| `projectos audit --save report.md` | Writes a quality audit report to a markdown file. |

## Use as MCP Server

ProjectOS can run as a stdio MCP server for MCP-compatible clients such as Codex and Claude Code.

```bash
codex mcp add projectos -- uv run --no-sync python -m mcp_server.server
```

The server exposes tools for planning, code review, status, decision queries, and escalation approval over JSON-RPC 2.0.

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

## Gate Policy Reference

Quality gate defaults live in `core/evaluation/quality_gate.py` as `DEFAULT_POLICIES`.

| Policy field | Meaning |
| --- | --- |
| `agent_name` | Agent or fallback policy name. |
| `min_combined_score` | Minimum weighted score required to pass when quality signals are present. |
| `require_llm_evaluation` | Adds a warning when no LLM judge score is attached. |
| `require_static_analysis` | Adds a warning when no static report is available. |
| `block_on_security_high` | Blocks when static analysis reports high-severity security issues. |
| `block_on_regression` | Escalates when the current score drops below the model-versioned baseline tolerance. |
| `regression_tolerance` | Allowed score drop before regression handling applies. |
| `escalate_on_block` | Indicates blocked work should be surfaced for human review. |

## Known Limitations

- The daemon is local-process only; there is no durable external queue or multi-process coordination.
- Model outputs are parsed defensively, but there is no semantic guarantee that generated code, tests, docs, or ADRs are correct.
- The manual `review` CLI command submits to a lightweight target unless wired with the full ProjectOS runtime.
- `decisions.log` is append-only at the content level through temp-file replacement, not an OS-level append-only file.
- Provider calls require valid local environment variables, except mocked tests and local Ollama-style use cases.

## Roadmap

Future `TASK_21+` work should focus on the next open-source readiness and runtime-hardening layer:

- Package installation and CLI verification on a fresh machine.
- Contributor-facing examples for adding agents and providers.
- Live-provider smoke checks that remain optional and environment-gated.
- More durable daemon lifecycle controls for start, stop, and restart flows.
- Better multi-project observability across project registries and queues.
- Expanded safety review around generated code writes and auto-commits.

## Contributing

Contribution rules are intentionally minimal for now: preserve the architecture rules in `AGENTS.md`, add tests with any behavioral change, keep all model access behind `core/model_provider.py`, and do not introduce an agent framework.
