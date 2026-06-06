# TASK_28: Codebase RAG — Repository Awareness for Agents

## Engineering Context

Currently when CodeReviewAgent reviews core/clone_agent.py,
it has no idea that:
- BaseAgent is the parent class
- AgentEvent is the primary input type
- CloneAgent dispatches to 6 other agents
- This file is imported by 8 other modules

This is why agent outputs are shallow — they lack codebase context.

Codebase RAG (Retrieval-Augmented Generation) solves this by:
1. Indexing the entire codebase into the vector store
2. Before any agent call, retrieving the most relevant code chunks
3. Injecting those chunks into the agent's context

This is the most impactful single change for agent output quality.
Production systems like Cursor, GitHub Copilot, and Claude Code
all use variants of this pattern.

## Pre-conditions
Read core/intelligence/embedder.py and vector_store.py from TASK_27.
Read ALL agent files to understand what context they currently receive.
Read core/base_agent.py to understand the handle() method signature.

## Deliverables

### 1. core/intelligence/code_indexer.py

@dataclass
class CodeChunk:
  chunk_id: str  (UUID)
  file_path: str
  chunk_type: str  (module, class, function, method, docstring, import)
  name: str  (function/class name or file name for module chunks)
  content: str  (actual code text)
  start_line: int
  end_line: int
  parent_name: Optional[str]  (class name for methods)
  imports: List[str]  (what this chunk imports)
  called_by: List[str]  (populated during indexing pass)
  docstring: Optional[str]
  complexity_score: Optional[float]  (from radon if available)

class CodeIndexer:
  """
  Parses Python files using AST and indexes them into vector store.
  
  Chunking strategy:
  - Module level: one chunk per file (imports + module docstring)
  - Class level: one chunk per class (class def + class docstring)
  - Function/method level: one chunk per function (full body)
  - Maximum chunk size: 100 lines (split larger functions at logical points)
  
  Why AST over regex or line splitting:
  - AST respects Python structure
  - Correctly handles nested functions, decorators, type hints
  - Extracts imports, docstrings, complexity accurately
  - Stdlib only (ast module)
  """
  
  __init__(
    vector_store: BaseVectorStore,
    embedder: BaseEmbedder,
    max_chunk_lines: int = 100
  )
  
  index_file(file_path: Path) -> List[CodeChunk]:
    1. Read file content
    2. Parse with ast.parse() — on SyntaxError, index as single
       raw text chunk with chunk_type="unparseable"
    3. Walk AST: extract Module, ClassDef, FunctionDef, AsyncFunctionDef
    4. For each node: create CodeChunk with content slice
    5. If function > max_chunk_lines: split at inner function/class boundaries
    6. Embed each chunk: embedder.embed(chunk.content)
    7. Store in vector_store with metadata:
       {file_path, chunk_type, name, start_line, end_line, parent_name}
    8. Return list of indexed chunks
  
  index_directory(
    root_path: Path,
    include_patterns: List[str] = ["*.py"],
    exclude_patterns: List[str] = ["__pycache__", ".venv", "test_*", ".git"]
  ) -> IndexingReport:
    Walk directory recursively.
    Call index_file() for each matching file.
    Track: files_indexed, chunks_created, errors, duration_ms
    Return IndexingReport.
  
  @dataclass
  class IndexingReport:
    files_indexed: int
    chunks_created: int
    errors: List[str]  (file paths that failed with reason)
    duration_ms: int
    total_lines_indexed: int
  
  update_file(file_path: Path) -> None:
    Delete all existing chunks for this file from vector_store.
    Re-index the file.
    Use this when a file changes (called from TriggerSystem).
  
  delete_file(file_path: Path) -> None:
    Remove all chunks for file_path from vector_store.

### 2. core/intelligence/context_retriever.py

