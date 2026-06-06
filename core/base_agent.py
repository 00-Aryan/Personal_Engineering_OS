"""Base agent abstraction for ProjectOS."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

from core.events import AgentEvent, AgentResult
from core.intelligence.collaboration import ConsultationRequest, ConsultationType
from core.model_provider import ModelProvider

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
    ) -> None:
        """Initialize shared agent identity, model provider, and logger."""
        self.name = name
        self.role_description = role_description
        self.model_provider = model_provider
        self.logger = logger
        self.context_retriever = context_retriever
        self.memory_manager = memory_manager
        self.collaboration_broker = collaboration_broker
        self._current_consultation_depth = 0

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
