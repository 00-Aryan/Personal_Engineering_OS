# TASK_31: Agent Collaboration Protocol

## Engineering Context

Current architecture: one event → one agent → one result.

This works for simple tasks. It breaks for complex ones:
- CodeWritingAgent implements auth → should ask ArchitectureAgent
  "is this the right pattern?" BEFORE writing 200 lines
- PlanningAgent decomposes a large feature → should ask
  CodeReviewAgent "is this decomposition implementable?"
- TestAgent generates tests → should ask CodeWritingAgent
  "this test calls a method that doesn't exist yet, fix it"

Agent collaboration is the pattern that separates toy multi-agent
systems from production ones. Without it, agents work in isolation
and produce outputs that conflict with each other.

Implementation approach:
- Collaboration is synchronous sub-calls within agent.handle()
- An agent can request a ConsultationResult from another agent
- Clone is NOT in the loop for consultations (would create deadlock)
- Consultations are capped at depth=1 (no cascading consultations)
- All consultations logged for audit

This is how production agentic systems (AutoGen, production LangGraph
pipelines) handle agent-to-agent communication without circular
dependencies.

## Pre-conditions
Read ALL agent files, core/agent_registry.py, core/base_agent.py.
Read core/intelligence/memory_manager.py from TASK_29.
Understand the current handle() method flow in every agent.

## Deliverables

### 1. core/intelligence/collaboration.py

class ConsultationType(Enum):
  ARCHITECTURE_REVIEW = "architecture_review"
  FEASIBILITY_CHECK = "feasibility_check"
  PATTERN_VALIDATION = "pattern_validation"
  CODE_VERIFICATION = "code_verification"
  PLAN_REVIEW = "plan_review"

@dataclass
class ConsultationRequest:
  consultation_id: str  (UUID)
  requesting_agent: str
  target_agent: str
  consultation_type: ConsultationType
  question: str  (specific question being asked)
  context: str  (relevant code/plan being consulted about)
  max_tokens: int = 500  (keep consultations brief)
  depth: int = 0  (current consultation depth, max=1)

@dataclass
class ConsultationResult:
  consultation_id: str
  responding_agent: str
  answer: str
  confidence: float  (0.0-1.0, agent's self-reported confidence)
  recommended_action: Optional[str]
  duration_ms: int
  depth: int

class CollaborationBroker:
  """
  Manages agent-to-agent consultations.
  
  Design rules:
  - Depth limit: max depth=1 (agents can't trigger further consultations)
  - No circular calls: A cannot consult A
  - Timeout: 30 seconds per consultation
  - All consultations logged to collaboration.jsonl
  - Clone is never a consultation target (it's the supervisor)
  """
  
  __init__(
    agent_registry: AgentRegistry,
    log_path: Path,
    max_depth: int = 1
  )
  
  consult(request: ConsultationRequest) -> ConsultationResult:
    1. Validate: depth <= max_depth, requesting != target
    2. Get target agent from registry
    3. Build consultation AgentEvent:
       event_type = MANUAL_TRIGGER
       payload = {
         "consultation": True,
         "question": request.question,
         "context": request.context,
         "max_tokens": request.max_tokens,
         "depth": request.depth + 1
       }
    4. Call target_agent.handle(consultation_event) with timeout=30s
    5. Extract answer from AgentResult.output
    6. Parse confidence if JSON, else default 0.7
    7. Log to collaboration.jsonl
    8. Return ConsultationResult
  
  get_collaboration_stats() -> Dict:
    {total_consultations, by_type, by_requesting_agent,
     avg_duration_ms, depth_1_pct}

### 2. Update core/base_agent.py
  Add collaboration_broker: Optional[CollaborationBroker] = None
  to __init__
  
  Add method:
  consult(
    target_agent: str,
    question: str,
    context: str,
    consultation_type: ConsultationType = ConsultationType.FEASIBILITY_CHECK
  ) -> Optional[str]:
    If collaboration_broker is None: return None
    If event.payload.get("depth", 0) >= 1: return None (depth limit)
    Build ConsultationRequest.
    Result = collaboration_broker.consult(request)
    Log: f"Consulted {target_agent}: {question[:50]}"
    Return result.answer

### 3. Update agents/code_writing_agent.py
  Before writing code for complex tasks (complexity indicator:
  task_description contains "auth", "security", "database",
  "migration", "architecture", or estimated_complexity in ["L", "XL"]):
  
  answer = self.consult(
    target_agent="architecture",
    question=f"Is this implementation approach appropriate? {task_description}",
    context=existing_code or "",
    consultation_type=ConsultationType.ARCHITECTURE_REVIEW
  )
  
  If answer: inject into model prompt:
    "Architecture guidance for this implementation:\n{answer}"

### 4. Update agents/planning_agent.py
  After generating task list:
  
  For each task with complexity XL:
    answer = self.consult(
      target_agent="code_review",
      question=f"Is this task decomposition implementable as written?",
      context=task.to_markdown(),
      consultation_type=ConsultationType.FEASIBILITY_CHECK
    )
    If answer contains "not implementable" or "missing":
      Add warning to task.acceptance_criteria:
        f"⚠ Review note: {answer[:200]}"

### 5. Update core/projectos.py
  Initialize CollaborationBroker with agent_registry.
  Pass to all agents.

### 6. New CLI command: projectos collab
  projectos collab stats
    Shows collaboration statistics from collaboration.jsonl
  
  projectos collab log --tail 10
    Shows last 10 consultations with question, answer, duration

### 7. tests/test_intelligence/test_collaboration.py
  All tests use simple mocked agents returning deterministic answers:
  
  - test_consult_returns_result
  - test_depth_limit_prevents_cascading
  - test_agent_cannot_consult_itself
  - test_consultation_logged_to_jsonl
  - test_timeout_returns_graceful_result
  - test_collaboration_stats_tracked
  - test_consult_with_no_broker_returns_none

## Constraints
- Consultation depth hard limit: max_depth=1, enforce strictly
- Consultation timeout: 30 seconds, returns graceful failure after
- Clone is never a consultation target
- Collaboration never blocks Clone's dispatch loop
- No circular imports between collaboration.py and agent files
  (use AgentRegistry for late binding)

## Verification
Full test suite. Write TASK_31_RESULT.md. Update tasks/README.md.
