"""End-to-end smoke test for ProjectOS Phase 4 intelligence components."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

import yaml

import core.projectos as projectos_module
from core.agent_registry import AgentRegistry
from core.events import AgentEvent, AgentResult, EventType
from core.intelligence.code_indexer import CodeIndexer
from core.intelligence.collaboration import (
    COLLABORATION_LOG_NAME,
    CollaborationBroker,
    ConsultationRequest,
    ConsultationType,
)
from core.intelligence.context_retriever import ContextRetriever
from core.intelligence.embedder import TFIDFEmbedder
from core.intelligence.memory_manager import MemoryManager
from core.intelligence.memory_store import MemoryRecord, MemoryStore, MemoryType
from core.intelligence.semantic_router import (
    ROUTING_DECISIONS_FILE_NAME,
    ROUTING_EXAMPLES_COLLECTION,
    RoutingExample,
    SemanticRouter,
)
from core.intelligence.vector_store import BaseVectorStore, NumpyVectorStore
from core.model_provider import ModelProvider
from core.projectos import ProjectOS


ENCODING = "utf-8"
STATE_DIR_NAME = ".projectos_state"
CONFIG_DIR_NAME = "config"
MODELS_FILE_NAME = "models.yaml"
CODE_INDEX_COLLECTION = "code_index"
MEMORY_AGENT_CODE_REVIEW = "code_review"
MEMORY_AGENT_PLANNING = "planning"
SMOKE_PASS_TEXT = "INTELLIGENCE SMOKE: PASSED"
SMOKE_FAIL_TEMPLATE = "INTELLIGENCE SMOKE: FAILED - {reason}"
DEPENDENCY_INJECTION_TEXT = "Use dependency injection pattern"
DESCRIPTION = "new feature request for the system add input validation to API endpoint"
PROJECT_CONTEXT = "API handlers live in api.py."
PYTHON_FENCE = "```python"
DECISIONS_LOG_NAME = "decisions.log"


class SmokeProvider(ModelProvider):
    """Mock provider that records model calls and returns deterministic output."""

    provider_key = "mock"

    def __init__(self, agent_name: str) -> None:
        """Initialize captured calls for one ProjectOS agent."""
        self.agent_name = agent_name
        self.calls: list[tuple[str, str, int]] = []

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Return deterministic model output for the configured agent."""
        self.calls.append((prompt, system_prompt, max_tokens))
        if self.agent_name == MEMORY_AGENT_PLANNING:
            return json.dumps(
                [
                    {
                        "id": "SMOKE-A",
                        "title": "Add API input validation",
                        "type": "feature",
                        "priority": "HIGH",
                        "estimated_complexity": "M",
                        "dependencies": [],
                        "acceptance_criteria": [
                            "Invalid API payloads return a clear validation error."
                        ],
                        "agent_assignment": "code_writing_agent",
                        "blocked_by": None,
                        "file_path": "api.py",
                    }
                ]
            )
        return ""

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield the deterministic completion as one fragment."""
        yield self.complete(prompt, system_prompt, 0)

    def get_model_name(self) -> str:
        """Return the deterministic smoke model name."""
        return f"smoke-{self.agent_name}"


class MockArchitectureAgent:
    """Mock consultation target for collaboration smoke tests."""

    def handle(self, event: AgentEvent) -> AgentResult:
        """Return a deterministic architecture consultation answer."""
        return AgentResult(success=True, output={"answer": DEPENDENCY_INJECTION_TEXT})


def run_smoke(project_root: Optional[Path] = None) -> tuple[bool, str]:
    """Run all intelligence smoke scenarios and return status plus message."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(project_root) if project_root is not None else Path(temp_dir)
            root.mkdir(parents=True, exist_ok=True)
            _scenario_indexing_and_retrieval(root)
            _scenario_memory_storage_and_recall(root)
            _scenario_semantic_routing(root)
            _scenario_collaboration(root)
            _scenario_full_pipeline(root)
        return True, SMOKE_PASS_TEXT
    except Exception as error:
        return False, SMOKE_FAIL_TEMPLATE.format(reason=error)


def main() -> int:
    """Run the smoke test and print the required status line."""
    passed, message = run_smoke()
    print(message)
    return 0 if passed else 1


def _scenario_indexing_and_retrieval(root: Path) -> None:
    """Verify real indexing and retrieval over local Python files."""
    project_dir = root / "scenario_a"
    state_dir = project_dir / STATE_DIR_NAME
    _write_python_project(project_dir)
    embedder = TFIDFEmbedder(state_dir=state_dir)
    vector_store = NumpyVectorStore(CODE_INDEX_COLLECTION, state_dir)
    indexer = CodeIndexer(vector_store, embedder)
    report = indexer.index_directory(project_dir)
    _assert(report.files_indexed == 3, "expected three indexed Python files")
    _assert(report.chunks_created >= 3, "expected at least three code chunks")

    retriever = ContextRetriever(vector_store, embedder)
    context = retriever.retrieve_for_task("review authentication function")
    _assert(bool(context.retrieved_chunks), "retrieval returned no chunks")
    _assert(PYTHON_FENCE in context.formatted_context, "formatted context missed code fence")


