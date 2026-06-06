# TASK_30: Semantic Clone Router

## Engineering Context

Current CloneAgent.classify_decision() works like this:
  "Does payload contain the string 'new_dependency'? → ESCALATE"

This is keyword matching. It breaks on:
  - "added new dependency manager" → misses keyword, wrong decision
  - "dependency injection pattern" → false positive, wrong escalation
  - Novel event types not anticipated when writing the code

A semantic router replaces keyword matching with embedding-based
similarity against labeled examples. This is how production
orchestration systems (LangGraph, DSPy, production Claude pipelines)
handle routing without rigid rule trees.

The router works by:
1. Maintaining a labeled example set per decision category
2. Embedding each incoming event description
3. Finding nearest labeled examples by cosine similarity
4. Routing to the category whose examples are most similar
5. Falling back to keyword rules when confidence is low

This makes Clone's routing adaptive, extensible, and auditable.
Adding a new routing rule = adding a few example strings.
No code changes required.

## Pre-conditions
Read core/clone_agent.py completely.
Read core/intelligence/embedder.py and vector_store.py from TASK_27.
Understand current classify_decision() and dispatch() methods fully.

## Deliverables

### 1. core/intelligence/semantic_router.py

@dataclass
class RoutingExample:
  text: str  (example event description)
  category: str  (AUTONOMOUS, ESCALATE, DEFER_PARALLEL, or agent name)
  weight: float = 1.0  (some examples are more representative)

@dataclass
class RoutingDecision:
  category: str
  confidence: float  (0.0-1.0, cosine similarity to nearest example)
  nearest_example: str  (the matching labeled example)
  routing_method: str  ("semantic" or "keyword_fallback")
  duration_ms: int

class SemanticRouter:
  """
  Routes events to categories using embedding similarity.
  
  Design:
  - Examples stored in vector store collection "routing_examples"
  - On init: embed all default examples and store
  - On route(): embed query, find nearest examples, return category
  - Confidence threshold: if max similarity < min_confidence,
    fall back to keyword rules
  - All routing decisions logged to routing_decisions.jsonl
  """
  
  DEFAULT_ROUTING_EXAMPLES: List[RoutingExample] = [
    # AUTONOMOUS examples
    RoutingExample("updated function docstring", "AUTONOMOUS"),
    RoutingExample("fixed code formatting", "AUTONOMOUS"),
    RoutingExample("added type hints to function", "AUTONOMOUS"),
    RoutingExample("test file generated for module", "AUTONOMOUS"),
    RoutingExample("documentation updated after code change", "AUTONOMOUS"),
    RoutingExample("backlog status updated to done", "AUTONOMOUS"),
    RoutingExample("comment added to explain logic", "AUTONOMOUS"),
    
    # ESCALATE examples
    RoutingExample("new external package dependency added", "ESCALATE"),
    RoutingExample("breaking change to public API", "ESCALATE"),
    RoutingExample("file deleted from repository", "ESCALATE"),
    RoutingExample("database schema migration required", "ESCALATE"),
    RoutingExample("authentication logic modified", "ESCALATE"),
    RoutingExample("changes to more than five core files", "ESCALATE"),
    RoutingExample("security vulnerability detected in code", "ESCALATE"),
    
    # DEFER_PARALLEL examples
    RoutingExample("waiting for permission to write file", "DEFER_PARALLEL"),
    RoutingExample("blocked by sandbox restriction", "DEFER_PARALLEL"),
    RoutingExample("requires human approval before proceeding", "DEFER_PARALLEL"),
    RoutingExample("dependency on another task not yet complete", "DEFER_PARALLEL"),
    
    # Agent routing examples
    RoutingExample("new feature request for the system", "planning"),
    RoutingExample("implement a function that does X", "code_writing"),
    RoutingExample("review the quality of this code file", "code_review"),
    RoutingExample("should we use pattern A or pattern B", "architecture"),
    RoutingExample("write tests for this module", "test"),
    RoutingExample("update docs to reflect new function", "docs"),
  ]
  
  __init__(
    embedder: BaseEmbedder,
    vector_store: BaseVectorStore,
    min_confidence: float = 0.60,
    log_path: Optional[Path] = None
  )
  
  On init:
    Check if routing examples already stored in vector_store.
    If not (first run): embed and store all DEFAULT_ROUTING_EXAMPLES.
    Load keyword fallback rules (same logic as current classify_decision)
  
  route(event_description: str) -> RoutingDecision:
    1. Embed event_description
    2. Search vector_store for top 3 nearest examples
    3. If nearest similarity >= min_confidence:
       Return semantic decision with confidence
    4. Else: apply keyword fallback rules
       Return keyword_fallback decision with confidence=0.0
    5. Log decision to routing_decisions.jsonl
  
  add_example(example: RoutingExample) -> None:
    Embed and store new example. Takes effect immediately.
    Persists across restarts.
  
  get_routing_stats() -> Dict:
    Returns: {total_decisions, semantic_pct, fallback_pct,
              avg_confidence, decisions_by_category}

### 2. Update core/clone_agent.py
  Add semantic_router: Optional[SemanticRouter] = None to __init__
  
  Update classify_decision():
    If semantic_router present:
      Build event_description from event:
        f"{event.event_type.value}: {str(event.payload)[:200]}"
      decision = semantic_router.route(event_description)
      Log: routing method, confidence, nearest example
      If decision.routing_method == "keyword_fallback":
        Log warning: "Semantic confidence low, used keyword fallback"
      Return DecisionCategory based on decision.category
    Else:
      Use existing keyword rules (unchanged)
  
  Update dispatch():
    If semantic_router present and event is MANUAL_TRIGGER or
    event_type has no explicit dispatch rule:
      Use semantic_router to determine target agent
    Else: use existing dispatch rules (unchanged)

### 3. New CLI command: projectos router
  projectos router stats
    Shows routing statistics from routing_decisions.jsonl
  
  projectos router add-example "text" --category ESCALATE
    Adds new routing example immediately
  
  projectos router test "describe your event"
    Shows how the router would classify this description
    Prints: category, confidence, nearest example

### 4. tests/test_intelligence/test_semantic_router.py
  All tests use TFIDFEmbedder (deterministic, no API calls):
  
  - test_route_docstring_update_autonomous
  - test_route_new_dependency_escalate
  - test_route_permission_blocked_defer
  - test_route_new_feature_to_planning
  - test_low_confidence_falls_back_to_keywords
  - test_add_example_affects_routing_immediately
  - test_routing_stats_tracked_correctly
  - test_routing_logged_to_jsonl
  - test_route_with_empty_payload_does_not_crash

## Constraints
- Fallback to keyword rules must always be available
- SemanticRouter must work without any API key (TFIDFEmbedder fallback)
- Routing decision must complete < 100ms
- All routing decisions logged (never silent)
- Adding examples must persist across process restarts

## Verification
Full test suite. Write TASK_30_RESULT.md. Update tasks/README.md.
