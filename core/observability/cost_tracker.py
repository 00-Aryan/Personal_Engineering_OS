"""Cost tracker and provider economics manager for ProjectOS agents."""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# Thread-local storage to track prompt details (specifically last_model)
from core.observability.token_budget import _local


@dataclass
class ProviderPricing:
    """Pricing details for a specific model provider configuration."""

    provider_name: str
    model_name: str
    input_cost_per_1k_tokens: float  # (USD)
    output_cost_per_1k_tokens: float  # (USD)
    free_tier_input_tokens_per_day: int  # (0 = no free tier)
    free_tier_output_tokens_per_day: int  # (0 = no free tier)
    currency: str = "USD"

    def is_free_tier(
        self,
        input_tokens: int,
        output_tokens: int,
        used_today: int,
    ) -> bool:
        """Return True if this call would be covered by free tier."""
        if self.free_tier_input_tokens_per_day <= 0 or self.free_tier_output_tokens_per_day <= 0:
            return False
        total_tokens_with_call = used_today + input_tokens + output_tokens
        return total_tokens_with_call <= min(
            self.free_tier_input_tokens_per_day,
            self.free_tier_output_tokens_per_day,
        )


PROVIDER_PRICING_CATALOG = {
    "gemini-flash": ProviderPricing(
        provider_name="gemini",
        model_name="gemini-1.5-flash",
        input_cost_per_1k_tokens=0.0,
        output_cost_per_1k_tokens=0.0,
        free_tier_input_tokens_per_day=1_000_000,
        free_tier_output_tokens_per_day=1_000_000,
    ),
    "deepseek-v3": ProviderPricing(
        provider_name="openrouter",
        model_name="deepseek/deepseek-chat",
        input_cost_per_1k_tokens=0.00014,
        output_cost_per_1k_tokens=0.00028,
        free_tier_input_tokens_per_day=0,
        free_tier_output_tokens_per_day=0,
    ),
    "openrouter-free": ProviderPricing(
        provider_name="openrouter",
        model_name="various-free",
        input_cost_per_1k_tokens=0.0,
        output_cost_per_1k_tokens=0.0,
        free_tier_input_tokens_per_day=500_000,
        free_tier_output_tokens_per_day=500_000,
    ),
    "ollama-local": ProviderPricing(
        provider_name="ollama",
        model_name="local",
        input_cost_per_1k_tokens=0.0,
        output_cost_per_1k_tokens=0.0,
        free_tier_input_tokens_per_day=999_999_999,
        free_tier_output_tokens_per_day=999_999_999,
    ),
}


