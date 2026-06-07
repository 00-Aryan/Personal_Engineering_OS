# Multi-Project Management & Isolation in ProjectOS

This document details the multi-project management architecture, the state and directory isolation mechanisms, and the verification results of processing an external project.

## 1. Multi-Project Architecture

ProjectOS supports managing multiple target codebases (both internal and external) using a registry-daemon model. The architecture is composed of the following key components:

- **[ProjectConfig](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/project_config.py#L73)**: Data class representing the configuration of a single managed project. It defines the name, root directory, file watching/ignoring patterns, state directory path, and model/provider configuration.
- **[ProjectRegistry](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/project_config.py#L172)**: Handles persistence and querying of project registrations. It persists project configs to a global-style registry configuration file (`projects.yaml`).
- **[MultiProjectOS](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/projectos.py#L686)**: The daemon orchestrator that manages multiple active runtimes. It initializes separate thread-bound runtime instances of [ProjectOS](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/projectos.py#L163) for all enabled registered projects, coordinates their startup and shutdown lifecycle, and tracks their live status.

---

## 2. State & Directory Isolation Mechanisms

To ensure that multiple active projects run side-by-side without interfering with each other's configurations, decisions, or trace outputs, ProjectOS enforces strict boundaries:

### A. State Directory Isolation
Every project config resolves its own `state_dir` (defaulting to `<project_root>/.projectos_state`). All observability, cost-tracking, token budgeting, and collaboration logs are directed to this localized state directory:
- **Trace logs** are written to `<state_dir>/traces.jsonl`.
- **Token budgets** are tracked in `<state_dir>/token_budget_status.json`.
- **Cost data** is saved to `<state_dir>/cost_tracker_status.json`.
- **Collaboration log** is kept in `<state_dir>/collaboration.jsonl`.
This prevents concurrent projects from reading or modifying each other's budgets and performance traces.

### B. Workspace Directory Safety
All file reads, file writes, and watch patterns are strictly rooted within the project's own `root_path`. Review outputs (e.g. `reviews/`) and source code edits are strictly contained within the targeted workspace.

### C. Independent Provider & Model Configuration
Each project can specify its own `models_config` path. This allows individual codebases to configure distinct model provider fallbacks (e.g., local Ollama instance for security vs. cloud-based Gemini Flash/Pro APIs for deep code reasoning) and separate rate limits.

### D. Thread Isolation
Each project runtime executes on its own event-processing background thread. Centralized locking is used within [MultiProjectOS](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/projectos.py#L686) during daemon startup, shutdown, and status polling to prevent race conditions.

---

## 3. External Project Verification

Verification of processing an external project located outside the main ProjectOS repository was performed using a dedicated validation suite.

### A. Verification Script
The automated verification script **[scripts/process_external.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/scripts/process_external.py)** performs the following workflow:
1. Creates a temporary project workspace in the scratch space (`scratch/external_project_temp`).
2. Scaffolds the standard directories (`agents/`, `reviews/`, `config/`).
3. Registers the project in a temporary project registry (`projects_temp.yaml`).
4. Spins up a mock daemon with [MultiProjectOS](file:///home/aryan/June-2026/Personal_Engineering%20_OS/core/projectos.py#L686).
5. Writes a dummy code file (`helper.py`) and submits a `CODE_CHANGED` event.
6. Asserts that the supervisor `CloneAgent` orchestrates the task and writes code reviews to the external project's local `reviews/` directory.
7. Asserts that the runtime state is captured inside the external project's `.projectos_state/` directory.
8. Unregisters the project and deletes all temporary files, ensuring a zero-footprint teardown.

### B. Verification Run Output
A test execution of [scripts/process_external.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/scripts/process_external.py) passes successfully:
```
Registering external project...
Starting MultiProjectOS daemon...
Submitting event 5d83b0da-4464-4f89-b22e-4268db59260b to external project...
EXTERNAL PROJECT RUN: PASSED
```

### C. Automated Unit & Integration Tests
The integration tests in **[tests/test_external.py](file:///home/aryan/June-2026/Personal_Engineering%20_OS/tests/test_external.py)** confirm the robustness of the multi-project engine:
- `test_project_registry_isolation`: Validates that adding, querying, and removing projects does not impact other registries.
- `test_multi_project_os_starts_and_stops`: Confirms that the orchestrator daemon initializes and terminates multiple project runtimes in parallel.
- `test_state_and_file_isolation`: Simulates concurrent events in multiple runtimes, confirming that reviews, state directories, and decisions files do not leak across project boundaries.
