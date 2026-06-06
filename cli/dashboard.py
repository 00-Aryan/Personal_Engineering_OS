"""Rich terminal dashboard for ProjectOS runtime activity."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from core.decision_log import DecisionLogger
from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.quality_gate import DEFAULT_POLICIES, GATE_LOG_NAME, QualityGate
from core.evaluation.quality_scorer import QualityScorer
from core.evaluation.regression_detector import RegressionDetector
from core.evaluation.static_analyzer import StaticAnalyzer
from core.persistence import PersistenceManager
from core.provider_health import ProviderHealthMonitor
from core.task_queue import TaskQueue
from core.observability.alerting import AlertManager, AlertSeverity

try:
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
except ImportError:
    Layout = None
    Live = None
    Panel = None
    Table = None


DEFAULT_REFRESH_INTERVAL = 1.0
THREAD_NAME = "projectos-dashboard"

STATUS_RUNNING = "RUNNING"
STATUS_STOPPED = "STOPPED"
STATUS_IDLE = "IDLE"
STATUS_ACTIVE = "ACTIVE"
STATUS_HEALTHY = "Healthy"
STATUS_DOWN = "Down"

AGENT_NAMES = (
    "clone",
    "planning",
    "code_writing",
    "code_review",
    "architecture",
    "test",
    "docs",
)

TITLE_PROJECTOS_DASHBOARD = "ProjectOS Dashboard"
TITLE_AGENTS = "Agents"
TITLE_PROVIDERS = "Providers"
TITLE_QUALITY = "Quality"
TITLE_QUEUE = "Queue"
TITLE_RECENT_DECISIONS = "Recent Decisions (last 5)"

LAYOUT_ROOT = "root"
LAYOUT_HEADER = "header"
LAYOUT_BODY = "body"
LAYOUT_AGENTS = "agents"
LAYOUT_PROVIDERS = "providers"
LAYOUT_QUALITY = "quality"
LAYOUT_QUEUE = "queue"
LAYOUT_DECISIONS = "decisions"

COLUMN_AGENT = "Agent"
COLUMN_STATUS = "Status"
COLUMN_PROVIDER = "Provider"
COLUMN_HEALTH = "Health"
COLUMN_SCORE = "Score"
COLUMN_BLOCK_RATE = "Block"
COLUMN_BASELINES = "Baselines"
COLUMN_TIME = "Time"
COLUMN_CATEGORY = "Category"
COLUMN_OUTCOME = "Outcome"

FIELD_TIMESTAMP = "timestamp"
FIELD_AGENT_NAME = "agent_name"
FIELD_DECISION_CATEGORY = "decision_category"
FIELD_OUTCOME = "outcome"
FIELD_REASONING = "reasoning"
STATUS_KEY_AGENT_STATUSES = "agent_statuses"

TEXT_TRUE_ICON = "✓"
TEXT_FALSE_ICON = "✗"
TEXT_NONE = "none"
TEXT_SEPARATOR = " | "
TEXT_NEWLINE = "\n"
TEXT_HEADER_TEMPLATE = "Status: {status} | Uptime: {uptime} | Tasks: {tasks}"
TEXT_QUEUE_TEMPLATE = (
    "Pending: {pending}  Blocked: {blocked}  Completed today: {completed}"
)
TEXT_PROVIDER_TEMPLATE = "{icon} {status}"
TEXT_DECISION_TEMPLATE = "{time} {agent} {category} {outcome}"
TEXT_QUALITY_TEMPLATE = "{agent} score={score} block={block_rate} baselines={baselines}"
ENCODING = "utf-8"

SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60
DECISION_LIMIT = 5
SUMMARY_DECISION_LIMIT = 1000
MIN_REFRESH_PER_SECOND = 1
TIMESTAMP_TIME_LENGTH = 8
QUALITY_EVALUATOR_NAME = "llm_judge"
QUALITY_SCORE_MISSING = "--"
QUALITY_SCORE_TEMPLATE = "{score:.2f}"
QUALITY_BLOCK_RATE_TEMPLATE = "{block_rate:.1f}%"
QUALITY_GATE_WINDOW = 100


@dataclass(frozen=True)
class AgentStatus:
    """One dashboard agent status row."""

    name: str
    status: str


@dataclass(frozen=True)
class ProviderStatus:
    """One provider health row."""

    name: str
    healthy: bool


@dataclass(frozen=True)
class QueueSummary:
    """Queue counts shown by the dashboard."""

    pending: int
    blocked: int
    completed_today: int


@dataclass(frozen=True)
class DecisionRow:
    """One recent decision row."""

    timestamp: str
    agent_name: str
    decision_category: str
    outcome: str
    reasoning: str


@dataclass(frozen=True)
class QualityRow:
    """One quality metrics row for an agent."""

    agent_name: str
    avg_score: Optional[float]
    block_rate: float
    baseline_count: int


@dataclass(frozen=True)
class DashboardData:
    """Complete dashboard snapshot for rendering and tests."""

    status: str
    uptime: str
    agents: tuple[AgentStatus, ...]
    providers: tuple[ProviderStatus, ...]
    quality: tuple[QualityRow, ...]
    queue: QueueSummary
    recent_decisions: tuple[DecisionRow, ...]
    active_alerts: tuple[Any, ...] = ()


class Dashboard:
    """Render ProjectOS runtime state in a non-blocking terminal dashboard."""

    def __init__(
        self,
        task_queue: TaskQueue,
        decision_logger: DecisionLogger,
        persistence_manager: PersistenceManager,
        health_monitor: ProviderHealthMonitor,
        refresh_interval: float = DEFAULT_REFRESH_INTERVAL,
        evaluation_store: Optional[EvaluationStore] = None,
        quality_gate: Optional[QualityGate] = None,
        regression_detector: Optional[RegressionDetector] = None,
        alert_manager: Optional[AlertManager] = None,
    ) -> None:
        """Initialize dashboard component references and thread state."""
        self.task_queue = task_queue
        self.decision_logger = decision_logger
        self.persistence_manager = persistence_manager
        self.health_monitor = health_monitor
        self.refresh_interval = max(float(refresh_interval), 0.1)
        state_dir = self.persistence_manager.state_dir
        self.evaluation_store = evaluation_store or EvaluationStore(state_dir)
        self.regression_detector = regression_detector or RegressionDetector(
            self.evaluation_store,
            state_dir,
        )
        self.quality_gate = quality_gate or self._default_quality_gate(state_dir)
        self.alert_manager = alert_manager or AlertManager(state_dir)
        self._started_at = datetime.now(timezone.utc)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def run(self) -> None:
        """Start the live dashboard in a daemon thread when Rich is available."""
        if Live is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_live_loop,
            name=THREAD_NAME,
            daemon=True,
        )
        self._thread.start()

    @property
    def is_available(self) -> bool:
        """Return whether the Rich dashboard renderer is importable."""
        return Live is not None

    def stop(self) -> None:
        """Stop the dashboard thread without raising."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.refresh_interval * 2)

    def layout_data(self) -> DashboardData:
        """Fetch current dashboard data from ProjectOS components."""
        pending_count = self._pending_count()
        blocked_count = self._blocked_count()
        recent_decisions = self._recent_decisions()
        try:
            active_alerts = tuple(self.alert_manager.get_active_alerts())
        except Exception:
            active_alerts = ()
        return DashboardData(
            status=STATUS_STOPPED if self._stop_event.is_set() else STATUS_RUNNING,
            uptime=self._uptime(),
            agents=self._agent_statuses(pending_count),
            providers=self._provider_statuses(),
            quality=self._quality_rows(),
            queue=QueueSummary(
                pending=pending_count,
                blocked=blocked_count,
                completed_today=self._completed_today(),
            ),
            recent_decisions=recent_decisions,
            active_alerts=active_alerts,
        )

    def render(self) -> Any:
        """Build a Rich renderable or plain text fallback."""
        data = self.layout_data()
        if Layout is None or Panel is None or Table is None:
            return self._plain_render(data)
        layout = Layout(name=LAYOUT_ROOT)
        layout.split_column(
            Layout(
                Panel(self._header_text(data), title=TITLE_PROJECTOS_DASHBOARD),
                name=LAYOUT_HEADER,
                size=3,
            ),
            Layout(name=LAYOUT_BODY, ratio=2),
            Layout(
                Panel(self._alerts_panel_content(data.active_alerts), title="Active Alerts"),
                name="alerts",
                ratio=1,
            ),
            Layout(
                Panel(self._queue_text(data.queue), title=TITLE_QUEUE),
                name=LAYOUT_QUEUE,
                size=3,
            ),
            Layout(
                Panel(
                    self._decisions_table(data.recent_decisions),
                    title=TITLE_RECENT_DECISIONS,
                ),
                name=LAYOUT_DECISIONS,
                ratio=2,
            ),
        )
        layout[LAYOUT_BODY].split_row(
            Layout(
                Panel(self._agents_table(data.agents), title=TITLE_AGENTS),
                name=LAYOUT_AGENTS,
            ),
            Layout(
                Panel(self._providers_table(data.providers), title=TITLE_PROVIDERS),
                name=LAYOUT_PROVIDERS,
            ),
            Layout(
                Panel(self._quality_table(data.quality), title=TITLE_QUALITY),
                name=LAYOUT_QUALITY,
            ),
        )
        return layout

    def _run_live_loop(self) -> None:
        """Refresh the Rich Live display until stop is requested."""
        if Live is None:
            return
        with Live(
            self.render(),
            refresh_per_second=self._refresh_per_second(),
            screen=False,
        ) as live:
            while not self._stop_event.wait(self.refresh_interval):
                live.update(self.render())

    def _refresh_per_second(self) -> int:
        """Return the Rich refresh-per-second setting."""
        return max(int(1 / self.refresh_interval), MIN_REFRESH_PER_SECOND)

    def _pending_count(self) -> int:
        """Return pending task count from the live queue."""
        try:
            return int(self.task_queue.get_pending_count())
        except Exception:
            return 0

    def _blocked_count(self) -> int:
        """Return blocked task count from the live queue."""
        try:
            return len(self.task_queue.get_blocked())
        except Exception:
            return 0

    def _agent_statuses(self, pending_count: int) -> tuple[AgentStatus, ...]:
        """Return agent statuses from persisted state with live fallback."""
        persisted_statuses = self._persisted_agent_statuses()
        if persisted_statuses:
            return tuple(
                AgentStatus(name=name, status=status)
                for name, status in persisted_statuses.items()
            )
        default_status = STATUS_ACTIVE if pending_count else STATUS_IDLE
        return tuple(AgentStatus(name=name, status=default_status) for name in AGENT_NAMES)

    def _persisted_agent_statuses(self) -> dict[str, str]:
        """Return persisted agent status values from the status snapshot."""
        payload = self._status_payload()
        agent_statuses = payload.get(STATUS_KEY_AGENT_STATUSES)
        if not isinstance(agent_statuses, Mapping):
            return {}
        return {
            str(agent_name): str(status)
            for agent_name, status in agent_statuses.items()
        }

    def _provider_statuses(self) -> tuple[ProviderStatus, ...]:
        """Return provider health from the health monitor."""
        try:
            statuses = self.health_monitor.get_status()
        except Exception:
            statuses = {}
        if not isinstance(statuses, Mapping):
            return tuple()
        return tuple(
            ProviderStatus(name=str(provider_name), healthy=bool(healthy))
            for provider_name, healthy in statuses.items()
        )

    def _quality_rows(self) -> tuple[QualityRow, ...]:
        """Return local quality metrics for dashboard display."""
        baselines = self._quality_baselines()
        return tuple(
            QualityRow(
                agent_name=agent_name,
                avg_score=self._agent_average_score(agent_name),
                block_rate=self._agent_block_rate(agent_name),
                baseline_count=self._agent_baseline_count(agent_name, baselines),
            )
            for agent_name in AGENT_NAMES
        )

    def _recent_decisions(self) -> tuple[DecisionRow, ...]:
        """Return the most recent decision log rows."""
        records = self._decision_records(DECISION_LIMIT)
        return tuple(self._decision_row(record) for record in records)

    def _completed_today(self) -> int:
        """Return the count of decision records written today."""
        today = datetime.now(timezone.utc).date()
        return sum(
            1
            for record in self._decision_records(SUMMARY_DECISION_LIMIT)
            if self._record_date(record) == today
        )

    def _decision_records(self, limit: int) -> list[Mapping[str, Any]]:
        """Return recent decision records from the decision logger."""
        try:
            records = self.decision_logger.query(limit=limit)
        except Exception:
            return []
        return [record for record in records if isinstance(record, Mapping)]

    def _record_date(self, record: Mapping[str, Any]) -> Any:
        """Return a decision record date or None when unavailable."""
        timestamp = record.get(FIELD_TIMESTAMP)
        if not isinstance(timestamp, str):
            return None
        try:
            return datetime.fromisoformat(timestamp).date()
        except ValueError:
            return None

    def _decision_row(self, record: Mapping[str, Any]) -> DecisionRow:
        """Convert one decision mapping to a display row."""
        return DecisionRow(
            timestamp=self._time_text(record.get(FIELD_TIMESTAMP)),
            agent_name=str(record.get(FIELD_AGENT_NAME, TEXT_NONE)),
            decision_category=str(record.get(FIELD_DECISION_CATEGORY, TEXT_NONE)),
            outcome=str(record.get(FIELD_OUTCOME, TEXT_NONE)),
            reasoning=str(record.get(FIELD_REASONING, TEXT_NONE)),
        )

    def _status_payload(self) -> Mapping[str, Any]:
        """Read the persisted status snapshot when it exists."""
        status_path = self.persistence_manager.status_path
        if not isinstance(status_path, Path) or not status_path.exists():
            return {}
        try:
            payload = json.loads(status_path.read_text(encoding=ENCODING))
        except (json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, Mapping) else {}

    def _default_quality_gate(self, state_dir: Path) -> QualityGate:
        """Create the local quality gate used by the dashboard."""
        static_analyzer = StaticAnalyzer()
        quality_scorer = QualityScorer(static_analyzer, self.evaluation_store)
        return QualityGate(
            DEFAULT_POLICIES,
            quality_scorer,
            self.regression_detector,
            state_dir / GATE_LOG_NAME,
        )

    def _agent_average_score(self, agent_name: str) -> Optional[float]:
        """Return average evaluation score for an agent without raising."""
        try:
            return self.evaluation_store.get_agent_average_score(
                agent_name,
                QUALITY_EVALUATOR_NAME,
            )
        except Exception:
            return None

    def _agent_block_rate(self, agent_name: str) -> float:
        """Return recent quality gate block rate for an agent without raising."""
        try:
            return self.quality_gate.get_block_rate(agent_name, QUALITY_GATE_WINDOW)
        except Exception:
            return 0.0

    def _quality_baselines(self) -> Mapping[str, Mapping[str, Any]]:
        """Return regression baselines without raising."""
        try:
            baselines = self.regression_detector.get_all_baselines()
        except Exception:
            return {}
        return baselines if isinstance(baselines, Mapping) else {}

    def _agent_baseline_count(
        self,
        agent_name: str,
        baselines: Mapping[str, Mapping[str, Any]],
    ) -> int:
        """Return number of regression baselines stored for one agent."""
        return sum(
            1
            for record in baselines.values()
            if isinstance(record, Mapping)
            and str(record.get(FIELD_AGENT_NAME, TEXT_NONE)) == agent_name
        )

    def _uptime(self) -> str:
        """Return dashboard uptime as HH:MM:SS."""
        elapsed_seconds = int(
            (datetime.now(timezone.utc) - self._started_at).total_seconds()
        )
        hours = elapsed_seconds // SECONDS_PER_HOUR
        minutes = (elapsed_seconds % SECONDS_PER_HOUR) // SECONDS_PER_MINUTE
        seconds = elapsed_seconds % SECONDS_PER_MINUTE
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _time_text(self, value: Any) -> str:
        """Return HH:MM:SS from an ISO timestamp or a placeholder."""
        if not isinstance(value, str):
            return TEXT_NONE
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value[:TIMESTAMP_TIME_LENGTH]
        return parsed.strftime("%H:%M:%S")

    def _alerts_panel_content(self, active_alerts: tuple[Any, ...]) -> str:
        """Format the active alerts panel content."""
        if not active_alerts:
            return "No active alerts.\n\n0 active | projectos alerts acknowledge-all to clear"

        lines = []
        for alert in active_alerts:
            if alert.severity == AlertSeverity.CRITICAL:
                indicator = "🔴 CRITICAL "
            elif alert.severity == AlertSeverity.WARNING:
                indicator = "🟡 WARNING  "
            else:
                indicator = "🟢 INFO     "

            lines.append(f"{indicator} {alert.title}")
            if alert.message:
                msg_lines = alert.message.split("\n")
                for msg_line in msg_lines:
                    lines.append(f"             {msg_line}")

        lines.append("")
        lines.append(f"{len(active_alerts)} active | projectos alerts acknowledge-all to clear")
        return "\n".join(lines)

    def _plain_render(self, data: DashboardData) -> str:
        """Return a plain text dashboard when Rich is unavailable."""
        lines = [
            TITLE_PROJECTOS_DASHBOARD,
            self._header_text(data),
            self._queue_text(data.queue),
        ]
        lines.extend(
            TEXT_QUALITY_TEMPLATE.format(
                agent=row.agent_name,
                score=self._quality_score_text(row.avg_score),
                block_rate=self._quality_block_rate_text(row.block_rate),
                baselines=row.baseline_count,
            )
            for row in data.quality
        )
        lines.append("\nActive Alerts:")
        lines.append(self._alerts_panel_content(data.active_alerts))
        lines.append("\nRecent Decisions:")
        lines.extend(
            TEXT_DECISION_TEMPLATE.format(
                time=decision.timestamp,
                agent=decision.agent_name,
                category=decision.decision_category,
                outcome=decision.outcome,
            )
            for decision in data.recent_decisions
        )
        return TEXT_NEWLINE.join(lines)

    def _header_text(self, data: DashboardData) -> str:
        """Return dashboard header text."""
        return TEXT_HEADER_TEMPLATE.format(
            status=data.status,
            uptime=data.uptime,
            tasks=data.queue.pending,
        )

    def _queue_text(self, queue_summary: QueueSummary) -> str:
        """Return queue summary text."""
        return TEXT_QUEUE_TEMPLATE.format(
            pending=queue_summary.pending,
            blocked=queue_summary.blocked,
            completed=queue_summary.completed_today,
        )

    def _agents_table(self, agents: tuple[AgentStatus, ...]) -> Any:
        """Return the Rich agents table."""
        table = Table(title=TITLE_AGENTS)
        table.add_column(COLUMN_AGENT)
        table.add_column(COLUMN_STATUS)
        for agent in agents:
            table.add_row(agent.name, agent.status)
        return table

    def _providers_table(self, providers: tuple[ProviderStatus, ...]) -> Any:
        """Return the Rich providers table."""
        table = Table(title=TITLE_PROVIDERS)
        table.add_column(COLUMN_PROVIDER)
        table.add_column(COLUMN_HEALTH)
        for provider in providers:
            table.add_row(provider.name, self._provider_health_text(provider))
        return table

    def _quality_table(self, rows: tuple[QualityRow, ...]) -> Any:
        """Return the Rich quality metrics table."""
        table = Table(title=TITLE_QUALITY)
        table.add_column(COLUMN_AGENT)
        table.add_column(COLUMN_SCORE)
        table.add_column(COLUMN_BLOCK_RATE)
        table.add_column(COLUMN_BASELINES)
        for row in rows:
            table.add_row(
                row.agent_name,
                self._quality_score_text(row.avg_score),
                self._quality_block_rate_text(row.block_rate),
                str(row.baseline_count),
            )
        return table

    def _decisions_table(self, decisions: tuple[DecisionRow, ...]) -> Any:
        """Return the Rich recent decisions table."""
        table = Table()
        table.add_column(COLUMN_TIME)
        table.add_column(COLUMN_AGENT)
        table.add_column(COLUMN_CATEGORY)
        table.add_column(COLUMN_OUTCOME)
        for decision in decisions:
            table.add_row(
                decision.timestamp,
                decision.agent_name,
                decision.decision_category,
                decision.outcome,
            )
        return table

    def _provider_health_text(self, provider: ProviderStatus) -> str:
        """Return provider health text with a compact status marker."""
        icon = TEXT_TRUE_ICON if provider.healthy else TEXT_FALSE_ICON
        status = STATUS_HEALTHY if provider.healthy else STATUS_DOWN
        return TEXT_PROVIDER_TEMPLATE.format(icon=icon, status=status)

    def _quality_score_text(self, score: Optional[float]) -> str:
        """Return display text for an optional quality score."""
        if score is None:
            return QUALITY_SCORE_MISSING
        return QUALITY_SCORE_TEMPLATE.format(score=score)

    def _quality_block_rate_text(self, block_rate: float) -> str:
        """Return display text for a quality gate block rate."""
        return QUALITY_BLOCK_RATE_TEMPLATE.format(block_rate=block_rate * 100.0)


__all__ = [
    "AgentStatus",
    "Dashboard",
    "DashboardData",
    "DecisionRow",
    "ProviderStatus",
    "QualityRow",
    "QueueSummary",
]