@dataclass
class CostRecord:
    """Represents a recorded cost event for a model call."""

    record_id: str
    timestamp: datetime
    agent_name: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_inr: float
    is_free_tier: bool
    trace_id: Optional[str]
    task_id: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize cost record to dictionary."""
        return {
            "record_id": self.record_id,
            "timestamp": self.timestamp.isoformat(),
            "agent_name": self.agent_name,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "cost_inr": self.cost_inr,
            "is_free_tier": self.is_free_tier,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
        }


class CostTracker:
    """Tracks token and model usage costs in USD/INR across agents and tasks."""

    def __init__(
        self,
        state_dir: Path,
        usd_to_inr: float = 83.5,
        pricing_catalog: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize CostTracker with state path and default/custom pricing catalog."""
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.state_dir / "costs.jsonl"
        self.usd_to_inr = usd_to_inr
        self._lock = threading.Lock()

        # Build catalog
        self.pricing_catalog = dict(PROVIDER_PRICING_CATALOG)
        if pricing_catalog:
            for k, v in pricing_catalog.items():
                if isinstance(v, ProviderPricing):
                    self.pricing_catalog[k] = v
                elif isinstance(v, dict):
                    self.pricing_catalog[k] = ProviderPricing(
                        provider_name=v.get("provider_name", "unknown"),
                        model_name=v.get("model_name", "unknown"),
                        input_cost_per_1k_tokens=float(v.get("input_cost_per_1k_tokens", 0.0)),
                        output_cost_per_1k_tokens=float(v.get("output_cost_per_1k_tokens", 0.0)),
                        free_tier_input_tokens_per_day=int(v.get("free_tier_input_tokens_per_day", 0)),
                        free_tier_output_tokens_per_day=int(v.get("free_tier_output_tokens_per_day", 0)),
                        currency=v.get("currency", "USD"),
                    )

    def record(
        self,
        agent_name: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> CostRecord:
        """Compute cost and append to costs.jsonl atomically."""
        try:
            # Resolve model name
            if not model:
                if hasattr(_local, "last_model"):
                    model = _local.last_model.get(agent_name)
            if not model:
                model = "unknown"

            # Find matching pricing
            pricing = None
            for p in self.pricing_catalog.values():
                if p.provider_name == provider and p.model_name == model:
                    pricing = p
                    break

            if not pricing:
                # Fallback to key or matching provider
                if model in self.pricing_catalog:
                    pricing = self.pricing_catalog[model]
                else:
                    for p in self.pricing_catalog.values():
                        if p.provider_name == provider:
                            pricing = p
                            break

            if not pricing:
                pricing = ProviderPricing(
                    provider_name=provider,
                    model_name=model,
                    input_cost_per_1k_tokens=0.0,
                    output_cost_per_1k_tokens=0.0,
                    free_tier_input_tokens_per_day=0,
                    free_tier_output_tokens_per_day=0,
                )

            # Check free tier status
            used_today = self._get_daily_tokens_for_provider_model(provider, model)
            is_free = pricing.is_free_tier(input_tokens, output_tokens, used_today)

            if is_free:
                cost_usd = 0.0
            else:
                cost_usd = (
                    (input_tokens / 1000.0) * pricing.input_cost_per_1k_tokens
                    + (output_tokens / 1000.0) * pricing.output_cost_per_1k_tokens
                )

            cost_inr = cost_usd * self.usd_to_inr

            record = CostRecord(
                record_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc),
                agent_name=agent_name,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                cost_inr=cost_inr,
                is_free_tier=is_free,
                trace_id=trace_id,
                task_id=task_id,
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

        except Exception as e:
            # Never raise, log and return empty cost record on error
            import logging
            logging.getLogger("projectos.cost_tracker").error(f"Failed to record cost: {e}")
            return CostRecord(
                record_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc),
                agent_name=agent_name,
                provider=provider,
                model=model or "unknown",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=0.0,
                cost_inr=0.0,
                is_free_tier=True,
                trace_id=trace_id,
                task_id=task_id,
            )

    def get_daily_cost(self, date_obj: Optional[date] = None) -> Dict[str, Any]:
        """Return summary of costs for the given date (default: today)."""
        if date_obj is None:
            date_obj = datetime.now(timezone.utc).date()
        date_str = date_obj.isoformat()

        total_usd = 0.0
        total_inr = 0.0
        by_agent: Dict[str, Dict[str, float]] = {}
        by_provider: Dict[str, Dict[str, float]] = {}
        free_tier_calls = 0
        paid_calls = 0

        if self.log_path.exists():
            with self._lock:
                try:
                    with open(self.log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                                t_date = data.get("timestamp", "")[:10]
                                if t_date == date_str:
                                    cost_usd = float(data.get("cost_usd", 0.0))
                                    cost_inr = float(data.get("cost_inr", 0.0))
                                    agent = data.get("agent_name", "unknown")
                                    provider = data.get("provider", "unknown")
                                    is_free = bool(data.get("is_free_tier", True))

                                    total_usd += cost_usd
                                    total_inr += cost_inr

                                    if agent not in by_agent:
                                        by_agent[agent] = {"usd": 0.0, "inr": 0.0}
                                    by_agent[agent]["usd"] += cost_usd
                                    by_agent[agent]["inr"] += cost_inr

                                    if provider not in by_provider:
                                        by_provider[provider] = {"usd": 0.0, "inr": 0.0}
                                    by_provider[provider]["usd"] += cost_usd
                                    by_provider[provider]["inr"] += cost_inr

                                    if is_free:
                                        free_tier_calls += 1
                                    else:
                                        paid_calls += 1
                            except Exception:
                                continue
                except Exception:
                    pass

        return {
            "total_usd": total_usd,
            "total_inr": total_inr,
            "by_agent": by_agent,
            "by_provider": by_provider,
            "free_tier_calls": free_tier_calls,
            "paid_calls": paid_calls,
        }

    def get_task_cost(self, task_id: str) -> Dict[str, Any]:
        """Return total cost for all model calls in a task."""
        total_usd = 0.0
        total_inr = 0.0
        calls = 0

        if self.log_path.exists():
            with self._lock:
                try:
                    with open(self.log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                                if data.get("task_id") == task_id:
                                    total_usd += float(data.get("cost_usd", 0.0))
                                    total_inr += float(data.get("cost_inr", 0.0))
                                    calls += 1
                            except Exception:
                                continue
                except Exception:
                    pass

        return {
            "total_usd": total_usd,
            "total_inr": total_inr,
            "calls": calls,
        }

    def get_monthly_projection(self, days_of_data: int = 7) -> Dict[str, Any]:
        """Project monthly cost from last N days average."""
        if days_of_data < 3:
            confidence = "low"
        elif days_of_data >= 14:
            confidence = "high"
        else:
            confidence = "medium"

        today = datetime.now(timezone.utc).date()
        import datetime as dt
        start_date = today - dt.timedelta(days=days_of_data - 1)

        total_usd = 0.0
        total_inr = 0.0

        if self.log_path.exists():
            with self._lock:
                try:
                    with open(self.log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                                t_date_str = data.get("timestamp", "")[:10]
                                t_date = date.fromisoformat(t_date_str)
                                if start_date <= t_date <= today:
                                    total_usd += float(data.get("cost_usd", 0.0))
                                    total_inr += float(data.get("cost_inr", 0.0))
                            except Exception:
                                continue
                except Exception:
                    pass

        daily_usd = total_usd / days_of_data
        daily_inr = total_inr / days_of_data

        return {
            "projected_usd": daily_usd * 30.0,
            "projected_inr": daily_inr * 30.0,
            "confidence": confidence,
        }

    def recommend_model_swap(self, agent_name: str) -> Optional[str]:
        """Recommend swap if agent daily cost exceeds threshold."""
        try:
            # Resolve config path
            config_path = Path(__file__).resolve().parents[2] / "config" / "models.yaml"
            current_model = "unknown"
            current_provider = "unknown"
            threshold = 100.0

            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = yaml.safe_load(f)
                        if isinstance(config, dict):
                            agents_config = config.get("agents", {})
                            if agent_name in agents_config:
                                current_model = agents_config[agent_name].get("model", "unknown")
                                current_provider = agents_config[agent_name].get("provider", "unknown")
                            pricing_config = config.get("pricing", {})
                            threshold = float(pricing_config.get("alert_threshold_daily_inr", 100.0))
                except Exception:
                    pass

            daily_costs = self.get_daily_cost()
            agent_cost_inr = daily_costs["by_agent"].get(agent_name, {}).get("inr", 0.0)

            if agent_cost_inr <= threshold:
                return None

            # 1. If Ollama available and current provider is not Ollama, recommend Ollama
            is_on_ollama = (current_provider == "ollama")
            if not is_on_ollama and self._is_ollama_available():
                return f"Recommend swapping {agent_name} to Ollama local for cost efficiency."

            # 2. Otherwise recommend a cheaper model if exists
            current_pricing = None
            if current_model in self.pricing_catalog:
                current_pricing = self.pricing_catalog[current_model]
            else:
                for p in self.pricing_catalog.values():
                    if p.model_name == current_model or (p.provider_name == current_provider and p.model_name == current_model):
                        current_pricing = p
                        break

            current_cost = (
                current_pricing.input_cost_per_1k_tokens + current_pricing.output_cost_per_1k_tokens
                if current_pricing
                else 0.0
            )

            cheaper_model_key = None
            cheaper_cost = current_cost
            for k, p in self.pricing_catalog.items():
                if p.provider_name == "ollama":
                    continue
                if p == current_pricing:
                    continue
                p_cost = p.input_cost_per_1k_tokens + p.output_cost_per_1k_tokens
                if p_cost < cheaper_cost:
                    cheaper_cost = p_cost
                    cheaper_model_key = k

            if cheaper_model_key:
                return f"Recommend swapping {agent_name} to {cheaper_model_key} for cost efficiency."

            return None
        except Exception:
            return None

    def _is_ollama_available(self) -> bool:
        """Check if Ollama local service is reachable."""
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=1)
            return response.status_code == 200
        except Exception:
            return False

    def _get_daily_tokens_for_provider_model(self, provider: str, model: str) -> int:
        """Get cumulative tokens (input + output) for provider and model today."""
        today_str = datetime.now(timezone.utc).date().isoformat()
        total_tokens = 0
        if self.log_path.exists():
            with self._lock:
                try:
                    with open(self.log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                                t_date = data.get("timestamp", "")[:10]
                                if (
                                    t_date == today_str
                                    and data.get("provider") == provider
                                    and data.get("model") == model
                                ):
                                    total_tokens += int(data.get("input_tokens", 0)) + int(data.get("output_tokens", 0))
                            except Exception:
                                continue
                except Exception:
                    pass
        return total_tokens
