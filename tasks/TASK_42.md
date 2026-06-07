# TASK_42: Performance Profiling + Real Bottleneck Analysis

## Engineering Context

With real API calls now running, the actual performance profile
of ProjectOS will differ significantly from mocked tests.

Expected bottlenecks (hypothesis — must be verified):
1. Context retrieval adds 200-400ms per agent call
2. Memory recall adds 100-200ms per agent call
3. Quality gate LLM evaluation doubles model call time
4. JSONL append operations under concurrent load create contention
5. TriggerSystem has false positives on certain file patterns

This task measures what actually happens, identifies the real top 3
bottlenecks, and fixes the ones that are fixable without major refactor.

## Pre-conditions
Read core/observability/tracer.py — this provides all timing data.
Read docs/dogfood_report.md and docs/external_project_report.md.
Real API calls are required for meaningful profiling.
If no providers: profile with mocks and note results are synthetic.

## Deliverables

### 1. scripts/profile_session.py

Runs a profiling session and analyzes trace data.

Steps:
1. Start ProjectOS with tracing enabled
2. Process 5 CODE_CHANGED events on core/ files
3. Stop, collect all traces from .projectos_state/traces.jsonl
4. Analyze:
   - Average total trace duration
   - Average per-component duration (from span tags)
   - Slowest 3 spans across all traces
   - Components with highest variance (inconsistent timing)
   - File I/O operations > 50ms

Write docs/performance_report.md:
  # Performance Profile Report
  Date, provider, real/mock
  
  ## Trace Summary
  Total traces, avg duration, max duration, min duration
  
  ## Component Breakdown
  Table: component | avg_ms | max_ms | % of total time
  
  ## Top 3 Bottlenecks
  Identified from actual trace data, not hypothesis
  
  ## Recommended Fixes
  For each bottleneck:
  - Root cause
  - Proposed fix
  - Expected improvement
  - Complexity (LOW/MEDIUM/HIGH)

### 2. Implement fixes for LOW complexity bottlenecks only

Read docs/performance_report.md after generating it.
For each bottleneck marked LOW complexity:
  Implement the fix.
  Re-run profile_session.py.
  Compare before/after timing.
  Document improvement in TASK_42_RESULT.md.

Do NOT implement MEDIUM or HIGH complexity fixes in this task.
Those go on the backlog as future tasks.

### 3. core/observability/performance_monitor.py

class PerformanceMonitor:
  __init__(tracer: Tracer, state_dir: Path)
  
  get_component_stats() -> Dict[str, ComponentStats]:
    Reads traces.jsonl, aggregates by component name.
    Returns stats for each component seen.
  
  @dataclass
  class ComponentStats:
    component: str
    call_count: int
    avg_duration_ms: float
    p50_duration_ms: float
    p95_duration_ms: float
    max_duration_ms: float
  
  get_slow_operations(threshold_ms: int = 500) -> List[Span]:
    Returns all spans slower than threshold from recent traces.
  
  suggest_optimizations() -> List[str]:
    Rule-based suggestions from stats:
    - If context_retrieval p95 > 500ms → "Consider reducing top_k"
    - If memory_recall avg > 200ms → "Consider memory cache layer"
    - If quality_gate avg > 1000ms → "Consider async evaluation"

### 4. New CLI command: projectos perf
  projectos perf stats
    Shows ComponentStats table for all components.
  
  projectos perf slow --threshold 500
    Shows operations slower than threshold.
  
  projectos perf suggest
    Shows optimization suggestions.

### 5. tests/test_observability/test_performance_monitor.py
  - test_get_component_stats_from_traces
  - test_p95_computed_correctly
  - test_get_slow_operations_filters_threshold
  - test_suggest_optimizations_triggers_on_slow_retrieval

## Constraints
- Profile script must handle empty traces.jsonl gracefully
- Never modify agent logic to improve benchmark scores artificially
- Fixes must not break any existing tests
- performance_report.md must distinguish real vs mock timing

## Verification
Full test suite passes.
docs/performance_report.md generated with real data.
Write TASK_42_RESULT.md. Update tasks/README.md.
