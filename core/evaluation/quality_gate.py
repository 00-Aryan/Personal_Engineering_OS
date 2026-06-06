"""Quality gate enforcement for ProjectOS agent outputs."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Mapping, Optional

from core.evaluation.base_evaluator import EvaluationResult
from core.evaluation.quality_scorer import CombinedScore, QualityScorer
from core.evaluation.regression_detector import RegressionDetector, RegressionReport
from core.evaluation.static_analyzer import (
    ComplexityMetrics,
    SecurityMetrics,
    StaticAnalysisReport,
    StyleMetrics,
)
from core.events import AgentResult


ENCODING = "utf-8"
NEWLINE = "\n"
LOGGER_NAME = "projectos.quality_gate"
GATE_LOG_NAME = "gate_decisions.jsonl"

POLICY_CODE_WRITING = "code_writing"
POLICY_CODE_REVIEW = "code_review"
POLICY_PLANNING = "planning"
POLICY_DEFAULT = "default"

REASON_LOW_SCORE_TEMPLATE = "combined score {score:.2f} below threshold {threshold:.2f}"
REASON_SECURITY_HIGH_TEMPLATE = "high severity security issues found: {count}"
REASON_REGRESSION_TEMPLATE = "regression detected: {recommendation}"
WARNING_LLM_REQUIRED = "llm evaluation required but unavailable"
WARNING_STATIC_REQUIRED = "static analysis required but unavailable"
WARNING_EVALUATION_FAILED_TEMPLATE = "quality gate evaluation failed open: {error}"
WARNING_REGRESSION_FAILED_TEMPLATE = "regression check skipped: {error}"
OVERRIDE_REASON_REQUIRED = "Override reason is required."
OVERRIDE_NOT_FOUND_TEMPLATE = "No blocked gate decision found for event_id: {event_id}"

FIELD_DECISION = "decision"
FIELD_AGENT_NAME = "agent_name"
FIELD_EVENT_ID = "event_id"
FIELD_COMBINED_SCORE = "combined_score"
FIELD_BLOCKING_REASONS = "blocking_reasons"
FIELD_WARNINGS = "warnings"
FIELD_GATE_POLICY = "gate_policy"
FIELD_TIMESTAMP = "timestamp"
FIELD_DURATION_MS = "duration_ms"
FIELD_HUMAN_OVERRIDE = "human_override"
FIELD_OVERRIDE_REASON = "override_reason"

MIN_RATE_WINDOW = 0
PERCENT_MULTIPLIER = 100.0


@dataclass(frozen=True)
class GatePolicy:
    """Configure quality gate behavior per agent type."""

    agent_name: str
    min_combined_score: float
    require_llm_evaluation: bool
    require_static_analysis: bool
    block_on_security_high: bool = True
    block_on_regression: bool = True
    regression_tolerance: float = 0.10
    escalate_on_block: bool = True


class GateDecision(Enum):
    """Quality gate decision outcomes."""

    PASS = "PASS"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"
    BYPASS = "BYPASS"


@dataclass(frozen=True)
class GateResult:
    """Result of one quality gate evaluation."""

    decision: GateDecision
    agent_name: str
    event_id: str
    combined_score: Optional[float]
    blocking_reasons: List[str]
    warnings: List[str]
    gate_policy: str
    timestamp: datetime
    duration_ms: int
    human_override: bool = False
    override_reason: Optional[str] = None


class QualityGate:
    """Evaluate agent output quality and persist gate decisions."""

    def __init__(
        self,
        policies: Dict[str, GatePolicy],
        quality_scorer: QualityScorer,
        regression_detector: RegressionDetector,
        gate_log_path: Path,
    ) -> None:
        """Initialize quality gate policies, scorers, and log path."""
        self.policies = dict(policies)
        self.quality_scorer = quality_scorer
        self.regression_detector = regression_detector
        self.gate_log_path = Path(gate_log_path)
        self._logger = logging.getLogger(LOGGER_NAME)

    def evaluate(
        self,
        agent_result: AgentResult,
        agent_name: str,
        llm_evaluation: Optional[EvaluationResult] = None,
        file_path: Optional[Path] = None,
        model_version: Optional[str] = None,
    ) -> GateResult:
        """Evaluate one agent result against configured quality policy."""
        started_at = perf_counter()
        policy = self._policy(agent_name)
        try:
            combined_score = self.quality_scorer.score(
                agent_result,
                llm_evaluation,
                file_path,
            )
            static_report = self._static_report(agent_result, file_path)
            warnings = self._missing_signal_warnings(
                policy,
                llm_evaluation,
                static_report,
            )
            blocking_reasons = self._blocking_reasons(
                policy,
                combined_score,
                static_report,
            )
            regression_report = self._regression_report(
                policy,
                agent_name,
                llm_evaluation,
                model_version,
                warnings,
            )
            if regression_report is not None and regression_report.regression_detected:
                blocking_reasons.append(
                    REASON_REGRESSION_TEMPLATE.format(
                        recommendation=regression_report.recommendation,
                    )
                )
                decision = GateDecision.ESCALATE
            elif blocking_reasons:
                decision = GateDecision.BLOCK
            else:
                decision = GateDecision.PASS
            gate_result = self._result(
                decision,
                agent_name,
                combined_score.event_id,
                combined_score.combined_score,
                blocking_reasons,
                warnings,
                policy,
                started_at,
            )
        except Exception as error:
            warning = WARNING_EVALUATION_FAILED_TEMPLATE.format(error=error)
            self._logger.warning(warning)
            gate_result = self._result(
                GateDecision.PASS,
                agent_name,
                self._fallback_event_id(agent_result),
                None,
                [],
                [warning],
                policy,
                started_at,
            )
        self._append_result(gate_result)
        return gate_result

    def override(self, event_id: str, reason: str) -> GateResult:
        """Append a BYPASS decision for a previously blocked event."""
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError(OVERRIDE_REASON_REQUIRED)
        previous_result = self._latest_blocked_result(event_id)
        if previous_result is None:
            raise ValueError(OVERRIDE_NOT_FOUND_TEMPLATE.format(event_id=event_id))
        gate_result = GateResult(
            decision=GateDecision.BYPASS,
            agent_name=previous_result.agent_name,
            event_id=event_id,
            combined_score=previous_result.combined_score,
            blocking_reasons=list(previous_result.blocking_reasons),
            warnings=list(previous_result.warnings),
            gate_policy=previous_result.gate_policy,
            timestamp=datetime.now(timezone.utc),
            duration_ms=0,
            human_override=True,
            override_reason=normalized_reason,
        )
        self._append_result(gate_result)
        return gate_result

    def get_block_rate(self, agent_name: str, window: int = 100) -> float:
        """Return recent BLOCK/ESCALATE rate for one agent."""
        if window <= MIN_RATE_WINDOW:
            return 0.0
        records = [
            result for result in self.recent_results(agent_name, window) if not result.human_override
        ]
        if not records:
            return 0.0
        blocked_count = sum(
            1
            for result in records
            if result.decision in (GateDecision.BLOCK, GateDecision.ESCALATE)
        )
        return blocked_count / len(records)

    def recent_results(
        self,
        agent_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[GateResult]:
        """Return recent gate decisions filtered by agent when provided."""
        if limit <= MIN_RATE_WINDOW:
            return []
        records = [
            result
            for result in self._records()
            if agent_name is None or result.agent_name == agent_name
        ]
        return records[-limit:]

    def _policy(self, agent_name: str) -> GatePolicy:
        """Return the configured policy for an agent or the default policy."""
        return self.policies.get(agent_name) or self.policies[POLICY_DEFAULT]

    def _blocking_reasons(
        self,
        policy: GatePolicy,
        combined_score: CombinedScore,
        static_report: Optional[StaticAnalysisReport],
    ) -> List[str]:
        """Return blocking reasons from score and security checks."""
        reasons: List[str] = []
        if self._has_score_signal(combined_score) and (
            combined_score.combined_score < policy.min_combined_score
        ):
            reasons.append(
                REASON_LOW_SCORE_TEMPLATE.format(
                    score=combined_score.combined_score,
                    threshold=policy.min_combined_score,
                )
            )
        high_severity_count = self._high_security_count(static_report)
        if policy.block_on_security_high and high_severity_count > 0:
            reasons.append(
                REASON_SECURITY_HIGH_TEMPLATE.format(count=high_severity_count)
            )
        return reasons

    def _has_score_signal(self, combined_score: CombinedScore) -> bool:
        """Return whether a combined score has at least one real component."""
        return (
            combined_score.llm_score is not None
            or combined_score.static_score is not None
        )

    def _missing_signal_warnings(
        self,
        policy: GatePolicy,
        llm_evaluation: Optional[EvaluationResult],
        static_report: Optional[StaticAnalysisReport],
    ) -> List[str]:
        """Return warnings for required but unavailable quality signals."""
        warnings: List[str] = []
        if policy.require_llm_evaluation and llm_evaluation is None:
            warnings.append(WARNING_LLM_REQUIRED)
        if policy.require_static_analysis and static_report is None:
            warnings.append(WARNING_STATIC_REQUIRED)
        return warnings

    def _regression_report(
        self,
        policy: GatePolicy,
        agent_name: str,
        llm_evaluation: Optional[EvaluationResult],
        model_version: Optional[str],
        warnings: List[str],
    ) -> Optional[RegressionReport]:
        """Return a regression report when configured and possible."""
        if not policy.block_on_regression or llm_evaluation is None or not model_version:
            return None
        try:
            return self.regression_detector.check_regression(
                agent_name,
                llm_evaluation,
                model_version,
            )
        except Exception as error:
            warnings.append(WARNING_REGRESSION_FAILED_TEMPLATE.format(error=error))
            return None

    def _static_report(
        self,
        agent_result: AgentResult,
        file_path: Optional[Path],
    ) -> Optional[StaticAnalysisReport]:
        """Return static report from scorer analyzer or persisted metadata."""
        if file_path is not None:
            static_analyzer = getattr(self.quality_scorer, "static_analyzer", None)
            analyze = getattr(static_analyzer, "analyze", None)
            if callable(analyze):
                try:
                    return analyze(file_path)
                except Exception:
                    return None
        report_path = agent_result.metadata.get("static_report")
        if isinstance(report_path, str):
            return self._load_static_report(Path(report_path))
        return None

    def _load_static_report(self, report_path: Path) -> Optional[StaticAnalysisReport]:
        """Load a static report object from persisted metadata JSON."""
        if not report_path.exists():
            return None
        try:
            payload = json.loads(report_path.read_text(encoding=ENCODING))
            complexity = payload.get("complexity")
            security = payload.get("security")
            style = payload.get("style")
            if not isinstance(complexity, Mapping):
                complexity = {}
            if not isinstance(security, Mapping):
                security = {}
            if not isinstance(style, Mapping):
                style = {}
            return StaticAnalysisReport(
                file_path=str(payload["file_path"]),
                timestamp=datetime.fromisoformat(str(payload["timestamp"])),
                complexity=self._complexity_metrics(complexity),
                security=self._security_metrics(security),
                style=self._style_metrics(style),
                overall_quality_score=float(payload["overall_quality_score"]),
                passed_quality_gate=bool(payload["passed_quality_gate"]),
            )
        except Exception:
            return None

    def _complexity_metrics(self, payload: Mapping[str, Any]) -> ComplexityMetrics:
        """Deserialize complexity metrics from persisted JSON."""
        return ComplexityMetrics(
            file_path=str(payload.get("file_path", "")),
            avg_cyclomatic_complexity=float(
                payload.get("avg_cyclomatic_complexity", 0.0)
            ),
            max_cyclomatic_complexity=float(
                payload.get("max_cyclomatic_complexity", 0.0)
            ),
            maintainability_index=float(payload.get("maintainability_index", 0.0)),
            lines_of_code=int(payload.get("lines_of_code", 0)),
            comment_ratio=float(payload.get("comment_ratio", 0.0)),
            function_count=int(payload.get("function_count", 0)),
            class_count=int(payload.get("class_count", 0)),
        )

    def _security_metrics(self, payload: Mapping[str, Any]) -> SecurityMetrics:
        """Deserialize security metrics from persisted JSON."""
        issues = payload.get("issues")
        if not isinstance(issues, list):
            issues = []
        return SecurityMetrics(
            file_path=str(payload.get("file_path", "")),
            high_severity_count=int(payload.get("high_severity_count", 0)),
            medium_severity_count=int(payload.get("medium_severity_count", 0)),
            low_severity_count=int(payload.get("low_severity_count", 0)),
            issues=[dict(issue) for issue in issues if isinstance(issue, Mapping)],
            bandit_available=bool(payload.get("bandit_available", False)),
        )

    def _style_metrics(self, payload: Mapping[str, Any]) -> StyleMetrics:
        """Deserialize style metrics from persisted JSON."""
        violations = payload.get("violations")
        if not isinstance(violations, list):
            violations = []
        return StyleMetrics(
            file_path=str(payload.get("file_path", "")),
            violation_count=int(payload.get("violation_count", 0)),
            violations=[str(violation) for violation in violations],
            flake8_available=bool(payload.get("flake8_available", False)),
        )

    def _high_security_count(
        self,
        static_report: Optional[StaticAnalysisReport],
    ) -> int:
        """Return high severity security issue count from a static report."""
        if static_report is None:
            return 0
        return static_report.security.high_severity_count

    def _result(
        self,
        decision: GateDecision,
        agent_name: str,
        event_id: str,
        combined_score: Optional[float],
        blocking_reasons: List[str],
        warnings: List[str],
        policy: GatePolicy,
        started_at: float,
    ) -> GateResult:
        """Build a gate result with elapsed duration."""
        return GateResult(
            decision=decision,
            agent_name=agent_name,
            event_id=event_id,
            combined_score=combined_score,
            blocking_reasons=list(blocking_reasons),
            warnings=list(warnings),
            gate_policy=policy.agent_name,
            timestamp=datetime.now(timezone.utc),
            duration_ms=int((perf_counter() - started_at) * 1000),
        )

    def _fallback_event_id(self, agent_result: AgentResult) -> str:
        """Return a best-effort event identifier from an agent result."""
        if agent_result.next_events:
            next_event = agent_result.next_events[0]
            return next_event.correlation_id or next_event.event_id
        return "unknown"

    def _latest_blocked_result(self, event_id: str) -> Optional[GateResult]:
        """Return the latest blocked or escalated result for an event."""
        for result in reversed(self._records()):
            if result.event_id != event_id:
                continue
            if result.decision in (GateDecision.BLOCK, GateDecision.ESCALATE):
                return result
        return None

    def _append_result(self, result: GateResult) -> None:
        """Append one gate result to the JSONL gate log."""
        self.gate_log_path.parent.mkdir(parents=True, exist_ok=True)
        encoded_line = (
            json.dumps(self._serialize(result), sort_keys=True, default=str)
            + NEWLINE
        ).encode(ENCODING)
        file_descriptor = os.open(
            self.gate_log_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o644,
        )
        try:
            os.write(file_descriptor, encoded_line)
        finally:
            os.close(file_descriptor)

    def _records(self) -> List[GateResult]:
        """Read gate JSONL records, skipping malformed lines."""
        if not self.gate_log_path.exists():
            return []
        results: List[GateResult] = []
        for line in self.gate_log_path.read_text(encoding=ENCODING).splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                results.append(self._deserialize(payload))
            except Exception as error:
                self._logger.warning("Skipped malformed gate decision: %s", error)
        return results

    def _serialize(self, result: GateResult) -> Dict[str, Any]:
        """Serialize a gate result to JSON-safe values."""
        payload = asdict(result)
        payload[FIELD_DECISION] = result.decision.value
        payload[FIELD_TIMESTAMP] = result.timestamp.isoformat()
        return payload

    def _deserialize(self, payload: Mapping[str, Any]) -> GateResult:
        """Deserialize one JSON mapping into a GateResult."""
        blocking_reasons = payload.get(FIELD_BLOCKING_REASONS)
        warnings = payload.get(FIELD_WARNINGS)
        if not isinstance(blocking_reasons, list):
            blocking_reasons = []
        if not isinstance(warnings, list):
            warnings = []
        score = payload.get(FIELD_COMBINED_SCORE)
        return GateResult(
            decision=GateDecision(str(payload[FIELD_DECISION])),
            agent_name=str(payload[FIELD_AGENT_NAME]),
            event_id=str(payload[FIELD_EVENT_ID]),
            combined_score=self._optional_float(score),
            blocking_reasons=[str(item) for item in blocking_reasons],
            warnings=[str(item) for item in warnings],
            gate_policy=str(payload[FIELD_GATE_POLICY]),
            timestamp=datetime.fromisoformat(str(payload[FIELD_TIMESTAMP])),
            duration_ms=int(payload.get(FIELD_DURATION_MS, 0)),
            human_override=bool(payload.get(FIELD_HUMAN_OVERRIDE, False)),
            override_reason=self._optional_string(payload.get(FIELD_OVERRIDE_REASON)),
        )

    def _optional_float(self, value: Any) -> Optional[float]:
        """Return a float or None."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _optional_string(self, value: Any) -> Optional[str]:
        """Return a string or None."""
        if value is None:
            return None
        return str(value)


