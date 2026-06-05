"""Agent registry for ProjectOS orchestration."""

from __future__ import annotations

from typing import Dict

from core.base_agent import BaseAgent


class AgentRegistry:
    """Hold ProjectOS agent instances keyed by name."""

    def __init__(self) -> None:
        """Initialize an empty agent registry."""
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, name: str, agent_instance: BaseAgent) -> None:
        """Register one agent instance by name."""
        self._agents[name] = agent_instance

    def get(self, agent_name: str) -> BaseAgent:
        """Return an agent instance by name."""
        return self._agents[agent_name]

    def list_all(self) -> Dict[str, BaseAgent]:
        """Return a copy of all registered agent instances."""
        return dict(self._agents)


__all__ = ["AgentRegistry"]
