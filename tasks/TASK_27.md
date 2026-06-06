# TASK_27: Embedding Abstraction + Vector Store

## Engineering Context

Every intelligence feature in Phase 4 requires two primitives:
1. Converting text to dense vector representations (embeddings)
2. Storing and retrieving vectors by semantic similarity

This task builds both as clean abstractions following the same
ModelProvider pattern established in Phase 1. Getting this right
is critical — every subsequent Phase 4 task depends on these
interfaces. A design mistake here costs 4 tasks of rework.

Key engineering decisions made for you:
- Embeddings: abstract interface, three concrete implementations
  (Gemini free tier, TF-IDF fallback, sentence-transformers optional)
- Vector store: ChromaDB as primary (lightweight, local, no server)
  with numpy cosine similarity as zero-dependency fallback
- Persistence: ChromaDB persists to .projectos_state/chroma_db/
- Collections: one per agent type for isolated memory spaces

Do not deviate from these decisions. They were chosen for:
- ₹0 cost (Gemini free tier + local ChromaDB)
- Zero server infrastructure
- Graceful degradation when tools unavailable

## Pre-conditions
Read core/model_provider.py completely.
The embedding abstraction must follow the exact same patterns.
Read core/evaluation/base_evaluator.py for dataclass patterns.

## Deliverables

### 1. core/intelligence/__init__.py
Empty file. Creates the intelligence subpackage.

### 2. core/intelligence/embedder.py

from abc import ABC, abstractmethod

class BaseEmbedder(ABC):
  """
  Abstract embedding interface.
  Follows same pattern as ModelProvider.
  All implementations must be swappable without changing callers.
  """
  
  @abstractmethod
  embed(text: str) -> List[float]:
    """Convert text to dense vector. Never raises — returns zero vector on error."""
  
  @abstractmethod
  embed_batch(texts: List[str]) -> List[List[float]]:
    """Batch embedding. More efficient than calling embed() N times."""
  
  @abstractmethod
  get_dimension() -> int:
    """Return embedding dimension. Must be consistent per instance."""
  
  @abstractmethod
  get_embedder_name() -> str:
    """Return identifier for logging and store compatibility checks."""

class GeminiEmbedder(BaseEmbedder):
  """
  Uses Gemini text-embedding-004 model (free tier).
  API endpoint: generativelanguage.googleapis.com/v1beta/models/
                text-embedding-004:embedContent
  Dimension: 768
  Rate limit: 1500 requests/minute on free tier.
  
  Requires GEMINI_API_KEY environment variable.
  Falls back to TFIDFEmbedder if API key not set.
  """
  __init__(api_key: Optional[str] = None, dimension: int = 768)
  
  embed(text: str) -> List[float]:
    POST to Gemini embedding endpoint.
    On any error (network, auth, rate limit) → log warning,
    return [0.0] * self.dimension (zero vector, never crash)
  
  embed_batch(texts: List[str]) -> List[List[float]]:
    Call embed() for each. Gemini free tier has no batch endpoint.

class TFIDFEmbedder(BaseEmbedder):
  """
  Zero-dependency fallback embedder using TF-IDF with vocabulary.
  Not semantic — but works offline, free, no API key required.
  Dimension: 512 (vocabulary size, configurable)
  
  Vocabulary is built incrementally from embedded texts.
  Saved to .projectos_state/tfidf_vocab.json on each update.
  Loaded on init if file exists.
  
  Use this when:
  - No Gemini API key available
  - Offline mode
  - Testing (deterministic, no API calls)
  """
  __init__(vocab_size: int = 512, state_dir: Optional[Path] = None)
  
  embed(text: str) -> List[float]:
    Tokenize text (split on non-alphanumeric, lowercase).
    Compute TF-IDF vector against current vocabulary.
    Update vocabulary with new tokens if vocab not full.
    Return normalized vector of length vocab_size.
  
  embed_batch(texts: List[str]) -> List[List[float]]:
    Process all texts, build joint vocabulary first, then embed each.
    More accurate than calling embed() sequentially.
  
  save_vocab(path: Path) -> None
  load_vocab(path: Path) -> None

class EmbedderFactory:
  """Creates the best available embedder based on environment."""
  
  @staticmethod
  create(state_dir: Path) -> BaseEmbedder:
    If GEMINI_API_KEY set → return GeminiEmbedder()
    Else → return TFIDFEmbedder(state_dir=state_dir)
    Log which embedder was selected and why.

### 3. core/intelligence/vector_store.py

