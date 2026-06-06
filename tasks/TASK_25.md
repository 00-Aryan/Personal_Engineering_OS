# TASK_25: Evaluation CI Pipeline + Quality Dashboard

## Engineering Context
Quality measurement without visibility is useless.
This task adds two things:

1. Evaluation CI — runs a structured quality benchmark on every
   commit, tracking whether ProjectOS's own code meets its own
   quality standards. The system evaluates itself.

2. Quality dashboard — extends the Rich terminal dashboard from
   TASK_17 with evaluation metrics, making quality visible
   during live operation.

This closes the feedback loop:
Code change → Quality gate → Metrics stored → Dashboard shows trend
                                                      ↓
                                            CI benchmark on commit

## Pre-conditions
Read ALL of core/evaluation/ from TASK_21-24.
Read cli/dashboard.py from TASK_17.
Read .github/workflows/ci.yml from TASK_20.

## Deliverables

### 1. scripts/quality_benchmark.py

Runs a structured benchmark of ProjectOS agents using mocked
providers (no real API calls — suitable for CI).

class BenchmarkSuite:
  BENCHMARK_CASES = [
    {
      "name": "code_review_basic",
      "agent": "code_review",
      "input_file": "core/base_agent.py",
      "expected_issue_types": ["style", "docs"],
      "min_issue_count": 1
    },
    {
      "name": "planning_feature",
      "agent": "planning",
      "input": "Add rate limiting to all API endpoints",
      "expected_task_count_range": (2, 8),
      "required_task_fields": ["id", "acceptance_criteria"]
    },
    {
      "name": "code_writing_function",
      "agent": "code_writing",
      "input": "Write a function to validate email addresses",
      "expected_output_contains": ["def ", "->", '"""']
    }
  ]
  
  run_all(use_mocks: bool = True) -> BenchmarkReport
  run_case(case: Dict) -> CaseResult
  
@dataclass
class CaseResult:
  name: str
  passed: bool
  score: float
  duration_ms: int
  failure_reason: Optional[str]

@dataclass
class BenchmarkReport:
  timestamp: datetime
  total_cases: int
  passed_cases: int
  pass_rate: float
  avg_score: float
  case_results: List[CaseResult]
  git_commit: Optional[str]  (current HEAD hash)
  
  def to_markdown(self) -> str:
    Formatted markdown table of results.
  
  def to_json(self) -> str:
    JSON serialization for CI artifact upload.

Writes results to:
  docs/benchmark_results.md (human-readable, appended)
  .projectos_state/benchmark_history.jsonl (machine-readable)

Exit code: 0 if pass_rate >= 0.80 else 1

### 2. Update .github/workflows/ci.yml
  Add quality job that runs after test job:
  
  quality:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - checkout
      - setup Python 3.12
      - install uv
      - uv pip install -e ".[dev]"
      - run: uv run --no-sync python scripts/quality_benchmark.py
      - upload benchmark_results.md as artifact
      - fail if exit code non-zero

### 3. Update cli/dashboard.py
  Add Quality Panel to dashboard layout:
  
  ┌─ Quality Metrics ─────────────────────────────────────┐
  │ Agent          Score   Gate    Regression  Evaluations │
  │ code_writing   0.82    ✓ Pass  → Stable    142         │
  │ code_review    0.71    ✓ Pass  ↓ Watch     89          │
  │ planning       0.91    ✓ Pass  ↑ Improved  34          │
  │                                                        │
  │ Block Rate: 4.2% | Overrides Today: 1 | Eval/hr: 23   │
  └────────────────────────────────────────────────────────┘

  Quality panel data sources:
  - Scores: EvaluationStore.get_agent_average_score()
  - Gate status: QualityGate.get_block_rate()
  - Regression: RegressionDetector.get_all_baselines()

### 4. New CLI command: projectos benchmark
  projectos benchmark run
    Runs BenchmarkSuite, shows live progress, prints report.
  
  projectos benchmark history
    Shows last 10 benchmark runs from benchmark_history.jsonl.
    Format: timestamp | pass_rate | avg_score | git_commit

### 5. tests/test_quality_benchmark.py
  - test_benchmark_suite_runs_all_cases
  - test_failed_case_does_not_crash_suite
  - test_benchmark_report_pass_rate_computed
  - test_report_written_to_markdown
  - test_history_appended_not_overwritten
  - test_exit_code_zero_on_high_pass_rate
  - test_exit_code_one_on_low_pass_rate

## Constraints
- Benchmark must complete in < 60 seconds (CI time limit)
- All cases use mocked providers in CI mode
- benchmark_history.jsonl is append-only
- Quality panel in dashboard must not slow refresh below 1 second

## Verification
Full test suite. Write TASK_25_RESULT.md. Update tasks/README.md.
