# TASK_22: Output Schema Validation + Regression Detector

## Engineering Context
TASK_21 added evaluation infrastructure. This task adds two things:

1. Schema validation — structured enforcement that agent outputs
   match expected formats BEFORE evaluation or file writes.
   This catches the most common failure mode: model returns
   something structurally wrong (wrong JSON keys, wrong types,
   missing fields).

2. Regression detection — compares current agent quality against
   its historical baseline. This is what tells you "CodeReviewAgent
   quality dropped 18% after you switched to a new model."

In production ML systems, regression detection without baselines
is meaningless. Baselines without version tracking are unreliable.
This task implements both correctly.

## Pre-conditions
Read core/evaluation/ completely before writing any code.
Read agents/code_writing_agent.py, agents/code_review_agent.py,
agents/planning_agent.py for their current output structures.

## Deliverables

### 1. core/evaluation/schema_validator.py

class OutputSchema:
  """Defines the expected structure of an agent's output."""
  
  agent_name: str
  required_fields: List[str]
  field_types: Dict[str, type]
  optional_fields: List[str]
  custom_validators: List[Callable[[Any], bool]]

@dataclass
class ValidationResult:
  valid: bool
  agent_name: str
  missing_fields: List[str]
  type_errors: Dict[str, str]  (field → "expected X got Y")
  custom_validator_failures: List[str]
  input_sample: str  (first 300 chars of validated content)

class SchemaValidator:
  __init__(schemas: Dict[str, OutputSchema])
    Keyed by agent_name.
  
  validate(agent_name: str, output: Any) -> ValidationResult
    Checks required fields, type correctness, custom validators.
    Returns ValidationResult(valid=False) if agent has no schema —
    never crashes on unknown agents.
  
  register_schema(schema: OutputSchema) -> None

Pre-built schemas for each agent:

CODE_REVIEW_SCHEMA = OutputSchema(
  agent_name="code_review",
  required_fields=["issues"],
  field_types={"issues": list},
  custom_validators=[
    lambda x: all("severity" in i for i in x.get("issues", [])),
    lambda x: all("description" in i for i in x.get("issues", [])),
  ]
)

PLANNING_SCHEMA = OutputSchema(
  agent_name="planning",
  required_fields=["tasks"],
  field_types={"tasks": list},
  custom_validators=[
    lambda x: all("id" in t for t in x.get("tasks", [])),
    lambda x: all("acceptance_criteria" in t for t in x.get("tasks", [])),
  ]
)

### 2. core/evaluation/regression_detector.py

class RegressionDetector:
  """
  Detects quality regression in agent outputs by comparing
  current performance against stored baselines.
  
  Baseline strategy:
  - Baseline is the rolling average of last N passing evaluations
  - N = 10 (configurable, must have >= 5 data points)
  - Regression threshold: current score < baseline × (1 - tolerance)
  - Default tolerance: 0.10 (10% degradation triggers regression)
  
  Version tracking:
  - Baseline is versioned by model name from config
  - Changing models resets baseline automatically
  - Baseline file: .projectos_state/baselines.json
  """
  
  __init__(
    evaluation_store: EvaluationStore,
    state_dir: Path,
    regression_tolerance: float = 0.10,
    min_baseline_samples: int = 5
  )
  
  @dataclass
  class RegressionReport:
    agent_name: str
    current_score: float
    baseline_score: float
    delta: float  (current - baseline)
    delta_pct: float  ((delta / baseline) * 100)
    regression_detected: bool
    model_version: str
    sample_size: int
    recommendation: str
    timestamp: datetime
  
  check_regression(
    agent_name: str,
    current_evaluation: EvaluationResult,
    model_version: str
  ) -> RegressionReport:
    1. Load baseline for agent_name + model_version from baselines.json
    2. If no baseline exists → create one from current_evaluation
       Return RegressionReport(regression_detected=False, 
                               recommendation="Baseline established")
    3. If baseline has fewer than min_baseline_samples → update baseline
       Return RegressionReport(regression_detected=False,
                               recommendation="Building baseline")
    4. Compute delta and delta_pct
    5. regression_detected = current < baseline × (1 - tolerance)
    6. recommendation:
       If regression: "Quality dropped X%. Review model/prompt changes."
       If improvement: "Quality improved X%. Consider updating baseline."
       If stable: "Within tolerance. No action needed."
    7. Update rolling baseline with current score (drop oldest)
    8. Save updated baseline to baselines.json atomically
  
  get_all_baselines() -> Dict[str, Dict]
    Returns all stored baselines with their sample sizes.
  
  reset_baseline(agent_name: str, model_version: str) -> None
    Removes baseline entry — next evaluation recreates it.

### 3. Update core/clone_agent.py
  Add optional evaluator hooks:
  
  __init__ gains:
    schema_validator: Optional[SchemaValidator] = None
    regression_detector: Optional[RegressionDetector] = None
    evaluation_store: Optional[EvaluationStore] = None
  
  After any agent produces AgentResult:
    If schema_validator present and result.output is dict:
      validation = schema_validator.validate(agent_name, result.output)
      If not validation.valid:
        Log warning with missing_fields and type_errors
        Set result.escalate = True
        Append to escalation_queue.md with reason "schema_validation_failed"

### 4. Update core/projectos.py
  Initialize SchemaValidator with pre-built schemas.
  Initialize EvaluationStore in .projectos_state/.
  Initialize RegressionDetector.
  Pass all to CloneAgent.

### 5. New CLI command: projectos quality
  projectos quality status
    Shows per-agent quality scores and regression status.
    Format:
    Agent          Score   Baseline  Delta   Status
    code_review    0.82    0.79      +0.03   ✓ Stable
    planning       0.71    0.84      -0.13   ⚠ Regression
  
  projectos quality reset --agent code_review
    Resets baseline for one agent.
  
  projectos quality baseline
    Shows all stored baselines with sample sizes.

### 6. tests/test_evaluation/test_schema_validator.py
  - test_valid_output_passes_code_review_schema
  - test_missing_required_field_fails
  - test_wrong_type_fails_with_message
  - test_custom_validator_failure_reported
  - test_unknown_agent_returns_valid_false_not_crash
  - test_register_new_schema_works

### 7. tests/test_evaluation/test_regression_detector.py
  Use tmp_path for all state files:
  - test_first_evaluation_creates_baseline
  - test_below_tolerance_triggers_regression
  - test_within_tolerance_no_regression
  - test_improvement_reported_correctly
  - test_model_change_resets_baseline
  - test_insufficient_samples_builds_without_triggering
  - test_reset_baseline_removes_entry
  - test_rolling_window_drops_oldest

## Constraints
- SchemaValidator must never crash on malformed input
- RegressionDetector must never crash if baselines.json is corrupt
  (log warning, treat as no baseline, rebuild)
- All baseline writes atomic
- No new dependencies

## Verification
Full test suite. Write TASK_22_RESULT.md. Update tasks/README.md.
