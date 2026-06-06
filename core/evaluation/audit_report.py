"""Human-readable audit reports for ProjectOS evaluation decisions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.quality_gate import GateDecision


ENCODING = "utf-8"
NEWLINE = "\n"
EVALUATOR_NAME_LLM_JUDGE = "llm_judge"
DECISION_PASS = GateDecision.PASS.value
DECISION_BLOCK = GateDecision.BLOCK.value
DECISION_ESCALATE = GateDecision.ESCALATE.value
DECISION_BYPASS = GateDecision.BYPASS.value
REGRESSION_MARKER = "regression detected"

FIELD_AGENT_NAME = "agent_name"
FIELD_TIMESTAMP = "timestamp"
FIELD_WEIGHTED_SCORE = "weighted_score"
FIELD_PASSED = "passed"
FIELD_DECISION = "decision"
FIELD_COMBINED_SCORE = "combined_score"
FIELD_BLOCKING_REASONS = "blocking_reasons"
FIELD_HUMAN_OVERRIDE = "human_override"
FIELD_OVERRIDE_REASON = "override_reason"
FIELD_RECOMMENDATION = "recommendation"

REPORT_TITLE = "# ProjectOS Quality Audit Report"
SUMMARY_HEADING = "## Summary"
PER_AGENT_HEADING = "## Per-Agent Quality Scores"
GATE_DECISIONS_HEADING = "## Quality Gate Decisions"
REGRESSIONS_HEADING = "## Regressions Detected"
OVERRIDES_HEADING = "## Human Overrides"
RECOMMENDATIONS_HEADING = "## Recommendations"
NO_ITEMS = "- None"

LOW_SCORE_THRESHOLD = 0.65
HIGH_BLOCK_RATE_THRESHOLD = 0.15
UNRESOLVED_REGRESSION_HOURS = 24
HOURS_PER_DAY = 24
SECONDS_PER_HOUR = 3600
PERCENT_MULTIPLIER = 100.0
GATE_DECISION_LIMIT = 50


@dataclass(frozen=True)
class EvaluationRecord:
    """One persisted evaluation record used by audit reports."""

    timestamp: datetime
    agent_name: str
    weighted_score: float
    passed: bool


@dataclass(frozen=True)
class GateRecord:
    """One persisted quality gate record used by audit reports."""

    timestamp: datetime
    agent_name: str
    decision: str
    combined_score: Optional[float]
    blocking_reasons: list[str]
    human_override: bool
    override_reason: Optional[str]


class EvaluationAuditReport:
    """
    Generates human-readable audit reports covering all quality
    decisions made by ProjectOS over a time window.
    """

    def __init__(
        self,
        evaluation_store: EvaluationStore,
        gate_log_path: Path,
        decision_log_path: Path,
    ) -> None:
        """Initialize audit report data sources."""
        self.evaluation_store = evaluation_store
        self.gate_log_path = Path(gate_log_path)
        self.decision_log_path = Path(decision_log_path)

    def generate(
        self,
        since: datetime,
        until: Optional[datetime] = None,
        agent_filter: Optional[str] = None,
    ) -> str:
        """Return a markdown audit report for the requested time window."""
        normalized_until = until or datetime.now(timezone.utc)
        evaluations = self._filtered_evaluations(since, normalized_until, agent_filter)
        gate_records = self._filtered_gate_records(since, normalized_until, agent_filter)
        agents = self._agents(evaluations, gate_records)
        lines = [
            REPORT_TITLE,
            f"Period: {since.isoformat()} to {normalized_until.isoformat()}",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
        ]
        lines.extend(self._summary_lines(evaluations, gate_records, agents))
        lines.extend(self._per_agent_lines(evaluations, gate_records, agents))
        lines.extend(self._gate_decision_lines(gate_records))
        lines.extend(self._regression_lines(gate_records))
        lines.extend(self._override_lines(gate_records))
        lines.extend(self._recommendation_lines(evaluations, gate_records, agents, normalized_until))
        return NEWLINE.join(lines).rstrip() + NEWLINE

    def _filtered_evaluations(
        self,
        since: datetime,
        until: datetime,
        agent_filter: Optional[str],
    ) -> list[EvaluationRecord]:
        """Return evaluation records matching the report filters."""
        return [
            record
            for record in self._evaluation_records()
            if since <= record.timestamp <= until
            and (agent_filter is None or record.agent_name == agent_filter)
        ]

    def _filtered_gate_records(
        self,
        since: datetime,
        until: datetime,
        agent_filter: Optional[str],
    ) -> list[GateRecord]:
        """Return gate records matching the report filters."""
        return [
            record
            for record in self._gate_records()
            if since <= record.timestamp <= until
            and (agent_filter is None or record.agent_name == agent_filter)
        ]

    def _evaluation_records(self) -> list[EvaluationRecord]:
        """Read evaluation JSONL records from the evaluation store."""
        evaluations_path = self.evaluation_store.evaluations_path
        if not evaluations_path.exists():
            return []
        records: list[EvaluationRecord] = []
        for line in evaluations_path.read_text(encoding=ENCODING).splitlines():
            payload = self._json_payload(line)
            if payload is None:
                continue
            record = self._evaluation_record(payload)
            if record is not None:
                records.append(record)
        return records

    def _gate_records(self) -> list[GateRecord]:
        """Read gate JSONL records from the gate log."""
        if not self.gate_log_path.exists():
            return []
        records: list[GateRecord] = []
        for line in self.gate_log_path.read_text(encoding=ENCODING).splitlines():
            payload = self._json_payload(line)
            if payload is None:
                continue
            record = self._gate_record(payload)
            if record is not None:
                records.append(record)
        return records

    def _evaluation_record(self, payload: Mapping[str, Any]) -> Optional[EvaluationRecord]:
        """Convert one evaluation JSON payload into an audit record."""
        try:
            return EvaluationRecord(
                timestamp=datetime.fromisoformat(str(payload[FIELD_TIMESTAMP])),
                agent_name=str(payload[FIELD_AGENT_NAME]),
                weighted_score=float(payload[FIELD_WEIGHTED_SCORE]),
                passed=bool(payload[FIELD_PASSED]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _gate_record(self, payload: Mapping[str, Any]) -> Optional[GateRecord]:
        """Convert one gate JSON payload into an audit record."""
        try:
            blocking_reasons = payload.get(FIELD_BLOCKING_REASONS)
            if not isinstance(blocking_reasons, list):
                blocking_reasons = []
            return GateRecord(
                timestamp=datetime.fromisoformat(str(payload[FIELD_TIMESTAMP])),
                agent_name=str(payload[FIELD_AGENT_NAME]),
                decision=str(payload[FIELD_DECISION]),
                combined_score=self._optional_float(payload.get(FIELD_COMBINED_SCORE)),
                blocking_reasons=[str(item) for item in blocking_reasons],
                human_override=bool(payload.get(FIELD_HUMAN_OVERRIDE, False)),
                override_reason=self._optional_string(payload.get(FIELD_OVERRIDE_REASON)),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _summary_lines(
        self,
        evaluations: list[EvaluationRecord],
        gate_records: list[GateRecord],
        agents: list[str],
    ) -> list[str]:
        """Return the report summary section."""
        return [
            SUMMARY_HEADING,
            f"- Total evaluations: {len(evaluations)}",
            f"- Pass rate: {self._pass_rate(evaluations):.1f}%",
            f"- Block rate: {self._block_rate(gate_records):.1f}%",
            f"- Override rate: {self._override_rate(gate_records):.1f}%",
            f"- Agents evaluated: {', '.join(agents) if agents else 'none'}",
            "",
        ]

    def _per_agent_lines(
        self,
        evaluations: list[EvaluationRecord],
        gate_records: list[GateRecord],
        agents: list[str],
    ) -> list[str]:
        """Return the per-agent score table section."""
        lines = [
            PER_AGENT_HEADING,
            "| agent | avg_score | evaluations | regressions | blocks |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        if not agents:
            lines.append("| none | -- | 0 | 0 | 0 |")
        for agent_name in agents:
            agent_evaluations = [
                record for record in evaluations if record.agent_name == agent_name
            ]
            agent_gate_records = [
                record for record in gate_records if record.agent_name == agent_name
            ]
            lines.append(
                "| {agent} | {avg_score} | {evaluations} | {regressions} | {blocks} |".format(
                    agent=agent_name,
                    avg_score=self._score_text(self._average_score(agent_evaluations)),
                    evaluations=len(agent_evaluations),
                    regressions=len(self._regression_records(agent_gate_records)),
                    blocks=len(self._blocked_records(agent_gate_records)),
                )
            )
        lines.append("")
        return lines

    def _gate_decision_lines(self, gate_records: list[GateRecord]) -> list[str]:
        """Return the quality gate decision table section."""
        lines = [
            GATE_DECISIONS_HEADING,
            "| timestamp | agent | decision | score | blocking_reason |",
            "| --- | --- | --- | ---: | --- |",
        ]
        selected_records = gate_records[-GATE_DECISION_LIMIT:]
        if not selected_records:
            lines.append("| none | none | none | -- | none |")
        for record in selected_records:
            lines.append(
                "| {timestamp} | {agent} | {decision} | {score} | {reason} |".format(
                    timestamp=record.timestamp.isoformat(),
                    agent=record.agent_name,
                    decision=record.decision,
                    score=self._score_text(record.combined_score),
                    reason=self._reason_text(record),
                )
            )
        lines.append("")
        return lines

    def _regression_lines(self, gate_records: list[GateRecord]) -> list[str]:
        """Return the regressions section."""
        lines = [REGRESSIONS_HEADING]
        regression_records = self._regression_records(gate_records)
        if not regression_records:
            lines.extend([NO_ITEMS, ""])
            return lines
        for record in regression_records:
            lines.append(
                "- {timestamp} {agent}: {reason}".format(
                    timestamp=record.timestamp.isoformat(),
                    agent=record.agent_name,
                    reason=self._reason_text(record),
                )
            )
        lines.append("")
        return lines

    def _override_lines(self, gate_records: list[GateRecord]) -> list[str]:
        """Return the human overrides section."""
        lines = [OVERRIDES_HEADING]
        overrides = [record for record in gate_records if record.human_override]
        if not overrides:
            lines.extend([NO_ITEMS, ""])
            return lines
        for record in overrides:
            lines.append(
                "- {timestamp} {agent}: {reason}".format(
                    timestamp=record.timestamp.isoformat(),
                    agent=record.agent_name,
                    reason=record.override_reason or "no reason provided",
                )
            )
        lines.append("")
        return lines

    def _recommendation_lines(
        self,
        evaluations: list[EvaluationRecord],
        gate_records: list[GateRecord],
        agents: list[str],
        until: datetime,
    ) -> list[str]:
        """Return actionable audit recommendations."""
        recommendations: list[str] = []
        for agent_name in agents:
            agent_evaluations = [
                record for record in evaluations if record.agent_name == agent_name
            ]
            agent_gate_records = [
                record for record in gate_records if record.agent_name == agent_name
            ]
            avg_score = self._average_score(agent_evaluations)
            if avg_score is not None and avg_score < LOW_SCORE_THRESHOLD:
                recommendations.append(f"- Review model/prompt for {agent_name}")
            if self._block_rate(agent_gate_records) > HIGH_BLOCK_RATE_THRESHOLD * PERCENT_MULTIPLIER:
                recommendations.append("- Gate policy may be too strict")
            if self._has_unresolved_regression(agent_gate_records, until):
                recommendations.append(f"- Investigate {agent_name} degradation")
        if not recommendations:
            recommendations = [NO_ITEMS]
        return [RECOMMENDATIONS_HEADING, *recommendations, ""]

    def _has_unresolved_regression(
        self,
        gate_records: list[GateRecord],
        until: datetime,
    ) -> bool:
        """Return whether an old regression lacks a later override."""
        overrides = [record for record in gate_records if record.human_override]
        latest_override = max((record.timestamp for record in overrides), default=None)
        for regression in self._regression_records(gate_records):
            if latest_override is not None and latest_override > regression.timestamp:
                continue
            age_seconds = (until - regression.timestamp).total_seconds()
            if age_seconds > UNRESOLVED_REGRESSION_HOURS * SECONDS_PER_HOUR:
                return True
        return False

    def _agents(
        self,
        evaluations: list[EvaluationRecord],
        gate_records: list[GateRecord],
    ) -> list[str]:
        """Return sorted agent names represented in the report."""
        names = {record.agent_name for record in evaluations}
        names.update(record.agent_name for record in gate_records)
        return sorted(name for name in names if name)

    def _pass_rate(self, evaluations: list[EvaluationRecord]) -> float:
        """Return evaluation pass rate as a percentage."""
        if not evaluations:
            return 0.0
        passed = sum(1 for record in evaluations if record.passed)
        return (passed / len(evaluations)) * PERCENT_MULTIPLIER

    def _block_rate(self, gate_records: list[GateRecord]) -> float:
        """Return gate block rate as a percentage."""
        candidates = [record for record in gate_records if not record.human_override]
        if not candidates:
            return 0.0
        blocked = len(self._blocked_records(candidates))
        return (blocked / len(candidates)) * PERCENT_MULTIPLIER

    def _override_rate(self, gate_records: list[GateRecord]) -> float:
        """Return gate override rate as a percentage."""
        if not gate_records:
            return 0.0
        overrides = sum(1 for record in gate_records if record.human_override)
        return (overrides / len(gate_records)) * PERCENT_MULTIPLIER

    def _blocked_records(self, gate_records: list[GateRecord]) -> list[GateRecord]:
        """Return gate records that blocked or escalated."""
        return [
            record
            for record in gate_records
            if record.decision in (DECISION_BLOCK, DECISION_ESCALATE)
        ]

    def _regression_records(self, gate_records: list[GateRecord]) -> list[GateRecord]:
        """Return gate records that represent regressions."""
        return [
            record
            for record in gate_records
            if any(REGRESSION_MARKER in reason.lower() for reason in record.blocking_reasons)
        ]

    def _average_score(self, evaluations: list[EvaluationRecord]) -> Optional[float]:
        """Return average score for evaluation records."""
        if not evaluations:
            return None
        return sum(record.weighted_score for record in evaluations) / len(evaluations)

    def _reason_text(self, record: GateRecord) -> str:
        """Return compact blocking reason text for a gate record."""
        if not record.blocking_reasons:
            return "none"
        return ", ".join(reason.replace("|", "/") for reason in record.blocking_reasons)

    def _score_text(self, score: Optional[float]) -> str:
        """Return display text for an optional score."""
        if score is None:
            return "--"
        return f"{score:.2f}"

    def _json_payload(self, line: str) -> Optional[Mapping[str, Any]]:
        """Parse one JSONL line into a mapping."""
        if not line.strip():
            return None
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, Mapping) else None

    def _optional_float(self, value: Any) -> Optional[float]:
        """Return a float or None."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _optional_string(self, value: Any) -> Optional[str]:
        """Return a non-empty string or None."""
        if isinstance(value, str) and value:
            return value
        return None


__all__ = ["EvaluationAuditReport"]
