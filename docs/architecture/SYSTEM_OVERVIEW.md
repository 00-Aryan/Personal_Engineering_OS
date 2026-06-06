# ProjectOS System Overview

## Component Diagram

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

## Data Flow: File Change To Agents

1. A Python source file is modified under the watched project directory.

2. `TriggerSystem` receives the filesystem notification, ignores test files, bytecode, `.git`, and `__pycache__`, then emits an `AgentEvent` with `event_type=CODE_CHANGED`.

3. `ProjectOS._event_loop()` reads the event from the queue and calls `clone_agent.handle(event)`.

4. `CloneAgent` classifies the event. Routine code changes are `AUTONOMOUS`; risky payloads are `ESCALATE`; blocked work is `DEFER_PARALLEL`.

5. For an autonomous `CODE_CHANGED`, Clone dispatches child events to `code_review`, `test_agent`, and `docs_agent` using `payload["target_agent"]`.

6. `TaskQueue.submit()` runs target agents in a `ThreadPoolExecutor`, so Clone can continue routing without waiting for each agent's model call or file work.

7. Agent results can emit `next_events`; `ProjectOS._handle_agent_result()` sends those back through Clone for another classification and dispatch pass.

## Event Lifecycle And Correlation IDs

`AgentEvent` is the common event envelope. It contains `event_type`, `source_agent`, `payload`, a generated `event_id`, optional `correlation_id`, timestamp, optional `blocked_by`, and priority.

Clone preserves correlation across dispatch. When it creates a targeted child event, the child receives the parent `correlation_id`; if the parent has none, the parent `event_id` becomes the correlation value. This gives a stable tracking key across a multi-agent chain such as planning, code writing, review, tests, and docs.

Blocked tasks use the same correlation key. `TaskQueue` stores blocked items by `correlation_id`, and `PERMISSION_GRANTED` events resume blocked work by passing the matching correlation back into `TaskQueue.unblock()`.

## Clone Decision Engine

Clone has three decision categories:

| Category | Meaning | Persistence |
| --- | --- | --- |
| `AUTONOMOUS` | The event is safe to route without human approval. | Appends a decision row to `decisions.log`. |
| `ESCALATE` | The event contains a high-risk signal such as a new dependency, breaking change, delete-file request, architecture change, model escalation result, or more than three affected files. | Appends `escalation_queue.md` and `decisions.log`. |
| `DEFER_PARALLEL` | The event is blocked by a permission or dependency, but unrelated work can continue. | Appends `blocked_tasks.md` and `decisions.log`, then dispatches independent queued events. |

The decision engine is implemented in `core/clone_agent.py`. It does not call a model provider for routine classification; it uses deterministic event type and payload checks.

## Parallel Execution And Non-Blocking Guarantee

ProjectOS uses two layers of non-blocking behavior:

1. `ProjectOS.start()` runs the filesystem event loop in a daemon thread, separate from the CLI process that started it.

2. `TaskQueue` submits target-agent work to a `ThreadPoolExecutor` with a bounded worker count. `submit()` returns a future for runnable work and returns immediately after storing blocked work.

The guarantee is practical rather than absolute: Clone and the event loop do not intentionally wait on agent model calls during normal dispatch. If the process exits, the in-memory queue and thread pool state are not durable.

## Blocked Task Handling And Reconnection

A task becomes blocked when its event has `blocked_by` set or its `event_type` is `PERMISSION_BLOCKED`.

When Clone receives blocked work:

1. Clone classifies the event as `DEFER_PARALLEL`.

2. Clone stores a blocked task row in `blocked_tasks.md` with the task event ID, blocker, correlation ID, and reconnect plan.

3. If the event has a `target_agent` and ProjectOS is fully wired, Clone asks `TaskQueue` to store the blocked event instead of running it.

4. Clone scans its internal queued events for work without a blocker and dispatches that work in parallel.

5. A later `PERMISSION_GRANTED` event with the same correlation ID calls `TaskQueue.unblock()`.

6. The resumed event is copied with `permission_granted=True`, `permission_context=PERMISSION_GRANTED`, and `blocked_by=None`, then submitted to the original target agent.

This design keeps blocked work visible in markdown while allowing unrelated events to continue.

