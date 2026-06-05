# Architecture Decisions

This page summarizes the month-one architecture decisions that shaped
ProjectOS. Generated ADR files live under `docs/adr/` when the Architecture
Agent writes them; month one used task result files and requirements
resolution notes as the decision record.

| ADR number | Title | Decision | Status |
| --- | --- | --- | --- |
| ADR-001 | Agent roster | ProjectOS uses Clone plus Planning, Code Writing, Code Review, Architecture, Test, and Documentation agents. | accepted |
| ADR-002 | Base agent contract | Every agent inherits from `core/base_agent.py` and implements `handle()` over shared event/result types. | accepted |
| ADR-003 | Model provider boundary | All model calls go through `core/model_provider.py`; agents never hardcode model names or provider API formats. | accepted |
| ADR-004 | Clone decision categories | Clone classifies work as `AUTONOMOUS`, `ESCALATE`, or `DEFER_PARALLEL` using deterministic event and payload checks. | accepted |
| ADR-005 | Decision logging | Human-readable decisions append to `decisions.log`; Clone also writes machine-readable `decisions.jsonl`. | accepted |
| ADR-006 | Atomic persistence | File writes use temp-file replacement, while JSONL decision records use OS append mode. | accepted |
| ADR-007 | Task queue execution | Agent work runs through a bounded `ThreadPoolExecutor` so Clone can continue routing events. | accepted |
| ADR-008 | Durable queue state | Pending and blocked events are persisted under `.projectos_state` for runtime recovery. | accepted |
| ADR-009 | Provider health and retry | Provider calls use standard retry behavior and background health checks for status and fallback routing. | accepted |
| ADR-010 | Write safety policy | Generated code writes are validated with path allowlists, protected files, size checks, and diff previews. | accepted |
| ADR-011 | Ollama fallback | Ollama is implemented as a local provider and can be used in fallback routing without changing agent code. | accepted |
| ADR-012 | Git integration | ProjectOS may stage and commit reviewed files, but protected branches are not auto-committed. | accepted |
| ADR-013 | Terminal dashboard | Rich dashboard support is optional and falls back to plain daemon output when unavailable. | accepted |
| ADR-014 | MCP server | ProjectOS exposes stdio MCP tools for planning, review, status, decisions, and escalation approval. | accepted |
| ADR-015 | Multi-project runtime | Multi-project mode runs isolated `ProjectOS` instances from a YAML-backed project registry. | accepted |
