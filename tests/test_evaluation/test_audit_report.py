"""Tests for human-readable evaluation audit reports."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.evaluation.audit_report import EvaluationAuditReport
from core.evaluation.base_evaluator import EvaluationResult
from core.evaluation.evaluation_store import EvaluationStore


AGENT_NAME = "code_writing"
OTHER_AGENT = "planning"
EVALUATOR_NAME = "llm_judge"
EVENT_ID = "event-1"
MODEL_VERSION = "model-v1"
REASONING = "reasoning"
RAW_SAMPLE = "raw"
GATE_LOG_NAME = "gate_decisions.jsonl"
DECISIONS_LOG_NAME = "decisions.log"


def test_audit_report_renders_summary_and_tables(tmp_path: Path) -> None:
    """Verify audit reports include summary, scores, and gate decisions."""
    store = EvaluationStore(tmp_path)
    store.save(_evaluation(0.9, AGENT_NAME, passed=True))
    _write_gate(
        tmp_path / GATE_LOG_NAME,
        AGENT_NAME,
        "PASS",
        0.9,
        [],
    )
    report = _report(tmp_path, store).generate(_since())

    assert "# ProjectOS Quality Audit Report" in report
    assert "Total evaluations: 1" in report
    assert "| code_writing | 0.90 | 1 | 0 | 0 |" in report
    assert "| PASS | 0.90 | none |" in report


def test_audit_report_filters_agent(tmp_path: Path) -> None:
    """Verify agent_filter excludes other agents."""
    store = EvaluationStore(tmp_path)
    store.save(_evaluation(0.9, AGENT_NAME, passed=True))
    store.save(_evaluation(0.8, OTHER_AGENT, passed=True))
    _write_gate(tmp_path / GATE_LOG_NAME, AGENT_NAME, "PASS", 0.9, [])
    _write_gate(tmp_path / GATE_LOG_NAME, OTHER_AGENT, "PASS", 0.8, [])

    report = _report(tmp_path, store).generate(_since(), agent_filter=AGENT_NAME)

    assert "code_writing" in report
    assert "planning" not in report


def test_audit_report_lists_regressions_and_overrides(tmp_path: Path) -> None:
    """Verify regressions and human overrides are rendered."""
    store = EvaluationStore(tmp_path)
    store.save(_evaluation(0.6, AGENT_NAME, passed=False))
    _write_gate(
        tmp_path / GATE_LOG_NAME,
        AGENT_NAME,
        "ESCALATE",
        0.6,
        ["regression detected: Quality dropped 20.0%."],
    )
    _write_gate(
        tmp_path / GATE_LOG_NAME,
        AGENT_NAME,
        "BYPASS",
        0.6,
        [],
        human_override=True,
        override_reason="manual approval",
    )

    report = _report(tmp_path, store).generate(_since())

    assert "## Regressions Detected" in report
    assert "Quality dropped" in report
    assert "## Human Overrides" in report
    assert "manual approval" in report


def test_audit_report_recommends_low_score_and_high_block_rate(tmp_path: Path) -> None:
    """Verify low-score and high-block-rate recommendations."""
    store = EvaluationStore(tmp_path)
    store.save(_evaluation(0.5, AGENT_NAME, passed=False))
    _write_gate(
        tmp_path / GATE_LOG_NAME,
        AGENT_NAME,
        "BLOCK",
        0.5,
        ["combined score 0.50 below threshold 0.65"],
    )

    report = _report(tmp_path, store).generate(_since())

    assert "Review model/prompt for code_writing" in report
    assert "Gate policy may be too strict" in report


def _report(tmp_path: Path, store: EvaluationStore) -> EvaluationAuditReport:
    """Return an audit report bound to temporary state files."""
    return EvaluationAuditReport(
        store,
        tmp_path / GATE_LOG_NAME,
        tmp_path / DECISIONS_LOG_NAME,
    )


def _evaluation(score: float, agent_name: str, passed: bool) -> EvaluationResult:
    """Return a persisted evaluation test record."""
    return EvaluationResult(
        evaluator_name=EVALUATOR_NAME,
        agent_name=agent_name,
        event_id=EVENT_ID,
        timestamp=datetime.now(timezone.utc),
        criteria_scores={"score": score},
        weighted_score=score,
        passed=passed,
        reasoning=REASONING,
        raw_output_sample=RAW_SAMPLE,
        evaluation_duration_ms=1,
        evaluator_model=MODEL_VERSION,
        metadata={},
    )


def _write_gate(
    path: Path,
    agent_name: str,
    decision: str,
    score: float,
    reasons: list[str],
    human_override: bool = False,
    override_reason: str | None = None,
) -> None:
    """Append one gate record to a test JSONL file."""
    payload = {
        "agent_name": agent_name,
        "blocking_reasons": reasons,
        "combined_score": score,
        "decision": decision,
        "duration_ms": 1,
        "event_id": EVENT_ID,
        "gate_policy": agent_name,
        "human_override": human_override,
        "override_reason": override_reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "warnings": [],
    }
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing + json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _since() -> datetime:
    """Return a timestamp before generated test records."""
    return datetime.now(timezone.utc) - timedelta(days=1)
