# TASK_37 Result: Alerting + Anomaly Detection

## Files Created

- [core/observability/alerting.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/observability/alerting.py)
- [core/observability/anomaly_detector.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/observability/anomaly_detector.py)
- [tests/test_observability/test_alerting.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/tests/test_observability/test_alerting.py)
- [tests/test_observability/test_anomaly_detector.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/tests/test_observability/test_anomaly_detector.py)

## Files Modified

- [core/observability/__init__.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/observability/__init__.py)
- [core/projectos.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/projectos.py)
- [cli/dashboard.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/cli/dashboard.py)
- [cli/main.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/cli/main.py)

## Test Count and Verification

- **New Tests:** 11 unit tests covering alerting rules, cooldowns, acknowledgments, active state filtering, and anomaly detection checks.
- **Total Tests:** 309 passing tests.
- **Verification Command:** `PYTHONDONTWRITEBYTECODE=1 uv run pytest`

## Decisions Made

1. **Avoid Circular Imports in Observability:**
   Removed package-level imports of `AlertManager` and `AnomalyDetector` from `core/observability/__init__.py` and imported `EvaluationStore` locally inside `AlertManager` constructor. This prevents dependencies on the evaluation package from executing during early system initialization phases (e.g. when importing `ModelProvider` which imports `TokenBudget`).
2. **Robust Log-based Cooldown Tracking:**
   Alert cooldown was implemented to track `(alert_type, component)` to prevent duplicate active notifications while avoiding thread blockages.
3. **Rolling Window Anomaly Check for Quality Gate:**
   Implemented quality gate block rates using a rolling 10-decision window over the last 50 decisions to provide a stable, meaningful time-series for Z-score calculation rather than Z-scoring individual binary decisions.
4. **Append-Only State Logging:**
   Persisted acknowledgments in the append-only `alerts.jsonl` log file, overwriting status in memory on load to keep state changes durable across daemon restarts.
