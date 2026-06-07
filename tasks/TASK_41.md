# TASK_41: Process a Real External Project

## Engineering Context

TASK_40 ran ProjectOS on itself — a familiar codebase.
This task runs ProjectOS on a genuinely unfamiliar project
to test whether the system generalizes beyond its own code.

Target project: The user has a content creation pipeline project
and a TenderIQ project. Either is valid. This task uses whichever
is available at a known path, or clones a small open-source Python
project if neither is available.

This is the final proof that ProjectOS works as a general tool,
not just a self-referential demo.

## Pre-conditions
Read docs/dogfood_report.md from TASK_40.
Fix any "Real Bugs Found" from dogfood before running this task.
Check for external project at:
  ~/June-2026/ (look for other Python projects)
  If none found: use https://github.com/tiangolo/fastapi (small, well-known)

## Deliverables

### 1. scripts/process_external.py

Runs ProjectOS against an external project directory.

Usage: python scripts/process_external.py --path /path/to/project

Steps:
1. Validate path exists and contains Python files
2. Count Python files (must have >= 3 to be meaningful)
3. Initialize ProjectOS with external path as root
4. Run CodeIndexer on the external project
   Exclude: .venv, __pycache__, .git, node_modules
5. Pick the 3 most complex files (by line count)
6. Run CODE_CHANGED event for each
7. Wait for review + test generation (timeout: 180 seconds each)
8. Collect all review reports from reviews/

Write external_project_report.md in docs/:
  # External Project Processing Report
  Project: [path or name]
  Date: [now]
  Provider: [which or mock]
  
  ## Project Stats
  Files indexed, total lines, languages detected
  
  ## Reviews Generated
  For each reviewed file:
    - File path
    - Issues found (count by severity)
    - Review report location
    - Quality gate decision
  
  ## Tests Generated
  For each test file generated:
    - Source file
    - Tests written
    - Tests passing / failing
  
  ## Observations
  What worked, what failed, what surprised you

### 2. scripts/benchmark_real.py

Runs benchmark with real API calls (not mocked).
Extends scripts/benchmark.py from TASK_15.

For each available provider:
  Run the same 3 benchmark cases as TASK_25.
  But this time with real model calls.
  Record: real latency, real output quality, real token usage.
  
Append results to docs/benchmark_results.md with label "REAL CALLS".
Compare against mock baseline from earlier benchmark runs.

Write docs/real_provider_comparison.md:
  Table: provider | task | latency_ms | tokens | quality_score | cost_inr
  Recommendation: which provider to use for which agent type

### 3. Fix issues discovered in TASK_40
Read docs/dogfood_report.md section "What Needs Fixing".
Fix each item listed there.
List fixes applied in TASK_41_RESULT.md under "Fixes Applied".

### 4. tests/test_external_processor.py
  - test_validates_path_exists
  - test_rejects_path_with_no_python_files
  - test_selects_most_complex_files (mock file system)
  - test_report_written_after_processing
  - test_graceful_timeout_handling

## Constraints
- Never modify the external project's files — read only
- All review reports go in ProjectOS's own reviews/ directory
- External project path must be configurable, not hardcoded
- Timeout per file must be respected — no hanging
- Report must be written even if all reviews fail

## Verification
Full test suite passes.
python scripts/process_external.py completes without crash.
docs/external_project_report.md exists with real content.
Write TASK_41_RESULT.md. Update tasks/README.md.
