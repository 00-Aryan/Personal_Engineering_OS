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
from core.model_provider import GeminiProvider, OllamaProvider, OpenRouterProvider
from core.persistence import PersistenceManager
from core.project_config import ProjectConfig, ProjectRegistry
from core.provider_health import ProviderHealthMonitor
from core.safety import DefaultSafetyPolicy
from core.task_queue import TaskQueue
from core.trigger_system import TriggerSystem


DEFAULT_CONFIG_PATH = Path("config/models.yaml")
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
        config_path: Path | str = DEFAULT_CONFIG_PATH,
        provider_factory: Optional[ProviderFactory] = None,
        project_root: Optional[Path | str] = None,
        state_dir: Optional[Path | str] = None,
        project_name: Optional[str] = None,
        watch_patterns: Optional[list[str]] = None,
        ignore_patterns: Optional[list[str]] = None,
    ) -> None:
        """Load configuration and initialize ProjectOS runtime components."""
        self.config_path = Path(config_path)
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
        self.providers = self._initialize_providers()
        self.provider_health_monitor = ProviderHealthMonitor(
            self._provider_health_targets()
        )
        self.git_manager = self._initialize_git_manager()
        self.agent_registry = AgentRegistry()
        self.event_queue: queue.Queue[AgentEvent] = queue.Queue()
        self.stop_event = threading.Event()
        self.safety_policy = DefaultSafetyPolicy(self.project_root)
        self.persistence_manager = PersistenceManager(self.state_dir)
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
        self.quality_gate = QualityGate(
            DEFAULT_POLICIES,
            self.quality_scorer,
            self.regression_detector,
            self.state_dir / GATE_LOG_NAME,
        )
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
        self.stop_event.clear()
        self._restore_persisted_queue_state()
        self.provider_health_monitor.start()
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
        if self._event_thread is not None:
            self._event_thread.join(timeout=EVENT_THREAD_JOIN_SECONDS)
        self.task_queue.shutdown(wait=True)
        self.persistence_manager.snapshot_status(
            self._agent_statuses(),
            self.provider_health_monitor.get_status(),
        )
        self._log_final_status()

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
            ),
            AGENT_CODE_WRITING: CodeWritingAgent(
                self.providers[AGENT_CODE_WRITING],
                logger,
                project_root=self.project_root,
                safety_policy=self.safety_policy,
                static_analyzer=self.static_analyzer,
            ),
            AGENT_CODE_REVIEW: CodeReviewAgent(
                self.providers[AGENT_CODE_REVIEW],
                logger,
                project_root=self.project_root,
                git_manager=self.git_manager,
            ),
            AGENT_ARCHITECTURE: ArchitectureAgent(
                self.providers[AGENT_ARCHITECTURE],
                logger,
                project_root=self.project_root,
            ),
            AGENT_TEST: TestAgent(
                self.providers[AGENT_TEST],
                logger,
                project_root=self.project_root,
            ),
            AGENT_DOCS: DocsAgent(
                self.providers[AGENT_DOCS],
                logger,
                project_root=self.project_root,
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

    def _provider_for_agent(self, agent_name: str) -> Any:
        """Return the configured provider for an agent."""
        if self.provider_factory is not None:
            return self.provider_factory(agent_name, self.config_path)
        provider_name = self._agent_config(agent_name).get(CONFIG_KEY_PROVIDER)
        provider_class = PROVIDER_CLASSES[str(provider_name)]
        return provider_class(agent_name, self.config_path)

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
        with self.config_path.open("r", encoding=ENCODING) as config_file:
            config = yaml.safe_load(config_file)
        if not isinstance(config, Mapping):
            raise ValueError("ProjectOS config must be a mapping.")
        return config

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
