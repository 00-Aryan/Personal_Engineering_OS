"""Statistical anomaly detection for ProjectOS time-series metrics."""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import List

LOGGER_NAME = "projectos.anomaly_detector"


class AnomalyDetector:
    """Detects statistical anomalies in time-series metrics using Z-scores."""

    @dataclass
    class AnomalyResult:
        metric_name: str
        agent_name: str
        current_value: float
        mean: float
        std_dev: float
        z_score: float
        is_anomaly: bool
        direction: str  # ("high" or "low")
        message: str

    def __init__(self, state_dir: Path, z_score_threshold: float = 2.5) -> None:
        self.state_dir = Path(state_dir)
        self.z_score_threshold = z_score_threshold
        self._logger = logging.getLogger(LOGGER_NAME)

    def _normal_result(self, metric_name: str, agent_name: str) -> AnomalyResult:
        """Helper to return a normal (non-anomalous) result."""
        return self.AnomalyResult(
            metric_name=metric_name,
            agent_name=agent_name,
            current_value=0.0,
            mean=0.0,
            std_dev=0.0,
            z_score=0.0,
            is_anomaly=False,
            direction="high",
            message="Normal",
        )

    def check_latency_anomaly(self, agent_name: str) -> AnomalyResult:
        """Check for latency anomalies using the last 50 spans for the agent."""
        try:
            log_path = self.state_dir / "traces.jsonl"
            if not log_path.exists():
                return self._normal_result("latency", agent_name)

            durations: List[float] = []
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("component") == agent_name:
                            dur = data.get("duration_ms")
                            if dur is not None:
                                durations.append(float(dur))
                    except Exception:
                        continue

            durations = durations[-50:]
            if len(durations) < 10:
                return self._normal_result("latency", agent_name)

            last_val = durations[-1]
            mean_val = statistics.mean(durations)
            try:
                std_val = statistics.stdev(durations)
            except Exception:
                std_val = 0.0

            if std_val == 0.0:
                z = 0.0
            else:
                z = (last_val - mean_val) / std_val

            is_anomaly = abs(z) > self.z_score_threshold
            direction = "high" if last_val >= mean_val else "low"
            message = (
                f"Latency anomaly: {agent_name} latency is {last_val:.1f}ms "
                f"(mean: {mean_val:.1f}ms, z_score: {z:.2f})"
            )

            return self.AnomalyResult(
                metric_name="latency",
                agent_name=agent_name,
                current_value=last_val,
                mean=mean_val,
                std_dev=std_val,
                z_score=z,
                is_anomaly=is_anomaly,
                direction=direction,
                message=message,
            )
        except Exception:
            return self._normal_result("latency", agent_name)

    def check_token_anomaly(self, agent_name: str) -> AnomalyResult:
        """Check for token budget usage anomalies using the last 50 calls."""
        try:
            log_path = self.state_dir / "token_usage.jsonl"
            if not log_path.exists():
                return self._normal_result("token_usage", agent_name)

            tokens: List[float] = []
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("agent_name") == agent_name:
                            tok = data.get("total_tokens")
                            if tok is not None:
                                tokens.append(float(tok))
                    except Exception:
                        continue

            tokens = tokens[-50:]
            if len(tokens) < 10:
                return self._normal_result("token_usage", agent_name)

            last_val = tokens[-1]
            mean_val = statistics.mean(tokens)
            try:
                std_val = statistics.stdev(tokens)
            except Exception:
                std_val = 0.0

            if std_val == 0.0:
                z = 0.0
            else:
                z = (last_val - mean_val) / std_val

            is_anomaly = abs(z) > self.z_score_threshold
            direction = "high" if last_val >= mean_val else "low"
            message = (
                f"Token usage anomaly: {agent_name} token usage is {last_val:.1f} "
                f"(mean: {mean_val:.1f}, z_score: {z:.2f})"
            )

            return self.AnomalyResult(
                metric_name="token_usage",
                agent_name=agent_name,
                current_value=last_val,
                mean=mean_val,
                std_dev=std_val,
                z_score=z,
                is_anomaly=is_anomaly,
                direction=direction,
                message=message,
            )
        except Exception:
            return self._normal_result("token_usage", agent_name)

    def check_gate_block_anomaly(self, agent_name: str) -> AnomalyResult:
        """Check for quality gate block rate anomalies using rolling window of 10."""
        try:
            log_path = self.state_dir / "gate_decisions.jsonl"
            if not log_path.exists():
                return self._normal_result("gate_block_rate", agent_name)

            decisions: List[float] = []
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("agent_name") == agent_name:
                            dec = data.get("decision")
                            if dec:
                                decisions.append(1.0 if dec == "BLOCK" else 0.0)
                    except Exception:
                        continue

            if len(decisions) < 10:
                return self._normal_result("gate_block_rate", agent_name)

            rates: List[float] = []
            for i in range(9, len(decisions)):
                rates.append(sum(decisions[i-9:i+1]) / 10.0)

            rates = rates[-50:]
            if len(rates) < 10:
                return self._normal_result("gate_block_rate", agent_name)

            last_val = rates[-1]
            mean_val = statistics.mean(rates)
            try:
                std_val = statistics.stdev(rates)
            except Exception:
                std_val = 0.0

            if std_val == 0.0:
                z = 0.0
            else:
                z = (last_val - mean_val) / std_val

            is_anomaly = abs(z) > self.z_score_threshold
            direction = "high" if last_val >= mean_val else "low"
            message = (
                f"Gate block rate anomaly: {agent_name} is {last_val*100:.1f}% "
                f"(mean: {mean_val*100:.1f}%, z_score: {z:.2f})"
            )

            return self.AnomalyResult(
                metric_name="gate_block_rate",
                agent_name=agent_name,
                current_value=last_val,
                mean=mean_val,
                std_dev=std_val,
                z_score=z,
                is_anomaly=is_anomaly,
                direction=direction,
                message=message,
            )
        except Exception:
            return self._normal_result("gate_block_rate", agent_name)

    def check_all(self) -> List[AnomalyResult]:
        """Runs checks for all known agents and returns only anomalies."""
        agents = ["clone", "planning", "code_writing", "code_review", "architecture", "test", "docs"]
        anomalies = []
        for agent in agents:
            try:
                res = self.check_latency_anomaly(agent)
                if res.is_anomaly:
                    anomalies.append(res)
            except Exception:
                pass
            try:
                res = self.check_token_anomaly(agent)
                if res.is_anomaly:
                    anomalies.append(res)
            except Exception:
                pass
            try:
                res = self.check_gate_block_anomaly(agent)
                if res.is_anomaly:
                    anomalies.append(res)
            except Exception:
                pass
        return anomalies
