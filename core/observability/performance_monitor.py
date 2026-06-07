"""Performance monitor for ProjectOS."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from core.observability.tracer import Tracer, Span

# Constants for zero hardcoded strings rule
SUGGEST_REDUCING_TOP_K = "Consider reducing top_k"
SUGGEST_MEMORY_CACHE = "Consider memory cache layer"
SUGGEST_ASYNC_EVAL = "Consider async evaluation"

COMPONENT_CONTEXT_RETRIEVAL = "context_retrieval"
COMPONENT_CONTEXT_RETRIEVER = "context_retriever"
COMPONENT_MEMORY_RECALL = "memory_recall"
COMPONENT_MEMORY_MANAGER = "memory_manager"
COMPONENT_QUALITY_GATE = "quality_gate"


class PerformanceMonitor:
    """Monitors performance and aggregates traces to recommend optimizations."""

    def __init__(self, tracer: Tracer, state_dir: Path) -> None:
        """Initialize the performance monitor with tracer and state directory."""
        self.tracer = tracer
        self.state_dir = Path(state_dir)

    @dataclass
    class ComponentStats:
        """Stats calculated for a specific component."""

        component: str
        call_count: int
        avg_duration_ms: float
        p50_duration_ms: float
        p95_duration_ms: float
        max_duration_ms: float

    @staticmethod
    def _percentile(sorted_data: List[float], percentile: float) -> float:
        """Calculate the percentile of a sorted list of values using linear interpolation."""
        if not sorted_data:
            return 0.0
        n = len(sorted_data)
        idx = (n - 1) * (percentile / 100.0)
        low = int(idx)
        high = min(low + 1, n - 1)
        if low == high:
            return float(sorted_data[low])
        weight = idx - low
        return float(sorted_data[low] * (1.0 - weight) + sorted_data[high] * weight)

    def get_component_stats(self) -> Dict[str, PerformanceMonitor.ComponentStats]:
        """Reads traces.jsonl, aggregates by component name, and computes duration stats."""
        trace_file = self.state_dir / "traces.jsonl"
        if not trace_file.exists():
            return {}

        component_durations: Dict[str, List[float]] = {}

        try:
            with open(trace_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        component = data.get("component")
                        duration_ms = data.get("duration_ms")
                        if component and duration_ms is not None:
                            if component not in component_durations:
                                component_durations[component] = []
                            component_durations[component].append(float(duration_ms))
                    except Exception:
                        continue
        except Exception:
            return {}

        stats: Dict[str, PerformanceMonitor.ComponentStats] = {}
        for comp, durations in component_durations.items():
            if not durations:
                continue
            sorted_dur = sorted(durations)
            avg_dur = sum(durations) / len(durations)
            max_dur = max(durations)

            p50 = self._percentile(sorted_dur, 50.0)
            p95 = self._percentile(sorted_dur, 95.0)

            stats[comp] = PerformanceMonitor.ComponentStats(
                component=comp,
                call_count=len(durations),
                avg_duration_ms=avg_dur,
                p50_duration_ms=p50,
                p95_duration_ms=p95,
                max_duration_ms=max_dur,
            )
        return stats

    def get_slow_operations(self, threshold_ms: int = 500) -> List[Span]:
        """Returns all spans slower than threshold from recent traces."""
        trace_file = self.state_dir / "traces.jsonl"
        if not trace_file.exists():
            return []

        slow_spans: List[Span] = []
        try:
            with open(trace_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        duration = data.get("duration_ms")
                        if duration is not None and duration >= threshold_ms:
                            slow_spans.append(Span.from_dict(data))
                    except Exception:
                        continue
        except Exception:
            pass
        return slow_spans

    def suggest_optimizations(self) -> List[str]:
        """Generate rule-based optimization suggestions based on component stats."""
        stats = self.get_component_stats()
        suggestions: List[str] = []

        # Rule 1: If context_retrieval (or context_retriever) p95 > 500ms
        cr_stats = stats.get(COMPONENT_CONTEXT_RETRIEVAL) or stats.get(COMPONENT_CONTEXT_RETRIEVER)
        if cr_stats and cr_stats.p95_duration_ms > 500:
            suggestions.append(SUGGEST_REDUCING_TOP_K)

        # Rule 2: If memory_recall (or memory_manager) avg > 200ms
        mr_stats = stats.get(COMPONENT_MEMORY_RECALL) or stats.get(COMPONENT_MEMORY_MANAGER)
        if mr_stats and mr_stats.avg_duration_ms > 200:
            suggestions.append(SUGGEST_MEMORY_CACHE)

        # Rule 3: If quality_gate avg > 1000ms
        qg_stats = stats.get(COMPONENT_QUALITY_GATE)
        if qg_stats and qg_stats.avg_duration_ms > 1000:
            suggestions.append(SUGGEST_ASYNC_EVAL)

        return suggestions
