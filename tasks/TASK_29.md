# TASK_29: Agent Memory — Learning From Past Work

## Engineering Context

Codebase RAG (TASK_28) gives agents knowledge of the current repo.
Agent Memory gives agents knowledge of their own past performance:
- What decisions worked well in the past
- What review patterns appear repeatedly in this codebase
- What planning decompositions were approved vs rejected
- What code patterns this project uses consistently

This is the difference between a contractor who reads your codebase
once versus one who has been working with you for 6 months.

Three memory types, each stored separately:
- Episodic: specific past events ("Last time I reviewed auth.py,
  I found SQL injection in line 42")
- Semantic: general patterns ("This codebase always uses dataclasses
  not Pydantic. Config always comes from YAML.")
- Procedural: workflow patterns ("When planning auth features,
  always decompose into: schema, routes, middleware, tests, docs")

## Pre-conditions
Read core/intelligence/ from TASK_27 and TASK_28 completely.
Read core/evaluation/evaluation_store.py for persistence patterns.
Read agents/ all files for output structures to store.

## Deliverables

### 1. core/intelligence/memory_store.py

class MemoryType(Enum):
  EPISODIC = "episodic"
  SEMANTIC = "semantic"
  PROCEDURAL = "procedural"

@dataclass
class MemoryRecord:
  memory_id: str  (UUID)
  memory_type: MemoryType
  agent_name: str
  content: str  (the actual memory text — what to remember)
  context: str  (what triggered this memory — for retrieval)
  importance_score: float  (0.0-1.0, higher = retrieved more)
  access_count: int  (how many times retrieved — for importance decay)
  created_at: datetime
  last_accessed: datetime
  metadata: Dict[str, Any]
  
  def to_retrieval_text(self) -> str:
    """Formats memory for injection into agent prompts."""
    return f"[{self.memory_type.value}] {self.content}"

class MemoryStore:
  """
  Manages all three memory types using the vector store.
  Uses separate vector store collections per memory type.
  
  Importance scoring:
  - Initial importance set by caller (0.5 default)
  - Each access increases importance by 0.05 (max 1.0)
  - Importance decays by 0.01 per day since last access
  - Records with importance < 0.1 are candidates for pruning
  
  Capacity management:
  - Max records per agent per type: 1000
  - When at capacity: prune lowest importance records first
  """
  
  __init__(
    vector_store_factory_fn: Callable,
    embedder: BaseEmbedder,
    state_dir: Path,
    max_records_per_agent: int = 1000
  )
  
  store(record: MemoryRecord) -> None:
    Embed record.context (used for retrieval, not content).
    Add to vector store with metadata for filtering.
    Save full record to memory JSONL file.
    Check capacity and prune if needed.
  
  retrieve(
    query: str,
    agent_name: str,
    memory_types: Optional[List[MemoryType]] = None,
    k: int = 5,
    min_importance: float = 0.1
  ) -> List[MemoryRecord]:
    Embed query.
    Search vector store filtered by agent_name and memory_types.
    Load full records from JSONL by memory_id.
    Update access_count and last_accessed for retrieved records.
    Recalculate importance_score for retrieved records.
    Return sorted by importance × similarity (combined score).
  
  prune(agent_name: str, memory_type: Optional[MemoryType] = None) -> int:
    Remove records below importance threshold.
    Returns count of pruned records.
  
  get_stats(agent_name: str) -> Dict:
    Returns: {total_records, by_type, avg_importance, oldest, newest}

### 2. core/intelligence/memory_manager.py

class MemoryManager:
  """
  High-level interface for all agents to interact with memory.
  Abstracts MemoryStore and provides agent-specific helpers.
  """
  
  __init__(memory_store: MemoryStore, embedder: BaseEmbedder)
  
  remember_decision(
    agent_name: str,
    decision: str,
    context: str,
    outcome: str,
    quality_score: Optional[float] = None
  ) -> None:
    Creates EPISODIC memory:
    content = f"Decision: {decision}. Outcome: {outcome}."
    importance = quality_score if quality_score else 0.5
    Stores with memory_type=EPISODIC.
  
  remember_pattern(
    agent_name: str,
    pattern: str,
    examples: List[str],
    confidence: float = 0.7
  ) -> None:
    Creates SEMANTIC memory for recurring patterns.
    content = f"Pattern: {pattern}. Examples: {'; '.join(examples[:3])}"
    importance = confidence
  
  remember_workflow(
    agent_name: str,
    workflow_name: str,
    steps: List[str],
    success_rate: float
  ) -> None:
    Creates PROCEDURAL memory.
    content = f"Workflow '{workflow_name}': {' → '.join(steps)}"
    importance = success_rate
  
  recall(
    agent_name: str,
    query: str,
    k: int = 3
  ) -> str:
    Retrieve top k memories for query.
    Format as text block for injection into agent prompts:
    "--- RELEVANT PAST EXPERIENCE ---
    [episodic] Last time I reviewed auth code: found SQL injection
    [semantic] This codebase uses dataclasses, not Pydantic
    --- END EXPERIENCE ---"
    Return empty string if no relevant memories found.
  
  learn_from_evaluation(
    agent_result: AgentResult,
    evaluation: EvaluationResult
  ) -> None:
    After each evaluation, extract learnable memories:
    - If evaluation.passed and score > 0.8:
        Extract patterns from agent output for SEMANTIC memory
    - If not evaluation.passed:
        Store failure context as EPISODIC memory with low importance
    - Always: store decision + outcome as EPISODIC memory

### 3. Update core/base_agent.py
  Add memory_manager: Optional[MemoryManager] = None to __init__
  
  Add helper method:
  recall_relevant(query: str, k: int = 3) -> str:
    If memory_manager present: return memory_manager.recall(
      self.name, query, k)
    Return empty string.
  
  Add helper method:
  remember(decision: str, context: str, outcome: str,
           quality_score: Optional[float] = None) -> None:
    If memory_manager present: call remember_decision().

### 4. Update agents/code_review_agent.py
  In handle(), before building prompt:
    memories = self.recall_relevant(
      query=f"review {event.payload.get('file_path', '')}", k=3)
    
  Inject memories into system prompt:
    "You have reviewed similar code before:\n{memories}"
  
  After producing review results:
    self.remember(
      decision=f"Reviewed {file_path}",
      context=f"File: {file_path}",
      outcome=f"Found {len(issues)} issues",
      quality_score=None  (updated after evaluation)
    )

### 5. Update agents/planning_agent.py
  In handle(), before building prompt:
    memories = self.recall_relevant(
      query=event.payload.get("description", ""), k=3)
  
  Inject workflow memories:
    "Similar planning decisions from this project:\n{memories}"
  
  After successful planning:
    self.remember_workflow(
      workflow_name=event.payload.get("description", "")[:50],
      steps=[t.title for t in tasks],
      success_rate=0.7  (updated by regression detector over time)
    )

### 6. Update core/projectos.py
  Initialize MemoryStore and MemoryManager.
  Pass MemoryManager to all agents.
  
  On start(), after indexing:
    Log memory stats per agent if any memories exist.

### 7. tests/test_intelligence/test_memory_store.py
  All use tmp_path with NumpyVectorStore:
  
  - test_store_and_retrieve_episodic_memory
  - test_retrieve_filters_by_agent_name
  - test_retrieve_filters_by_memory_type
  - test_access_count_incremented_on_retrieve
  - test_importance_decay_applied
  - test_pruning_removes_low_importance
  - test_capacity_limit_triggers_pruning
  - test_stats_accurate_after_operations

### 8. tests/test_intelligence/test_memory_manager.py
  - test_remember_decision_creates_episodic_record
  - test_remember_pattern_creates_semantic_record
  - test_recall_returns_formatted_string
  - test_recall_empty_returns_empty_string
  - test_learn_from_evaluation_creates_memory_on_pass
  - test_learn_from_evaluation_stores_failure_context

## Constraints
- Memory retrieval must add < 200ms overhead per agent call
- Importance scores stay in [0.0, 1.0] always (clamp, never raise)
- JSONL backing file is append-only (same as DecisionLogger pattern)
- Memory store never raises — log errors, return empty results
- MemoryManager.recall() always returns str (never None)

## Verification
Full test suite. Write TASK_29_RESULT.md. Update tasks/README.md.
