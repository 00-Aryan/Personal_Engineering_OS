# TASK_33: Distributed Tracing — Agent Call Chain Visibility

## Engineering Context

ProjectOS now has 7 agents, 9 intelligence components, and a quality
evaluation pipeline. An event enters the system and triggers a chain
of calls: Clone → SemanticRouter → ContextRetriever → MemoryManager
→ Agent → CollaborationBroker → QualityGate → EvaluationStore.

Right now, if something goes wrong anywhere in that chain, you have:
- decisions.log (text, unstructured)
- escalation_queue.md (only escalations)
- routing_decisions.jsonl (routing only)

You cannot answer: "Why did this CODE_CHANGED event take 8 seconds?"
"Which component caused this review to be blocked?"
"What was the exact call sequence for event abc-123?"

Distributed tracing solves this. It's the standard observability
primitive in production systems (Jaeger, OpenTelemetry, Datadog APM).
We implement a lightweight version that:
- Assigns a trace_id to every event entering the system
- Creates spans for every significant operation within that trace
- Records timing, status, and metadata per span
- Stores traces in a queryable format
- Surfaces them in the CLI and dashboard

This is NOT a full OpenTelemetry implementation. It follows the same
conceptual model but uses only stdlib and existing project patterns.

## Pre-conditions
Read core/events.py, core/clone_agent.py, core/intelligence/,
core/evaluation/ completely before writing any code.
The tracing system must instrument EXISTING code paths, not replace them.

## Deliverables

### 1. core/observability/__init__.py
Empty. Creates the observability subpackage.

### 2. core/observability/tracer.py

class SpanStatus(Enum):
  OK = "ok"
  ERROR = "error"
  TIMEOUT = "timeout"
  SKIPPED = "skipped"

@dataclass
class Span:
  span_id: str  (UUID)
  trace_id: str  (UUID — same for all spans in one event chain)
  parent_span_id: Optional[str]
  operation_name: str
  component: str  (e.g., "clone_agent", "context_retriever", "quality_gate")
  started_at: datetime
  ended_at: Optional[datetime]
  duration_ms: Optional[int]
  status: SpanStatus
  tags: Dict[str, Any]  (e.g., agent_name, event_type, file_path)
  error_message: Optional[str]
  
  def finish(self, status: SpanStatus = SpanStatus.OK,
             error: Optional[str] = None) -> None:
    Sets ended_at, computes duration_ms, sets status.

class Tracer:
  """
  Lightweight distributed tracer.
  
  Usage pattern (context manager):
    with tracer.span("context_retrieval", component="context_retriever",
                     tags={"file": "auth.py"}) as span:
      result = retriever.retrieve(...)
      span.tags["chunks_retrieved"] = len(result.chunks)
  
  Usage pattern (manual):
    span = tracer.start_span("clone_dispatch", component="clone")
    try:
      result = clone.dispatch(event)
      span.finish(SpanStatus.OK)
    except Exception as e:
      span.finish(SpanStatus.ERROR, error=str(e))
  
  Thread safety:
    Each thread has its own current_span context via threading.local().
    Spans from concurrent agent calls don't interfere.
  """
  
  __init__(
    trace_store: TraceStore,
    enabled: bool = True
  )
  
  start_trace(event_id: str, event_type: str) -> str:
    Creates a new trace_id for this event.
    Stores mapping: event_id → trace_id.
    Returns trace_id.
  
  start_span(
    operation_name: str,
    component: str,
    trace_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
    tags: Optional[Dict] = None
  ) -> Span:
    Creates and returns a new Span.
    Does NOT auto-finish — caller must call span.finish().
  
  span(operation_name, component, trace_id=None, tags=None):
    Context manager version. Auto-finishes on exit.
    On exception: sets SpanStatus.ERROR with exception message.
  
  get_trace(trace_id: str) -> List[Span]:
    Returns all spans for a trace, sorted by started_at.
  
  get_trace_for_event(event_id: str) -> Optional[List[Span]]:
    Looks up trace_id by event_id, returns spans.

