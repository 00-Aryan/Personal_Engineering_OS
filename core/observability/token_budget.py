"""Token budget manager for ProjectOS agents."""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Thread-local storage to track prompt details
_local = threading.local()


@dataclass
class TokenUsageRecord:
    """Represents a recorded token usage entry."""

    record_id: str
    timestamp: datetime
    agent_name: str
    operation: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    trace_id: Optional[str]
    event_id: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize record to dictionary."""
        return {
            "record_id": self.record_id,
            "timestamp": self.timestamp.isoformat(),
            "agent_name": self.agent_name,
            "operation": self.operation,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "trace_id": self.trace_id,
            "event_id": self.event_id,
        }


@dataclass
class BudgetCheckResult:
    """Result of checking a budget limit request."""

    allowed: bool
    estimated_tokens: int
    soft_limit_exceeded: bool
    hard_limit_exceeded: bool
    daily_limit_exceeded: bool
    warning_message: Optional[str]
    daily_used_today: int
    daily_limit: int


class TokenBudget:
    """Manages per-agent token limits and daily counters."""

    DEFAULT_BUDGETS = {
        "code_review": {
            "soft_limit_per_call": 3000,
            "hard_limit_per_call": 6000,
            "daily_limit": 100000,
        },
        "code_writing": {
            "soft_limit_per_call": 3000,
            "hard_limit_per_call": 6000,
            "daily_limit": 100000,
        },
        "planning": {
            "soft_limit_per_call": 2000,
            "hard_limit_per_call": 4000,
            "daily_limit": 50000,
        },
        "architecture": {
            "soft_limit_per_call": 2000,
            "hard_limit_per_call": 4000,
            "daily_limit": 30000,
        },
        "test": {
            "soft_limit_per_call": 3000,
            "hard_limit_per_call": 6000,
            "daily_limit": 80000,
        },
        "docs": {
            "soft_limit_per_call": 1500,
            "hard_limit_per_call": 3000,
            "daily_limit": 40000,
        },
        "clone": {
            "soft_limit_per_call": 1000,
            "hard_limit_per_call": 2000,
            "daily_limit": 200000,
        },
        "default": {
            "soft_limit_per_call": 2000,
            "hard_limit_per_call": 4000,
            "daily_limit": 50000,
        },
    }

    def __init__(
        self,
        state_dir: Path,
        budgets: Optional[Dict[str, Dict[str, int]]] = None,
    ) -> None:
        """Initialize TokenBudget with configuration and cached metrics."""
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.state_dir / "token_usage.jsonl"
        self.budgets = dict(self.DEFAULT_BUDGETS)
        if budgets:
            for agent, limits in budgets.items():
                mapped_limits = {}
                if "soft" in limits:
                    mapped_limits["soft_limit_per_call"] = limits["soft"]
                if "soft_limit_per_call" in limits:
                    mapped_limits["soft_limit_per_call"] = limits["soft_limit_per_call"]

                if "hard" in limits:
                    mapped_limits["hard_limit_per_call"] = limits["hard"]
                if "hard_limit_per_call" in limits:
                    mapped_limits["hard_limit_per_call"] = limits["hard_limit_per_call"]

                if "daily" in limits:
                    mapped_limits["daily_limit"] = limits["daily"]
                if "daily_limit" in limits:
                    mapped_limits["daily_limit"] = limits["daily_limit"]

                if agent in self.budgets:
                    self.budgets[agent].update(mapped_limits)
                else:
                    default_lims = dict(self.DEFAULT_BUDGETS.get("default", {}))
                    default_lims.update(mapped_limits)
                    self.budgets[agent] = default_lims
        self._lock = threading.Lock()
        self._daily_cache: Dict[str, int] = {}
        self._cached_date: Optional[date] = None

    def _ensure_cache_valid(self) -> None:
        """Reset and pre-populate daily usage cache if day changed."""
        current_date = datetime.now(timezone.utc).date()
        if self._cached_date != current_date:
            with self._lock:
                self._daily_cache.clear()
                self._cached_date = current_date
                date_str = current_date.isoformat()
                if self.log_path.exists():
                    try:
                        with open(self.log_path, "r", encoding="utf-8") as f:
                            for line in f:
                                if not line.strip():
                                    continue
                                try:
                                    data = json.loads(line)
                                    t_date = data.get("timestamp", "")[:10]
                                    if t_date == date_str:
                                        a_name = data.get("agent_name")
                                        tokens = data.get("total_tokens", 0)
                                        if a_name:
                                            self._daily_cache[a_name] = (
                                                self._daily_cache.get(a_name, 0)
                                                + tokens
                                            )
                                except Exception:
                                    continue
                    except Exception:
                        pass

    def check_and_record(
        self,
        agent_name: str,
        prompt: str,
        operation: str = "model_call",
    ) -> BudgetCheckResult:
        """Verify prompt against call-limits and daily constraints."""
        self._ensure_cache_valid()
        estimated_tokens = len(prompt) // 4

        # Track prompt length and operation in thread-local storage
        if not hasattr(_local, "last_prompt_tokens"):
            _local.last_prompt_tokens = {}
        _local.last_prompt_tokens[agent_name] = estimated_tokens
        if not hasattr(_local, "last_operation"):
            _local.last_operation = {}
        _local.last_operation[agent_name] = operation

        budget = self.budgets.get(agent_name, self.budgets["default"])
        soft_limit = budget.get("soft_limit_per_call", 2000)
        hard_limit = budget.get("hard_limit_per_call", 4000)
        daily_limit = budget.get("daily_limit", 50000)

        daily_used = self.get_daily_usage(agent_name)

        soft_exceeded = estimated_tokens > soft_limit
        hard_exceeded = estimated_tokens > hard_limit
        daily_exceeded = (daily_used + estimated_tokens) > daily_limit

        allowed = not hard_exceeded and not daily_exceeded
        warning_msg = None
        if not allowed:
            if hard_exceeded:
                warning_msg = (
                    f"Prompt tokens {estimated_tokens} exceeds hard limit "
                    f"{hard_limit} for {agent_name}."
                )
            else:
                warning_msg = (
                    f"Prompt tokens {estimated_tokens} exceeds daily limit "
                    f"{daily_limit} (used {daily_used}) for {agent_name}."
                )
        elif soft_exceeded:
            warning_msg = (
                f"Warning: Prompt tokens {estimated_tokens} exceeds soft limit "
                f"{soft_limit} for {agent_name}."
            )

        return BudgetCheckResult(
            allowed=allowed,
            estimated_tokens=estimated_tokens,
            soft_limit_exceeded=soft_exceeded,
            hard_limit_exceeded=hard_exceeded,
            daily_limit_exceeded=daily_exceeded,
            warning_message=warning_msg,
            daily_used_today=daily_used,
            daily_limit=daily_limit,
        )

    def record_completion(
        self,
        agent_name: str,
        completion: str,
        trace_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> TokenUsageRecord:
        """Record model generation tokens and append to usage statistics."""
        self._ensure_cache_valid()
        completion_tokens = len(completion) // 4

        prompt_tokens = 0
        if hasattr(_local, "last_prompt_tokens"):
            prompt_tokens = _local.last_prompt_tokens.get(agent_name, 0)

        operation = "model_call"
        if hasattr(_local, "last_operation"):
            operation = _local.last_operation.get(agent_name, "model_call")

        provider = "unknown"
        if hasattr(_local, "last_provider"):
            provider = _local.last_provider.get(agent_name, "unknown")

        total_tokens = prompt_tokens + completion_tokens

        # Update cached daily sum
        with self._lock:
            self._daily_cache[agent_name] = (
                self._daily_cache.get(agent_name, 0) + total_tokens
            )

        record = TokenUsageRecord(
            record_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            agent_name=agent_name,
            operation=operation,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=0.0,
            trace_id=trace_id,
            event_id=event_id,
        )

        # Append to file atomically
        encoded = (
            json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        with self._lock:
            fd = os.open(
                self.log_path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )
            try:
                os.write(fd, encoded)
            finally:
                os.close(fd)

        return record

    def get_daily_usage(
        self,
        agent_name: str,
        date_obj: Optional[date] = None,
    ) -> int:
        """Return cumulative token usage for agent on a date."""
        if date_obj is None:
            date_obj = datetime.now(timezone.utc).date()

        current_date = datetime.now(timezone.utc).date()
        if date_obj == current_date:
            self._ensure_cache_valid()
            return self._daily_cache.get(agent_name, 0)

        total = 0
        date_str = date_obj.isoformat()
        if not self.log_path.exists():
            return 0

        with self._lock:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        t_date = data.get("timestamp", "")[:10]
                        if (
                            t_date == date_str
                            and data.get("agent_name") == agent_name
                        ):
                            total += data.get("total_tokens", 0)
                    except Exception:
                        continue

        return total

    def get_usage_summary(self, days: int = 7) -> Dict[str, Any]:
        """Return historical summary of token usage per agent."""
        if not self.log_path.exists():
            return {}

        import datetime as dt

        cutoff = datetime.now(timezone.utc).date() - dt.timedelta(days=days)
        summary: Dict[str, Any] = {}

        with self._lock:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        t_date_str = data.get("timestamp", "")[:10]
                        t_date = date.fromisoformat(t_date_str)
                        if t_date < cutoff:
                            continue

                        agent = data.get("agent_name", "unknown")
                        tokens = data.get("total_tokens", 0)

                        if agent not in summary:
                            summary[agent] = {
                                "total_tokens": 0,
                                "total_calls": 0,
                                "avg_per_call": 0.0,
                                "daily_breakdown": {},
                            }

                        summary[agent]["total_tokens"] += tokens
                        summary[agent]["total_calls"] += 1
                        summary[agent]["daily_breakdown"][t_date_str] = (
                            summary[agent]["daily_breakdown"].get(t_date_str, 0)
                            + tokens
                        )
                    except Exception:
                        continue

        for agent in summary:
            calls = summary[agent]["total_calls"]
            if calls > 0:
                summary[agent]["avg_per_call"] = (
                    summary[agent]["total_tokens"] / calls
                )

        return summary

    def reset_agent_usage(self, agent_name: str) -> None:
        """Reset the today usage counter for an agent by removing today's entries from log."""
        self._ensure_cache_valid()
        current_date = datetime.now(timezone.utc).date()
        date_str = current_date.isoformat()

        with self._lock:
            self._daily_cache[agent_name] = 0
            if self.log_path.exists():
                try:
                    kept_lines = []
                    with open(self.log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                                t_date = data.get("timestamp", "")[:10]
                                if t_date == date_str and data.get("agent_name") == agent_name:
                                    continue
                                kept_lines.append(line)
                            except Exception:
                                kept_lines.append(line)

                    import tempfile
                    temp_fd, temp_path = tempfile.mkstemp(dir=str(self.log_path.parent))
                    try:
                        with os.fdopen(temp_fd, "w", encoding="utf-8") as temp_f:
                            temp_f.writelines(kept_lines)
                        os.replace(temp_path, self.log_path)
                    except Exception:
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                        raise
                except Exception:
                    pass


    def trim_context_to_budget(self, context: str, budget_remaining: int) -> str:
        """Trims codebase context to fit within remaining token budget."""
        if not context:
            return ""

        tokens = len(context) // 4
        if tokens <= budget_remaining:
            return context

        parts = context.split("\n---\n")
        while len(parts) > 1:
            parts.pop()
            rebuilt = "\n---\n".join(parts).rstrip()
            if len(rebuilt) // 4 <= budget_remaining:
                return rebuilt

        first_part = parts[0]
        if len(first_part) // 4 > budget_remaining:
            return first_part[: budget_remaining * 4]
        return first_part

    def get_budget(self, agent_name: str) -> Dict[str, int]:
        """Return a budget dictionary containing soft, hard, and daily limits for the agent."""
        budget = self.budgets.get(agent_name, self.budgets.get("default", {}))
        return {
            "soft": budget.get("soft_limit_per_call", 2000),
            "hard": budget.get("hard_limit_per_call", 4000),
            "daily": budget.get("daily_limit", 50000),
        }

    def check_daily_threshold_alert(
        self,
        agent_name: str,
        threshold_pct: float = 0.60,
    ) -> Optional[str]:
        """
        Return a warning string if agent has used >= threshold_pct of its
        daily budget, otherwise return None.
        """
        usage = self.get_daily_usage(agent_name)
        budget = self.get_budget(agent_name).get("daily", 0)
        if budget == 0:
            return None
        pct = usage / budget
        if pct >= threshold_pct:
            return (
                f"⚠️ Token alert: {agent_name} used {pct:.0%} of daily budget. "
                f"Running in conservative mode (reduced context, shorter outputs)."
            )
        return None

    def conservative_mode_active(self, agent_name: str) -> bool:
        """Return True if agent is at or above 60% daily budget usage."""
        return self.check_daily_threshold_alert(agent_name) is not None
