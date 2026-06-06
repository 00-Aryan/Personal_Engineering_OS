# TASK_24: Quality Gate Enforcement Layer

## Engineering Context
TASK_21-23 built measurement tools. This task builds the enforcement
layer — the component that sits between agent output and file writes,
making go/no-go decisions based on quality signals.

This is the most architecturally important task in Phase 3.
A quality gate that blocks too much → system becomes useless.
A quality gate that blocks too little → system produces garbage.

The gate must be CONFIGURABLE, AUDITABLE, and BYPASSABLE.
- Configurable: different thresholds per agent type
- Auditable: every gate decision logged with full reasoning
- Bypassable: human override always possible via escalation

## Pre-conditions
Read ALL evaluation components built in TASK_21-23.
Read core/clone_agent.py, agents/code_writing_agent.py,
agents/code_review_agent.py.

## Deliverables

### 1. core/evaluation/quality_gate.py

class GatePolicy:
  """Configures quality gate behavior per agent type."""
  agent_name: str
  min_combined_score: float
  require_llm_evaluation: bool
  require_static_analysis: bool
  block_on_security_high: bool = True
  block_on_regression: bool = True
  regression_tolerance: float = 0.10
  escalate_on_block: bool = True

class GateDecision(Enum):
  PASS = "PASS"
  BLOCK = "BLOCK"
  ESCALATE = "ESCALATE"
  BYPASS = "BYPASS"  (human override applied)

@dataclass
class GateResult:
  decision: GateDecision
  agent_name: str
  event_id: str
  combined_score: Optional[float]
  blocking_reasons: List[str]
  warnings: List[str]
  gate_policy: str  (policy name)
  timestamp: datetime
  duration_ms: int
  human_override: bool = False
  override_reason: Optional[str] = None

class QualityGate:
  __init__(
    policies: Dict[str, GatePolicy],
    quality_scorer: QualityScorer,
    regression_detector: RegressionDetector,
    gate_log_path: Path
  )
  
  evaluate(
    agent_result: AgentResult,
    agent_name: str,
    llm_evaluation: Optional[EvaluationResult] = None,
    file_path: Optional[Path] = None,
    model_version: Optional[str] = None
  ) -> GateResult:
    
    1. Get policy for agent_name (use default if none configured)
    2. Compute combined score via quality_scorer
    3. Check regression via regression_detector
    4. Apply policy rules in order:
       a. score < min_combined_score → BLOCK, add reason
       b. security_high > 0 AND block_on_security_high → BLOCK
       c. regression_detected AND block_on_regression → ESCALATE
       d. All pass → PASS
    5. Log GateResult to gate_decisions.jsonl (atomic append)
    6. Return GateResult
  
  override(event_id: str, reason: str) -> GateResult:
    Marks a previously blocked decision as BYPASS.
    Updates gate_decisions.jsonl entry.
    Requires reason to be non-empty.
  
  get_block_rate(agent_name: str, window: int = 100) -> float:
    Percentage of gate evaluations that resulted in BLOCK/ESCALATE
    over last N decisions for this agent.

DEFAULT_POLICIES = {
  "code_writing": GatePolicy(
    agent_name="code_writing",
    min_combined_score=0.65,
    require_llm_evaluation=True,
    require_static_analysis=True,
    block_on_security_high=True,
    block_on_regression=True
  ),
  "code_review": GatePolicy(
    agent_name="code_review",
    min_combined_score=0.70,
    require_llm_evaluation=True,
    require_static_analysis=False,
    block_on_security_high=False,
    block_on_regression=True
  ),
  "planning": GatePolicy(
    agent_name="planning",
    min_combined_score=0.60,
    require_llm_evaluation=True,
    require_static_analysis=False,
    block_on_security_high=False,
    block_on_regression=False
  ),
  "default": GatePolicy(
    agent_name="default",
    min_combined_score=0.50,
    require_llm_evaluation=False,
    require_static_analysis=False,
    block_on_security_high=True,
    block_on_regression=False
  )
}

### 2. Update core/projectos.py
  Initialize QualityGate with DEFAULT_POLICIES.
  Initialize LLMJudge for each agent type with DIFFERENT 
  provider than the agent's own (gemini-flash as judge by default).
  Pass gate to CloneAgent.

### 3. Update core/clone_agent.py
  After dispatch returns AgentResult:
    If quality_gate present:
      Run gate.evaluate(result, agent_name, ...)
      If BLOCK → do NOT write files, return escalated result
      If ESCALATE → write to escalation_queue.md, continue but flag
      If PASS → proceed normally
      Log gate decision to decisions.log

### 4. New CLI command: projectos gate
  projectos gate status
    Shows current block rate per agent and recent gate decisions.
    Format:
    Agent          Block Rate  Last 10: P P P B P P E P P P
    code_writing   8.3%        [P=Pass B=Block E=Escalate]
  
  projectos gate override <event_id> --reason "manual review passed"
    Marks blocked event as human-overridden.
  
  projectos gate policies
    Shows current policy configuration per agent in table format.

### 5. tests/test_evaluation/test_quality_gate.py
  All use mocked evaluator and scorer:
  
  - test_pass_decision_on_high_score
  - test_block_decision_on_low_score
  - test_block_on_security_high_severity
  - test_escalate_on_regression_detected
  - test_override_changes_decision_to_bypass
  - test_override_requires_nonempty_reason
  - test_gate_result_logged_to_jsonl
  - test_block_rate_computed_correctly
  - test_default_policy_used_for_unknown_agent
  - test_pass_without_llm_eval_if_not_required

## Constraints
- Quality gate must add < 500ms overhead on average
  (most time is in LLM evaluation, not gate logic itself)
- gate_decisions.jsonl is append-only
- Override requires non-empty reason string — enforce strictly
- Gate never crashes — if evaluation fails, default to PASS
  with warning logged (fail-open, not fail-closed)

## Verification
Full test suite. Write TASK_24_RESULT.md. Update tasks/README.md.