@dataclass
class VectorRecord:
  id: str  (UUID)
  text: str  (original text, stored for retrieval)
  embedding: List[float]
  metadata: Dict[str, Any]  (agent_name, event_id, timestamp, type)
  created_at: datetime

@dataclass
class SearchResult:
  record: VectorRecord
  similarity_score: float  (0.0 to 1.0, cosine similarity)
  rank: int  (1 = most similar)

class BaseVectorStore(ABC):
  @abstractmethod
  add(record: VectorRecord) -> None
  
  @abstractmethod
  search(query_embedding: List[float], k: int = 5,
         filter_metadata: Optional[Dict] = None) -> List[SearchResult]
  
  @abstractmethod
  delete(record_id: str) -> bool
  
  @abstractmethod
  count() -> int
  
  @abstractmethod
  get_collection_name() -> str

class ChromaVectorStore(BaseVectorStore):
  """
  ChromaDB-backed persistent vector store.
  Persists to state_dir/chroma_db/.
  One ChromaVectorStore instance = one ChromaDB collection.
  
  ChromaDB install check: try import chromadb
  If not available → raise ImportError with install instructions.
  """
  __init__(collection_name: str, state_dir: Path, embedder: BaseEmbedder)
  
  add(record: VectorRecord) -> None:
    Store embedding + metadata + text in ChromaDB collection.
    ChromaDB handles persistence automatically.
  
  search(query_embedding, k=5, filter_metadata=None) -> List[SearchResult]:
    ChromaDB query with optional metadata filtering.
    Convert ChromaDB results to SearchResult dataclasses.
    Scores are already cosine similarity in ChromaDB.

class NumpyVectorStore(BaseVectorStore):
  """
  Pure numpy fallback. In-memory with JSON persistence.
  Use when ChromaDB not available.
  Persists to state_dir/vector_store_{collection_name}.json
  
  Performance: O(N) linear scan. Acceptable for < 10,000 records.
  """
  __init__(collection_name: str, state_dir: Path)
  
  On init: load existing records from JSON if file exists.
  
  add(record: VectorRecord) -> None:
    Append to in-memory list.
    Save to JSON atomically (write temp, rename).
  
  search(query_embedding, k=5, filter_metadata=None) -> List[SearchResult]:
    Compute cosine similarity: dot(q, v) / (|q| * |v|)
    Use numpy for vectorized computation over all records.
    Apply metadata filter BEFORE similarity (reduces computation).
    Return top k sorted by score descending.

class VectorStoreFactory:
  @staticmethod
  create(collection_name: str, state_dir: Path,
         embedder: BaseEmbedder) -> BaseVectorStore:
    Try ChromaVectorStore first.
    On ImportError → fall back to NumpyVectorStore.
    Log which store was selected.

### 4. tests/test_intelligence/test_embedder.py
Create tests/test_intelligence/__init__.py first.

- test_tfidf_embed_returns_correct_dimension
- test_tfidf_embed_batch_consistent_with_single
- test_tfidf_zero_vector_never_raised_on_empty_input
- test_tfidf_vocab_saved_and_loaded (use tmp_path)
- test_gemini_embedder_falls_back_on_missing_key (mock env)
- test_gemini_embedder_returns_zero_vector_on_http_error (mock requests)
- test_embedder_factory_returns_tfidf_without_api_key

### 5. tests/test_intelligence/test_vector_store.py
All tests use NumpyVectorStore (no ChromaDB dependency in CI):

- test_add_and_search_returns_correct_record
- test_search_returns_k_results
- test_cosine_similarity_identical_vectors_score_one
- test_cosine_similarity_orthogonal_vectors_score_zero
- test_metadata_filter_applied_before_similarity
- test_persistence_survives_reload (save to tmp_path, reload)
- test_delete_removes_record
- test_count_accurate_after_adds_and_deletes
- test_search_empty_store_returns_empty_list

## Constraints
- TFIDFEmbedder must work with zero dependencies (stdlib only)
- NumpyVectorStore requires only numpy (already in project)
- ChromaVectorStore must fail gracefully on import error
- All embedders return consistent dimension across calls
- VectorRecord.id must be UUID4 always
- search() never raises — returns empty list on error

## New Dependencies
Add to requirements.txt and pyproject.toml:
  chromadb>=0.5.0  (optional — used only if importable)
  numpy>=1.24.0  (may already be present from ML coursework)

DO NOT add sentence-transformers — too heavy for this stage.

## Verification
UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 
uv run --no-sync pytest tests/test_intelligence/ -v
Full suite. Write TASK_27_RESULT.md. Update tasks/README.md.
