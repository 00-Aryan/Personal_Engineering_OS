# TASK_27_RESULT: Embedding Abstraction + Vector Store

## Status
DONE

## Files Created
- core/intelligence/__init__.py
- core/intelligence/embedder.py
- core/intelligence/vector_store.py
- tests/test_intelligence/__init__.py
- tests/test_intelligence/test_embedder.py
- tests/test_intelligence/test_vector_store.py

## Files Modified
- pyproject.toml
- requirements.txt
- tasks/README.md
- decisions.log

## Implementation Summary
- Added BaseEmbedder with GeminiEmbedder, TFIDFEmbedder, and EmbedderFactory.
- Added persistent TF-IDF vocabulary storage at state_dir/tfidf_vocab.json using atomic writes.
- Added BaseVectorStore with ChromaVectorStore, NumpyVectorStore, and VectorStoreFactory.
- Added VectorRecord and SearchResult dataclasses.
- Implemented JSON persistence for NumpyVectorStore using atomic writes.
- Added optional ChromaDB support with graceful ImportError fallback.
- Added deterministic tests for embedder fallback behavior and vector store search/persistence.

## Decisions Made
- GeminiEmbedder uses a TF-IDF fallback when GEMINI_API_KEY is missing, but stores that direct fallback state under /tmp to avoid polluting the project state during direct construction and tests.
- NumpyVectorStore falls back to stdlib cosine math if numpy import fails, while still using numpy when available. This keeps search non-raising as required.
- VectorRecord validates supplied IDs and replaces non-UUID4 IDs with UUID4 values in __post_init__.
- Chroma distances are converted to similarity by 1.0 - distance and clamped to 0.0-1.0.

## Verification
- Targeted: `UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest tests/test_intelligence/ -v`
  - Result: 16 passed
- Full suite: `UV_CACHE_DIR=/tmp/uv-cache PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -v`
  - Result: 205 passed

## Human Review
- ChromaVectorStore is implemented but not exercised in CI because tests intentionally use NumpyVectorStore and ChromaDB may not be installed.

## Next Task Dependency Check
- TASK_28 can depend on core/intelligence/embedder.py and core/intelligence/vector_store.py.
