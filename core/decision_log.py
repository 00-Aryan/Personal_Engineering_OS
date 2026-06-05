"""Machine-readable Clone decision logging for ProjectOS."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


ENCODING = "utf-8"
DECISIONS_JSONL_NAME = "decisions.jsonl"
LOGGER_NAME = "projectos.decision_log"

FIELD_TIMESTAMP = "timestamp"
FIELD_EVENT_ID = "event_id"
FIELD_CORRELATION_ID = "correlation_id"
FIELD_AGENT_NAME = "agent_name"
FIELD_DECISION_CATEGORY = "decision_category"
FIELD_REASONING = "reasoning"
FIELD_OUTCOME = "outcome"
FIELD_ESCALATED = "escalated"
FIELD_DURATION_MS = "duration_ms"

CATEGORY_AUTONOMOUS = "AUTONOMOUS"
CATEGORY_ESCALATE = "ESCALATE"
CATEGORY_DEFER = "DEFER"
CATEGORY_DEFER_PARALLEL = "DEFER_PARALLEL"


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class DecisionLogger:
    """Append and query machine-readable Clone decision records."""

    def __init__(self, log_dir: Path) -> None:
        """Initialize the JSONL decision log path."""
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / DECISIONS_JSONL_NAME
        self._logger = logging.getLogger(LOGGER_NAME)

    def log(
        self,
        event_id: str,
        correlation_id: Optional[str],
        agent_name: str,
        decision_category: str,
        reasoning: str,
        outcome: str,
        escalated: bool = False,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Append one decision as a JSON line."""
        record = {
            FIELD_TIMESTAMP: _utc_timestamp(),
            FIELD_EVENT_ID: event_id,
            FIELD_CORRELATION_ID: correlation_id,
            FIELD_AGENT_NAME: agent_name,
            FIELD_DECISION_CATEGORY: decision_category,
            FIELD_REASONING: reasoning,
            FIELD_OUTCOME: outcome,
            FIELD_ESCALATED: escalated,
            FIELD_DURATION_MS: duration_ms,
        }
        self._append_json_line(record)

    def query(
        self,
        agent_name: Optional[str] = None,
        decision_category: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return recent decisions filtered by agent, category, and timestamp."""
        if limit <= 0:
            return []
        matches = [
            record
            for record in self._records()
            if self._matches(record, agent_name, decision_category, since)
        ]
        return matches[-limit:]

    def summary(self) -> Dict[str, Any]:
        """Return aggregate counts for all JSONL decision records."""
        records = self._records()
        by_category = {
            CATEGORY_AUTONOMOUS: 0,
            CATEGORY_ESCALATE: 0,
            CATEGORY_DEFER: 0,
        }
        by_agent: Dict[str, int] = {}
        escalated_count = 0

        for record in records:
            category = str(record.get(FIELD_DECISION_CATEGORY, ""))
            summary_category = self._summary_category(category)
            by_category[summary_category] = by_category.get(summary_category, 0) + 1
            agent_name = str(record.get(FIELD_AGENT_NAME, "unknown"))
            by_agent[agent_name] = by_agent.get(agent_name, 0) + 1
            if bool(record.get(FIELD_ESCALATED)) or category == CATEGORY_ESCALATE:
                escalated_count += 1

        total_decisions = len(records)
        escalation_rate = (
            escalated_count / total_decisions if total_decisions else 0.0
        )
        return {
            "total_decisions": total_decisions,
            "by_category": by_category,
            "by_agent": by_agent,
            "escalation_rate": escalation_rate,
        }

    def _append_json_line(self, record: Mapping[str, Any]) -> None:
        """Append one JSON line with OS append semantics."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        encoded_line = (
            json.dumps(record, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode(ENCODING)
        file_descriptor = os.open(
            self.log_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o644,
        )
        try:
            os.write(file_descriptor, encoded_line)
        finally:
            os.close(file_descriptor)

    def _records(self) -> List[Dict[str, Any]]:
        """Read valid JSONL records, skipping malformed lines."""
        if not self.log_path.exists():
            return []
        records: List[Dict[str, Any]] = []
        for line in self.log_path.read_text(encoding=ENCODING).splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                self._logger.warning("Skipped malformed decision line: %s", error)
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def _matches(
        self,
        record: Mapping[str, Any],
        agent_name: Optional[str],
        decision_category: Optional[str],
        since: Optional[datetime],
    ) -> bool:
        """Return whether a record matches query filters."""
        if agent_name is not None and record.get(FIELD_AGENT_NAME) != agent_name:
            return False
        if (
            decision_category is not None
            and record.get(FIELD_DECISION_CATEGORY) != decision_category
        ):
            return False
        if since is not None and not self._is_since(record, since):
            return False
        return True

    def _is_since(self, record: Mapping[str, Any], since: datetime) -> bool:
        """Return whether a record timestamp is on or after a lower bound."""
        timestamp = record.get(FIELD_TIMESTAMP)
        if not isinstance(timestamp, str):
            return False
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            return False
        return parsed_timestamp >= since

    def _summary_category(self, decision_category: str) -> str:
        """Normalize a decision category for summary buckets."""
        if decision_category == CATEGORY_DEFER_PARALLEL:
            return CATEGORY_DEFER
        if decision_category in (CATEGORY_AUTONOMOUS, CATEGORY_ESCALATE):
            return decision_category
        return decision_category or "UNKNOWN"


__all__ = ["DecisionLogger"]