def _scenario_memory_storage_and_recall(root: Path) -> None:
    """Verify real memory storage, recall filtering, and access updates."""
    state_dir = root / "scenario_b" / STATE_DIR_NAME
    embedder = TFIDFEmbedder(state_dir=state_dir)
    memory_store = MemoryStore(_numpy_store_factory, embedder, state_dir)
    memory_manager = MemoryManager(memory_store, embedder)
    for index in range(3):
        memory_store.store(
            MemoryRecord(
                memory_id=f"review-memory-{index}",
                memory_type=MemoryType.EPISODIC,
                agent_name=MEMORY_AGENT_CODE_REVIEW,
                content=f"Review auth validation branch {index}.",
                context=f"code review authentication validation {index}",
                importance_score=0.9,
            )
        )
    for index in range(2):
        memory_store.store(
            MemoryRecord(
                memory_id=f"planning-memory-{index}",
                memory_type=MemoryType.SEMANTIC,
                agent_name=MEMORY_AGENT_PLANNING,
                content=f"Planning pattern {index}.",
                context=f"planning backlog decomposition {index}",
                importance_score=0.9,
            )
        )

    recalled = memory_manager.recall(MEMORY_AGENT_CODE_REVIEW, "authentication review", k=3)
    _assert(recalled, "recall returned an empty memory string")
    _assert(MEMORY_AGENT_PLANNING not in recalled, "recall leaked another agent's memory")
    records = _memory_records(memory_store.records_path)
    _assert(
        any(
            record["agent_name"] == MEMORY_AGENT_CODE_REVIEW
            and int(record["access_count"]) > 0
            for record in records
        ),
        "code review memory access count did not increment",
    )


def _scenario_semantic_routing(root: Path) -> None:
    """Verify semantic routing categories and persisted decisions."""
    state_dir = root / "scenario_c" / STATE_DIR_NAME
    embedder = TFIDFEmbedder(state_dir=state_dir)
    vector_store = NumpyVectorStore(ROUTING_EXAMPLES_COLLECTION, state_dir)
    router = SemanticRouter(
        embedder,
        vector_store,
        log_path=state_dir / ROUTING_DECISIONS_FILE_NAME,
    )
    autonomous = router.route("updating a docstring in a utility function")
    _assert(autonomous.category == "AUTONOMOUS", "docstring route was not autonomous")
    escalation = router.route("added requests library as new dependency")
    _assert(escalation.category == "ESCALATE", "dependency route did not escalate")
    _assert(
        escalation.routing_method in {"semantic", "keyword_fallback"},
        "unexpected routing method",
    )


def _scenario_collaboration(root: Path) -> None:
    """Verify bounded collaboration consultations."""
    registry = AgentRegistry()
    registry.register("architecture", MockArchitectureAgent())  # type: ignore[arg-type]
    broker = CollaborationBroker(
        registry,
        root / "scenario_d" / STATE_DIR_NAME / COLLABORATION_LOG_NAME,
    )
    allowed = broker.consult(_consultation_request(depth=0))
    _assert(
        "dependency injection" in allowed.answer.lower(),
        "allowed consultation missed dependency injection answer",
    )
    _assert(allowed.depth == 0, "allowed consultation depth changed")
    blocked = broker.consult(_consultation_request(depth=1))
    _assert("depth limit" in blocked.answer, "depth-limited consultation was allowed")


