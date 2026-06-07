"""Main ProjectOS orchestrator."""

from __future__ import annotations

import logging
import os
import queue
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import yaml

from agents.architecture_agent import ArchitectureAgent
from agents.code_review_agent import CodeReviewAgent
from agents.code_writing_agent import CodeWritingAgent
from agents.docs_agent import DocsAgent
from agents.planning_agent import PlanningAgent
from agents.test_agent import TestAgent
from core.agent_registry import AgentRegistry
from core.clone_agent import CloneAgent
from core.observability.tracer import Tracer, TraceStore
from core.observability.token_budget import TokenBudget
from core.observability.cost_tracker import CostTracker
from core.observability.rate_limiter import ProviderRateLimits
from core.observability.circuit_breaker import CircuitBreaker
from core.observability.alerting import AlertManager
from core.evaluation.criteria_library import (
    code_review_criteria,
    code_writing_criteria,
    documentation_criteria,
    planning_criteria,
)
from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.llm_judge import LLMJudge
from core.evaluation.quality_gate import DEFAULT_POLICIES, GATE_LOG_NAME, QualityGate
from core.evaluation.quality_scorer import QualityScorer
from core.evaluation.regression_detector import RegressionDetector
from core.evaluation.schema_validator import DEFAULT_SCHEMAS, SchemaValidator
from core.evaluation.static_analyzer import StaticAnalyzer
from core.events import AgentEvent, AgentResult
from core.git_manager import GitManager
from core.intelligence.code_indexer import CodeIndexer, IndexingReport
from core.intelligence.collaboration import COLLABORATION_LOG_NAME, CollaborationBroker
from core.intelligence.context_retriever import ContextRetriever
from core.intelligence.embedder import EmbedderFactory
from core.intelligence.memory_manager import MemoryManager
from core.intelligence.memory_store import MemoryStore
from core.intelligence.semantic_router import (
    ROUTING_DECISIONS_FILE_NAME,
    ROUTING_EXAMPLES_COLLECTION,
    SemanticRouter,
)
from core.intelligence.vector_store import VectorStoreFactory
from core.model_provider import GeminiProvider, OllamaProvider, OpenRouterProvider
from core.persistence import PersistenceManager
from core.project_config import ProjectConfig, ProjectRegistry
from core.provider_health import ProviderHealthMonitor
from core.safety import DefaultSafetyPolicy
from core.task_queue import TaskQueue
from core.trigger_system import TriggerSystem


DEFAULT_CONFIG_PATH = Path("config/projectos.yaml")
CONFIG_DIR_NAME = "config"
DECISIONS_LOG_NAME = "decisions.log"
STATE_DIR_NAME = ".projectos_state"
ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

CONFIG_KEY_AGENTS = "agents"
CONFIG_KEY_MODEL = "model"
CONFIG_KEY_PROVIDER = "provider"

AGENT_CLONE = "clone"
AGENT_PLANNING = "planning"
AGENT_CODE_WRITING = "code_writing"
AGENT_CODE_REVIEW = "code_review"
AGENT_ARCHITECTURE = "architecture"
AGENT_TEST = "test"
AGENT_DOCS = "docs"

ALIAS_SUFFIX = "_agent"
WORKER_AGENT_NAMES = (
    AGENT_PLANNING,
    AGENT_CODE_WRITING,
    AGENT_CODE_REVIEW,
    AGENT_ARCHITECTURE,
    AGENT_TEST,
    AGENT_DOCS,
)
ALL_AGENT_NAMES = (AGENT_CLONE,) + WORKER_AGENT_NAMES

PROVIDER_CLASSES = {
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
    "openrouter": OpenRouterProvider,
}

LOGGER_NAME = "projectos"
EVENT_QUEUE_TIMEOUT_SECONDS = 0.2
EVENT_THREAD_JOIN_SECONDS = 1.0
MULTI_PROJECT_THREAD_JOIN_SECONDS = 1.0
TASK_QUEUE_WORKERS = 4
FINAL_STATUS_REASON = "ProjectOS stopped cleanly"
PAYLOAD_KEY_TARGET_AGENT = "target_agent"
RESTORE_LOG_TEMPLATE = (
    "Restored {pending_count} pending events and {blocked_count} blocked tasks"
)
GIT_REPO_WARNING = "ProjectOS git integration disabled: not a git repo"
STATUS_KEY_RUNNING = "running"
STATUS_KEY_ROOT_PATH = "root_path"
STATUS_KEY_PENDING_COUNT = "pending_count"
STATUS_KEY_BLOCKED_COUNT = "blocked_count"
STATUS_KEY_PROVIDERS = "providers"
CODE_INDEX_COLLECTION_NAME = "code_index"
INDEXING_LOG_TEMPLATE = (
    "Code index built: {files} files, {chunks} chunks, {duration_ms} ms"
)
MEMORY_STATS_LOG_TEMPLATE = "Memory stats for {agent_name}: {total_records} records"