## Model Provider Layer

All model calls go through `core/model_provider.py`. Providers load `config/models.yaml`, resolve each agent's provider and model, read API keys from configured environment variables when needed, and expose `complete()` and `stream()` methods.

Implemented provider adapters are OpenRouter, Gemini, and Ollama. Tests use mocked providers so the verification suite does not require live API calls.

## Phase 3 Evaluation Subsystem

Phase 3 adds a quality layer that sits between worker-agent output and Clone's downstream dispatch decisions.

```text
             +-----------------------+
             | Worker Agent Result   |
             +-----------+-----------+
                         |
                         v
             +-----------+-----------+
             | SchemaValidator       |
             | output shape checks   |
             +-----------+-----------+
                         |
                         v
 +-----------------------+-----------------------+
 |                                               |
 v                                               v
+----------------------+             +----------+-----------+
| LLMJudge             |             | StaticAnalyzer       |
| rubric scores        |             | code quality signals |
+----------+-----------+             +----------+-----------+
           |                                    |
           +----------------+-------------------+
                            |
                            v
                 +----------+-----------+
                 | QualityScorer        |
                 | weighted score       |
                 +----------+-----------+
                            |
                            v
                 +----------+-----------+
                 | RegressionDetector   |
                 | model baselines      |
                 +----------+-----------+
                            |
                            v
                 +----------+-----------+
                 | QualityGate          |
                 | PASS/BLOCK/ESCALATE |
                 +----------------------+
```

Persistent evaluation artifacts:

- `.projectos_state/evaluations.jsonl` stores LLM judge results.
- `.projectos_state/baselines.json` stores rolling model-versioned baselines.
- `.projectos_state/gate_decisions.jsonl` stores append-only gate decisions and overrides.
- `.projectos_state/static_analysis/` stores static reports emitted by the code-writing path.
- `decisions.log` and `escalation_queue.md` remain the human-facing operational trail.

## Quality Gate And Clone Dispatch

`ProjectOS` initializes `EvaluationStore`, `SchemaValidator`, `RegressionDetector`, `StaticAnalyzer`, `QualityScorer`, and `QualityGate`, then injects them into `CloneAgent`.

When a worker agent returns an `AgentResult`, `ProjectOS._handle_agent_result()` passes the result through `CloneAgent.process_agent_result()` before dispatching follow-up events. Clone validates result schema first. If validation fails, Clone marks the result for escalation and writes an escalation row.

If a quality gate is configured, Clone then calls `QualityGate.evaluate()`. A `PASS` decision appends an autonomous gate decision to `decisions.log` and allows downstream events to continue. A `BLOCK` decision clears downstream events, marks the result as escalating, appends a gate record, and writes `escalation_queue.md`. An `ESCALATE` decision preserves downstream flow but still marks the result and writes an escalation row for human review.

Human operators can append an override with `projectos gate override EVENT_ID --reason TEXT`. Overrides are stored as `BYPASS` rows in `gate_decisions.jsonl`; earlier blocked rows are never rewritten.

## Evaluation Data Flow

```text
AgentResult
  -> DEFAULT_SCHEMAS validation
  -> LLMJudge rubric scoring
  -> EvaluationStore.save()
  -> StaticAnalyzer.analyze(file_path)
  -> QualityScorer.score(llm_weight=0.6, static_weight=0.4)
  -> RegressionDetector.check_regression(agent, score, model_version)
  -> QualityGate.evaluate()
  -> CloneAgent PASS/BLOCK/ESCALATE handling
```

The benchmark and smoke scripts use mocked providers and deterministic static signals so CI can verify the pipeline without live API calls.

## Baseline Versioning Strategy

Regression baselines are keyed by `agent_name:model_version`. Each model version receives an independent rolling score window, so changing an agent model automatically starts a fresh baseline rather than comparing the new model against the old model's distribution.

`RegressionDetector` keeps the latest ten scores by default and requires at least five samples before a regression can trigger. A regression is detected when the current score falls below the baseline by more than the configured tolerance, currently ten percent by default. Baselines can be inspected with `projectos quality baseline` and reset per agent with `projectos quality reset --agent AGENT_NAME`.
