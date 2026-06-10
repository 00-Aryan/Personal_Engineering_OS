"""Alerting system for ProjectOS observability."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.observability.token_budget import TokenBudget
from core.observability.cost_tracker import CostTracker
from core.notifications.telegram_notifier import TelegramNotifier

import yaml

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
    alert_id: str
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    component: str
    metric_value: float
    threshold: float
    timestamp: datetime
    acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize alert to dictionary."""
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "component": self.component,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "acknowledged_by": self.acknowledged_by,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Alert:
        """De-serialize alert from dictionary."""
        acknowledged_at = d.get("acknowledged_at")
        return cls(
            alert_id=d["alert_id"],
            alert_type=AlertType(d["alert_type"]),
            severity=AlertSeverity(d["severity"]),
            title=d["title"],
            message=d["message"],
            component=d["component"],
            metric_value=float(d["metric_value"]),
            threshold=float(d["threshold"]),
            timestamp=datetime.fromisoformat(d["timestamp"]),
            acknowledged=bool(d.get("acknowledged", False)),
            acknowledged_at=datetime.fromisoformat(acknowledged_at) if acknowledged_at else None,
            acknowledged_by=d.get("acknowledged_by", ""),
        )


class AlertRule:
    """Configures evaluation of alerts under specific types and frequencies."""

    def __init__(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        check_fn: Callable[[], Optional[Alert] | List[Alert]],
        check_interval_seconds: int = 60,
        cooldown_seconds: int = 300,
    ) -> None:
        self.alert_type = alert_type
        self.severity = severity
        self.check_fn = check_fn
        self.check_interval_seconds = check_interval_seconds
        self.cooldown_seconds = cooldown_seconds
        self.last_checked_at: Optional[datetime] = None


