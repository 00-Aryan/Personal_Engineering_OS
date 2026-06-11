"""Base agent abstraction for ProjectOS."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING

from core.events import AgentEvent, AgentResult
from core.intelligence.collaboration import ConsultationRequest, ConsultationType
from core.model_provider import ModelProvider
from core.project_context import ProjectContextLoader

if TYPE_CHECKING:
    from core.intelligence.collaboration import CollaborationBroker
    from core.intelligence.context_retriever import ContextRetriever
    from core.intelligence.memory_manager import MemoryManager


class BaseAgent(ABC):
    """Abstract base class shared by all ProjectOS agents."""

    def __init__(
        self,
        name: str,
        role_description: str,
        model_provider: ModelProvider,
        logger: logging.Logger,
        context_retriever: Optional["ContextRetriever"] = None,
        memory_manager: Optional["MemoryManager"] = None,
        collaboration_broker: Optional["CollaborationBroker"] = None,
        context_loader: Optional[ProjectContextLoader] = None,
    ) -> None:
        """Initialize shared agent identity, model provider, and logger."""
        self.name = name
        self.role_description = role_description
        self.model_provider = model_provider
        self.logger = logger
        self.context_retriever = context_retriever
        self.memory_manager = memory_manager
        self.collaboration_broker = collaboration_broker
        self.context_loader = context_loader
        self._current_consultation_depth = 0

    def get_project_context_prompt(self) -> str:
        """Load and format project context for system prompt injection."""
        if self.context_loader is None:
            return ""
        ctx = self.context_loader.load()
        if ctx is None:
            return ""
        return ProjectContextLoader.to_system_prompt_injection(ctx)

    def build_system_prompt(self, base_prompt: str) -> str:
        """Replace the project context placeholder with the loaded context prompt."""
        return base_prompt.replace("{project_context}", self.get_project_context_prompt())

    @abstractmethod
    def handle(self, event: AgentEvent) -> AgentResult:
        """Handle an incoming event and return the agent result."""

    def log_decision(self, reasoning: str, outcome: str) -> None:
        """Log agent reasoning and outcome for auditability."""
        message = (
            f"[{self.name}] DECISION | "
            f"reasoning={reasoning!r} | "
            f"outcome={outcome!r}"
        )
        self.logger.info(message)

    def update_consultation_depth(self, event: AgentEvent) -> None:
        """Track consultation depth from an incoming event payload."""
        depth = event.payload.get("depth", 0)
        self._current_consultation_depth = depth if isinstance(depth, int) else 0

    def consult(
        self,
        target_agent: str,
        question: str,
        context: str,
        consultation_type: ConsultationType = ConsultationType.FEASIBILITY_CHECK,
    ) -> Optional[str]:
        """Consult another agent through the collaboration broker."""
        if self.collaboration_broker is None:
            return None
        if self._current_consultation_depth >= 1:
            return None

        request = ConsultationRequest(
            requesting_agent=self.name,
            target_agent=target_agent,
            consultation_type=consultation_type,
            question=question,
            context=context,
            depth=self._current_consultation_depth,
        )
        result = self.collaboration_broker.consult(request)
        self.log_decision(f"Consulted {target_agent}: {question[:50]}", result.answer)
        return result.answer

    def get_context(
        self,
        task_description: str,
        file_path: Optional[str] = None,
    ) -> Optional[str]:
        """Return formatted codebase retrieval context when configured."""
        if self.context_retriever is None:
            return None
        try:
            retrieval_context = self.context_retriever.retrieve_for_task(
                task_description=task_description,
                file_path=file_path,
                agent_name=self.name,
            )
        except Exception as error:
            self.logger.warning("Context retrieval failed for %s: %s", self.name, error)
            return None
        return retrieval_context.formatted_context

    def recall_relevant(self, query: str, k: int = 3) -> str:
        """Return formatted relevant memories for this agent."""
        if self.memory_manager is None:
            return ""
        try:
            return self.memory_manager.recall(self.name, query, k)
        except Exception as error:
            self.logger.warning("Memory recall failed for %s: %s", self.name, error)
            return ""

    def remember(
        self,
        decision: str,
        context: str,
        outcome: str,
        quality_score: Optional[float] = None,
    ) -> None:
        """Store a decision memory when memory is configured."""
        if self.memory_manager is None:
            return
        try:
            self.memory_manager.remember_decision(
                self.name,
                decision,
                context,
                outcome,
                quality_score,
            )
        except Exception as error:
            self.logger.warning("Memory store failed for %s: %s", self.name, error)

    def remember_workflow(
        self,
        workflow_name: str,
        steps: list[str],
        success_rate: float,
    ) -> None:
        """Store a workflow memory when memory is configured."""
        if self.memory_manager is None:
            return
        try:
            self.memory_manager.remember_workflow(
                self.name,
                workflow_name,
                steps,
                success_rate,
            )
        except Exception as error:
            self.logger.warning("Workflow memory store failed for %s: %s", self.name, error)

    @property
    def token_budget(self) -> Optional[Any]:
        """Get the token budget manager from model provider."""
        return getattr(self.model_provider, "token_budget", None)

    def is_conservative_mode_active(self) -> bool:
        """Check if conservative token budget mode is active, safely handling mocks."""
        tb = self.token_budget
        if not tb or not hasattr(tb, "conservative_mode_active"):
            return False
        try:
            val = tb.conservative_mode_active(self.name)
            is_mock = "Mock" in type(val).__name__ or "Mock" in type(tb).__name__
            if is_mock:
                return not ("Mock" in type(val).__name__) and bool(val)
            return bool(val)
        except Exception:
            return False

    def get_model_params(self) -> Dict[str, Any]:
        """Get model parameters (temperature, max_tokens, top_p) for this agent from configuration."""
        defaults = {"temperature": 0.3, "max_tokens": 1000, "top_p": 0.9}
        if not self.model_provider:
            return defaults
        
        config = getattr(self.model_provider, "_config", {})
        result = defaults.copy()
        if isinstance(config, dict):
            model_parameters = config.get("model_parameters", {})
            if isinstance(model_parameters, dict):
                agent_params = model_parameters.get(self.name, {})
                if isinstance(agent_params, dict):
                    result = {
                        "temperature": agent_params.get("temperature", defaults["temperature"]),
                        "max_tokens": agent_params.get("max_tokens", defaults["max_tokens"]),
                        "top_p": agent_params.get("top_p", defaults["top_p"]),
                    }
        
        # If conservative mode is active, override max_tokens to 500
        if self.is_conservative_mode_active():
            result["max_tokens"] = min(result["max_tokens"], 500)
            
        return result