DEFAULT_POLICIES = {
    POLICY_CODE_WRITING: GatePolicy(
        agent_name=POLICY_CODE_WRITING,
        min_combined_score=0.65,
        require_llm_evaluation=True,
        require_static_analysis=True,
        block_on_security_high=True,
        block_on_regression=True,
    ),
    POLICY_CODE_REVIEW: GatePolicy(
        agent_name=POLICY_CODE_REVIEW,
        min_combined_score=0.70,
        require_llm_evaluation=True,
        require_static_analysis=False,
        block_on_security_high=False,
        block_on_regression=True,
    ),
    POLICY_PLANNING: GatePolicy(
        agent_name=POLICY_PLANNING,
        min_combined_score=0.60,
        require_llm_evaluation=True,
        require_static_analysis=False,
        block_on_security_high=False,
        block_on_regression=False,
    ),
    POLICY_DEFAULT: GatePolicy(
        agent_name=POLICY_DEFAULT,
        min_combined_score=0.50,
        require_llm_evaluation=False,
        require_static_analysis=False,
        block_on_security_high=True,
        block_on_regression=False,
    ),
}


__all__ = [
    "DEFAULT_POLICIES",
    "GATE_LOG_NAME",
    "GateDecision",
    "GatePolicy",
    "GateResult",
    "QualityGate",
]
