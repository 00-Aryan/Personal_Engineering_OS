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
from core.events import AgentEvent, AgentResult
from core.model_provider import GeminiProvider, OllamaProvider, OpenRouterProvider
from core.task_queue import TaskQueue
from core.trigger_system import TriggerSystem


DEFAULT_CONFIG_PATH = Path("config/models.yaml")
CONFIG_DIR_NAME = "config"
DECISIONS_LOG_NAME = "decisions.log"
ENCODING = "utf-8"
EMPTY_TEXT = ""
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

CONFIG_KEY_AGENTS = "agents"
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
TASK_QUEUE_WORKERS = 4
FINAL_STATUS_REASON = "ProjectOS stopped cleanly"

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
    ) -> None:
        """Load configuration and initialize ProjectOS runtime components."""
        self.config_path = Path(config_path)
        self.project_root = self._project_root_for_config(self.config_path)
        self.config = self._load_config()
        self.provider_factory = provider_factory
        self.logger = logging.getLogger(LOGGER_NAME)
        self.providers = self._initialize_providers()
        self.agent_registry = AgentRegistry()
        self.event_queue: queue.Queue[AgentEvent] = queue.Queue()
        self.stop_event = threading.Event()
        self.task_queue = TaskQueue(
            max_workers=TASK_QUEUE_WORKERS,
            result_callback=self._handle_agent_result,
        )
        self.clone_agent = self._initialize_agents()
        self.trigger_system = TriggerSystem(self.project_root, self.event_queue)
        self._event_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start trigger watching and event-loop processing."""
        if self._event_thread is not None and self._event_thread.is_alive():
            return
        self.stop_event.clear()
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
        if self._event_thread is not None:
            self._event_thread.join(timeout=EVENT_THREAD_JOIN_SECONDS)
        self.task_queue.shutdown(wait=True)
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
        for next_event in result.next_events:
            self.clone_agent.handle(next_event)

    def _initialize_providers(self) -> dict[str, Any]:
        """Initialize configured providers for all ProjectOS agents."""
        return {
            agent_name: self._provider_for_agent(agent_name)
            for agent_name in ALL_AGENT_NAMES
        }

    def _initialize_agents(self) -> CloneAgent:
        """Initialize and register Clone plus all worker agents."""
        logger = logging.getLogger(LOGGER_NAME)
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
            ),
            AGENT_CODE_REVIEW: CodeReviewAgent(
                self.providers[AGENT_CODE_REVIEW],
                logger,
                project_root=self.project_root,
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
        )
        self._register_agent_with_alias(AGENT_CLONE, clone_agent)
        return clone_agent

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

    def _log_final_status(self) -> None:
        """Append ProjectOS shutdown status to decisions.log."""
        _append_atomically(
            self.project_root / DECISIONS_LOG_NAME,
            f"[projectos] {FINAL_STATUS_REASON}{NEWLINE}",
        )


__all__ = ["ProjectOS"]
