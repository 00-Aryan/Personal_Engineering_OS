# TASK_37: Alerting + Anomaly Detection

## Engineering Context

ProjectOS now has full visibility into:
- Traces (TASK_33): what happened and how long it took
- Token budgets (TASK_34): how many tokens each agent used
- Costs (TASK_35): what it cost in real currency
- Reliability (TASK_36): provider health and rate limits

This data is useless unless something acts on it.

Alerting closes the loop: when a metric crosses a threshold, you
are notified — even if you're studying and not watching the dashboard.

Anomaly detection goes further: it learns normal behavior and alerts
when something unusual happens, even without a predefined threshold.

Production systems (Datadog, PagerDuty, Grafana Alerting) use both.
This task implements lightweight versions of both using only the
data already in ProjectOS state files.

## Pre-conditions
Read ALL files in core/observability/ from TASK_33-36.
Read core/evaluation/regression_detector.py from TASK_22.
Read core/decision_log.py for JSONL patterns.

## Deliverables

### 1. core/observability/alerting.py

class AlertSeverity(Enum):
  INFO = "info"
  WARNING = "warning"
  CRITICAL = "critical"

class AlertType(Enum):
  QUALITY_REGRESSION = "quality_regression"
  TOKEN_BUDGET_EXCEEDED = "token_budget_exceeded"
  COST_THRESHOLD_EXCEEDED = "cost_threshold_exceeded"
  CIRCUIT_BREAKER_OPENED = "circuit_breaker_opened"
  PROVIDER_UNAVAILABLE = "provider_unavailable"
  SLOW_TRACE = "slow_trace"
  BLOCKED_TASK_QUEUE_GROWING = "blocked_task_queue_growing"
  EVALUATION_FAILURE_RATE_HIGH = "evaluation_failure_rate_high"

@dataclass
class Alert:
  alert_id: str  (UUID)
  alert_type: AlertType
  severity: AlertSeverity
  title: str
  message: str
  component: str  (which system triggered this)
  metric_value: float  (the value that triggered the alert)
  threshold: float  (the threshold that was crossed)
  timestamp: datetime
  acknowledged: bool = False
  acknowledged_at: Optional[datetime] = None
  acknowledged_by: str = ""  ("human" or "auto")

class AlertRule:
  __init__(
    alert_type: AlertType,
    severity: AlertSeverity,
    check_fn: Callable[[], Optional[Alert]],
    check_interval_seconds: int = 60,
    cooldown_seconds: int = 300
  )
  cooldown prevents the same alert firing repeatedly.

class AlertManager:
  """
  Evaluates alert rules on a schedule and stores fired alerts.
  
  Runs in background thread.
  Writes all alerts to alerts.jsonl.
  Provides CLI surface for acknowledgment.
  """
  
  __init__(
    state_dir: Path,
    rules: Optional[List[AlertRule]] = None
  )
  
  DEFAULT_RULES built from these checks:
  
  Rule 1 — Quality regression:
    Read EvaluationStore. If any agent avg_score < 0.60
    AND has >= 10 evaluations → CRITICAL alert
  
  Rule 2 — Token budget:
    Read token_usage.jsonl. If any agent used > 80% daily limit
    today → WARNING alert
  
  Rule 3 — Daily cost:
    Read costs.jsonl. If today total_inr > config threshold
    (default ₹100) → WARNING alert
  
  Rule 4 — Circuit breaker:
    Read circuit_state.json. If any circuit OPEN → CRITICAL alert
  
  Rule 5 — Slow traces:
    Read traces.jsonl. If last 10 traces avg duration > 10000ms
    → WARNING alert
  
  Rule 6 — Blocked queue growing:
    Read blocked_tasks.md. If blocked count > 10 → WARNING alert
  
  Rule 7 — Evaluation failure rate:
    Read gate_decisions.jsonl. If BLOCK rate > 30% in last 50
    decisions → WARNING alert
  
  start() → background thread evaluating rules on schedule
  stop() → clean shutdown
  
  get_active_alerts() -> List[Alert]:
    Returns unacknowledged alerts sorted by severity then timestamp.
  
  acknowledge(alert_id: str) -> bool:
    Marks alert as acknowledged. Returns False if not found.
  
  acknowledge_all() -> int:
    Acknowledges all active alerts. Returns count.

