# Contributing

ProjectOS is a local-first multi-agent engineering system. Contributions
should preserve the architecture rules in `AGENTS.md` and keep behavior
small, testable, and auditable.

## How To Add A New Agent

1. Create an agent module under `agents/` with a class that inherits from
   `core.base_agent.BaseAgent`.
2. Implement `handle(self, event: AgentEvent) -> AgentResult` with type
   hints and a docstring.
3. Add the agent provider and model assignment to `config/models.yaml`.
4. Register the agent in `core/projectos.py` and add Clone dispatch rules in
   `core/clone_agent.py` only for the events the agent should own.

## How To Add A New Model Provider

All model calls must go through `core.model_provider.ModelProvider`. Add a
provider by subclassing `ModelProvider`, implementing `complete()`,
`stream()`, and `health_check()`, then loading all provider-specific URLs,
keys, and model names from `config/models.yaml`.

Do not hardcode model names or API formats inside agents. Agents receive a
configured provider instance and call the common provider interface only.

## Running Tests

Run the full suite before marking a task complete:

```bash
UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest
```

For smoke verification:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-sync python smoke_test.py --ci
```

## Code Standards

- Every function must have a docstring.
- Every function must have type hints.
- Avoid hardcoded values; use config, constants, or environment variables.
- Use atomic file writes when changing files from ProjectOS code.
- Keep model calls behind `core/model_provider.py`.
- Do not introduce LangChain, CrewAI, or another agent framework.

## PR Checklist

- Tests pass locally.
- `AGENTS.md` was not modified.
- A task result file was written when completing a task.
- New behavior has focused tests.
- Model names and provider details are read from configuration.