class RetrievalContext:
  """Assembled context ready to inject into an agent prompt."""
  
  query: str
  retrieved_chunks: List[CodeChunk]
  similarity_scores: List[float]
  total_tokens_estimate: int  (len(full_context) // 4)
  retrieval_duration_ms: int
  
  @property
  def formatted_context(self) -> str:
    """
    Formats chunks for injection into agent prompts.
    Format:
    --- RELEVANT CODEBASE CONTEXT ---
    [file_path:start_line-end_line] (similarity: 0.87)
```python
    [chunk content]
```
    ---
    """

class ContextRetriever:
  """
  Retrieves relevant code chunks for a given agent task.
  
  Retrieval strategy:
  1. Primary query: embed the task description/event payload
  2. File context query: embed the file being worked on (if applicable)
  3. Combine results, deduplicate, rank by score
  4. Apply token budget: never exceed max_context_tokens
  5. Always include: the file being modified (if it exists in index)
  """
  
  __init__(
    vector_store: BaseVectorStore,
    embedder: BaseEmbedder,
    max_context_tokens: int = 2000,
    top_k: int = 8
  )
  
  retrieve_for_task(
    task_description: str,
    file_path: Optional[str] = None,
    agent_name: Optional[str] = None,
    metadata_filter: Optional[Dict] = None
  ) -> RetrievalContext:
    1. Embed task_description
    2. Search vector_store for top_k similar chunks
    3. If file_path provided: always include chunks from that file
       (even if similarity is low)
    4. Deduplicate by chunk_id
    5. Sort by similarity score descending
    6. Trim to max_context_tokens (drop lowest-score chunks first)
    7. Return RetrievalContext
  
  retrieve_related_files(file_path: str) -> List[str]:
    Find files that import or are imported by file_path.
    Query vector_store for chunks with import references.
    Returns list of related file paths.

### 3. Update core/trigger_system.py
  When a CODE_CHANGED event fires for a .py file:
    If code_indexer is available (injected at init):
      Call code_indexer.update_file(event.file_path) asynchronously.
      Do not block the trigger — run in background thread.
      Log: "Index updated for [file_path]"

### 4. Update core/projectos.py
  On start():
    Initialize CodeIndexer with vector_store and embedder.
    Index entire project directory (exclude .venv, __pycache__).
    Log IndexingReport: N files, M chunks indexed in X ms.
  Pass code_indexer to TriggerSystem.
  Pass context_retriever to all agents that accept it.

### 5. Update core/base_agent.py
  Add optional context_retriever: Optional[ContextRetriever] = None
  to __init__.
  
  Add helper method:
  get_context(task_description: str, file_path: Optional[str]) 
    -> Optional[str]:
    If context_retriever present:
      Return retrieval_context.formatted_context
    Else return None.
  
  Agents call this BEFORE building their model prompt.

### 6. Update agents/code_review_agent.py and code_writing_agent.py
  In handle():
    Before building model prompt:
      context = self.get_context(
        task_description=event.payload.get("task_description", ""),
        file_path=event.payload.get("file_path")
      )
    Inject context into system_prompt if available:
      "You have access to relevant codebase context:\n{context}"

### 7. New CLI command: projectos index
  projectos index status
    Shows: files indexed, chunks stored, embedder type, last updated
  
  projectos index rebuild
    Re-indexes entire project from scratch. Shows progress.
  
  projectos index search "query text" --k 5
    Manual semantic search. Useful for debugging retrieval.
    Shows: file, function name, similarity score, first 3 lines

### 8. tests/test_intelligence/test_code_indexer.py
  Use tmp_path with real Python files written for tests:
  
  - test_index_simple_function_creates_chunk
  - test_index_class_creates_class_and_method_chunks
  - test_syntax_error_creates_raw_chunk_not_crash
  - test_update_file_replaces_old_chunks
  - test_delete_file_removes_all_chunks
  - test_index_directory_excludes_venv_pattern
  - test_indexing_report_accurate_counts

### 9. tests/test_intelligence/test_context_retriever.py
  - test_retrieve_returns_relevant_chunks
  - test_file_path_chunks_always_included
  - test_token_budget_respected
  - test_deduplication_works
  - test_formatted_context_contains_file_path_and_lines
  - test_empty_store_returns_empty_context

## Constraints
- AST parsing must handle Python 3.10, 3.11, 3.12, 3.14
- index_directory must complete < 30 seconds for typical project
- Context injection must never exceed max_context_tokens
- update_file must be non-blocking (called from trigger system)
- Never index .venv, __pycache__, .git, migrations/

## Verification
Full test suite. Write TASK_28_RESULT.md. Update tasks/README.md.
