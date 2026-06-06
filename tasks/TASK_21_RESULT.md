# TASK_21 Result: Evaluation Framework + LLM-as-Judge

## Files Created
- core/evaluation/__init__.py
- core/evaluation/base_evaluator.py
- core/evaluation/criteria_library.py
- core/evaluation/evaluation_store.py
- core/evaluation/llm_judge.py
- tests/test_evaluation/__init__.py
- tests/test_evaluation/test_evaluation_store.py
- tests/test_evaluation/test_llm_judge.py

## Files Modified
- tasks/README.md

## Test Count and Result
- Targeted: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_evaluation/ -v`
- Result: 13 passed
- Full suite: `UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest`
- Result: 138 passed

## Decisions Made
- Kept evaluation as a new standalone `core.evaluation` subpackage so later Phase 3 tasks can integrate it without changing current agent behavior prematurely.
- Used dataclasses for `EvaluationCriteria` and `EvaluationResult`, consistent with existing ProjectOS event/result types.
- Implemented score validation in `BaseEvaluator.compute_weighted_score()` and raise `ValueError` when criterion weights do not sum to 1.0.
- Used `context["agent_name"]` and `context["event_id"]` to bind evaluations to current `AgentResult` instances because `AgentResult` itself does not carry event identity.
- Made invalid judge JSON return a failed `EvaluationResult` with score `0.0` instead of raising, matching the task requirement.
- Mirrored existing atomic read-modify-replace write style for `evaluations.jsonl`.

## Human Review
- None flagged.

## Next Task Dependency Check
- TASK_22 can now build on:
  - `EvaluationStore`
  - `EvaluationResult`
  - `EvaluationCriteria`
  - `LLMJudge`
  - predefined criteria functions in `criteria_library.py`
