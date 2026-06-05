# TASK_13: JSONL Decision Logging

## Problem
decisions.log is markdown text. Clone cannot audit its own 
history programmatically. No machine-readable audit trail exists.

## Pre-conditions
Read core/clone_agent.py and decisions.log format fully.

## Deliverables

### 1. core/decision_log.py

class DecisionLogger:
  __init__(log_dir: Path)
  
  log(
    event_id: str,
    correlation_id: Optional[str],
    agent_name: str,
    decision_category: str,
    reasoning: str,
    outcome: str,
    escalated: bool = False,
    duration_ms: Optional[int] = None
  ) -> None
  
  Writes one JSON line to decisions.jsonl:
  {
    "timestamp": "ISO8601",
    "event_id": "...",
    "correlation_id": "...",
    "agent_name": "...",
    "decision_category": "AUTONOMOUS|ESCALATE|DEFER_PARALLEL",
    "reasoning": "...",
    "outcome": "...",
    "escalated": false,
    "duration_ms": 42
  }
  Write is atomic. Appends only. Never overwrites.
  
  query(
    agent_name: Optional[str] = None,
    decision_category: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 100
  ) -> List[Dict]
  Reads decisions.jsonl, filters by params, returns last N matches.
  
  summary() -> Dict
  Returns:
  {
    "total_decisions": int,
    "by_category": {"AUTONOMOUS": N, "ESCALATE": N, "DEFER": N},
    "by_agent": {"clone": N, "planning": N, ...},
    "escalation_rate": float
  }

### 2. Update core/clone_agent.py
  Add DecisionLogger alongside existing decisions.log writer.
  Every log_decision() call writes to both files.
  Keep existing markdown log — do not remove it.
  Add duration_ms: measure time from event receipt to result return.

### 3. New CLI command: projectos decisions
  projectos decisions --tail 20
    Shows last 20 decisions from decisions.jsonl in formatted table.
  
  projectos decisions --summary
    Shows summary dict as formatted output.
  
  projectos decisions --agent clone --tail 10
    Filter by agent.

### 4. tests/test_decision_log.py
  - test_log_writes_valid_jsonl
  - test_each_line_is_valid_json
  - test_append_only_never_overwrites
  - test_query_filters_by_agent
  - test_query_filters_by_category
  - test_query_respects_limit
  - test_summary_counts_correctly
  - test_malformed_line_skipped_in_query

## Constraints
- decisions.jsonl is append-only always
- query() never raises on malformed lines
- duration_ms is optional (None if not measured)
- No new dependencies

## Verification
Full test suite. Write TASK_13_RESULT.md. Update tasks/README.md.
