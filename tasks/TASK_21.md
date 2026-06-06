# TASK_21: Evaluation Framework + LLM-as-Judge

## Engineering Context
Every agent in ProjectOS produces output that is trusted blindly.
In production LLM systems, this is a critical failure mode. Output
quality degrades silently when models change, prompts drift, or
context is insufficient. LLM-as-Judge is the industry-standard
pattern for automated evaluation of LLM outputs at scale.

This task establishes the evaluation foundation that all subsequent
Phase 3 tasks build on. Design it correctly here — every later task
depends on these abstractions.

## Pre-conditions
Read ALL files in core/ and agents/ before writing any code.
Pay particular attention to:
- core/base_agent.py (AgentResult structure)
- core/events.py (AgentEvent structure)
- core/decision_log.py (how decisions are logged)
- agents/code_review_agent.py (example of agent output)

## Deliverables

### 1. core/evaluation/base_evaluator.py

Define the evaluation type system:

@dataclass
class EvaluationCriteria:
  name: str
  description: str
  weight: float  (0.0 to 1.0, weights must sum to 1.0 per evaluator)
  passing_threshold: float  (0.0 to 1.0)

@dataclass  
class EvaluationResult:
  evaluator_name: str
  agent_name: str
  event_id: str
  timestamp: datetime
  criteria_scores: Dict[str, float]  (criteria name → score 0.0-1.0)
  weighted_score: float  (computed from criteria_scores × weights)
  passed: bool  (weighted_score >= passing_threshold)
  reasoning: str  (why this score was given)
  raw_output_sample: str  (first 500 chars of agent output)
  evaluation_duration_ms: int
  evaluator_model: str  (which model did the judging)
  metadata: Dict[str, Any]

class BaseEvaluator(ABC):
  name: str
  criteria: List[EvaluationCriteria]
  passing_threshold: float = 0.7
  
  @abstractmethod
  evaluate(agent_result: AgentResult, context: Dict) -> EvaluationResult
  
  compute_weighted_score(criteria_scores: Dict[str, float]) -> float
    Validates weights sum to 1.0. Raises ValueError if not.
    Computes dot product of scores × weights.
  
  format_evaluation_prompt(agent_result, context) -> str
    Builds structured prompt for judge model.
    Must include: output to evaluate, criteria definitions,
    scoring instructions, output format specification.

### 2. core/evaluation/llm_judge.py

class LLMJudge(BaseEvaluator):
  """
  Evaluates agent output quality using a separate LLM as judge.
  
  Design principles:
  - Judge model should be different from the judged agent's model
    (avoids self-serving bias)
  - Scoring is done per-criteria, not holistically
    (reduces anchoring bias)
  - Judge is given explicit rubrics, not open-ended instructions
    (reduces inconsistency)
  - Judge output is parsed as structured JSON
    (enables programmatic quality gates)
  """
  
  __init__(
    judge_model_provider: ModelProvider,
    criteria: List[EvaluationCriteria],
    passing_threshold: float = 0.7
  )

  JUDGE_SYSTEM_PROMPT = """
  You are an expert code and technical writing evaluator.
  You evaluate AI agent outputs with precision and consistency.
  
  Rules:
  - Score each criterion independently on a 0.0 to 1.0 scale
  - 1.0 = perfect, 0.0 = completely fails the criterion
  - Provide specific reasoning for each score
  - Do not consider factors outside the defined criteria
  - Output ONLY valid JSON, no markdown, no preamble
  
  Output format:
  {
    "criteria_scores": {"criterion_name": score_float, ...},
    "reasoning": "specific explanation for each score",
    "overall_assessment": "one sentence summary"
  }
  """
  
  evaluate(agent_result: AgentResult, context: Dict) -> EvaluationResult:
    1. Build evaluation prompt with output + criteria rubrics
    2. Call judge_model_provider.complete() with JUDGE_SYSTEM_PROMPT
    3. Parse JSON response
    4. On JSON parse failure: return EvaluationResult with
       weighted_score=0.0, passed=False, 
       reasoning="Judge returned invalid JSON: [raw output]"
       Never crash.
    5. Compute weighted score
    6. Return complete EvaluationResult

### 3. core/evaluation/criteria_library.py