ProviderFactory = Callable[[str, Path], Any]


def _write_atomically(path: Path, content: str) -> None:
    """Write content to a path by replacing it with a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{TEMP_PREFIX}{path.name}.",
        suffix=TEMP_SUFFIX,
        dir=str(path.parent),
    )
    try:
        with os.fdopen(
            file_descriptor,
            FILE_WRITE_MODE,
            encoding=ENCODING,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file while preserving existing content."""
    existing_content = path.read_text(encoding=ENCODING) if path.exists() else EMPTY_TEXT
    _write_atomically(path, f"{existing_content}{content}")


class ProjectOS:
    """Main orchestrator that wires Clone, agents, triggers, and queue."""

    def __init__(
        self,
        config_path: Path = DEFAULT_CONFIG_PATH,
        provider_factory: Optional[ProviderFactory] = None,
        project_root: Optional[Path | str] = None,
        state_dir: Optional[Path | str] = None,
        project_name: Optional[str] = None,
        watch_patterns: Optional[list[str]] = None,
        ignore_patterns: Optional[list[str]] = None,
    ) -> None:
        """Load configuration and initialize ProjectOS runtime components."""
        self.config_path = Path(config_path)
        
        is_new_config = False
        master_config = None
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding=ENCODING) as f:
                    peek = yaml.safe_load(f)
                if isinstance(peek, dict) and ("project" in peek or peek.get("version") == "0.3.0" or "token_budgets" in peek):
                    is_new_config = True
            except Exception:
                pass

        if is_new_config:
            from core.config_loader import ProjectConfig as MasterProjectConfig
            env_file = (Path(project_root) if project_root else Path(".")).resolve() / ".env"
            if not env_file.exists():
                env_file = Path(".env")
            master_config = MasterProjectConfig.load(self.config_path, env_file=env_file)
            
            self.project_root = Path(project_root).resolve() if project_root is not None else master_config.project_root
            self.project_name = project_name or master_config.project_name
            self.state_dir = Path(state_dir).resolve() if state_dir is not None else master_config.state_dir
            self.watch_patterns = watch_patterns if watch_patterns is not None else master_config.watch_patterns
            self.ignore_patterns = ignore_patterns if ignore_patterns is not None else master_config.ignore_patterns
        else:
            self.project_root = (
                Path(project_root).resolve()
                if project_root is not None
                else self._project_root_for_config(self.config_path)
            )
            self.project_name = project_name or self.project_root.name
            self.state_dir = (
                Path(state_dir).resolve()
                if state_dir is not None
                else self.project_root / STATE_DIR_NAME
            )
            self.watch_patterns = watch_patterns
            self.ignore_patterns = ignore_patterns

        self.config = self._load_config()
        self.provider_factory = provider_factory
        self.logger = logging.getLogger(f"{LOGGER_NAME}.{self.project_name}")
        self.trace_store = TraceStore(self.state_dir)
        self.tracer = Tracer(self.trace_store, enabled=True)

        token_budgets_config = None
        self.quality_gates_config = {}
        circuit_breaker_threshold = None
        circuit_breaker_timeout = None
        circuit_breaker_min_open = None
        circuit_breaker_success_threshold = None
        alerts_config = None
        usd_to_inr = 83.5

        if master_config:
            token_budgets_config = master_config.token_budgets
            self.quality_gates_config = master_config.quality_gates
            circuit_breaker_threshold = master_config.circuit_breaker_failure_threshold
            circuit_breaker_timeout = float(master_config.circuit_breaker_recovery_timeout_seconds)
            circuit_breaker_min_open = float(master_config.circuit_breaker_minimum_open_duration)
            circuit_breaker_success_threshold = int(master_config.circuit_breaker_consecutive_success_threshold)
            alerts_config = master_config.raw_config.get("alerts", {})
            usd_to_inr = master_config.usd_to_inr
        else:
            try:
                usd_to_inr = float(self.config.get("pricing", {}).get("usd_to_inr", 83.5))
            except Exception:
                pass

        self.token_budget = TokenBudget(self.state_dir, budgets=token_budgets_config)
        custom_catalog = self.config.get("pricing", {}).get("catalog", None)
        self.cost_tracker = CostTracker(
            self.state_dir,
            usd_to_inr=usd_to_inr,
            pricing_catalog=custom_catalog
        )
        self.cost_tracker.tracer = self.tracer
        self.circuit_breakers = {
            "gemini": CircuitBreaker(
                "gemini",
                failure_threshold=circuit_breaker_threshold,
                recovery_timeout=circuit_breaker_timeout,
                state_dir=self.state_dir,
                minimum_open_duration=circuit_breaker_min_open,
                consecutive_success_threshold=circuit_breaker_success_threshold,
            ),
            "openrouter": CircuitBreaker(
                "openrouter",
                failure_threshold=circuit_breaker_threshold,
                recovery_timeout=circuit_breaker_timeout,
                state_dir=self.state_dir,
                minimum_open_duration=circuit_breaker_min_open,
                consecutive_success_threshold=circuit_breaker_success_threshold,
            ),
            "ollama": CircuitBreaker(
                "ollama",
                failure_threshold=circuit_breaker_threshold,
                recovery_timeout=circuit_breaker_timeout,
                state_dir=self.state_dir,
                minimum_open_duration=circuit_breaker_min_open,
                consecutive_success_threshold=circuit_breaker_success_threshold,
            ),
        }
        self.provider_health_monitor = ProviderHealthMonitor({})
        self.providers = self._initialize_providers()
        health_targets = self._provider_health_targets()
        self.provider_health_monitor.providers.update(health_targets)
        for name in health_targets:
            if name not in self.provider_health_monitor._status:
                self.provider_health_monitor._status[name] = False
        self.git_manager = self._initialize_git_manager()
        self.agent_registry = AgentRegistry()
        self.collaboration_broker = CollaborationBroker(
            self.agent_registry,
            self.state_dir / COLLABORATION_LOG_NAME,
        )
        self.event_queue: queue.Queue[AgentEvent] = queue.Queue()
        self.stop_event = threading.Event()
        self.safety_policy = DefaultSafetyPolicy(self.project_root)
        self.persistence_manager = PersistenceManager(self.state_dir)
        self.embedder = EmbedderFactory.create(self.state_dir)
        self.vector_store = VectorStoreFactory.create(
            CODE_INDEX_COLLECTION_NAME,
            self.state_dir,
            self.embedder,
        )
        self.routing_vector_store = VectorStoreFactory.create(
            ROUTING_EXAMPLES_COLLECTION,
            self.state_dir,
            self.embedder,
        )
        self.code_indexer = CodeIndexer(self.vector_store, self.embedder)
        self.context_retriever = ContextRetriever(
            self.vector_store,
            self.embedder,
            tracer=self.tracer,
            token_budget=self.token_budget,
        )
        self.semantic_router = SemanticRouter(
            self.embedder,
            self.routing_vector_store,
            log_path=self.state_dir / ROUTING_DECISIONS_FILE_NAME,
        )
        self.memory_store = MemoryStore(
            VectorStoreFactory.create,
            self.embedder,
            self.state_dir,
        )
        self.memory_manager = MemoryManager(self.memory_store, self.embedder, tracer=self.tracer)
        self.evaluation_store = EvaluationStore(self.state_dir)
        self.static_analyzer = StaticAnalyzer()
        self.quality_scorer = QualityScorer(
            self.static_analyzer,
            self.evaluation_store,
        )
        self.schema_validator = SchemaValidator(DEFAULT_SCHEMAS)
        self.regression_detector = RegressionDetector(
            self.evaluation_store,
            self.state_dir,
        )
        from core.evaluation.quality_gate import DEFAULT_POLICIES, GatePolicy
        policies = dict(DEFAULT_POLICIES)
        if self.quality_gates_config:
            for agent_name, gate in self.quality_gates_config.items():
                default_policy = DEFAULT_POLICIES.get(agent_name)
                min_score = gate.get("min_score", default_policy.min_combined_score if default_policy else 0.50)
                req_llm = gate.get("require_llm_eval", default_policy.require_llm_evaluation if default_policy else False)
                req_static = gate.get("require_static", default_policy.require_static_analysis if default_policy else False)
                block_sec = gate.get("block_security_high", default_policy.block_on_security_high if default_policy else True)
                block_reg = gate.get("block_regression", default_policy.block_on_regression if default_policy else False)
                
                policies[agent_name] = GatePolicy(
                    agent_name=agent_name,
                    min_combined_score=min_score,
                    require_llm_evaluation=req_llm,
                    require_static_analysis=req_static,
                    block_on_security_high=block_sec,
                    block_on_regression=block_reg
                )
        self.quality_gate = QualityGate(
            policies,
            self.quality_scorer,
            self.regression_detector,
            self.state_dir / GATE_LOG_NAME,
            tracer=self.tracer,
        )
        self.alert_manager = AlertManager(self.state_dir, alerts_config=alerts_config)
        self.quality_evaluators = self._initialize_quality_evaluators()
        self.task_queue = TaskQueue(
            max_workers=TASK_QUEUE_WORKERS,
            result_callback=self._handle_agent_result,
            persistence_manager=self.persistence_manager,
        )
        self.clone_agent = self._initialize_agents()
        self.trigger_system = TriggerSystem(
            self.project_root,
            self.event_queue,
            watch_patterns=self.watch_patterns,
            ignore_patterns=self.ignore_patterns,
            code_indexer=self.code_indexer,
        )
        self._event_thread: Optional[threading.Thread] = None

    @classmethod
    def from_project_config(
        cls,
        config: ProjectConfig,
        provider_factory: Optional[ProviderFactory] = None,
    ) -> "ProjectOS":
        """Create a ProjectOS runtime from a registered project config."""
        return cls(
            config_path=config.models_config,
            provider_factory=provider_factory,
            project_root=config.root_path,
            state_dir=config.state_dir,
            project_name=config.name,
            watch_patterns=config.watch_patterns,
            ignore_patterns=config.ignore_patterns,
        )

    def start(self) -> None:
        """Start trigger watching and event-loop processing."""
        if self._event_thread is not None and self._event_thread.is_alive():
            return

        import signal
        try:
            signal.signal(signal.SIGINT, self._shutdown_handler)
            signal.signal(signal.SIGTERM, self._shutdown_handler)
        except ValueError:
            pass

        self.stop_event.clear()
        if self.tracer and self.tracer.enabled:
            self.logger.info("Tracing enabled. Traces stored in .projectos_state/")
        self._build_code_index()
        self._log_memory_stats()
        self._restore_persisted_queue_state()
        self.provider_health_monitor.start()
        self.alert_manager.start()
        self.trigger_system.start()
        self._event_thread = threading.Thread(
            target=self._event_loop,
            name=LOGGER_NAME,
            daemon=True,
        )
        self._event_thread.start()

    def stop(self) -> None:
        """Gracefully stop trigger watching, workers, and event processing."""
        self.stop_event.set()
        self.trigger_system.stop()
        self.provider_health_monitor.stop()
        self.alert_manager.stop()
        if self._event_thread is not None:
            self._event_thread.join(timeout=EVENT_THREAD_JOIN_SECONDS)
        self.task_queue.shutdown(wait=True)
        self.persistence_manager.snapshot_status(
            self._agent_statuses(),
            self.provider_health_monitor.get_status(),
        )
        self._log_final_status()

    def _shutdown_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals gracefully and exit."""
        import sys
        self.logger.info("Signal %d received, shutting down gracefully...", signum)
        self.stop_event.set()
        self.trigger_system.stop()
        self.provider_health_monitor.stop()
        
        def shutdown_queue():
            self.task_queue.shutdown(wait=True)
        t = threading.Thread(target=shutdown_queue)
        t.start()
        t.join(timeout=10.0)
        
        self.alert_manager.stop()
        sys.stdout.flush()
        sys.stderr.flush()
        
        self.persistence_manager.snapshot_status(
            self._agent_statuses(),
            self.provider_health_monitor.get_status(),
        )
        self._log_final_status()
        self.logger.info("ProjectOS shutdown complete")
        sys.exit(0)

    def submit_event(self, event: AgentEvent) -> AgentResult:
        """Submit one event directly to Clone for orchestration."""
        return self.clone_agent.handle(event)

    def _event_loop(self) -> None:
        """Read trigger events and pass each one through Clone."""
        while not self.stop_event.is_set():
            try:
                event = self.event_queue.get(timeout=EVENT_QUEUE_TIMEOUT_SECONDS)
            except queue.Empty:
                continue
            self.clone_agent.handle(event)

    def _handle_agent_result(self, result: AgentResult) -> None:
        """Route agent next_events back through Clone."""
        self.clone_agent.process_agent_result(result)
        for next_event in result.next_events:
            self.clone_agent.handle(next_event)

    def _build_code_index(self) -> IndexingReport:
        """Rebuild the project code index and log the report."""
        self.code_indexer.clear()
        report = self.code_indexer.index_directory(self.project_root)
        self.logger.info(
            INDEXING_LOG_TEMPLATE.format(
                files=report.files_indexed,
                chunks=report.chunks_created,
                duration_ms=report.duration_ms,
            )
        )
        return report

    def _log_memory_stats(self) -> None:
        """Log memory counts for agents with stored memories."""
        for agent_name in ALL_AGENT_NAMES:
            stats = self.memory_store.get_stats(agent_name)
            total_records = int(stats.get("total_records", 0))
            if total_records <= 0:
                continue
            self.logger.info(
                MEMORY_STATS_LOG_TEMPLATE.format(
                    agent_name=agent_name,
                    total_records=total_records,
                )
            )

    def _restore_persisted_queue_state(self) -> None:
        """Restore durable pending and blocked queue items."""
        restored_pending_count = self._restore_pending_events()
        restored_blocked_count = self._restore_blocked_events()
        self.logger.info(
            RESTORE_LOG_TEMPLATE.format(
                pending_count=restored_pending_count,
                blocked_count=restored_blocked_count,
            )
        )

    def _restore_pending_events(self) -> int:
        """Load persisted pending events and resubmit dispatchable ones."""
        restored_count = 0
        for event in self.persistence_manager.load_pending_events():
            target_agent = self._target_agent_for_event(event)
            if target_agent is None:
                continue
            self.persistence_manager.clear_pending_event(event.event_id)
            self.task_queue.submit(event, target_agent)
            restored_count += 1
        return restored_count

    def _restore_blocked_events(self) -> int:
        """Load persisted blocked events into the task queue."""
        restored_count = 0
        for event in self.persistence_manager.load_blocked_tasks():
            target_agent = self._target_agent_for_event(event)
            if target_agent is None:
                continue
            self.task_queue.restore_blocked(event, target_agent)
            restored_count += 1
        return restored_count

    def _target_agent_for_event(self, event: AgentEvent) -> Optional[Any]:
        """Return the registered target agent for a persisted event."""
        target_agent_name = event.payload.get(PAYLOAD_KEY_TARGET_AGENT)
        if not isinstance(target_agent_name, str) or not target_agent_name:
            return None
        try:
            return self.agent_registry.get(target_agent_name)
        except KeyError:
            self.logger.warning("Persisted event target missing: %s", target_agent_name)
            return None

    def _initialize_providers(self) -> dict[str, Any]:
        """Initialize configured providers for all ProjectOS agents."""
        return {
            agent_name: self._provider_for_agent(agent_name)
            for agent_name in ALL_AGENT_NAMES
        }

    def _initialize_agents(self) -> CloneAgent:
        """Initialize and register Clone plus all worker agents."""
        logger = self.logger
        worker_agents = {
            AGENT_PLANNING: PlanningAgent(
                self.providers[AGENT_PLANNING],
                logger,
                project_root=self.project_root,
                context_retriever=self.context_retriever,
                memory_manager=self.memory_manager,
                collaboration_broker=self.collaboration_broker,
            ),
            AGENT_CODE_WRITING: CodeWritingAgent(
                self.providers[AGENT_CODE_WRITING],
                logger,
                project_root=self.project_root,
                safety_policy=self.safety_policy,
                static_analyzer=self.static_analyzer,
                context_retriever=self.context_retriever,
                memory_manager=self.memory_manager,
                collaboration_broker=self.collaboration_broker,
                tracer=self.tracer,
            ),
            AGENT_CODE_REVIEW: CodeReviewAgent(
                self.providers[AGENT_CODE_REVIEW],
                logger,
                project_root=self.project_root,
                git_manager=self.git_manager,
                context_retriever=self.context_retriever,
                memory_manager=self.memory_manager,
                collaboration_broker=self.collaboration_broker,
                tracer=self.tracer,
            ),
            AGENT_ARCHITECTURE: ArchitectureAgent(
                self.providers[AGENT_ARCHITECTURE],
                logger,
                project_root=self.project_root,
                memory_manager=self.memory_manager,
                collaboration_broker=self.collaboration_broker,
            ),
            AGENT_TEST: TestAgent(
                self.providers[AGENT_TEST],
                logger,
                project_root=self.project_root,
                memory_manager=self.memory_manager,
                collaboration_broker=self.collaboration_broker,
            ),
            AGENT_DOCS: DocsAgent(
                self.providers[AGENT_DOCS],
                logger,
                project_root=self.project_root,
                memory_manager=self.memory_manager,
                collaboration_broker=self.collaboration_broker,
            ),
        }
        for agent_name, agent_instance in worker_agents.items():
            self._register_agent_with_alias(agent_name, agent_instance)

        clone_agent = CloneAgent(
            self.providers[AGENT_CLONE],
            logger,
            project_root=self.project_root,
            agent_registry=self.agent_registry,
            task_queue=self.task_queue,
            schema_validator=self.schema_validator,
            regression_detector=self.regression_detector,
            evaluation_store=self.evaluation_store,
            quality_gate=self.quality_gate,
            memory_manager=self.memory_manager,
            semantic_router=self.semantic_router,
            collaboration_broker=self.collaboration_broker,
            tracer=self.tracer,
        )
        self._register_agent_with_alias(AGENT_CLONE, clone_agent)
        return clone_agent

    def _initialize_quality_evaluators(self) -> dict[str, LLMJudge]:
        """Initialize LLM judges using configured non-identical providers."""
        criteria_by_agent = {
            AGENT_CODE_WRITING: code_writing_criteria(),
            AGENT_CODE_REVIEW: code_review_criteria(),
            AGENT_PLANNING: planning_criteria(),
            AGENT_DOCS: documentation_criteria(),
        }
        return {
            agent_name: LLMJudge(self._judge_provider_for_agent(agent_name), criteria)
            for agent_name, criteria in criteria_by_agent.items()
        }

    def _judge_provider_for_agent(self, agent_name: str) -> Any:
        """Return a judge provider different from the evaluated agent when possible."""
        agent_provider_name = self._agent_provider_name(agent_name)
        for candidate_name, provider in self.providers.items():
            if candidate_name == agent_name:
                continue
            if self._agent_provider_name(candidate_name) != agent_provider_name:
                return provider
        return self.providers[AGENT_CLONE]

    def _register_agent_with_alias(self, name: str, agent_instance: Any) -> None:
        """Register an agent by canonical name and legacy alias."""
        self.agent_registry.register(name, agent_instance)
        self.agent_registry.register(f"{name}{ALIAS_SUFFIX}", agent_instance)

    def _provider_instance_for_model(self, model_key: str, agent_name: str) -> Optional[ModelProvider]:
        """Create a model provider instance for a specific model key."""
        if "ollama" in model_key:
            provider_name = "ollama"
        elif "gemini" in model_key:
            provider_name = "gemini"
        else:
            provider_name = "openrouter"

        provider_class = PROVIDER_CLASSES[provider_name]
        provider = provider_class(
            agent_name=None,
            config_path=self.config_path,
            token_budget=self.token_budget,
            cost_tracker=self.cost_tracker,
            rate_limiter=ProviderRateLimits.get(provider_name),
            circuit_breaker=self.circuit_breakers.get(provider_name),
        )
        provider._model_name = model_key
        return provider

    def _provider_for_agent(self, agent_name: str) -> Any:
        """Return the configured provider for an agent."""
        if self.provider_factory is not None:
            provider = self.provider_factory(agent_name, self.config_path)
        else:
            provider_name = self._agent_config(agent_name).get(CONFIG_KEY_PROVIDER)
            provider_class = PROVIDER_CLASSES[str(provider_name)]
            provider = provider_class(
                agent_name,
                self.config_path,
                token_budget=self.token_budget,
                cost_tracker=self.cost_tracker,
                rate_limiter=ProviderRateLimits.get(str(provider_name)),
                circuit_breaker=self.circuit_breakers.get(str(provider_name)),
            )

        if provider is not None:
            if not getattr(provider, "token_budget", None):
                provider.token_budget = self.token_budget
            if not getattr(provider, "cost_tracker", None):
                provider.cost_tracker = self.cost_tracker
            if not getattr(provider, "rate_limiter", None):
                provider_name_str = self._agent_config(agent_name).get(CONFIG_KEY_PROVIDER)
                provider.rate_limiter = ProviderRateLimits.get(str(provider_name_str))
            if not getattr(provider, "circuit_breaker", None):
                provider_name_str = self._agent_config(agent_name).get(CONFIG_KEY_PROVIDER)
                provider.circuit_breaker = self.circuit_breakers.get(str(provider_name_str))
            if not getattr(provider, "tracer", None):
                provider.tracer = self.tracer

        # Check if fallback chain exists and construct FallbackRouter
        fallback_chain = self.config.get("fallback_chain", {}).get(agent_name)
        if fallback_chain and isinstance(fallback_chain, list) and provider is not None:
            fallbacks = []
            for fallback_model in fallback_chain:
                if fallback_model == provider.get_model_name():
                    continue
                fb_prov = self._provider_instance_for_model(fallback_model, agent_name)
                if fb_prov:
                    fallbacks.append(fb_prov)
            if fallbacks:
                from core.fallback_router import FallbackRouter
                fallback_router = FallbackRouter(
                    primary=provider,
                    fallbacks=fallbacks,
                    health_monitor=self.provider_health_monitor
                )
                provider.fallback_router = fallback_router
                for fb in fallbacks:
                    fb.fallback_router = fallback_router
                return fallback_router

        return provider

    def _provider_health_targets(self) -> dict[str, Any]:
        """Return one provider instance per configured provider name."""
        health_targets: dict[str, Any] = {}
        for agent_name, provider in self.providers.items():
            provider_name = self._agent_config(agent_name).get(CONFIG_KEY_PROVIDER)
            if isinstance(provider_name, str) and provider_name not in health_targets:
                health_targets[provider_name] = provider
        return health_targets

    def _agent_provider_name(self, agent_name: str) -> str:
        """Return the provider key configured for one agent."""
        return str(self._agent_config(agent_name).get(CONFIG_KEY_PROVIDER))

    def _initialize_git_manager(self) -> Optional[GitManager]:
        """Return a GitManager only when the project root is a git repository."""
        git_manager = GitManager(self.project_root)
        if git_manager.is_git_repo():
            return git_manager
        self.logger.warning(GIT_REPO_WARNING)
        return None

    def _agent_config(self, agent_name: str) -> Mapping[str, Any]:
        """Return one configured agent mapping."""
        agents = self.config.get(CONFIG_KEY_AGENTS)
        if not isinstance(agents, Mapping):
            raise ValueError("ProjectOS config must define agents.")
        agent_config = agents.get(agent_name)
        if not isinstance(agent_config, Mapping):
            raise ValueError(f"ProjectOS config missing agent: {agent_name}")
        return agent_config

    def _load_config(self) -> Mapping[str, Any]:
        """Load the ProjectOS model configuration."""
        if self.config_path.name == "models.yaml":
            sibling_projectos = self.config_path.parent / "projectos.yaml"
            if sibling_projectos.exists():
                self.logger.warning(
                    "config/models.yaml is deprecated. Please use config/projectos.yaml instead."
                )
        with self.config_path.open("r", encoding=ENCODING) as config_file:
            config = yaml.safe_load(config_file)
        if not isinstance(config, Mapping):
            raise ValueError("ProjectOS config must be a mapping.")
        if "project" in config or config.get("version") == "0.3.0" or "token_budgets" in config:
            from core.config_loader import adapt_to_legacy_config
            config = adapt_to_legacy_config(config)
        return config

    def _get_usd_to_inr(self) -> float:
        """Return the configured USD to INR exchange rate from config."""
        try:
            pricing = self.config.get("pricing", {})
            return float(pricing.get("usd_to_inr", 83.5))
        except Exception:
            return 83.5

    def _project_root_for_config(self, config_path: Path) -> Path:
        """Return the project root inferred from config/models.yaml."""
        resolved_path = config_path.resolve()
        if resolved_path.parent.name == CONFIG_DIR_NAME:
            return resolved_path.parent.parent
        return Path.cwd()

    def _agent_statuses(self) -> dict[str, str]:
        """Return current agent model assignments for status snapshots."""
        return {
            agent_name: str(self.providers[agent_name].get_model_name())
            for agent_name in ALL_AGENT_NAMES
            if agent_name in self.providers
        }

    def run_for_duration(self, seconds: int) -> dict[str, Any]:
        """Start all components, process events for N seconds, and gracefully shut down.

        This enables scripted dogfood sessions without manual Ctrl+C.
        """
        import time

        events_processed = 0
        decisions_logged = 0
        errors: list[str] = []

        original_handle = self.clone_agent.handle
        original_log = self.clone_agent.decision_logger.log

        lock = threading.Lock()

        def wrapped_handle(event: AgentEvent) -> Any:
            nonlocal events_processed
            try:
                result = original_handle(event)
                with lock:
                    events_processed += 1
                return result
            except Exception as e:
                with lock:
                    errors.append(str(e))
                raise

        def wrapped_log(*args: Any, **kwargs: Any) -> Any:
            nonlocal decisions_logged
            try:
                res = original_log(*args, **kwargs)
                with lock:
                    decisions_logged += 1
                return res
            except Exception as e:
                with lock:
                    errors.append(str(e))
                raise

        self.clone_agent.handle = wrapped_handle
        self.clone_agent.decision_logger.log = wrapped_log

        shutdown_event = threading.Event()

        def expire_duration():
            shutdown_event.set()

        timer = threading.Timer(seconds, expire_duration)
        timer.daemon = True
        timer.start()

        try:
            self.start()
            while not shutdown_event.is_set():
                time.sleep(0.5)
        except Exception as e:
            errors.append(str(e))
        finally:
            timer.cancel()
            self.stop()
            self.clone_agent.handle = original_handle
            self.clone_agent.decision_logger.log = original_log

        return {
            "events_processed": events_processed,
            "decisions_logged": decisions_logged,
            "errors": errors,
        }

    def _log_final_status(self) -> None:
        """Append ProjectOS shutdown status to decisions.log."""
        _append_atomically(
            self.project_root / DECISIONS_LOG_NAME,
            f"[projectos] {FINAL_STATUS_REASON}{NEWLINE}",
        )


class MultiProjectOS:
    """Run one ProjectOS runtime per enabled registered project."""

    def __init__(self, registry: ProjectRegistry) -> None:
        """Initialize multi-project orchestration from a project registry."""
        self.registry = registry
        self.instances: dict[str, ProjectOS] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self.logger = logging.getLogger(f"{LOGGER_NAME}.multi")

    def start(self) -> None:
        """Start all enabled registered projects."""
        for project_config in self.registry.list_projects():
            self._start_project(project_config)

    def stop(self) -> None:
        """Stop all running project instances cleanly."""
        with self._lock:
            instances = list(self.instances.items())
            threads = list(self._threads.values())
        for project_name, project_os in instances:
            self.logger.info("[%s] stopping", project_name)
            project_os.stop()
        for thread in threads:
            thread.join(timeout=MULTI_PROJECT_THREAD_JOIN_SECONDS)

    def status(self) -> dict[str, dict[str, Any]]:
        """Return status by project name."""
        with self._lock:
            instances = dict(self.instances)
        return {
            project_name: self._project_status(project_os)
            for project_name, project_os in instances.items()
        }

    def _start_project(self, config: ProjectConfig) -> None:
        """Create and start one ProjectOS instance in a thread."""
        with self._lock:
            if config.name in self.instances:
                return
            project_os = ProjectOS.from_project_config(config)
            self.instances[config.name] = project_os
        thread = threading.Thread(
            target=self._run_project,
            args=(config.name, project_os),
            name=f"{LOGGER_NAME}.{config.name}",
            daemon=True,
        )
        with self._lock:
            self._threads[config.name] = thread
        thread.start()

    def _run_project(self, project_name: str, project_os: ProjectOS) -> None:
        """Start one ProjectOS instance with project-prefixed logging."""
        self.logger.info("[%s] starting", project_name)
        project_os.start()

    def _project_status(self, project_os: ProjectOS) -> dict[str, Any]:
        """Return one project status mapping."""
        return {
            STATUS_KEY_RUNNING: (
                project_os._event_thread is not None
                and project_os._event_thread.is_alive()
            ),
            STATUS_KEY_ROOT_PATH: str(project_os.project_root),
            STATUS_KEY_PENDING_COUNT: project_os.task_queue.get_pending_count(),
            STATUS_KEY_BLOCKED_COUNT: len(project_os.task_queue.get_blocked()),
            STATUS_KEY_PROVIDERS: project_os.provider_health_monitor.get_status(),
        }


__all__ = ["MultiProjectOS", "ProjectOS"]
