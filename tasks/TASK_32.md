# TASK_32: Phase 4 Integration + Intelligence Smoke Test

## Engineering Context

Phase 4 added 5 intelligence components:
  TASK_27: Embedding abstraction + Vector store
  TASK_28: Codebase RAG — repository awareness
  TASK_29: Agent memory — learning from past work
  TASK_30: Semantic Clone router
  TASK_31: Agent collaboration protocol

This task is the Phase 4 equivalent of TASK_09 (integration) and
TASK_26 (verification). It verifies all intelligence components
work together, measures the quality improvement Phase 4 provides
over Phase 3 baseline, and prepares documentation for Phase 5.

The quality delta measurement is the critical deliverable:
Phase 3 gave us quality measurement. Phase 4 should IMPROVE scores.
If average evaluation scores don't improve after Phase 4, the
intelligence components are not working — fix them before moving on.

## Pre-conditions
Run full test suite first. Report count before making any changes.
Read ALL files in core/intelligence/.
Read TASK_27 through TASK_31 result files for known gaps.
Read core/evaluation/ to understand quality measurement.

## Deliverables

### 1. scripts/intelligence_smoke.py

Full end-to-end intelligence pipeline test using mocked model providers
but REAL vector store (NumpyVectorStore) and REAL embedder (TFIDFEmbedder).

Why real components here:
- TFIDFEmbedder is deterministic — tests are reproducible
- NumpyVectorStore uses real math — catches actual integration bugs
- Model calls are still mocked — no API keys or costs required

Test Scenario A — Indexing and Retrieval:
  1. Create temp project directory with 3 Python files
  2. Initialize CodeIndexer with NumpyVectorStore + TFIDFEmbedder
  3. Index the directory
  4. Assert: IndexingReport.files_indexed == 3
  5. Assert: IndexingReport.chunks_created >= 3
  6. Query: retrieve_for_task("review authentication function")
  7. Assert: RetrievalContext.retrieved_chunks is non-empty
  8. Assert: formatted_context contains "python" code block

Test Scenario B — Memory Storage and Recall:
  1. Initialize MemoryStore + MemoryManager
  2. Store 3 episodic memories for "code_review" agent
  3. Store 2 semantic memories for "planning" agent
  4. Recall with relevant query for "code_review"
  5. Assert: returned memories are for correct agent
  6. Assert: recall() returns non-empty formatted string
  7. Assert: access_count incremented after recall

Test Scenario C — Semantic Routing:
  1. Initialize SemanticRouter with TFIDFEmbedder + NumpyVectorStore
  2. Route: "updating a docstring in a utility function"
  3. Assert: category is "AUTONOMOUS"
  4. Route: "added requests library as new dependency"
  5. Assert: category is "ESCALATE"
  6. Assert: routing_method is "semantic" or "keyword_fallback"
     (both acceptable — TF-IDF may not have high confidence)

Test Scenario D — Collaboration Protocol:
  1. Initialize CollaborationBroker with mock agent registry
  2. MockArchitectureAgent returns: "Use dependency injection pattern"
  3. Submit ConsultationRequest from "code_writing" to "architecture"
  4. Assert: ConsultationResult.answer contains "dependency injection"
  5. Assert: depth=0 consultation allowed
  6. Submit same consultation with depth=1
  7. Assert: ConsultationResult indicates depth limit reached

Test Scenario E — Full Pipeline:
  1. Initialize full ProjectOS with all intelligence components
     (mocked model providers, real vector components)
  2. Index project files
  3. Submit MANUAL_TRIGGER for "add input validation to API endpoint"
  4. Verify: PlanningAgent's model prompt contains codebase context
  5. Verify: PlanningAgent's model prompt contains memory context (if any)
  6. Verify: decisions.log has routing decision logged
  7. Verify: routing_decisions.jsonl has entry

Print INTELLIGENCE SMOKE: PASSED or INTELLIGENCE SMOKE: FAILED.
Exit code 0 or 1.

### 2. scripts/quality_delta.py

Measures quality improvement from Phase 4 intelligence components.

How it works:
  Run benchmark_suite twice:
  - Round 1: agents WITHOUT context (memory=None, retriever=None)
  - Round 2: agents WITH context (memory populated, retriever active)
  
  Compare EvaluationResult.weighted_score between rounds.

class QualityDeltaReport:
  baseline_scores: Dict[str, float]  (agent → score without intelligence)
  enhanced_scores: Dict[str, float]  (agent → score with intelligence)
  deltas: Dict[str, float]  (enhanced - baseline)
  improvement_pct: Dict[str, float]
  overall_improvement: float  (average across agents)
  passed: bool  (overall_improvement >= 0.0, i.e., no regression)

Report written to:
  docs/phase4_quality_delta.md
  .projectos_state/quality_deltas.jsonl

Note: With TF-IDF embedder and mocked models, improvement may be
minimal. The test passes as long as scores don't REGRESS (>= 0.0).
Real improvement will show when real embeddings and models are used.

### 3. Update AGENTS.md
  Add Phase 4 section:
  
  ## Intelligence Components (Phase 4)
  
  ### Before any agent call, the following context is assembled:
  1. Codebase context: retrieved via CodeIndexer + ContextRetriever
  2. Memory context: recalled via MemoryManager
  3. Routing: classified via SemanticRouter
  
  ### Test command for intelligence components:
  UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 
  uv run --no-sync python scripts/intelligence_smoke.py
  
  ### Never do in intelligence components:
  - Hard-code routing rules without adding semantic examples
  - Add synchronous model calls to memory storage (async or skip)
  - Exceed consultation depth > 1
  - Store raw model outputs as memories without distillation

### 4. Update README.md
  Add Phase 4 section after Phase 3:
  
  ## Agent Intelligence (Phase 4)
  
  ProjectOS agents are context-aware through three mechanisms:
  
  **Codebase RAG**: Before acting, agents retrieve relevant code
  from an indexed vector store of your repository.
  
  **Agent Memory**: Agents accumulate episodic, semantic, and
  procedural memories that improve output quality over time.
  
  **Semantic Routing**: Clone classifies events using embedding
  similarity rather than keyword matching.
  
  **Agent Collaboration**: Agents consult each other for complex
  tasks, bounded by depth limits to prevent cascades.
  
  ASCII diagram of intelligence data flow:
  
  Incoming Event
       ↓
  SemanticRouter (classify + route)
       ↓
  ContextRetriever (fetch relevant code)
  + MemoryManager (recall past experience)
       ↓
  Agent (informed model call)
       ↓
  CollaborationBroker (consult if needed)
       ↓
  Quality Gate (evaluate output)
       ↓
  MemoryManager.learn_from_evaluation() (store learnings)

### 5. Final test run and count
  UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 
  uv run --no-sync pytest -v
  Report final total.

### 6. Run all smoke tests in sequence
  uv run --no-sync python smoke_test.py --ci
  uv run --no-sync python scripts/evaluation_smoke.py
  uv run --no-sync python scripts/intelligence_smoke.py
  All three must pass before TASK_32 is marked DONE.

### 7. Write TASK_32_RESULT.md
  - Files in core/intelligence/ (final count)
  - Final test count
  - All three smoke test results
  - Quality delta report summary
  - Known limitations of Phase 4
  - Phase 5 (Production Observability) prerequisites
  - One paragraph: what a ProjectOS agent can now do that it
    could not do before Phase 4

### 8. Update tasks/README.md
  Mark TASK_32 DONE.
  Add section: Phase 5 — Production Observability (TASK_33-38, PENDING)
