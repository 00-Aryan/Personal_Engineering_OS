# Trigger System

## Source-Defined Triggers

ProjectOS uses the triggers listed in the agent roster and autonomy rules.

## Agent Triggers

| Trigger | Agent | Required Output |
|---|---|---|
| New idea / sprint start | Planning Agent | Backlog, tasks, constraints |
| Any code change | Code Review Agent | Review report, issues flagged |
| New feature / design decision | Architecture Agent | ADR, risk flags |
| Any code change | Test Agent | Tests written and run automatically |
| Any code change | Documentation Agent | Docs updated automatically |

## Code Change Trigger Chain

Any code change must auto-trigger:

- Tests
- Docs
- Backlog update

## Permission Block Trigger

When Task A needs permission, the Clone must start Task B immediately.

The Clone must plan reconnection between blocked and parallel tasks.

## Model Switch Trigger

The `/model` command changes the model assigned to an agent:

```text
/model <agent_name> <model_name>
```

Example:

```text
/model code-review deepseek-v4
```

## Background Execution

ProjectOS must support a daemon process that runs in the background while
Aryan studies.

