# Known Limitations

These are real limitations of the current version.
They are documented here so users know what to expect.

## Security
- **No true sandbox**: Generated code and tests run on your host machine. 
  AST scanning provides basic protection but is not foolproof.
  Do not run ProjectOS on projects containing sensitive credentials
  without reviewing generated code first.

## Model Quality
- **All tests use mocked providers**: The test suite validates structure
  and wiring, not output quality. Real model output quality varies.
- **Quality gates are heuristic**: The LLM-as-judge evaluator uses
  another model to grade output. This can have errors.

## Infrastructure  
- **JSONL files grow indefinitely**: Log files are append-only and
  not rotated. Long-running deployments should periodically archive
  .projectos_state/ files.
- **Single-machine only**: All state is local. No sync across machines.
- **No web UI**: Terminal and Telegram only.

## Model Providers
- **Gemini free tier limits**: 1500 requests/minute, 1M tokens/day.
  Heavy usage will hit limits.
- **Ollama requires local hardware**: CPU-only inference is slow.
  Expect 30-120 seconds per completion on a laptop without GPU.

## Platform
- **Linux and macOS only**: Windows support is untested.
- **Python 3.10+ required**: Older Python versions not supported.

## Current Phase
- **Phase 9 features experimental**: Project intake, phase management,
  and Telegram integration are new in v0.6.0 and may have rough edges.
  Report issues at: https://github.com/00-Aryan/Personal_Engineering_OS/issues
