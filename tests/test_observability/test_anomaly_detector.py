import tempfile
import json
from pathlib import Path
import pytest

from core.observability.anomaly_detector import AnomalyDetector


def test_no_anomaly_below_10_data_points():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        detector = AnomalyDetector(state_dir)
        
        # Write only 5 latency spans
        traces_path = state_dir / "traces.jsonl"
        with open(traces_path, "w", encoding="utf-8") as f:
            for i in range(5):
                f.write(json.dumps({
                    "component": "planning",
                    "duration_ms": 100 + i,
                    "started_at": "2026-06-07T00:00:00Z",
                    "ended_at": "2026-06-07T00:00:01Z"
                }) + "\n")
                
        res = detector.check_latency_anomaly("planning")
        assert res.is_anomaly is False
        assert res.z_score == 0.0


def test_anomaly_detected_on_high_z_score():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        detector = AnomalyDetector(state_dir, z_score_threshold=2.0)
        
        # Write 10 spans: 9 normal (around 100ms) and 1 high anomaly (1000ms)
        traces_path = state_dir / "traces.jsonl"
        with open(traces_path, "w", encoding="utf-8") as f:
            for i in range(9):
                f.write(json.dumps({
                    "component": "planning",
                    "duration_ms": 100,
                    "started_at": "2026-06-07T00:00:00Z",
                    "ended_at": "2026-06-07T00:00:01Z"
                }) + "\n")
            f.write(json.dumps({
                "component": "planning",
                "duration_ms": 1000,
                "started_at": "2026-06-07T00:00:00Z",
                "ended_at": "2026-06-07T00:00:01Z"
            }) + "\n")
            
        res = detector.check_latency_anomaly("planning")
        assert res.is_anomaly is True
        assert res.z_score > 2.0
        assert res.direction == "high"


def test_normal_within_threshold():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        detector = AnomalyDetector(state_dir, z_score_threshold=3.0)
        
        # Write 12 normal spans
        traces_path = state_dir / "traces.jsonl"
        with open(traces_path, "w", encoding="utf-8") as f:
            for i in range(12):
                f.write(json.dumps({
                    "component": "planning",
                    "duration_ms": 100 + (i % 3),
                    "started_at": "2026-06-07T00:00:00Z",
                    "ended_at": "2026-06-07T00:00:01Z"
                }) + "\n")
                
        res = detector.check_latency_anomaly("planning")
        assert res.is_anomaly is False


def test_direction_high_when_above_mean():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        detector = AnomalyDetector(state_dir, z_score_threshold=1.5)
        
        # Write 10 tokens records
        tokens_path = state_dir / "token_usage.jsonl"
        with open(tokens_path, "w", encoding="utf-8") as f:
            for i in range(9):
                f.write(json.dumps({
                    "agent_name": "planning",
                    "total_tokens": 1000
                }) + "\n")
            f.write(json.dumps({
                "agent_name": "planning",
                "total_tokens": 2000
            }) + "\n")
            
        res = detector.check_token_anomaly("planning")
        assert res.direction == "high"
        assert res.is_anomaly is True


def test_direction_low_when_below_mean():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        detector = AnomalyDetector(state_dir, z_score_threshold=1.5)
        
        # Write 10 tokens records: 9 high, 1 low
        tokens_path = state_dir / "token_usage.jsonl"
        with open(tokens_path, "w", encoding="utf-8") as f:
            for i in range(9):
                f.write(json.dumps({
                    "agent_name": "planning",
                    "total_tokens": 2000
                }) + "\n")
            f.write(json.dumps({
                "agent_name": "planning",
                "total_tokens": 500
            }) + "\n")
            
        res = detector.check_token_anomaly("planning")
        assert res.direction == "low"
        assert res.is_anomaly is True


def test_check_all_returns_only_anomalies():
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        detector = AnomalyDetector(state_dir, z_score_threshold=2.0)
        
        # Add normal trace spans for planning (no anomalies)
        # Add anomalous tokens records for code_writing
        traces_path = state_dir / "traces.jsonl"
        with open(traces_path, "w", encoding="utf-8") as f:
            for i in range(15):
                f.write(json.dumps({
                    "component": "planning",
                    "duration_ms": 100
                }) + "\n")
                
        tokens_path = state_dir / "token_usage.jsonl"
        with open(tokens_path, "w", encoding="utf-8") as f:
            for i in range(9):
                f.write(json.dumps({
                    "agent_name": "code_writing",
                    "total_tokens": 100
                }) + "\n")
            f.write(json.dumps({
                "agent_name": "code_writing",
                "total_tokens": 5000
            }) + "\n")
            
        anomalies = detector.check_all()
        assert len(anomalies) == 1
        assert anomalies[0].agent_name == "code_writing"
        assert anomalies[0].metric_name == "token_usage"
