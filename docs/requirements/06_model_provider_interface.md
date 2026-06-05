# Model Provider Interface

## Critical Requirement

Swapping the model for any single agent must require changing one config
value only.

## Model Switch Interface

The model switch command is:

```text
/model <agent_name> <model_name>
```

Example:

```text
/model code-review deepseek-v4
```

## Initial Model Assignments

The source-defined initial assignments are:

- Planning: DeepSeek V4, selected for strong reasoning
- Coding/Implementation: Minimax 2.5, selected as free and strong for code
- Review: TBD, benchmark first

## Supported Launch Providers

The supported launch providers are:

- OpenRouter free tier for DeepSeek V4 and Minimax 2.5
- Ollama as local fallback

## Future Provider Direction

Paid APIs must be possible as drop-in replacements.

## Data Structure Rule

All model calls must go through a single ModelProvider interface.

No agent may hardcode a model.

No agent may hardcode an API format.