class TraceStore:
  """Persists traces to .projectos_state/traces.jsonl"""
  
  __init__(state_dir: Path, max_traces: int = 10000)
  
  save_span(span: Span) -> None:
    Atomic append to traces.jsonl.
  
  load_trace(trace_id: str) -> List[Span]:
    Read traces.jsonl, filter by trace_id.
    Return sorted by started_at.
  
  load_recent_traces(limit: int = 20) -> List[str]:
    Return last N unique trace_ids (by first span timestamp).
  
  get_slow_traces(
    threshold_ms: int = 5000,
    limit: int = 10
  ) -> List[Dict]:
    Finds traces where total duration > threshold_ms.
    Returns: [{trace_id, total_duration_ms, event_type, span_count}]
  
  prune_old_traces(keep_days: int = 7) -> int:
    Removes traces older than keep_days. Returns count removed.

### 3. Instrument existing components
Add tracer spans to these specific locations.
Add tracer: Optional[Tracer] = None parameter to each class __init__.

Instrument in core/clone_agent.py:
  handle():
    span = tracer.start_span("clone.handle", component="clone",
      tags={"event_type": event.event_type.value,
            "event_id": event.event_id})
  classify_decision():
    span: tags={"decision": category.value, "method": routing_method}
  dispatch():
    span: tags={"target_agents": [list of dispatched agents]}
  escalate():
    span: tags={"reason": reason}

Instrument in core/intelligence/context_retriever.py:
  retrieve_for_task():
    span: tags={"chunks_retrieved": N, "query_tokens": len//4}

Instrument in core/intelligence/memory_manager.py:
  recall():
    span: tags={"memories_retrieved": N, "agent_name": name}

Instrument in core/evaluation/quality_gate.py:
  evaluate():
    span: tags={"decision": gate_result.decision.value,
                "score": combined_score}

Instrument in agents/code_review_agent.py, code_writing_agent.py:
  handle():
    span: tags={"file_path": file_path, "agent": self.name}

### 4. Update core/projectos.py
  Initialize TraceStore and Tracer.
  Pass tracer to: CloneAgent, ContextRetriever, MemoryManager,
  QualityGate, CodeReviewAgent, CodeWritingAgent.
  
  On start(): log "Tracing enabled. Traces stored in .projectos_state/"

### 5. New CLI command: projectos trace
  projectos trace list
    Shows last 20 traces with:
    trace_id (short) | event_type | duration_ms | span_count | status
  
  projectos trace show <trace_id>
    Shows full trace as ASCII waterfall:
    clone.handle          ████████████████████░░ 450ms [OK]
      clone.classify       ████░                  45ms  [OK]
      clone.dispatch       ████████░              120ms [OK]
      context_retrieval    ████████████░          210ms [OK]
      code_review.handle   ████████████████░      380ms [OK]
        quality_gate       ████░                  60ms  [OK]
  
  projectos trace slow --threshold 3000
    Shows traces that took longer than 3 seconds.

### 6. tests/test_observability/__init__.py (empty)

### 7. tests/test_observability/test_tracer.py
  - test_start_span_returns_span
  - test_span_finish_sets_duration
  - test_context_manager_finishes_span_on_exit
  - test_context_manager_sets_error_on_exception
  - test_get_trace_returns_all_spans
  - test_spans_sorted_by_started_at
  - test_trace_store_persists_and_loads (tmp_path)
  - test_get_slow_traces_filters_correctly
  - test_tracer_disabled_is_noop (enabled=False, no writes)
  - test_thread_safety (two threads write spans, no interleaving)

## Constraints
- Tracer with enabled=False must have ZERO overhead (no-op all calls)
- Span context manager must never suppress exceptions
- TraceStore is append-only — never delete individual spans
- Trace waterfall must render in standard 80-char terminal width
- No new dependencies (stdlib: threading, contextlib, uuid, json)

## Verification
Full test suite. Write TASK_33_RESULT.md. Update tasks/README.md.