Pre-built criteria sets for each agent type.
Each function returns List[EvaluationCriteria] with weights summing to 1.0.

code_writing_criteria() -> List[EvaluationCriteria]:
  - correctness: weight=0.35 "Code is syntactically valid Python 
    that implements the described functionality"
  - type_safety: weight=0.15 "All functions have type hints"
  - documentation: weight=0.15 "All functions have docstrings"
  - no_hardcoding: weight=0.20 "No hardcoded values, strings, 
    or paths that should be configurable"
  - error_handling: weight=0.15 "Handles expected failure modes 
    gracefully without crashing"

code_review_criteria() -> List[EvaluationCriteria]:
  - issue_specificity: weight=0.30 "Issues have specific file/line 
    references, not vague general complaints"
  - severity_calibration: weight=0.25 "CRITICAL severity used only 
    for actual breaking issues, not style preferences"
  - actionability: weight=0.30 "Each issue includes a concrete 
    suggested fix, not just identification"
  - completeness: weight=0.15 "Review covers security, logic, 
    performance, and documentation gaps"

planning_criteria() -> List[EvaluationCriteria]:
  - decomposition_quality: weight=0.30 "Tasks are atomic and 
    independently executable"
  - acceptance_criteria: weight=0.25 "Each task has measurable 
    done conditions"
  - dependency_accuracy: weight=0.25 "Task dependencies reflect 
    actual technical constraints"
  - agent_assignment: weight=0.20 "Each task assigned to the 
    correct agent type"

documentation_criteria() -> List[EvaluationCriteria]:
  - accuracy: weight=0.40 "Documentation matches the actual 
    code behavior"
  - completeness: weight=0.35 "All parameters, returns, and 
    exceptions documented"
  - clarity: weight=0.25 "Explanation is understandable without 
    reading the implementation"

### 4. core/evaluation/evaluation_store.py

class EvaluationStore:
  """Persists all evaluation results for regression detection in TASK_22."""
  
  __init__(store_dir: Path)
  
  save(result: EvaluationResult) -> None
    Appends to evaluations.jsonl (same pattern as DecisionLogger).
    Atomic write.
  
  load_recent(
    agent_name: str,
    evaluator_name: str,
    limit: int = 50
  ) -> List[EvaluationResult]
    Returns most recent N results for agent+evaluator combination.
  
  load_for_event(event_id: str) -> List[EvaluationResult]
    Returns all evaluations for a specific event.
  
  get_agent_average_score(
    agent_name: str,
    evaluator_name: str,
    window: int = 20
  ) -> Optional[float]
    Average weighted_score over last N evaluations.
    Returns None if fewer than 5 results exist (insufficient data).

### 5. core/evaluation/__init__.py
  Export: BaseEvaluator, LLMJudge, EvaluationResult, 
          EvaluationCriteria, EvaluationStore

### 6. tests/test_evaluation/test_llm_judge.py
  All tests use mocked model provider returning valid JSON.
  
  - test_evaluate_returns_evaluation_result
  - test_weighted_score_computed_correctly
  - test_passed_true_when_above_threshold
  - test_passed_false_when_below_threshold
  - test_invalid_json_returns_failed_result_not_crash
  - test_criteria_weights_must_sum_to_one
  - test_evaluation_duration_ms_populated
  - test_raw_output_sample_truncated_to_500_chars

### 7. tests/test_evaluation/test_evaluation_store.py
  - test_save_and_load_recent
  - test_load_for_event_returns_correct_results
  - test_get_agent_average_score_correct
  - test_returns_none_when_insufficient_data (fewer than 5)
  - test_append_only_never_overwrites

## Architecture Note
LLMJudge must be initialized with a DIFFERENT provider than the 
agent being judged. This is enforced by convention, not code.
Document this clearly in the class docstring.
Example: CodeWritingAgent uses openrouter-free → Judge uses gemini-flash.

## Constraints
- core/evaluation/ is a new subpackage — add __init__.py
- Zero new dependencies beyond stdlib
- All file writes atomic
- EvaluationResult is a dataclass, not Pydantic (consistent with codebase)
- Tests in tests/test_evaluation/ subdirectory with __init__.py

## Verification
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_evaluation/ -v
Full suite: UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest
Write TASK_21_RESULT.md. Update tasks/README.md.