class AlertManager:
    """Evaluates alert rules on a schedule, stores fired alerts, and handles acknowledgments."""

    def __init__(
        self,
        state_dir: Path,
        rules: Optional[List[AlertRule]] = None,
        alerts_config: Optional[Dict[str, Any]] = None,
        notifier: Optional[TelegramNotifier] = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.state_dir / "alerts.jsonl"
        self._lock = threading.Lock()
        self.notifier = notifier
        
        self.alerts_config = alerts_config or {}
        self.daily_cost_inr_threshold = float(self.alerts_config.get("daily_cost_inr_threshold", 100.0))
        self.monthly_cost_inr_threshold = float(self.alerts_config.get("monthly_cost_inr_threshold", 2000.0))
        self.quality_score_minimum = float(self.alerts_config.get("quality_score_minimum", 0.60))
        self.blocked_queue_max = int(self.alerts_config.get("blocked_queue_max", 10))
        self.evaluation_failure_rate_max = float(self.alerts_config.get("evaluation_failure_rate_max", 0.30))

        self.token_budget = TokenBudget(self.state_dir)
        self.cost_tracker = CostTracker(self.state_dir)
        from core.evaluation.evaluation_store import EvaluationStore
        self.evaluation_store = EvaluationStore(self.state_dir)
        
        self._alerts: List[Alert] = []
        self._last_fired_at: Dict[Tuple[AlertType, str], datetime] = {}
        
        with self._lock:
            self._load_alerts()
            
        self.rules = rules if rules is not None else self._get_default_rules()
        
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _load_alerts(self) -> None:
        """Load stored alerts from alerts.jsonl file."""
        if not self.log_path.exists():
            return
        alerts_by_id = {}
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        alert = Alert.from_dict(data)
                        alerts_by_id[alert.alert_id] = alert
                    except Exception:
                        continue
        except Exception:
            pass
        self._alerts = list(alerts_by_id.values())

    def _append_alert(self, alert: Alert) -> None:
        """Append alert JSON record to alerts.jsonl file."""
        encoded = (
            json.dumps(alert.to_dict(), sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        fd = os.open(
            self.log_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o644,
        )
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)

    def _get_default_rules(self) -> List[AlertRule]:
        """Build the list of DEFAULT rules."""
        return [
            AlertRule(AlertType.QUALITY_REGRESSION, AlertSeverity.CRITICAL, self._check_quality_regression),
            AlertRule(AlertType.TOKEN_BUDGET_EXCEEDED, AlertSeverity.WARNING, self._check_token_budget),
            AlertRule(AlertType.COST_THRESHOLD_EXCEEDED, AlertSeverity.WARNING, self._check_daily_cost),
            AlertRule(AlertType.CIRCUIT_BREAKER_OPENED, AlertSeverity.CRITICAL, self._check_circuit_breaker),
            AlertRule(AlertType.SLOW_TRACE, AlertSeverity.WARNING, self._check_slow_traces),
            AlertRule(AlertType.BLOCKED_TASK_QUEUE_GROWING, AlertSeverity.WARNING, self._check_blocked_queue),
            AlertRule(AlertType.EVALUATION_FAILURE_RATE_HIGH, AlertSeverity.WARNING, self._check_eval_failure_rate),
            AlertRule(AlertType.SLOW_TRACE, AlertSeverity.INFO, self._check_anomalies, check_interval_seconds=60),
        ]

    def _check_quality_regression(self) -> List[Alert]:
        """Rule 1: Quality regression."""
        alerts = []
        try:
            records = self.evaluation_store._records()
            agent_scores: Dict[str, List[float]] = {}
            for r in records:
                agent_scores.setdefault(r.agent_name, []).append(r.weighted_score)
            
            for agent_name, scores in agent_scores.items():
                if len(scores) >= 10:
                    avg = sum(scores) / len(scores)
                    if avg < self.quality_score_minimum:
                        alerts.append(Alert(
                            alert_id=str(uuid.uuid4()),
                            alert_type=AlertType.QUALITY_REGRESSION,
                            severity=AlertSeverity.CRITICAL,
                            title=f"Quality regression: {agent_name}",
                            message=f"Agent {agent_name} average score is {avg:.2f} (< {self.quality_score_minimum:.2f}) over {len(scores)} evaluations",
                            component=agent_name,
                            metric_value=avg,
                            threshold=self.quality_score_minimum,
                            timestamp=datetime.now(timezone.utc),
                        ))
        except Exception:
            pass
        return alerts

    def _check_token_budget(self) -> List[Alert]:
        """Rule 2: Token budget."""
        alerts = []
        try:
            for agent_name, budget_cfg in self.token_budget.budgets.items():
                if agent_name == "default":
                    continue
                used = self.token_budget.get_daily_usage(agent_name)
                limit = budget_cfg.get("daily_limit", 50000)
                if used > 0.8 * limit:
                    pct = (used / limit) * 100.0 if limit > 0 else 0.0
                    alerts.append(Alert(
                        alert_id=str(uuid.uuid4()),
                        alert_type=AlertType.TOKEN_BUDGET_EXCEEDED,
                        severity=AlertSeverity.WARNING,
                        title=f"Token budget warning: {agent_name}",
                        message=f"Token budget {pct:.0f}%: {agent_name} (today)",
                        component=agent_name,
                        metric_value=float(used),
                        threshold=float(limit * 0.8),
                        timestamp=datetime.now(timezone.utc),
                    ))
        except Exception:
            pass
        return alerts

    def _check_daily_cost(self) -> Optional[Alert]:
        """Rule 3: Daily cost."""
        try:
            daily_cost = self.cost_tracker.get_daily_cost()
            total_inr = daily_cost.get("total_inr", 0.0)
            threshold = self.daily_cost_inr_threshold
            
            if total_inr > threshold:
                return Alert(
                    alert_id=str(uuid.uuid4()),
                    alert_type=AlertType.COST_THRESHOLD_EXCEEDED,
                    severity=AlertSeverity.WARNING,
                    title="Daily cost threshold exceeded",
                    message=f"Today daily cost is INR {total_inr:.2f} (threshold: INR {threshold:.2f})",
                    component="cost_tracker",
                    metric_value=total_inr,
                    threshold=threshold,
                    timestamp=datetime.now(timezone.utc),
                )
        except Exception:
            pass
        return None

    def _check_circuit_breaker(self) -> List[Alert]:
        """Rule 4: Circuit breaker."""
        alerts = []
        try:
            for file_path in self.state_dir.glob("circuit_state_*.json"):
                filename = file_path.name
                provider = filename.replace("circuit_state_", "").replace(".json", "")
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    state = data.get("state", "closed")
                    if state.lower() == "open":
                        alerts.append(Alert(
                            alert_id=str(uuid.uuid4()),
                            alert_type=AlertType.CIRCUIT_BREAKER_OPENED,
                            severity=AlertSeverity.CRITICAL,
                            title=f"Circuit breaker OPEN: {provider}",
                            message=f"Circuit breaker for provider {provider} is OPEN",
                            component=provider,
                            metric_value=1.0,
                            threshold=0.0,
                            timestamp=datetime.now(timezone.utc),
                        ))
                except Exception:
                    pass
            
            circuit_state_file = self.state_dir / "circuit_state.json"
            if circuit_state_file.exists():
                try:
                    data = json.loads(circuit_state_file.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        state = data.get("state", "closed")
                        if state.lower() == "open":
                            alerts.append(Alert(
                                alert_id=str(uuid.uuid4()),
                                alert_type=AlertType.CIRCUIT_BREAKER_OPENED,
                                severity=AlertSeverity.CRITICAL,
                                title="Circuit breaker OPEN",
                                message="Circuit breaker is OPEN",
                                component="circuit_breaker",
                                metric_value=1.0,
                                threshold=0.0,
                                timestamp=datetime.now(timezone.utc),
                            ))
                except Exception:
                    pass
        except Exception:
            pass
        return alerts

    def _check_slow_traces(self) -> Optional[Alert]:
        """Rule 5: Slow traces."""
        try:
            log_path = self.state_dir / "traces.jsonl"
            if not log_path.exists():
                return None
            
            from collections import defaultdict
            trace_spans = defaultdict(list)
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        t_id = data.get("trace_id")
                        if t_id:
                            trace_spans[t_id].append(data)
                    except Exception:
                        continue
            
            traces = []
            for t_id, spans in trace_spans.items():
                earliest_start = None
                latest_end = None
                for s in spans:
                    try:
                        start = datetime.fromisoformat(s["started_at"])
                        if earliest_start is None or start < earliest_start:
                            earliest_start = start
                    except Exception:
                        continue
                    if s.get("ended_at"):
                        try:
                            end = datetime.fromisoformat(s["ended_at"])
                            if latest_end is None or end > latest_end:
                                latest_end = end
                        except Exception:
                            continue
                
                if earliest_start and latest_end:
                    dur = (latest_end - earliest_start).total_seconds() * 1000
                    traces.append((earliest_start, dur))
            
            if not traces:
                return None
            
            traces.sort(key=lambda x: x[0], reverse=True)
            recent_traces = traces[:10]
            avg_dur = sum(x[1] for x in recent_traces) / len(recent_traces)
            
            if avg_dur > 10000.0:
                return Alert(
                    alert_id=str(uuid.uuid4()),
                    alert_type=AlertType.SLOW_TRACE,
                    severity=AlertSeverity.WARNING,
                    title="Slow traces detected",
                    message=f"Average duration of last {len(recent_traces)} traces is {avg_dur:.0f}ms (> 10000ms)",
                    component="tracer",
                    metric_value=avg_dur,
                    threshold=10000.0,
                    timestamp=datetime.now(timezone.utc),
                )
        except Exception:
            pass
        return None

    def _check_blocked_queue(self) -> Optional[Alert]:
        """Rule 6: Blocked tasks queue growing."""
        try:
            blocked_tasks_path = self.state_dir.parent / "blocked_tasks.md"
            if not blocked_tasks_path.exists():
                return None
            
            count = 0
            lines = blocked_tasks_path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                line = line.strip()
                if line.startswith("|") and "task_id" not in line and "---" not in line:
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if parts:
                        count += 1
            
            if count > self.blocked_queue_max:
                return Alert(
                    alert_id=str(uuid.uuid4()),
                    alert_type=AlertType.BLOCKED_TASK_QUEUE_GROWING,
                    severity=AlertSeverity.WARNING,
                    title="Blocked task queue growing",
                    message=f"Blocked tasks count is {count} (> {self.blocked_queue_max})",
                    component="task_queue",
                    metric_value=float(count),
                    threshold=float(self.blocked_queue_max),
                    timestamp=datetime.now(timezone.utc),
                )
        except Exception:
            pass
        return None

    def _check_eval_failure_rate(self) -> Optional[Alert]:
        """Rule 7: Evaluation failure rate."""
        try:
            gate_decisions_path = self.state_dir / "gate_decisions.jsonl"
            if not gate_decisions_path.exists():
                return None
            
            decisions = []
            with open(gate_decisions_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        dec = data.get("decision")
                        if dec:
                            decisions.append(dec)
                    except Exception:
                        continue
            
            if not decisions:
                return None
            
            recent_decisions = decisions[-50:]
            block_count = sum(1 for d in recent_decisions if d == "BLOCK")
            block_rate = (block_count / len(recent_decisions)) * 100.0
            
            threshold = self.evaluation_failure_rate_max
            threshold_pct = threshold * 100.0 if threshold <= 1.0 else threshold
            if block_rate > threshold_pct:
                return Alert(
                    alert_id=str(uuid.uuid4()),
                    alert_type=AlertType.EVALUATION_FAILURE_RATE_HIGH,
                    severity=AlertSeverity.WARNING,
                    title="High evaluation failure rate",
                    message=f"Gate block rate is {block_rate:.1f}% in last {len(recent_decisions)} decisions (> {threshold_pct:.1f}%)",
                    component="quality_gate",
                    metric_value=block_rate,
                    threshold=threshold_pct,
                    timestamp=datetime.now(timezone.utc),
                )
        except Exception:
            pass
        return None

    def _check_anomalies(self) -> List[Alert]:
        """Rule 8: Anomaly detection."""
        alerts = []
        try:
            from core.observability.anomaly_detector import AnomalyDetector
            detector = AnomalyDetector(self.state_dir)
            anomalies = detector.check_all()
            for anomaly in anomalies:
                if "latency" in anomaly.metric_name.lower():
                    alert_type = AlertType.SLOW_TRACE
                    mean = anomaly.mean
                    val = anomaly.current_value
                    ratio = val / mean if mean != 0 else 1.0
                    title = f"Latency anomaly: {anomaly.agent_name} {ratio:.1f}x avg"
                else:
                    alert_type = AlertType.TOKEN_BUDGET_EXCEEDED
                    mean = anomaly.mean
                    val = anomaly.current_value
                    ratio = val / mean if mean != 0 else 1.0
                    title = f"Token anomaly: {anomaly.agent_name} {ratio:.1f}x avg"
                
                alerts.append(Alert(
                    alert_id=str(uuid.uuid4()),
                    alert_type=alert_type,
                    severity=AlertSeverity.INFO,
                    title=title,
                    message=anomaly.message,
                    component=anomaly.agent_name,
                    metric_value=anomaly.z_score,
                    threshold=detector.z_score_threshold,
                    timestamp=datetime.now(timezone.utc),
                ))
        except Exception:
            pass
        return alerts

    def start(self) -> None:
        """Start the background thread evaluating rules on a schedule."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="projectos-alerting",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the background alerting loop cleanly."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _run_loop(self) -> None:
        """Run schedule checks inside a background thread loop."""
        while not self._stop_event.wait(1.0):
            self.evaluate_rules()

    def evaluate_rules(self) -> None:
        """Evaluate rules and fire alerts where conditions are met."""
        now = datetime.now(timezone.utc)
        for rule in self.rules:
            if rule.last_checked_at is None or (now - rule.last_checked_at).total_seconds() >= rule.check_interval_seconds:
                rule.last_checked_at = now
                try:
                    res = rule.check_fn()
                    if not res:
                        continue
                    if isinstance(res, list):
                        for alert in res:
                            self.process_fired_alert(alert)
                    else:
                        self.process_fired_alert(res)
                except Exception:
                    pass

    def process_fired_alert(self, alert: Alert) -> None:
        """Check cooldown and fire alert if allowed."""
        key = (alert.alert_type, alert.component)
        now = datetime.now(timezone.utc)
        
        cooldown = 300
        for rule in self.rules:
            if rule.alert_type == alert.alert_type:
                cooldown = rule.cooldown_seconds
                break
                
        with self._lock:
            if key in self._last_fired_at:
                last_fired = self._last_fired_at[key]
                if (now - last_fired).total_seconds() < cooldown:
                    return
            
            self._last_fired_at[key] = now
            self._alerts.append(alert)
            self._append_alert(alert)
            if self.notifier is not None:
                self.notifier.send_alert(
                    severity=alert.severity.value,
                    message=alert.message,
                    component=alert.component,
                )

    def get_active_alerts(self) -> List[Alert]:
        """Return active unacknowledged alerts sorted by severity then timestamp."""
        with self._lock:
            active = [a for a in self._alerts if not a.acknowledged]
            severity_map = {
                AlertSeverity.CRITICAL: 0,
                AlertSeverity.WARNING: 1,
                AlertSeverity.INFO: 2,
            }
            active.sort(key=lambda a: (severity_map.get(a.severity, 99), a.timestamp))
            return active

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge one alert by id."""
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id and not alert.acknowledged:
                    alert.acknowledged = True
                    alert.acknowledged_at = datetime.now(timezone.utc)
                    alert.acknowledged_by = "human"
                    self._append_alert(alert)
                    return True
            return False

    def acknowledge_all(self) -> int:
        """Acknowledge all active alerts."""
        count = 0
        with self._lock:
            now = datetime.now(timezone.utc)
            for alert in self._alerts:
                if not alert.acknowledged:
                    alert.acknowledged = True
                    alert.acknowledged_at = now
                    alert.acknowledged_by = "human"
                    self._append_alert(alert)
                    count += 1
            return count
