# CLI Interface

## Primary Interface

The primary interaction interface is the CLI.

## Background Process

ProjectOS must include a daemon process that runs in the background while
Aryan studies.

## Key Commands

The key commands are:

- `/model`
- `/status`
- `/approve`
- `/backlog`
- `/review`

## Model Command

The source-defined model command interface is:

```text
/model <agent_name> <model_name>
```

Example:

```text
/model code-review deepseek-v4
```

## Command Details Not Specified In Source

The source does not define command arguments or behavior for:

- `/status`
- `/approve`
- `/backlog`
- `/review`

