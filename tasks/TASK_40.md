# TASK_40: Dogfood — Run ProjectOS on ProjectOS

## Engineering Context

"Eating your own dogfood" means using your own tool on itself.
This is the most reliable way to find real bugs.

ProjectOS will now review its own code, plan improvements to itself,
and generate tests for its own modules — using real API calls if
available, falling back to mocks if not.

This task runs ProjectOS as a daemon for 5 minutes against its own
codebase and collects what actually happens: what works, what breaks,
what the agents actually produce on real code.

## Pre-conditions
Read core/projectos.py, cli/main.py completely.
Read TASK_39_RESULT.md — at least one provider must be available.
If no providers available: run in mock mode and document clearly.

## Deliverables

### 1. scripts/dogfood.py

Orchestrated dogfood session:

Phase A — Index own codebase:
  Initialize ProjectOS pointing at its own repo root.
  Run CodeIndexer on core/, agents/, cli/ (exclude tests/, .venv/).
  Assert: IndexingReport.files_indexed >= 10
  Assert: IndexingReport.chunks_created >= 50
  Log report to .projectos_state/dogfood_indexing.json

Phase B — Self code review:
  Trigger CODE_CHANGED event for: core/clone_agent.py
  Let it flow through: Clone → CodeReview → TestAgent → DocsAgent
  Wait for completion (timeout: 120 seconds)
  Assert: review file created in reviews/
  Assert: decisions.log has new entries
  Log: what issues the agent found in its own code

Phase C — Self planning:
  Submit MANUAL_TRIGGER with description:
  "Add structured JSON export for all agent output types
   so external tools can consume ProjectOS results"
  Let PlanningAgent decompose it
  Assert: backlog.md has new entries with PLAN- IDs
  Log: the generated task breakdown

Phase D — Self architecture review:
  Submit ARCHITECTURE_QUESTION event:
  question: "Should ProjectOS expose a REST API or stick with CLI only?"
  context: "Current architecture is CLI + daemon. External integrations
            need programmatic access."
  Let ArchitectureAgent respond
  Assert: new ADR file created in docs/adr/
  Log: the recommendation

Write dogfood_report.md in docs/:
  # ProjectOS Dogfood Report
  Date: [now]
  Provider: [which provider was used or "mock"]
  
  ## Indexing
  Files indexed, chunks created, duration
  
  ## Code Review Findings
  What the agent found in core/clone_agent.py
  (real issues or mock output — label clearly)
  
  ## Planning Output
  The generated task breakdown for JSON export feature
  
  ## Architecture Recommendation
  ADR summary for REST API vs CLI question
  
  ## Real Bugs Found
  Any errors, crashes, or unexpected behavior during the session
  
  ## What Worked
  Components that ran correctly end-to-end
  
  ## What Needs Fixing
  Honest list of failures or gaps discovered

### 2. Update core/projectos.py
Add method:
  run_for_duration(seconds: int) -> Dict:
    Starts all components, processes events for N seconds,
    gracefully shuts down.
    Returns: {events_processed, decisions_logged, errors}
    
  This enables scripted dogfood sessions without manual Ctrl+C.

### 3. tests/test_dogfood.py
No real API calls — test the session orchestration only:
  - test_dogfood_indexing_phase_completes
  - test_dogfood_triggers_review_event
  - test_dogfood_report_written
  - test_run_for_duration_stops_cleanly
  - test_dogfood_handles_provider_failure_gracefully

## Constraints
- Dogfood session must stop cleanly after configured duration
- If provider fails mid-session: log error, continue with mock
- dogfood_report.md must be generated regardless of failures
- Real API call results must be labeled "REAL OUTPUT"
- Mock results must be labeled "MOCK OUTPUT"
- Script must exit 0 even if some phases fail
  (failure is information, not a test failure)

## Verification
Full test suite passes.
python scripts/dogfood.py completes without crash.
docs/dogfood_report.md exists and has content.
Write TASK_40_RESULT.md. Update tasks/README.md.
