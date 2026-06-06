"""Distributed tracer for ProjectOS."""

from __future__ import annotations

import contextlib
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


class SpanStatus(Enum):
    """Status of a trace span."""

    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass
class Span:
    """Represents a single operation within a distributed trace."""

    span_id: str
    trace_id: str
    parent_span_id: Optional[str]
    operation_name: str
    component: str
    started_at: datetime
    ended_at: Optional[datetime]
    duration_ms: Optional[int]
    status: SpanStatus
    tags: Dict[str, Any]
    error_message: Optional[str]
    _trace_store: Optional[TraceStore] = field(default=None, repr=False, compare=False)

    def finish(
        self,
        status: SpanStatus = SpanStatus.OK,
        error: Optional[str] = None,
    ) -> None:
        """Finish the span, recording its duration and status."""
        self.ended_at = datetime.now(timezone.utc)
        self.status = status
        self.duration_ms = int((self.ended_at - self.started_at).total_seconds() * 1000)
        if error is not None:
            self.error_message = error
        if self._trace_store is not None:
            self._trace_store.save_span(self)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize span to a dictionary."""
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "operation_name": self.operation_name,
            "component": self.component,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "tags": self.tags,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Span:
        """De-serialize span from a dictionary."""
        started_at = datetime.fromisoformat(data["started_at"])
        ended_at = (
            datetime.fromisoformat(data["ended_at"])
            if data.get("ended_at")
            else None
        )
        return cls(
            span_id=data["span_id"],
            trace_id=data["trace_id"],
            parent_span_id=data.get("parent_span_id"),
            operation_name=data["operation_name"],
            component=data["component"],
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=data.get("duration_ms"),
            status=SpanStatus(data["status"]),
            tags=data.get("tags") or {},
            error_message=data.get("error_message"),
        )


class TraceStore:
    """Persists traces to .projectos_state/traces.jsonl."""

    def __init__(self, state_dir: Path, max_traces: int = 10000) -> None:
        """Initialize trace store with directory and max trace limit."""
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.state_dir / "traces.jsonl"
        self.max_traces = max_traces
        self._lock = threading.Lock()

    def save_span(self, span: Span) -> None:
        """Atomic append to traces.jsonl."""
        record = span.to_dict()
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        encoded_line = line.encode("utf-8")

        with self._lock:
            file_descriptor = os.open(
                self.log_path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )
            try:
                os.write(file_descriptor, encoded_line)
            finally:
                os.close(file_descriptor)

    def load_trace(self, trace_id: str) -> List[Span]:
        """Read traces.jsonl, filter by trace_id."""
        if not self.log_path.exists():
            return []

        spans = []
        with self._lock:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("trace_id") == trace_id:
                            spans.append(Span.from_dict(data))
                    except Exception:
                        continue

        return sorted(spans, key=lambda s: s.started_at)

    def load_recent_traces(self, limit: int = 20) -> List[str]:
        """Return last N unique trace_ids (by first span timestamp)."""
        if not self.log_path.exists():
            return []

        trace_starts = {}
        with self._lock:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        t_id = data.get("trace_id")
                        started_at = datetime.fromisoformat(data["started_at"])
                        if t_id:
                            if (
                                t_id not in trace_starts
                                or started_at < trace_starts[t_id]
                            ):
                                trace_starts[t_id] = started_at
                    except Exception:
                        continue

        sorted_traces = sorted(
            trace_starts.items(), key=lambda x: x[1], reverse=True
        )
        return [t_id for t_id, _ in sorted_traces[:limit]]

    def get_slow_traces(
        self,
        threshold_ms: int = 5000,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Finds traces where total duration > threshold_ms."""
        if not self.log_path.exists():
            return []

        from collections import defaultdict

        trace_spans = defaultdict(list)

        with self._lock:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        t_id = data.get("trace_id")
                        if t_id:
                            trace_spans[t_id].append(data)
                    except Exception:
                        continue

        slow_traces = []
        for t_id, spans in trace_spans.items():
            earliest_start = None
            latest_end = None
            event_type = "unknown"

            for s in spans:
                start = datetime.fromisoformat(s["started_at"])
                if earliest_start is None or start < earliest_start:
                    earliest_start = start

                if "event_type" in s.get("tags", {}):
                    event_type = s["tags"]["event_type"]

                if s.get("ended_at"):
                    end = datetime.fromisoformat(s["ended_at"])
                    if latest_end is None or end > latest_end:
                        latest_end = end

            if earliest_start and latest_end:
                duration = int(
                    (latest_end - earliest_start).total_seconds() * 1000
                )
                if duration > threshold_ms:
                    slow_traces.append(
                        {
                            "trace_id": t_id,
                            "total_duration_ms": duration,
                            "event_type": event_type,
                            "span_count": len(spans),
                            "started_at": earliest_start,
                        }
                    )

        slow_traces.sort(key=lambda x: x["total_duration_ms"], reverse=True)
        for st in slow_traces:
            st.pop("started_at", None)

        return slow_traces[:limit]

    def prune_old_traces(self, keep_days: int = 7) -> int:
        """Removes traces older than keep_days. Returns count removed."""
        if not self.log_path.exists():
            return 0

        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)

        trace_earliest = {}
        all_spans = []

        with self._lock:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        all_spans.append(data)
                        t_id = data.get("trace_id")
                        start = datetime.fromisoformat(data["started_at"])
                        if t_id:
                            if (
                                t_id not in trace_earliest
                                or start < trace_earliest[t_id]
                            ):
                                trace_earliest[t_id] = start
                    except Exception:
                        continue

            traces_to_keep = {
                t_id
                for t_id, earliest in trace_earliest.items()
                if earliest >= cutoff
            }

            kept_lines = []
            removed_traces = set(trace_earliest.keys()) - traces_to_keep

            for s in all_spans:
                if s.get("trace_id") in traces_to_keep:
                    line = (
                        json.dumps(s, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    )
                    kept_lines.append(line)

            if kept_lines:
                temp_path = self.log_path.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.writelines(kept_lines)
                os.replace(temp_path, self.log_path)
            else:
                if self.log_path.exists():
                    os.unlink(self.log_path)

        return len(removed_traces)


class Tracer:
    """Lightweight distributed tracer."""

    def __init__(self, trace_store: TraceStore, enabled: bool = True) -> None:
        """Initialize the tracer with a store and enable flag."""
        self.trace_store = trace_store
        self.enabled = enabled
        self._lock = threading.Lock()
        self._event_to_trace: Dict[str, str] = {}
        self._local = threading.local()

    def start_trace(self, event_id: str, event_type: str) -> str:
        """Creates a new trace_id for this event and returns it."""
        if not self.enabled:
            return ""
        trace_id = str(uuid.uuid4())
        with self._lock:
            self._event_to_trace[event_id] = trace_id

        self._local.current_trace_id = trace_id
        return trace_id

    def start_span(
        self,
        operation_name: str,
        component: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None,
    ) -> Span:
        """Creates and returns a new Span."""
        if not self.enabled:
            return Span(
                span_id="",
                trace_id="",
                parent_span_id=None,
                operation_name=operation_name,
                component=component,
                started_at=datetime.now(timezone.utc),
                ended_at=None,
                duration_ms=None,
                status=SpanStatus.OK,
                tags=tags or {},
                error_message=None,
                _trace_store=None,
            )

        if not hasattr(self._local, "spans"):
            self._local.spans = []

        if parent_span_id is None and self._local.spans:
            parent_span_id = self._local.spans[-1].span_id

        if not trace_id:
            if self._local.spans:
                trace_id = self._local.spans[-1].trace_id
            elif hasattr(self._local, "current_trace_id"):
                trace_id = self._local.current_trace_id
            else:
                trace_id = str(uuid.uuid4())

        return Span(
            span_id=str(uuid.uuid4()),
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            component=component,
            started_at=datetime.now(timezone.utc),
            ended_at=None,
            duration_ms=None,
            status=SpanStatus.OK,
            tags=tags or {},
            error_message=None,
            _trace_store=self.trace_store,
        )

    @contextlib.contextmanager
    def span(
        self,
        operation_name: str,
        component: str,
        trace_id: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Span]:
        """Context manager version of span logging."""
        span_obj = self.start_span(
            operation_name=operation_name,
            component=component,
            trace_id=trace_id,
            tags=tags,
        )

        if not hasattr(self._local, "spans"):
            self._local.spans = []

        if self.enabled:
            self._local.spans.append(span_obj)

        try:
            yield span_obj
            if self.enabled and span_obj.ended_at is None:
                span_obj.finish(SpanStatus.OK)
        except Exception as e:
            if self.enabled:
                span_obj.finish(SpanStatus.ERROR, error=str(e))
            raise
        finally:
            if self.enabled and self._local.spans:
                self._local.spans.pop()

    def get_trace(self, trace_id: str) -> List[Span]:
        """Returns all spans for a trace, sorted by started_at."""
        if not self.enabled:
            return []
        return self.trace_store.load_trace(trace_id)

    def get_trace_for_event(self, event_id: str) -> Optional[List[Span]]:
        """Looks up trace_id by event_id, returns spans."""
        if not self.enabled:
            return None

        with self._lock:
            trace_id = self._event_to_trace.get(event_id)

        if not trace_id:
            # Look up in trace file
            if self.trace_store.log_path.exists():
                with self.trace_store._lock:
                    try:
                        with open(self.trace_store.log_path, "r", encoding="utf-8") as f:
                            for line in f:
                                if not line.strip():
                                    continue
                                try:
                                    data = json.loads(line)
                                    if (
                                        data.get("tags", {}).get("event_id")
                                        == event_id
                                    ):
                                        trace_id = data.get("trace_id")
                                        break
                                except Exception:
                                    continue
                    except Exception:
                        pass

            if trace_id:
                with self._lock:
                    self._event_to_trace[event_id] = trace_id

        if trace_id:
            return self.get_trace(trace_id)
        return None
