# TASK_23: Static Code Quality Analyzer

## Engineering Context
LLM-as-Judge (TASK_21) evaluates semantic quality.
Regression detection (TASK_22) tracks quality over time.
This task adds objective, deterministic code quality measurement
using static analysis — metrics that don't require a model call
and can't be hallucinated.

Static analysis provides ground truth:
- Cyclomatic complexity (is this code too complex?)
- Maintainability index (will this be readable in 6 months?)
- Test coverage ratio (how much of this is tested?)
- Security issues (bandit — does this have known vulnerabilities?)
- Style violations (flake8 — does it follow PEP8?)

These metrics are CHEAP (no API call), FAST (< 1 second), and
DETERMINISTIC (same code = same score every time).

## Pre-conditions
Read agents/code_writing_agent.py, core/evaluation/base_evaluator.py.
Note: radon, bandit, flake8 are available as subprocess commands.
Check if they're installed: which radon || echo "not found"
If not available, implement graceful degradation.

## Deliverables

### 1. core/evaluation/static_analyzer.py

@dataclass
class ComplexityMetrics:
  file_path: str
  avg_cyclomatic_complexity: float
  max_cyclomatic_complexity: float
  maintainability_index: float  (0-100, higher is better)
  lines_of_code: int
  comment_ratio: float  (comment lines / total lines)
  function_count: int
  class_count: int
  
@dataclass  
class SecurityMetrics:
  file_path: str
  high_severity_count: int
  medium_severity_count: int
  low_severity_count: int
  issues: List[Dict]  (bandit issue dicts)
  bandit_available: bool  (False if bandit not installed)

@dataclass
class StyleMetrics:
  file_path: str
  violation_count: int
  violations: List[str]  (flake8 output lines)
  flake8_available: bool

@dataclass
class StaticAnalysisReport:
  file_path: str
  timestamp: datetime
  complexity: ComplexityMetrics
  security: SecurityMetrics
  style: StyleMetrics
  overall_quality_score: float  (computed composite 0.0-1.0)
  passed_quality_gate: bool
  
  @property
  def summary(self) -> str:
    One-line human-readable summary of the report.

class StaticAnalyzer:
  __init__(
    complexity_threshold: float = 10.0,
    maintainability_threshold: float = 20.0,
    max_security_high: int = 0,
    max_style_violations: int = 10
  )
  
  analyze(file_path: Path) -> StaticAnalysisReport:
    1. Run complexity analysis (radon cc + radon mi via subprocess)
       If radon not available → ComplexityMetrics with all zeros,
       log warning "radon not installed, skipping complexity"
    2. Run security analysis (bandit -f json via subprocess)
       If bandit not available → SecurityMetrics with bandit_available=False
    3. Run style analysis (flake8 via subprocess)
       If flake8 not available → StyleMetrics with flake8_available=False
    4. Compute overall_quality_score:
       complexity_score = 1.0 if avg_cc <= threshold else 
                         max(0, 1 - (avg_cc - threshold) / threshold)
       maintainability_score = maintainability_index / 100.0
       security_score = 1.0 if high_count == 0 else 0.0
       style_score = max(0, 1 - violation_count / 50)
       overall = weighted average:
         complexity: 0.30, maintainability: 0.25,
         security: 0.30, style: 0.15
    5. passed_quality_gate = overall_quality_score >= 0.6
    
  batch_analyze(file_paths: List[Path]) -> List[StaticAnalysisReport]:
    Runs analyze() on each file. Catches per-file errors, continues.
    Returns partial results on failure.

### 2. core/evaluation/quality_scorer.py

class QualityScorer:
  """
  Combines LLM evaluation scores with static analysis scores
  into a single unified quality measurement per agent output.
  """
  
  __init__(
    static_analyzer: StaticAnalyzer,
    evaluation_store: EvaluationStore,
    llm_weight: float = 0.60,
    static_weight: float = 0.40
  )
  
  Note: weights must sum to 1.0. Raise ValueError if not.
  Note: If static analysis unavailable for a file → 
        use llm_weight=1.0 automatically (graceful degradation)
  
  @dataclass
  class CombinedScore:
    agent_name: str
    event_id: str
    file_path: Optional[str]
    llm_score: Optional[float]
    static_score: Optional[float]
    combined_score: float
    passed: bool  (combined_score >= 0.65)
    breakdown: Dict[str, float]
    timestamp: datetime
  
  score(
    agent_result: AgentResult,
    llm_evaluation: Optional[EvaluationResult],
    file_path: Optional[Path]
  ) -> CombinedScore

### 3. Update agents/code_writing_agent.py
  After writing a file, if static_analyzer injected:
    Run analyze(file_path)
    If not report.passed_quality_gate:
      Append warning to decisions.log
      Set escalate=True if high_severity security issues found
    Store report path in AgentResult.metadata["static_report"]

### 4. tests/test_evaluation/test_static_analyzer.py
  Use tmp_path with real Python files (no subprocess mocking needed
  for basic tests — use files that predictably pass/fail):
  
  - test_analyze_simple_function_passes (write clean function to tmp)
  - test_overall_score_computed_from_components
  - test_passed_quality_gate_threshold
  - test_batch_analyze_continues_on_single_failure
  - test_missing_tool_degrades_gracefully (mock subprocess to fail)
  - test_security_score_zero_on_high_severity_issue
  - test_quality_scorer_combines_llm_and_static

## Constraints
- subprocess calls must have timeout=30
- Never crash if tool not installed — degrade gracefully
- StaticAnalysisReport is immutable after creation (frozen dataclass)
- No new Python package dependencies 
  (radon/bandit/flake8 are CLI tools, called via subprocess)

## Verification
Full test suite. Write TASK_23_RESULT.md. Update tasks/README.md.
