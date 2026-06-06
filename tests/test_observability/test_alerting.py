import tempfile
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
import pytest

from core.observability.alerting import AlertManager, Alert, AlertSeverity, AlertType, AlertRule
from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.base_evaluator import EvaluationResult


def test_quality_regression_rule_fires_on_low_score():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        
        # Setup EvaluationStore with 10 low evaluations
        store = EvaluationStore(state_dir)
        for i in range(10):
            res = EvaluationResult(
                evaluator_name="llm_judge",
                agent_name="planning",
                event_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc),
                criteria_scores={"correctness": 0.5},
                weighted_score=0.50,
                passed=False,
                reasoning="test",
                raw_output_sample="test",
                evaluation_duration_ms=100,
                evaluator_model="test",
                metadata={},
            )
            store.save(res)
            
        manager = AlertManager(state_dir)
        # Manually evaluate rules to trigger alert
        manager.evaluate_rules()
        
        active = manager.get_active_alerts()
        assert len(active) > 0
        quality_alerts = [a for a in active if a.alert_type == AlertType.QUALITY_REGRESSION]
        assert len(quality_alerts) == 1
        assert quality_alerts[0].severity == AlertSeverity.CRITICAL
        assert quality_alerts[0].component == "planning"
        assert quality_alerts[0].metric_value == 0.50


def test_alert_cooldown_prevents_duplicate_fires():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        
        # Create a rule with custom check
        fired_count = 0
        def dummy_check():
            nonlocal fired_count
            fired_count += 1
            return Alert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.CIRCUIT_BREAKER_OPENED,
                severity=AlertSeverity.CRITICAL,
                title="Test Circuit",
                message="Circuit open",
                component="test_cb",
                metric_value=1.0,
                threshold=0.0,
                timestamp=datetime.now(timezone.utc)
            )
            
        rule = AlertRule(
            AlertType.CIRCUIT_BREAKER_OPENED,
            AlertSeverity.CRITICAL,
            dummy_check,
            check_interval_seconds=1,
            cooldown_seconds=50
        )
        
        manager = AlertManager(state_dir, rules=[rule])
        
        # Fire once
        manager.evaluate_rules()
        assert len(manager.get_active_alerts()) == 1
        
        # Should not fire again due to cooldown
        manager.evaluate_rules()
        assert len(manager.get_active_alerts()) == 1


def test_acknowledge_marks_alert_done():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        manager = AlertManager(state_dir)
        
        alert = Alert(
            alert_id="alert-123",
            alert_type=AlertType.SLOW_TRACE,
            severity=AlertSeverity.WARNING,
            title="Slow Trace",
            message="too slow",
            component="tracer",
            metric_value=12000.0,
            threshold=10000.0,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Force add to manager
        manager._alerts.append(alert)
        manager._append_alert(alert)
        
        assert len(manager.get_active_alerts()) == 1
        
        success = manager.acknowledge("alert-123")
        assert success is True
        assert len(manager.get_active_alerts()) == 0
        
        # Check reload persistence
        new_manager = AlertManager(state_dir)
        assert len(new_manager.get_active_alerts()) == 0


def test_acknowledge_all_clears_active_alerts():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        manager = AlertManager(state_dir)
        
        alert1 = Alert(
            alert_id="alert-1",
            alert_type=AlertType.SLOW_TRACE,
            severity=AlertSeverity.WARNING,
            title="Slow Trace 1",
            message="too slow 1",
            component="tracer",
            metric_value=12000.0,
            threshold=10000.0,
            timestamp=datetime.now(timezone.utc)
        )
        alert2 = Alert(
            alert_id="alert-2",
            alert_type=AlertType.SLOW_TRACE,
            severity=AlertSeverity.WARNING,
            title="Slow Trace 2",
            message="too slow 2",
            component="tracer",
            metric_value=13000.0,
            threshold=10000.0,
            timestamp=datetime.now(timezone.utc)
        )
        
        manager._alerts.extend([alert1, alert2])
        manager._append_alert(alert1)
        manager._append_alert(alert2)
        
        assert len(manager.get_active_alerts()) == 2
        
        count = manager.acknowledge_all()
        assert count == 2
        assert len(manager.get_active_alerts()) == 0


def test_get_active_alerts_excludes_acknowledged():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        manager = AlertManager(state_dir)
        
        alert1 = Alert(
            alert_id="alert-1",
            alert_type=AlertType.SLOW_TRACE,
            severity=AlertSeverity.WARNING,
            title="Slow Trace 1",
            message="too slow 1",
            component="tracer",
            metric_value=12000.0,
            threshold=10000.0,
            timestamp=datetime.now(timezone.utc),
            acknowledged=True
        )
        alert2 = Alert(
            alert_id="alert-2",
            alert_type=AlertType.SLOW_TRACE,
            severity=AlertSeverity.CRITICAL,
            title="Slow Trace 2",
            message="too slow 2",
            component="tracer",
            metric_value=13000.0,
            threshold=10000.0,
            timestamp=datetime.now(timezone.utc),
            acknowledged=False
        )
        
        manager._alerts.extend([alert1, alert2])
        manager._append_alert(alert1)
        manager._append_alert(alert2)
        
        active = manager.get_active_alerts()
        assert len(active) == 1
        assert active[0].alert_id == "alert-2"
