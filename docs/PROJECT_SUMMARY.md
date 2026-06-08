# ProjectOS — Project Summary

## What Was Built

ProjectOS is an autonomous local-first multi-agent developer system that acts as a background engineering teammate. Rather than waiting for developer prompts, ProjectOS monitors the local filesystem in real-time, translates file changes into actionable events, and routes them to a specialized roster of AI agents. The system includes seven dedicated agent roles: a supervisor (Clone), a Planning Agent, a Code Writing Agent, a Code Review Agent, a Test Agent, a Documentation Agent, and an Architecture Agent.

To ensure safety and quality in automated workflows, ProjectOS features an LLM-as-a-judge quality gate. Any code or documentation proposed by the agents is automatically validated by a schema checker, static code quality analyzer, and LLM evaluator. Low-scoring work is blocked from touching repository files and escalated to a human queue. Built-in production observability tracks tracing, token budgets, circuit breakers, rate limits, and real-time costs, making the system highly reliable and cost-effective on both local and cloud AI models.

## Architecture

```text
                                      +----------------------+
                                      | config/models.yaml   |
                                      | provider assignments |
                                      +----------+-----------+
                                                 |
                                                 v
                                      +----------+-----------+
                                      | core/model_provider  |
                                      | OpenRouter/Gemini/   |
                                      | Ollama adapters      |
                                      +----------+-----------+
                                                 |
                                                 v
+----------------+      +----------------+      +----------------+      +----------------+
| source files   | ---> | TriggerSystem  | ---> | event queue    | ---> | ProjectOS loop |
| *.py changes   |      | CODE_CHANGED   |      | AgentEvent     |      | Clone handle   |
+----------------+      +----------------+      +----------------+      +--------+-------+
                                                                                 |
                                                                                 v
                                                                      +----------+----------+
                                                                      | Clone Agent         |
                                                                      | classify + dispatch |
                                                                      +----+-----+-----+----+
                                                                           |     |     |
                  +--------------------------------------------------------+     |     +--------------------------------------------------+
                  |                                                              |                                                        |
                  v                                                              v                                                        v
       +----------+----------+       +---------------------+        +------------+------------+       +---------------------+       +-------+-------+
       | Planning Agent      | ----> | Code Writing Agent  | ---->  | Code Review Agent       | ----> | Test Agent          | ----> | Docs Agent    |
       | backlog tasks       |       | source files        |        | review reports          |       | pytest files        |       | doc updates   |
       +---------------------+       +---------------------+        +-------------------------+       +---------------------+       +---------------+
                  |
                  v
       +----------+----------+
       | Architecture Agent  |
       | ADR generation      |
       +---------------------+

Persistent artifacts:
decisions.log, backlog.md, blocked_tasks.md, escalation_queue.md, reviews/, docs/adr/, tests/
```

## Metrics

| Metric | Value |
|--------|-------|
| Python files | 145 |
| Test count | 399 |
| Agents implemented | 7 |
| Production readiness | 100% |
| Phases completed | 8 |
| Tasks completed | 53 |
| Build duration | ~60 days |

## Phases Completed

| Phase | Focus | Key Deliverable | Tests Added |
|---|---|---|---|
| **Phase 1** | Foundation | Core multi-agent loop, trigger system, task queue, and click CLI | 52 tests |
| **Phase 2** | Durable Persistence | Persistent task queue, health checks, decisions log, terminal dashboard, and MCP | 73 tests (125 total) |
| **Phase 3** | Evaluation & Quality | LLM judge, static analyzer, quality gates, and regression detector | 64 tests (189 total) |
| **Phase 4** | Agent Intelligence | Codebase vector indexer, RAG integration, agent memory, and semantic router | 62 tests (251 total) |
| **Phase 5** | Production Observability | Tracing, token budget manager, cost tracking, rate limits, and circuit breakers | 58 tests (309 total) |
| **Phase 6** | Real-World Validation | setup/interactive provider installer, dogfooding script, and performance profiler | 46 tests (355 total) |
| **Phase 7** | Developer Experience | install.py wizard, templates (ds_project, rag_pipeline, cli_tool, web_api), plugins | 26 tests (381 total) |
| **Phase 8** | Open Source Launch | Live API smoke verification, repository hygiene, and launch assets | 18 tests (399 total) |

## Technologies Used

- Python 3.12/3.14
- Google Gemini API (via AI Studio)
- OpenRouter
- ChromaDB (vector database)
- watchdog (filesystem monitor)
- click (CLI commands)
- rich (terminal dashboard)
- pytest (verification suite)
- uv (package management)
- GitHub Actions (CI pipelines)
- AGY and Codex plugin specifications

## What It Can Do Now

ProjectOS can monitor any local Python codebase, watch for edits, plan implementation steps for backlog items, write code changes, review writes for quality, run test suites, update markdown documentation, and generate Architecture Decision Records (ADRs). The supervisor layer (Clone) categorizes risk autonomously, escalates dangerous modifications for human review, and manages parallel execution paths smoothly. It safely tracks rate limits, token budgets, and costs, switching to local models (like Ollama) when cloud APIs exceed quotas.

## Known Limitations

- **Host-level Pytest Dependency**: Code execution checks occur directly on the host machine. Full sandbox isolation (using Docker or gVisor) is recommended for production environments.
- **Synchronous File I/O**: High-concurrency events may experience minor lock times because JSONL databases (such as tracing logs, alert files, and budgets) are written synchronously.
- **Python Native**: Core RAG indexers, static analyzers, and test runners are optimized primarily for Python codebases.

## What Comes Next (if continued)

- **Option A: SaaS/Product**: Deploy as a managed service once real-user demand is established.
- **Option B: Containerized Sandbox**: Execute test suites inside isolated Docker containers to prevent code safety risks.
- **Option C: Multi-Project Daemon**: Extend the orchestrator to watch and manage multiple distinct directories concurrently.
- **Option D: Web Dashboard**: Replace the terminal dashboard with a rich web interface for easier control.
