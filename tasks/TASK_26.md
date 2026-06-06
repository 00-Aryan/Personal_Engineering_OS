# TASK_26: Phase 3 Integration + Evaluation Audit Trail

## Engineering Context
Phase 3 added 5 interconnected components:
  TASK_21: LLM-as-Judge + EvaluationStore
  TASK_22: Schema validation + Regression detection
  TASK_23: Static code analysis + Quality scoring
  TASK_24: Quality gate enforcement
  TASK_25: CI benchmark pipeline + Dashboard quality panel

This final task integrates all Phase 3 components into a coherent
system, verifies the full evaluation pipeline end-to-end, adds a
human-readable audit trail for all quality decisions, and updates
all documentation to reflect the new capabilities.

This mirrors what TASK_09 did for Phase 2 (integration) and
what TASK_10 did for v1 (documentation + smoke test).

## Pre-conditions
Read ALL files in core/evaluation/ before writing any code.
Read TASK_21 through TASK_25 result files for known gaps.
Run full test suite first and report current count before changes.

## Deliverables

### 1. Integration smoke test — scripts/evaluation_smoke.py

Full end-to-end evaluation pipeline test using mocked providers.

Steps in order:
1. Initialize EvaluationStore, SchemaValidator, RegressionDetector
2. Initialize StaticAnalyzer
3. Initialize QualityScorer(llm_weight=0.6, static_weight=0.4)
4. Initialize QualityGate with DEFAULT_POLICIES
5. Initialize LLMJudge with mocked provider returning valid score JSON

Scenario A — Clean code path:
  Simulate CodeWritingAgent producing a valid, clean Python function
  Run through full gate: schema → LLM judge → static → gate decision
  Assert: GateDecision.PASS
  Assert: EvaluationResult stored in EvaluationStore
  Assert: decisions.log has gate entry

Scenario B — Bad code path:
  Simulate CodeWritingAgent producing code with syntax error
  Run through full gate
  Assert: GateDecision.BLOCK
  Assert: blocking_reasons is non-empty
  Assert: escalation_queue.md has entry

Scenario C — Regression path:
  Seed EvaluationStore with 10 passing evaluations at score 0.85
  Submit evaluation at score 0.65 (below 10% tolerance of 0.85)
  Assert: RegressionReport.regression_detected is True
  Assert: GateDecision is ESCALATE

Scenario D — Human override:
  Block an evaluation (Scenario B)
  Call gate.override(event_id, reason="manually reviewed, safe to ship")
  Assert: GateResult.decision == GateDecision.BYPASS
  Assert: override logged to gate_decisions.jsonl

Print EVALUATION SMOKE: PASSED or EVALUATION SMOKE: FAILED with reason.
Exit code 0 or 1.

### 2. core/evaluation/audit_report.py

class EvaluationAuditReport:
  """
  Generates human-readable audit reports covering all quality
  decisions made by ProjectOS over a time window.
  """
  
  __init__(
    evaluation_store: EvaluationStore,
    gate_log_path: Path,
    decision_log_path: Path
  )
  
  generate(
    since: datetime,
    until: Optional[datetime] = None,
    agent_filter: Optional[str] = None
  ) -> str:
    Returns markdown report containing:
    
    # ProjectOS Quality Audit Report
    Period: [since] to [until]
    Generated: [now]
    
    ## Summary
    - Total evaluations: N
    - Pass rate: X%
    - Block rate: X%
    - Override rate: X%
    - Agents evaluated: list
    
    ## Per-Agent Quality Scores
    Table: agent | avg_score | evaluations | regressions | blocks
    
    ## Quality Gate Decisions
    Table: timestamp | agent | decision | score | blocking_reason
    (last 50 decisions or filtered window)
    
    ## Regressions Detected
    List of regression events with delta and recommendation
    
    ## Human Overrides
    List of override events with reason
    
    ## Recommendations
    Agents with avg_score < 0.65 → "Review model/prompt for [agent]"
    Agents with block_rate > 15% → "Gate policy may be too strict"
    Any regression unresolved > 24h → "Investigate [agent] degradation"

### 3. New CLI command: projectos audit
  projectos audit --days 7
    Generates EvaluationAuditReport for last 7 days.
    Prints to terminal with Rich formatting.
  
  projectos audit --save report.md
    Writes report to file.
  
  projectos audit --agent code_writing --days 30
    Filtered audit for one agent.

### 4. Update README.md
  Add Phase 3 section:
  - Evaluation & Quality overview (one paragraph)
  - Quality pipeline diagram (ASCII):
    Agent Output → Schema Validation → LLM Judge → Static Analysis
                                                          ↓
                              File Written ← Quality Gate (PASS/BLOCK)
  - How to view quality metrics: projectos quality status
  - How to run benchmark: projectos benchmark run
  - How to generate audit report: projectos audit --days 7
  - Gate policy configuration reference

### 5. Update docs/architecture/SYSTEM_OVERVIEW.md
  Add Phase 3 section:
  - Evaluation subsystem component diagram
  - How quality gate integrates with Clone Agent dispatch
  - Evaluation data flow
  - Baseline versioning strategy

### 6. Final test run and count
  UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 
  uv run --no-sync pytest -v
  Report final total.

### 7. Write TASK_26_RESULT.md
  - Total files in core/evaluation/
  - Final test count
  - Evaluation smoke test result
  - Phase 3 components and their integration status
  - Known limitations
  - Phase 4 (Agent Intelligence) prerequisites
  - One paragraph: what Phase 3 enables that was impossible before

### 8. Update tasks/README.md
  Mark TASK_26 DONE.
  Add section: Phase 4 — Agent Intelligence (TASK_27-32, PENDING)
