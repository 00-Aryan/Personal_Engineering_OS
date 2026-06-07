# ProjectOS Dogfooding Report

This document details the dogfooding setup, runtime execution flow, and findings when running ProjectOS on its own codebase.

## 1. Dogfooding Design and Flow

Dogfooding is executed using the `scripts/dogfood.py` script. The script mimics the production orchestration flow by performing the following steps:

1. **Initialization**: Starts a `ProjectOS` instance pointing to the current repository directory.
2. **Provider Configuration**: Checks if live API keys are present (via `.projectos_state/provider_status.json`). If none are available, it automatically activates mock mode using a custom `DogfoodMockModelProvider`.
3. **Trigger Simulation**: Generates a temporary Python file `agents/dogfood_temp.py` and submits a `CODE_CHANGED` event for it to the orchestrator.
4. **Execution Verification**: Verifies that the supervisor (`CloneAgent`) receives the event, classifies it, and routes it to `code_review` (which generates `reviews/dogfood_temp_review.md`), `test`, and `docs` agents.
5. **Clean Shutdown and Cleanup**: Waits for the task queue to settle, shuts down cleanly, and deletes all generated temporary files.

## 2. Simulated Run Results

A mock dogfooding run was executed successfully:
- All stages of the pipeline (AST-based code indexing, event classification, agent routing, review output generation, and clean queue teardown) executed in under 5 seconds.
- Review reports were successfully formatted and stored under `reviews/`.
- Git commits were safely bypassed due to protected branch safeguards on the `main` branch.
- The execution ended with a clean exit code 0 and printed `DOGFOOD RUN: PASSED`.

## 3. Codebase Observations and Critical Fixes

During the initial dogfooding runs, two critical, previously hidden bugs were discovered and successfully resolved:

### A. Circular Initialization Dependency (`core/projectos.py`)
- **Observation**: When initializing `ProjectOS` with any configuration containing a `fallback_chain` (like the default `config/models.yaml`), the constructor crashed with an `AttributeError` stating that `self.provider_health_monitor` was missing.
- **Root Cause**: `self.providers` was initialized via `_initialize_providers()`, which referenced `fallback_chain` configs. The instantiations of the fallback chains required `self.provider_health_monitor`. However, `self.provider_health_monitor` was defined *after* `self.providers`.
- **Fix**: Re-ordered the initialization sequence. `self.provider_health_monitor` is now initialized first with an empty targets list. Once `self.providers` is constructed, the health monitor's target list is dynamically updated with the resolved providers.

### B. ChromaDB Metadata Type Violation (`core/intelligence/vector_store.py`)
- **Observation**: The indexing engine crashed with the error `Cannot convert Python object to MetadataValue`.
- **Root Cause**: In AST parsing, chunks contain metadata fields like `parent_name` or `docstring` which can be `None`. The vector store's Chroma integration was passing `None` values into ChromaDB. Newer versions of ChromaDB reject `None` as a valid metadata type.
- **Fix**: Modified `ChromaVectorStore._metadata()` to filter out keys whose values are `None`, which is fully compatible with ChromaDB and returns `None` naturally when queried using `.get()`.