def _scenario_full_pipeline(root: Path) -> None:
    """Verify ProjectOS wires routing, context retrieval, memory, and Planning."""
    project_dir = root / "scenario_e"
    state_dir = project_dir / STATE_DIR_NAME
    logging.getLogger(f"projectos.{project_dir.name}").disabled = True
    _write_python_project(project_dir)
    _write_config(project_dir)
    providers: dict[str, SmokeProvider] = {}
    original_factory = projectos_module.VectorStoreFactory.create
    projectos_module.VectorStoreFactory.create = staticmethod(_numpy_store_factory)
    try:
        project_os = ProjectOS(
            project_dir / CONFIG_DIR_NAME / MODELS_FILE_NAME,
            provider_factory=_provider_factory(providers),
            project_root=project_dir,
            state_dir=state_dir,
        )
        project_os.clone_agent.task_queue = None
        project_os.semantic_router.add_example(
            RoutingExample(
                text=f"MANUAL_TRIGGER: {str(_manual_payload())}",
                category=MEMORY_AGENT_PLANNING,
                weight=3.0,
            )
        )
        project_os.memory_manager.remember_workflow(
            MEMORY_AGENT_PLANNING,
            "input validation planning",
            ["inspect endpoint", "split validation task"],
            0.9,
        )
        project_os._build_code_index()
        parent_result = project_os.submit_event(
            AgentEvent(
                event_type=EventType.MANUAL_TRIGGER,
                source_agent="intelligence_smoke",
                payload=_manual_payload(),
            )
        )
        _assert(parent_result.next_events, "Clone produced no routed event")
        planning_event = parent_result.next_events[0]
        planning_agent = project_os.agent_registry.get(MEMORY_AGENT_PLANNING)
        planning_result = planning_agent.handle(planning_event)
        _assert(planning_result.success, "PlanningAgent failed in full pipeline")
    finally:
        if "project_os" in locals():
            project_os.task_queue.shutdown(wait=True)
        projectos_module.VectorStoreFactory.create = original_factory

    planning_provider = providers[MEMORY_AGENT_PLANNING]
    _assert(planning_provider.calls, "Planning provider was not called")
    prompt, system_prompt, _max_tokens = planning_provider.calls[-1]
    _assert("Codebase context:" in prompt, "Planning prompt missed codebase context")
    _assert(PYTHON_FENCE in prompt, "Planning prompt missed retrieved Python code")
    _assert(
        "Similar planning decisions" in system_prompt,
        "Planning system prompt missed memory context",
    )
    decisions_log = project_dir / DECISIONS_LOG_NAME
    routing_log = state_dir / ROUTING_DECISIONS_FILE_NAME
    _assert(decisions_log.exists() and decisions_log.read_text(encoding=ENCODING), "decisions.log empty")
    _assert(routing_log.exists() and routing_log.read_text(encoding=ENCODING), "routing log empty")


def _consultation_request(depth: int) -> ConsultationRequest:
    """Return a standard smoke consultation request."""
    return ConsultationRequest(
        requesting_agent="code_writing",
        target_agent="architecture",
        consultation_type=ConsultationType.ARCHITECTURE_REVIEW,
        question="Which pattern should this use?",
        context="class ApiHandler: pass",
        depth=depth,
    )


def _provider_factory(providers: dict[str, SmokeProvider]) -> Any:
    """Return a provider factory that captures providers by agent name."""
    def factory(agent_name: str, _config_path: Path) -> SmokeProvider:
        """Create and retain one smoke provider."""
        provider = SmokeProvider(agent_name)
        providers[agent_name] = provider
        return provider

    return factory


def _numpy_store_factory(
    collection_name: str,
    state_dir: Path,
    _embedder: Any,
) -> BaseVectorStore:
    """Return a deterministic local vector store."""
    return NumpyVectorStore(collection_name, state_dir)


def _manual_payload() -> dict[str, str]:
    """Return the manual trigger payload used by the full pipeline."""
    return {
        "description": DESCRIPTION,
        "project_context": PROJECT_CONTEXT,
    }


def _write_python_project(project_dir: Path) -> None:
    """Create a small Python project used by smoke scenarios."""
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "auth.py").write_text(
        '''"""Authentication helpers."""


def authenticate_user(token: str) -> bool:
    """Return whether an API token is present."""
    return bool(token and token.strip())
''',
        encoding=ENCODING,
    )
    (project_dir / "api.py").write_text(
        '''"""API endpoint module."""

from auth import authenticate_user


def handle_request(payload: dict[str, str]) -> str:
    """Handle an incoming request."""
    return "ok" if authenticate_user(payload.get("token", "")) else "denied"
''',
        encoding=ENCODING,
    )
    (project_dir / "validation.py").write_text(
        '''"""Validation helpers."""


def require_field(payload: dict[str, str], field: str) -> bool:
    """Return whether a payload field is present."""
    return bool(payload.get(field))
''',
        encoding=ENCODING,
    )


def _write_config(project_dir: Path) -> None:
    """Write a complete models config for ProjectOS initialization."""
    config_dir = project_dir / CONFIG_DIR_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "providers": {"mock": {"default_model": "mock"}},
        "agents": {
            "clone": {"provider": "mock", "model": "mock-clone"},
            "planning": {"provider": "mock", "model": "mock-planning"},
            "code_writing": {"provider": "mock", "model": "mock-code-writing"},
            "code_review": {"provider": "mock", "model": "mock-code-review"},
            "architecture": {"provider": "mock", "model": "mock-architecture"},
            "test": {"provider": "mock", "model": "mock-test"},
            "docs": {"provider": "mock", "model": "mock-docs"},
        },
    }
    (config_dir / MODELS_FILE_NAME).write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding=ENCODING,
    )


def _memory_records(path: Path) -> list[Mapping[str, Any]]:
    """Return memory records from JSONL."""
    return [
        json.loads(line)
        for line in path.read_text(encoding=ENCODING).splitlines()
        if line.strip()
    ]


def _assert(condition: bool, message: str) -> None:
    """Raise AssertionError with message when condition is false."""
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