### 2. core/observability/anomaly_detector.py

class AnomalyDetector:
  """
  Detects statistical anomalies in time-series metrics.
  
  Method: Z-score based anomaly detection.
  z = (value - mean) / std_dev
  If |z| > threshold (default 2.5) → anomaly
  
  Applied to:
  - Per-agent call latency (from traces)
  - Per-agent token usage per call (from token_usage.jsonl)
  - Quality gate block rate (from gate_decisions.jsonl)
  
  Requires minimum 10 data points before detecting anomalies.
  Below 10 points: always returns normal.
  
  This is the same statistical approach used in production ML
  monitoring (Evidently, WhyLogs, basic Datadog anomaly detection).
  """
  
  __init__(state_dir: Path, z_score_threshold: float = 2.5)
  
  @dataclass
  class AnomalyResult:
    metric_name: str
    agent_name: str
    current_value: float
    mean: float
    std_dev: float
    z_score: float
    is_anomaly: bool
    direction: str  ("high" or "low")
    message: str
  
  check_latency_anomaly(agent_name: str) -> AnomalyResult:
    Load last 50 trace spans for agent from traces.jsonl.
    Compute mean and std of duration_ms.
    Check last span against distribution.
  
  check_token_anomaly(agent_name: str) -> AnomalyResult:
    Load last 50 token usage records for agent.
    Compute mean and std of total_tokens.
    Check last record against distribution.
  
  check_all() -> List[AnomalyResult]:
    Runs both checks for all known agents.
    Returns only anomalies (is_anomaly=True).

### 3. Update AlertManager
  Add anomaly detection rule:
  Rule 8 — Anomaly detected:
    Run anomaly_detector.check_all().
    For each anomaly: fire INFO alert with z_score and direction.

### 4. Update cli/dashboard.py
  Add Alerts Panel:
  
  ┌─ Active Alerts ────────────────────────────────────────┐
  │ 🔴 CRITICAL  Circuit breaker OPEN: openrouter          │
  │              Opened 3m ago. Use: projectos reliability  │
  │ 🟡 WARNING   Token budget 83%: code_review (today)     │
  │ 🟢 INFO      Latency anomaly: planning 2.3x avg        │
  │                                                        │
  │ 3 active | projectos alerts acknowledge-all to clear   │
  └────────────────────────────────────────────────────────┘

### 5. New CLI command: projectos alerts
  projectos alerts list
    Shows all unacknowledged alerts sorted by severity.
  
  projectos alerts list --all
    Shows last 50 alerts including acknowledged.
  
  projectos alerts acknowledge <alert_id>
    Acknowledges one alert.
  
  projectos alerts acknowledge-all
    Acknowledges all active alerts.
  
  projectos alerts anomalies
    Runs anomaly detection right now, shows results.

### 6. tests/test_observability/test_alerting.py
  - test_quality_regression_rule_fires_on_low_score
  - test_alert_cooldown_prevents_duplicate_fires
  - test_acknowledge_marks_alert_done
  - test_acknowledge_all_clears_active_alerts
  - test_get_active_alerts_excludes_acknowledged

### 7. tests/test_observability/test_anomaly_detector.py
  - test_no_anomaly_below_10_data_points
  - test_anomaly_detected_on_high_z_score
  - test_normal_within_threshold
  - test_direction_high_when_above_mean
  - test_direction_low_when_below_mean
  - test_check_all_returns_only_anomalies

## Constraints
- AlertManager background thread must stop cleanly on shutdown
- Cooldown prevents same alert_type + component firing more than once per cooldown period
- alerts.jsonl is append-only
- Anomaly detection never raises — returns is_anomaly=False on error
- All Z-score computations use stdlib statistics module only

## Verification
Full test suite. Write TASK_37_RESULT.md. Update tasks/README.md.
