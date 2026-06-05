"""Base agent abstraction for ProjectOS."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from core.events import AgentEvent, AgentResult
from core.model_provider import ModelProvider


class BaseAgent(ABC):
    """Abstract base class shared by all ProjectOS agents."""

    def __init__(
        self,
        name: str,
        role_description: str,
        model_provider: ModelProvider,
        logger: logging.Logger,
    ) -> None:
        """Initialize shared agent identity, model provider, and logger."""
        self.name = name
        self.role_description = role_description
        self.model_provider = model_provider
        self.logger = logger

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
