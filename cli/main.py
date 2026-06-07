"""Click command line interface for ProjectOS."""

from __future__ import annotations

import os
import json
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

import click
import yaml

from cli.dashboard import Dashboard
from core.decision_log import DecisionLogger
from core.evaluation.audit_report import EvaluationAuditReport
from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.quality_gate import (
    DEFAULT_POLICIES,
    GATE_LOG_NAME,
    GateDecision,
    QualityGate,
)
from core.evaluation.quality_scorer import QualityScorer
from core.evaluation.regression_detector import RegressionDetector
from core.evaluation.static_analyzer import StaticAnalyzer
from core.events import AgentEvent, AgentResult, EventType
from core.observability.tracer import Tracer, TraceStore, SpanStatus, Span
from core.observability.performance_monitor import PerformanceMonitor
from core.observability.token_budget import TokenBudget
from core.observability.cost_tracker import CostTracker
from core.observability.alerting import AlertManager, AlertSeverity

from core.intelligence.code_indexer import CodeIndexer
from core.intelligence.collaboration import COLLABORATION_LOG_NAME, CollaborationBroker
from core.intelligence.embedder import EmbedderFactory
from core.intelligence.semantic_router import (
    ROUTING_DECISIONS_FILE_NAME,
    ROUTING_EXAMPLES_COLLECTION,
    RoutingExample,
    SemanticRouter,
)
from core.intelligence.vector_store import (
    BaseVectorStore,
    SearchResult,
    VectorRecord,
    VectorStoreFactory,
)
from core.project_config import ProjectConfig, ProjectRegistry
from core.projectos import MultiProjectOS, ProjectOS
from core.task_queue import TaskQueue
from scripts.quality_benchmark import (
    BenchmarkSuite,
    HISTORY_HEADER,
    NO_HISTORY_MESSAGE,
    exit_code_for_report,
    history_rows,
)


DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENCODING = "utf-8"
FILE_WRITE_MODE = "w"
NEWLINE = "\n"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"

CONFIG_PATH = "config/models.yaml"
TASKS_README_PATH = "tasks/README.md"
BACKLOG_PATH = "backlog.md"
DECISIONS_LOG_PATH = "decisions.log"
ESCALATION_QUEUE_PATH = "escalation_queue.md"
STATE_DIR_PATH = ".projectos_state"
LAST_STATUS_FILE = "last_status.json"

CONFIG_KEY_AGENTS = "agents"
CONFIG_KEY_MODEL = "model"
CONFIG_KEY_PROVIDERS = "providers"
STATUS_KEY_TIMESTAMP = "timestamp"
STATUS_KEY_PENDING_COUNT = "pending_count"
STATUS_KEY_BLOCKED_COUNT = "blocked_count"
STATUS_KEY_PROVIDER_HEALTH = "provider_health"
PROJECT_STATUS_ENABLED = "enabled"
SOURCE_AGENT_REVIEW_COMMAND = "cli_review"
PAYLOAD_KEY_FILE_PATH = "file_path"
PAYLOAD_KEY_MANUAL = "manual"

STATUS_LABEL_AGENTS = "Agents"
STATUS_LABEL_PENDING = "Pending tasks count"
STATUS_LABEL_LAST_ACTIVITY = "Last activity"
STATUS_LABEL_LAST_SEEN = "Last seen"
STATUS_LABEL_PERSISTED_PENDING = "Persisted pending count"
STATUS_LABEL_PERSISTED_BLOCKED = "Persisted blocked count"
STATUS_LABEL_PROVIDER_HEALTH = "Provider health"
MISSING_VALUE = "none"
HEALTHY_VALUE = "Healthy"
UNREACHABLE_VALUE = "Unreachable"
PENDING_STATUS = "PENDING"
APPROVED_STATUS = "APPROVED"
REJECTED_STATUS = "REJECTED"

PRIORITY_HIGH = "HIGH"
PRIORITY_MEDIUM = "MEDIUM"
PRIORITY_LOW = "LOW"
COLOR_RED = "red"
COLOR_YELLOW = "yellow"
COLOR_GREEN = "green"

CONFIRM_APPROVE_TEMPLATE = "Approve item {event_id}"
NO_PENDING_ESCALATIONS = "No pending escalation items."
NO_BACKLOG_FOUND = "No backlog found."
MODEL_CONFIRMATION_TEMPLATE = "Agent {agent_name} now uses {model_name}"
REVIEW_SUBMITTED_TEMPLATE = "Submitted CODE_CHANGED for {file_path}"
RUNNING_MESSAGE = "ProjectOS daemon running. Press Ctrl+C to stop."
RUNNING_ALL_MESSAGE = "ProjectOS multi-project daemon running. Press Ctrl+C to stop."
SHUTDOWN_MESSAGE = "ProjectOS daemon stopped."
DASHBOARD_UNAVAILABLE_MESSAGE = "Rich dashboard unavailable; using plain output."
PROJECTS_EMPTY_MESSAGE = "No projects registered."
PROJECT_ADDED_TEMPLATE = "Added project {project_name}: {project_path}"
PROJECT_REMOVED_TEMPLATE = "Removed project {project_name}"
PROJECTS_HEADER = "name | path | status"
DECISIONS_TABLE_HEADER = (
    "timestamp | event_id | agent | category | outcome | escalated | reasoning"
)
DECISIONS_EMPTY_MESSAGE = "No decisions found."
GIT_COMMAND = "git"
GIT_TIMEOUT_SECONDS = 30
GIT_AUTHOR_FILTER = "ProjectOS"
GIT_LOG_LIMIT = "-10"
NO_AUTO_COMMITS_MESSAGE = "No ProjectOS auto-commits found."
GIT_LOG_ERROR_MESSAGE = "Unable to read ProjectOS git log."
QUALITY_EVALUATOR_NAME = "llm_judge"
QUALITY_HEADER = "Agent          Score   Baseline  Delta   Status"
QUALITY_BASELINE_HEADER = "Agent          Model          Baseline  Samples"
QUALITY_NO_BASELINES = "No quality baselines found."
QUALITY_RESET_TEMPLATE = "Reset baseline for {agent_name} ({model_version})"
QUALITY_STATUS_NO_DATA = "No Data"
QUALITY_STATUS_STABLE = "Stable"
QUALITY_STATUS_REGRESSION = "Regression"
QUALITY_MISSING_SCORE = "--"
QUALITY_DELTA_TEMPLATE = "{delta:+.2f}"
QUALITY_SCORE_TEMPLATE = "{score:.2f}"
QUALITY_BASELINE_KEY_TEMPLATE = "{agent_name}:{model_version}"
QUALITY_STABLE_RATIO = 0.90
QUALITY_FIELD_AGENT_NAME = "agent_name"
QUALITY_FIELD_MODEL_VERSION = "model_version"
QUALITY_FIELD_BASELINE_SCORE = "baseline_score"
QUALITY_FIELD_SAMPLE_SIZE = "sample_size"
QUALITY_AGENT_WIDTH = 14
QUALITY_SCORE_WIDTH = 7
QUALITY_BASELINE_WIDTH = 9
QUALITY_DELTA_WIDTH = 7
QUALITY_MODEL_WIDTH = 14
GATE_HEADER = "Agent          Block Rate  Last 10"
GATE_POLICY_HEADER = "Agent          Min Score  LLM  Static  Security  Regression"
GATE_OVERRIDE_TEMPLATE = "Bypassed gate decision for {event_id}: {reason}"
GATE_NO_DECISIONS = "No gate decisions found."
GATE_AGENT_WIDTH = 14
GATE_RATE_WIDTH = 12
GATE_SCORE_WIDTH = 11
GATE_FLAG_WIDTH = 5
GATE_SECURITY_WIDTH = 10
GATE_REGRESSION_WIDTH = 10
GATE_STATUS_PASS = "P"
GATE_STATUS_BLOCK = "B"
GATE_STATUS_ESCALATE = "E"
GATE_STATUS_BYPASS = "Y"
GATE_RATE_TEMPLATE = "{rate:.1f}%"
GATE_SCORE_TEMPLATE = "{score:.2f}"
GATE_TRUE = "yes"
GATE_FALSE = "no"
BENCHMARK_RUNNING_MESSAGE = "Running quality benchmark..."
AUDIT_DEFAULT_DAYS = 7
AUDIT_SAVED_TEMPLATE = "Saved audit report to {path}"
CODE_INDEX_COLLECTION_NAME = "code_index"
INDEX_STATUS_TEMPLATE = (
    "files indexed: {files}\n"
    "chunks stored: {chunks}\n"
    "embedder: {embedder}\n"
    "last updated: {last_updated}"
)
INDEX_REBUILD_TEMPLATE = (
    "Indexed {files} files, {chunks} chunks, {lines} lines in {duration_ms} ms"
)
INDEX_SEARCH_TEMPLATE = "{file_path} | {name} | {score:.2f}\n{preview}"
INDEX_UNKNOWN_VALUE = "unknown"
INDEX_PREVIEW_LINES = 3
ROUTER_STATS_TEMPLATE = (
    "total decisions: {total}\n"
    "semantic pct: {semantic_pct:.2f}\n"
    "fallback pct: {fallback_pct:.2f}\n"
    "avg confidence: {avg_confidence:.2f}\n"
    "decisions by category: {decisions_by_category}"
)
ROUTER_ADD_EXAMPLE_TEMPLATE = "Added routing example for {category}: {text}"
ROUTER_TEST_TEMPLATE = (
    "category: {category}\n"
    "confidence: {confidence:.2f}\n"
    "nearest example: {nearest_example}\n"
    "routing method: {routing_method}"
)
COLLAB_STATS_TEMPLATE = (
    "total consultations: {total}\n"
    "by type: {by_type}\n"
    "by requesting agent: {by_requesting_agent}\n"
    "avg duration ms: {avg_duration_ms}\n"
    "depth 1 pct: {depth_1_pct:.2f}"
)
COLLAB_LOG_TEMPLATE = (
    "{consultation_type} | {requesting_agent} -> {target_agent} | "
    "{duration_ms} ms\nQ: {question}\nA: {answer}"
)
COLLAB_EMPTY_MESSAGE = "No collaboration consultations found."


class EmptyAgentRegistry:
    """Minimal registry used when reading collaboration stats from disk."""

    def get(self, agent_name: str) -> object:
        """Raise for all lookup attempts."""
        raise KeyError(agent_name)

class ReviewSubmissionTarget:
    """Minimal target that records manually submitted review events."""

    def __init__(self) -> None:
        """Initialize the manual review target."""
        self.handled_events: list[AgentEvent] = []

    def handle(self, event: AgentEvent) -> AgentResult:
        """Record the review event and return a successful result."""
        self.handled_events.append(event)
        return AgentResult(success=True, output=dict(event.payload))


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


@click.group(name="projectos")
@click.option(
    "--project-root",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    hidden=True,
)
@click.pass_context
def cli(ctx: click.Context, project_root: Optional[Path]) -> None:
    """Run ProjectOS command line tools."""
    ctx.ensure_object(dict)
    if project_root is not None:
        ctx.obj["project_root"] = project_root
    elif "project_root" not in ctx.obj:
        ctx.obj["project_root"] = Path.cwd()


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show agent model assignments and project activity."""
    project_root = _project_root(ctx)
    config = _load_config(project_root)
    click.echo(f"{STATUS_LABEL_AGENTS}:")
    for agent_name, agent_config in _agent_configs(config).items():
        model_name = agent_config.get(CONFIG_KEY_MODEL, MISSING_VALUE)
        click.echo(f"- {agent_name}: {model_name}")
    click.echo(f"{STATUS_LABEL_PENDING}: {_pending_tasks_count(project_root)}")
    click.echo(f"{STATUS_LABEL_LAST_ACTIVITY}: {_last_activity(project_root)}")
    persisted_status = _last_status(project_root)
    click.echo(f"{STATUS_LABEL_PROVIDER_HEALTH}:")
    for provider_name, healthy in _provider_health(config, persisted_status).items():
        label = HEALTHY_VALUE if healthy else UNREACHABLE_VALUE
        click.echo(f"- {provider_name}: {label}")
    click.echo("Circuit Breakers:")
    for provider_name in ["gemini", "openrouter", "ollama"]:
        state_file = project_root / STATE_DIR_PATH / f"circuit_state_{provider_name}.json"
        state_str = "CLOSED"
        if state_file.exists():
            try:
                state_data = json.loads(state_file.read_text(encoding="utf-8"))
                state_str = state_data.get("state", "closed").upper()
            except Exception:
                pass
        click.echo(f"- {provider_name}: {state_str}")
    if persisted_status:
        click.echo(
            f"{STATUS_LABEL_LAST_SEEN}: "
            f"{persisted_status.get(STATUS_KEY_TIMESTAMP, MISSING_VALUE)}"
        )
        click.echo(
            f"{STATUS_LABEL_PERSISTED_PENDING}: "
            f"{persisted_status.get(STATUS_KEY_PENDING_COUNT, 0)}"
        )
        click.echo(
            f"{STATUS_LABEL_PERSISTED_BLOCKED}: "
            f"{persisted_status.get(STATUS_KEY_BLOCKED_COUNT, 0)}"
        )


@cli.command()
@click.argument("agent_name")
@click.argument("model_name")
@click.pass_context
def model(ctx: click.Context, agent_name: str, model_name: str) -> None:
    """Update one agent model in config/models.yaml."""
    project_root = _project_root(ctx)
    config = _load_config(project_root)
    agents = _agent_configs(config)
    if agent_name not in agents:
        raise click.ClickException(f"Unknown agent: {agent_name}")
    agents[agent_name][CONFIG_KEY_MODEL] = model_name
    _write_config(project_root, config)
    click.echo(
        MODEL_CONFIRMATION_TEMPLATE.format(
            agent_name=agent_name,
            model_name=model_name,
        )
    )


@cli.command()
@click.pass_context
def approve(ctx: click.Context) -> None:
    """Approve or reject pending escalation queue items."""
    project_root = _project_root(ctx)
    queue_path = project_root / ESCALATION_QUEUE_PATH
    if not queue_path.exists():
        click.echo(NO_PENDING_ESCALATIONS)
        return

    lines = queue_path.read_text(encoding=ENCODING).splitlines()
    updated_lines = _updated_escalation_lines(lines)
    if updated_lines == lines:
        click.echo(NO_PENDING_ESCALATIONS)
        return
    _write_atomically(queue_path, NEWLINE.join(updated_lines) + NEWLINE)


@cli.command()
@click.pass_context
def backlog(ctx: click.Context) -> None:
    """Print backlog markdown with priority colors."""
    project_root = _project_root(ctx)
    backlog_path = project_root / BACKLOG_PATH
    if not backlog_path.exists():
        click.echo(NO_BACKLOG_FOUND)
        return
    for line in backlog_path.read_text(encoding=ENCODING).splitlines():
        click.secho(line, fg=_priority_color(line))


@cli.command()
@click.argument("file_path", type=click.Path(path_type=Path))
@click.pass_context
def review(ctx: click.Context, file_path: Path) -> None:
    """Manually submit a CODE_CHANGED event for one file."""
    project_root = _project_root(ctx)
    task_queue = _task_queue(ctx)
    target_agent = _review_target_agent(ctx)
    resolved_path = file_path if file_path.is_absolute() else project_root / file_path
    event = AgentEvent(
        event_type=EventType.CODE_CHANGED,
        source_agent=SOURCE_AGENT_REVIEW_COMMAND,
        payload={
            PAYLOAD_KEY_FILE_PATH: str(resolved_path),
            PAYLOAD_KEY_MANUAL: True,
        },
    )
    task_queue.submit(event, target_agent)
    click.echo(REVIEW_SUBMITTED_TEMPLATE.format(file_path=resolved_path))


@cli.command()
@click.option("--dashboard", "use_dashboard", is_flag=True)
@click.option("--all", "run_all", is_flag=True)
@click.pass_context
def run(ctx: click.Context, use_dashboard: bool, run_all: bool) -> None:
    """Run the trigger system, Clone Agent, and task queue until interrupted."""
    if run_all:
        _run_all_projects()
        return

    project_root = _project_root(ctx)
    project_os = ProjectOS(project_root / CONFIG_PATH)
    dashboard = _dashboard(project_os) if use_dashboard else None
    project_os.start()
    if dashboard is not None:
        dashboard.run()
        if not dashboard.is_available:
            click.echo(DASHBOARD_UNAVAILABLE_MESSAGE)
            click.echo(RUNNING_MESSAGE)
    else:
        click.echo(RUNNING_MESSAGE)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if dashboard is not None:
            dashboard.stop()
        project_os.stop()
        click.echo(SHUTDOWN_MESSAGE)


@cli.group()
def projects() -> None:
    """Manage registered ProjectOS projects."""


@projects.command(name="list")
def projects_list() -> None:
    """List registered enabled ProjectOS projects."""
    registry = ProjectRegistry()
    project_configs = registry.list_projects()
    if not project_configs:
        click.echo(PROJECTS_EMPTY_MESSAGE)
        return
    click.echo(PROJECTS_HEADER)
    for project_config in project_configs:
        click.echo(_project_row(project_config))


@projects.command(name="add")
@click.option("--name", "project_name", required=True)
@click.option(
    "--path",
    "project_path",
    required=True,
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
)
def projects_add(project_name: str, project_path: Path) -> None:
    """Add one project to the global ProjectOS registry."""
    registry = ProjectRegistry()
    project_config = ProjectConfig.create(project_name, project_path)
    registry.add_project(project_config)
    click.echo(
        PROJECT_ADDED_TEMPLATE.format(
            project_name=project_config.name,
            project_path=project_config.root_path,
        )
    )


@projects.command(name="remove")
@click.option("--name", "project_name", required=True)
def projects_remove(project_name: str) -> None:
    """Remove one project from the global ProjectOS registry."""
    registry = ProjectRegistry()
    registry.remove_project(project_name)
    click.echo(PROJECT_REMOVED_TEMPLATE.format(project_name=project_name))


@cli.command(name="git-log")
@click.pass_context
def git_log(ctx: click.Context) -> None:
    """Show recent auto-commits made by ProjectOS."""
    project_root = _project_root(ctx)
    completed_process = _git_log(project_root)
    if completed_process is None:
        click.echo(GIT_LOG_ERROR_MESSAGE)
        return
    if completed_process.returncode != 0 or not completed_process.stdout.strip():
        click.echo(NO_AUTO_COMMITS_MESSAGE)
        return
    click.echo(completed_process.stdout.rstrip())


@cli.command()
@click.option("--tail", type=int, default=20, show_default=True)
@click.option("--summary", "show_summary", is_flag=True)
@click.option("--agent", "agent_name", default=None)
@click.pass_context
def decisions(
    ctx: click.Context,
    tail: int,
    show_summary: bool,
    agent_name: Optional[str],
) -> None:
    """Show machine-readable Clone decisions from decisions.jsonl."""
    project_root = _project_root(ctx)
    decision_logger = DecisionLogger(project_root)
    if show_summary:
        click.echo(json.dumps(decision_logger.summary(), indent=2, sort_keys=True))
        return

    records = decision_logger.query(agent_name=agent_name, limit=tail)
    if not records:
        click.echo(DECISIONS_EMPTY_MESSAGE)
        return
    click.echo(DECISIONS_TABLE_HEADER)
    for record in records:
        click.echo(_decision_table_row(record))


@cli.group()
def quality() -> None:
    """Inspect evaluation quality scores and baselines."""


@quality.command(name="status")
@click.pass_context
def quality_status(ctx: click.Context) -> None:
    """Show per-agent quality scores and regression status."""
    project_root = _project_root(ctx)
    config = _load_config(project_root)
    evaluation_store = EvaluationStore(project_root / STATE_DIR_PATH)
    regression_detector = RegressionDetector(
        evaluation_store,
        project_root / STATE_DIR_PATH,
    )
    baselines = regression_detector.get_all_baselines()
    click.echo(QUALITY_HEADER)
    for agent_name, agent_config in _agent_configs(config).items():
        model_version = str(agent_config.get(CONFIG_KEY_MODEL, MISSING_VALUE))
        score = evaluation_store.get_agent_average_score(
            agent_name,
            QUALITY_EVALUATOR_NAME,
        )
        baseline = _quality_baseline(baselines, agent_name, model_version)
        click.echo(_quality_status_row(agent_name, score, baseline))


@quality.command(name="baseline")
@click.pass_context
def quality_baseline(ctx: click.Context) -> None:
    """Show stored quality baselines with sample sizes."""
    project_root = _project_root(ctx)
    evaluation_store = EvaluationStore(project_root / STATE_DIR_PATH)
    regression_detector = RegressionDetector(
        evaluation_store,
        project_root / STATE_DIR_PATH,
    )
    baselines = regression_detector.get_all_baselines()
    if not baselines:
        click.echo(QUALITY_NO_BASELINES)
        return
    click.echo(QUALITY_BASELINE_HEADER)
    for record in baselines.values():
        click.echo(_quality_baseline_row(record))


@quality.command(name="reset")
@click.option("--agent", "agent_name", required=True)
@click.pass_context
def quality_reset(ctx: click.Context, agent_name: str) -> None:
    """Reset the baseline for one configured agent."""
    project_root = _project_root(ctx)
    config = _load_config(project_root)
    agent_configs = _agent_configs(config)
    if agent_name not in agent_configs:
        raise click.ClickException(f"Unknown agent: {agent_name}")
    model_version = str(agent_configs[agent_name].get(CONFIG_KEY_MODEL, MISSING_VALUE))
    evaluation_store = EvaluationStore(project_root / STATE_DIR_PATH)
    regression_detector = RegressionDetector(
        evaluation_store,
        project_root / STATE_DIR_PATH,
    )
    regression_detector.reset_baseline(agent_name, model_version)
    click.echo(
        QUALITY_RESET_TEMPLATE.format(
            agent_name=agent_name,
            model_version=model_version,
        )
    )


@cli.group()
def gate() -> None:
    """Inspect and override quality gate decisions."""


@gate.command(name="status")
@click.pass_context
def gate_status(ctx: click.Context) -> None:
    """Show block rates and recent gate decisions by agent."""
    quality_gate = _quality_gate(ctx)
    agent_names = _gate_agent_names(quality_gate)
    if not agent_names:
        click.echo(GATE_NO_DECISIONS)
        return
    click.echo(GATE_HEADER)
    for agent_name in agent_names:
        click.echo(_gate_status_row(quality_gate, agent_name))


@gate.command(name="override")
@click.argument("event_id")
@click.option("--reason", required=True)
@click.pass_context
def gate_override(ctx: click.Context, event_id: str, reason: str) -> None:
    """Mark a blocked quality gate decision as human-overridden."""
    quality_gate = _quality_gate(ctx)
    try:
        result = quality_gate.override(event_id, reason)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    click.echo(
        GATE_OVERRIDE_TEMPLATE.format(
            event_id=result.event_id,
            reason=result.override_reason,
        )
    )


@gate.command(name="policies")
@click.pass_context
def gate_policies(ctx: click.Context) -> None:
    """Show configured quality gate policies."""
    quality_gate = _quality_gate(ctx)
    click.echo(GATE_POLICY_HEADER)
    for policy in quality_gate.policies.values():
        click.echo(_gate_policy_row(policy))


@cli.group()
def benchmark() -> None:
    """Run and inspect ProjectOS quality benchmarks."""


@benchmark.command(name="run")
@click.pass_context
def benchmark_run(ctx: click.Context) -> None:
    """Run the mocked quality benchmark suite."""
    project_root = _project_root(ctx)
    click.echo(BENCHMARK_RUNNING_MESSAGE)
    report = BenchmarkSuite(project_root).run_all(use_mocks=True)
    click.echo(report.to_markdown())
    raise click.exceptions.Exit(exit_code_for_report(report))


@benchmark.command(name="history")
@click.pass_context
def benchmark_history(ctx: click.Context) -> None:
    """Show the last ten quality benchmark runs."""
    rows = history_rows(_project_root(ctx), limit=10)
    if not rows:
        click.echo(NO_HISTORY_MESSAGE)
        return
    click.echo(HISTORY_HEADER)
    for row in rows:
        click.echo(row)


@cli.command(name="audit")
@click.option("--days", type=int, default=AUDIT_DEFAULT_DAYS, show_default=True)
@click.option("--save", "save_path", type=click.Path(path_type=Path), default=None)
@click.option("--agent", "agent_name", default=None)
@click.pass_context
def audit(ctx: click.Context, days: int, save_path: Optional[Path], agent_name: Optional[str]) -> None:
    """Generate a human-readable quality audit report."""
    project_root = _project_root(ctx)
    since = datetime.now(timezone.utc) - timedelta(days=max(days, 0))
    report = EvaluationAuditReport(
        EvaluationStore(project_root / STATE_DIR_PATH),
        project_root / STATE_DIR_PATH / GATE_LOG_NAME,
        project_root / DECISIONS_LOG_PATH,
    ).generate(since, agent_filter=agent_name)
    if save_path is not None:
        resolved_path = save_path if save_path.is_absolute() else project_root / save_path
        _write_atomically(resolved_path, report)
        click.echo(AUDIT_SAVED_TEMPLATE.format(path=resolved_path))
        return
    _echo_markdown(report)


@cli.group(name="index")
def index_group() -> None:
    """Inspect and rebuild the ProjectOS code index."""


@index_group.command(name="status")
@click.pass_context
def index_status(ctx: click.Context) -> None:
    """Show current code index status."""
    project_root = _project_root(ctx)
    embedder, vector_store = _code_index_components(project_root)
    records = _vector_records(vector_store)
    files_indexed = len(
        {
            str(record.metadata.get(PAYLOAD_KEY_FILE_PATH))
            for record in records
            if record.metadata.get(PAYLOAD_KEY_FILE_PATH)
        }
    )
    click.echo(
        INDEX_STATUS_TEMPLATE.format(
            files=files_indexed,
            chunks=vector_store.count(),
            embedder=embedder.get_embedder_name(),
            last_updated=_last_index_update(records),
        )
    )


@index_group.command(name="rebuild")
@click.pass_context
def index_rebuild(ctx: click.Context) -> None:
    """Rebuild the entire code index for the project."""
    project_root = _project_root(ctx)
    embedder, vector_store = _code_index_components(project_root)
    indexer = CodeIndexer(vector_store, embedder)
    indexer.clear()
    report = indexer.index_directory(project_root)
    click.echo(
        INDEX_REBUILD_TEMPLATE.format(
            files=report.files_indexed,
            chunks=report.chunks_created,
            lines=report.total_lines_indexed,
            duration_ms=report.duration_ms,
        )
    )


@index_group.command(name="search")
@click.argument("query")
@click.option("--k", type=int, default=5, show_default=True)
@click.pass_context
def index_search(ctx: click.Context, query: str, k: int) -> None:
    """Search indexed code chunks semantically."""
    project_root = _project_root(ctx)
    embedder, vector_store = _code_index_components(project_root)
    results = vector_store.search(embedder.embed(query), k=max(k, 0))
    for result in results:
        click.echo(_index_search_row(result))


@cli.group(name="router")
def router_group() -> None:
    """Inspect and update the semantic Clone router."""


@router_group.command(name="stats")
@click.pass_context
def router_stats(ctx: click.Context) -> None:
    """Show semantic routing statistics."""
    router = _semantic_router(ctx)
    stats = router.get_routing_stats()
    click.echo(
        ROUTER_STATS_TEMPLATE.format(
            total=stats.get("total_decisions", 0),
            semantic_pct=float(stats.get("semantic_pct", 0.0)),
            fallback_pct=float(stats.get("fallback_pct", 0.0)),
            avg_confidence=float(stats.get("avg_confidence", 0.0)),
            decisions_by_category=json.dumps(
                stats.get("decisions_by_category", {}),
                sort_keys=True,
            ),
        )
    )


@router_group.command(name="add-example")
@click.argument("text")
@click.option("--category", required=True)
@click.pass_context
def router_add_example(ctx: click.Context, text: str, category: str) -> None:
    """Add a semantic routing example."""
    router = _semantic_router(ctx)
    router.add_example(RoutingExample(text=text, category=category))
    click.echo(ROUTER_ADD_EXAMPLE_TEMPLATE.format(category=category, text=text))


@router_group.command(name="test")
@click.argument("description")
@click.pass_context
def router_test(ctx: click.Context, description: str) -> None:
    """Show how the router classifies an event description."""
    router = _semantic_router(ctx)
    decision = router.route(description)
    click.echo(
        ROUTER_TEST_TEMPLATE.format(
            category=decision.category,
            confidence=decision.confidence,
            nearest_example=decision.nearest_example,
            routing_method=decision.routing_method,
        )
    )


@cli.group(name="collab")
def collab_group() -> None:
    """Inspect ProjectOS agent collaboration."""


@collab_group.command(name="stats")
@click.pass_context
def collab_stats(ctx: click.Context) -> None:
    """Show collaboration statistics."""
    stats = _collaboration_broker(ctx).get_collaboration_stats()
    click.echo(
        COLLAB_STATS_TEMPLATE.format(
            total=stats.get("total_consultations", 0),
            by_type=json.dumps(stats.get("by_type", {}), sort_keys=True),
            by_requesting_agent=json.dumps(
                stats.get("by_requesting_agent", {}),
                sort_keys=True,
            ),
            avg_duration_ms=stats.get("avg_duration_ms", 0),
            depth_1_pct=float(stats.get("depth_1_pct", 0.0)),
        )
    )


@collab_group.command(name="log")
@click.option("--tail", type=int, default=10, show_default=True)
@click.pass_context
def collab_log(ctx: click.Context, tail: int) -> None:
    """Show recent collaboration consultations."""
    records = _collaboration_log_records(_project_root(ctx), max(tail, 0))
    if not records:
        click.echo(COLLAB_EMPTY_MESSAGE)
        return
    for record in records:
        click.echo(_collaboration_log_row(record))


@cli.group(name="trace")
def trace_group() -> None:
    """Manage and view distributed traces."""
    pass


def _trace_store(ctx: click.Context) -> TraceStore:
    project_root = _project_root(ctx)
    state_dir = project_root / STATE_DIR_PATH
    return TraceStore(state_dir)


def _build_trace_tree(spans: List[Span]) -> tuple[List[Span], Dict[str, List[Span]]]:
    from collections import defaultdict
    children = defaultdict(list)
    roots = []
    span_map = {s.span_id: s for s in spans}
    for s in spans:
        parent = s.parent_span_id
        if not parent or parent not in span_map:
            roots.append(s)
        else:
            children[parent].append(s)
    for pid in children:
        children[pid].sort(key=lambda s: s.started_at)
    roots.sort(key=lambda s: s.started_at)
    return roots, children


def _waterfall_row(span: Span, depth: int, trace_start: datetime, trace_end: datetime, bar_width: int = 22) -> str:
    indent = "  " * depth
    name = f"{indent}{span.operation_name}"
    name_str = f"{name:<25}"[:25]
    total_seconds = (trace_end - trace_start).total_seconds()
    if total_seconds <= 0:
        total_seconds = 0.001
    start_offset = (span.started_at - trace_start).total_seconds()
    duration = (span.ended_at - span.started_at).total_seconds() if span.ended_at else 0.0
    start_char = int((start_offset / total_seconds) * bar_width)
    duration_chars = int((duration / total_seconds) * bar_width)
    if start_char >= bar_width:
        start_char = bar_width - 1
    if start_char + duration_chars > bar_width:
        duration_chars = bar_width - start_char
    solid = "█" * max(duration_chars, 1)
    trailing = "░░" if depth == 0 else "░"
    bar = " " * start_char + solid + trailing
    bar_str = f"{bar:<{bar_width + 2}}"
    dur_ms = span.duration_ms if span.duration_ms is not None else 0
    status_str = f"[{span.status.value.upper()}]"
    return f"{name_str} {bar_str} {dur_ms}ms {status_str}"


@trace_group.command(name="list")
@click.pass_context
def trace_list(ctx: click.Context) -> None:
    """Show the last 20 traces."""
    store = _trace_store(ctx)
    trace_ids = store.load_recent_traces(limit=20)
    if not trace_ids:
        click.echo("No traces found.")
        return
    click.echo(f"{'trace_id':<12} | {'event_type':<20} | {'duration_ms':<11} | {'span_count':<10} | {'status':<8}")
    click.echo("-" * 70)
    for t_id in trace_ids:
        spans = store.load_trace(t_id)
        if not spans:
            continue
        earliest_start = min(s.started_at for s in spans)
        finished_ends = [s.ended_at for s in spans if s.ended_at]
        latest_end = max(finished_ends) if finished_ends else None
        duration = 0
        if latest_end:
            duration = int((latest_end - earliest_start).total_seconds() * 1000)
        event_type = "unknown"
        for s in spans:
            if "event_type" in s.tags:
                event_type = s.tags["event_type"]
                break
        status = "OK"
        if any(s.status == SpanStatus.ERROR for s in spans):
            status = "ERROR"
        elif any(s.status == SpanStatus.TIMEOUT for s in spans):
            status = "TIMEOUT"
        short_id = t_id[:8]
        click.echo(f"{short_id:<12} | {event_type:<20} | {f'{duration}ms':<11} | {len(spans):<10} | {status:<8}")


@trace_group.command(name="show")
@click.argument("trace_id")
@click.pass_context
def trace_show(ctx: click.Context, trace_id: str) -> None:
    """Show a full trace waterfall."""
    store = _trace_store(ctx)
    full_trace_id = trace_id
    if len(trace_id) == 8:
        recent = store.load_recent_traces(limit=100)
        matched = [t for t in recent if t.startswith(trace_id)]
        if matched:
            full_trace_id = matched[0]
    spans = store.load_trace(full_trace_id)
    if not spans:
        click.echo(f"Trace {trace_id} not found.")
        return
    roots, children = _build_trace_tree(spans)
    trace_start = min(s.started_at for s in spans)
    finished_ends = [s.ended_at for s in spans if s.ended_at]
    trace_end = max(finished_ends) if finished_ends else trace_start
    def print_span(span, depth):
        click.echo(_waterfall_row(span, depth, trace_start, trace_end))
        for child in children.get(span.span_id, []):
            print_span(child, depth + 1)
    for root in roots:
        print_span(root, 0)


@trace_group.command(name="slow")
@click.option("--threshold", type=int, default=5000, show_default=True)
@click.pass_context
def trace_slow(ctx: click.Context, threshold: int) -> None:
    """Show traces that took longer than threshold."""
    store = _trace_store(ctx)
    slow_traces = store.get_slow_traces(threshold_ms=threshold)
    if not slow_traces:
        click.echo(f"No traces found slower than {threshold}ms.")
        return
    click.echo(f"{'trace_id':<12} | {'event_type':<20} | {'duration_ms':<11} | {'span_count':<10}")
    click.echo("-" * 60)
    for t in slow_traces:
        short_id = t["trace_id"][:8]
        click.echo(f"{short_id:<12} | {t['event_type']:<20} | {f'{t['total_duration_ms']}ms':<11} | {t['span_count']:<10}")


@cli.group(name="perf")
def perf_group() -> None:
    """Analyze and monitor ProjectOS performance."""
    pass


def _performance_monitor(ctx: click.Context) -> PerformanceMonitor:
    project_root = _project_root(ctx)
    state_dir = project_root / STATE_DIR_PATH
    store = TraceStore(state_dir)
    tracer = Tracer(store)
    return PerformanceMonitor(tracer, state_dir)


@perf_group.command(name="stats")
@click.pass_context
def perf_stats(ctx: click.Context) -> None:
    """Show ComponentStats table for all components."""
    monitor = _performance_monitor(ctx)
    stats = monitor.get_component_stats()
    if not stats:
        click.echo("No performance stats found.")
        return
    click.echo(f"{'component':<25} | {'calls':<5} | {'avg_ms':<8} | {'p50_ms':<8} | {'p95_ms':<8} | {'max_ms':<8}")
    click.echo("-" * 75)
    for comp in sorted(stats.keys()):
        stat = stats[comp]
        click.echo(
            f"{stat.component:<25} | "
            f"{stat.call_count:<5} | "
            f"{stat.avg_duration_ms:<8.1f} | "
            f"{stat.p50_duration_ms:<8.1f} | "
            f"{stat.p95_duration_ms:<8.1f} | "
            f"{stat.max_duration_ms:<8.1f}"
        )


@perf_group.command(name="slow")
@click.option("--threshold", type=int, default=500, show_default=True)
@click.pass_context
def perf_slow(ctx: click.Context, threshold: int) -> None:
    """Show operations slower than threshold."""
    monitor = _performance_monitor(ctx)
    slow_ops = monitor.get_slow_operations(threshold_ms=threshold)
    if not slow_ops:
        click.echo(f"No operations slower than {threshold}ms found.")
        return
    click.echo(f"{'trace_id':<12} | {'component':<20} | {'operation':<25} | {'duration_ms':<11} | {'status':<8}")
    click.echo("-" * 82)
    for span in slow_ops:
        short_id = span.trace_id[:8]
        dur = f"{span.duration_ms}ms" if span.duration_ms is not None else "N/A"
        click.echo(f"{short_id:<12} | {span.component:<20} | {span.operation_name:<25} | {dur:<11} | {span.status.value.upper():<8}")


@perf_group.command(name="suggest")
@click.pass_context
def perf_suggest(ctx: click.Context) -> None:
    """Show optimization suggestions."""
    monitor = _performance_monitor(ctx)
    suggestions = monitor.suggest_optimizations()
    if not suggestions:
        click.echo("No optimization suggestions.")
        return
    for suggestion in suggestions:
        click.echo(f"- {suggestion}")


def _project_root(ctx: click.Context) -> Path:

    """Return the active project root from Click context."""
    value = ctx.obj.get("project_root") if ctx.obj else None
    return Path(value) if value is not None else DEFAULT_PROJECT_ROOT


def _task_queue(ctx: click.Context) -> TaskQueue:
    """Return a task queue from context or create a new one."""
    if ctx.obj is not None and "task_queue" in ctx.obj:
        return ctx.obj["task_queue"]
    return TaskQueue()


def _review_target_agent(ctx: click.Context) -> Any:
    """Return the manual review submission target."""
    if ctx.obj is not None and "review_target_agent" in ctx.obj:
        return ctx.obj["review_target_agent"]
    return ReviewSubmissionTarget()


def _quality_gate(ctx: click.Context) -> QualityGate:
    """Return a quality gate from context or local project state."""
    if ctx.obj is not None and "quality_gate" in ctx.obj:
        return ctx.obj["quality_gate"]
    project_root = _project_root(ctx)
    state_dir = project_root / STATE_DIR_PATH
    evaluation_store = EvaluationStore(state_dir)
    static_analyzer = StaticAnalyzer()
    quality_scorer = QualityScorer(static_analyzer, evaluation_store)
    regression_detector = RegressionDetector(evaluation_store, state_dir)
    return QualityGate(
        DEFAULT_POLICIES,
        quality_scorer,
        regression_detector,
        state_dir / GATE_LOG_NAME,
    )


def _code_index_components(project_root: Path) -> tuple[Any, BaseVectorStore]:
    """Return the embedder and vector store used for code indexing."""
    state_dir = project_root / STATE_DIR_PATH
    embedder = EmbedderFactory.create(state_dir)
    vector_store = VectorStoreFactory.create(
        CODE_INDEX_COLLECTION_NAME,
        state_dir,
        embedder,
    )
    return embedder, vector_store


def _semantic_router(ctx: click.Context) -> SemanticRouter:
    """Return a semantic router from context or local project state."""
    if ctx.obj is not None and "semantic_router" in ctx.obj:
        return ctx.obj["semantic_router"]
    project_root = _project_root(ctx)
    state_dir = project_root / STATE_DIR_PATH
    embedder = EmbedderFactory.create(state_dir)
    vector_store = VectorStoreFactory.create(
        ROUTING_EXAMPLES_COLLECTION,
        state_dir,
        embedder,
    )
    return SemanticRouter(
        embedder,
        vector_store,
        log_path=state_dir / ROUTING_DECISIONS_FILE_NAME,
    )


def _collaboration_broker(ctx: click.Context) -> CollaborationBroker:
    """Return a collaboration broker for local log inspection."""
    if ctx.obj is not None and "collaboration_broker" in ctx.obj:
        return ctx.obj["collaboration_broker"]
    project_root = _project_root(ctx)
    return CollaborationBroker(
        EmptyAgentRegistry(),
        project_root / STATE_DIR_PATH / COLLABORATION_LOG_NAME,
    )


def _collaboration_log_records(
    project_root: Path,
    tail: int,
) -> list[Mapping[str, Any]]:
    """Return recent valid collaboration log records."""
    log_path = project_root / STATE_DIR_PATH / COLLABORATION_LOG_NAME
    if not log_path.exists() or tail <= 0:
        return []
    records: list[Mapping[str, Any]] = []
    for line in log_path.read_text(encoding=ENCODING).splitlines()[-tail:]:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, Mapping):
            records.append(record)
    return records


def _collaboration_log_row(record: Mapping[str, Any]) -> str:
    """Return one formatted collaboration log row."""
    return COLLAB_LOG_TEMPLATE.format(
        consultation_type=record.get("consultation_type", MISSING_VALUE),
        requesting_agent=record.get("requesting_agent", MISSING_VALUE),
        target_agent=record.get("target_agent", MISSING_VALUE),
        duration_ms=record.get("duration_ms", 0),
        question=record.get("question", MISSING_VALUE),
        answer=record.get("answer", MISSING_VALUE),
    )


def _vector_records(vector_store: BaseVectorStore) -> list[VectorRecord]:
    """Return vector records when supported by the backing store."""
    records = getattr(vector_store, "records", None)
    if isinstance(records, list):
        return list(records)
    collection = getattr(vector_store, "collection", None)
    if collection is None:
        return []
    try:
        response = collection.get(include=["documents", "metadatas", "embeddings"])
    except Exception:
        return []
    return [
        VectorRecord(
            id=str(record_id),
            text=str(document or ""),
            embedding=list(embedding or []),
            metadata=dict(metadata or {}),
        )
        for record_id, document, metadata, embedding in zip(
            response.get("ids", []),
            response.get("documents", []),
            response.get("metadatas", []),
            response.get("embeddings", []),
        )
    ]


def _last_index_update(records: list[VectorRecord]) -> str:
    """Return the latest vector record creation time for display."""
    if not records:
        return INDEX_UNKNOWN_VALUE
    return max(record.created_at for record in records).isoformat()


def _index_search_row(result: SearchResult) -> str:
    """Return one CLI search result row."""
    metadata = result.record.metadata
    preview = NEWLINE.join(result.record.text.splitlines()[:INDEX_PREVIEW_LINES])
    return INDEX_SEARCH_TEMPLATE.format(
        file_path=metadata.get(PAYLOAD_KEY_FILE_PATH, INDEX_UNKNOWN_VALUE),
        name=metadata.get("name", INDEX_UNKNOWN_VALUE),
        score=result.similarity_score,
        preview=preview,
    )


def _run_all_projects() -> None:
    """Run all enabled registered projects until interrupted."""
    multi_project_os = MultiProjectOS(ProjectRegistry())
    multi_project_os.start()
    click.echo(RUNNING_ALL_MESSAGE)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        multi_project_os.stop()
        click.echo(SHUTDOWN_MESSAGE)


def _dashboard(project_os: ProjectOS) -> Dashboard:
    """Return a dashboard connected to the running ProjectOS instance."""
    return Dashboard(
        task_queue=project_os.task_queue,
        decision_logger=DecisionLogger(project_os.project_root),
        persistence_manager=project_os.persistence_manager,
        health_monitor=project_os.provider_health_monitor,
        alert_manager=project_os.alert_manager,
    )


def _project_row(project_config: ProjectConfig) -> str:
    """Return one formatted projects list row."""
    status = PROJECT_STATUS_ENABLED if project_config.enabled else MISSING_VALUE
    return " | ".join(
        [
            project_config.name,
            str(project_config.root_path),
            status,
        ]
    )


def _load_config(project_root: Path) -> Mapping[str, Any]:
    """Load config/models.yaml from the project root."""
    config_path = project_root / CONFIG_PATH
    with config_path.open("r", encoding=ENCODING) as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, Mapping):
        raise click.ClickException("Model config must be a mapping.")
    return dict(config)


def _write_config(project_root: Path, config: Mapping[str, Any]) -> None:
    """Write config/models.yaml atomically."""
    rendered_config = yaml.safe_dump(config, sort_keys=False)
    _write_atomically(project_root / CONFIG_PATH, rendered_config)


def _agent_configs(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return mutable agent config mappings."""
    agents = config.get(CONFIG_KEY_AGENTS)
    if not isinstance(agents, Mapping):
        raise click.ClickException("Model config must define agents.")
    return {
        str(agent_name): agent_config
        for agent_name, agent_config in agents.items()
        if isinstance(agent_config, dict)
    }


def _provider_health(
    config: Mapping[str, Any],
    persisted_status: Mapping[str, Any],
) -> dict[str, bool]:
    """Return last known provider health by provider name."""
    providers = config.get(CONFIG_KEY_PROVIDERS)
    if not isinstance(providers, Mapping):
        return {}
    persisted_health = persisted_status.get(STATUS_KEY_PROVIDER_HEALTH, {})
    if not isinstance(persisted_health, Mapping):
        persisted_health = {}
    return {
        str(provider_name): bool(persisted_health.get(str(provider_name), False))
        for provider_name in providers
    }


def _pending_tasks_count(project_root: Path) -> int:
    """Return the number of PENDING task status lines."""
    tasks_path = project_root / TASKS_README_PATH
    if not tasks_path.exists():
        return 0
    return sum(
        1
        for line in tasks_path.read_text(encoding=ENCODING).splitlines()
        if line.startswith("- TASK_") and PENDING_STATUS in line
    )


def _last_activity(project_root: Path) -> str:
    """Return the latest decision-log timestamp when available."""
    decisions_path = project_root / DECISIONS_LOG_PATH
    if not decisions_path.exists():
        return MISSING_VALUE
    lines = [
        line.strip()
        for line in decisions_path.read_text(encoding=ENCODING).splitlines()
        if line.strip()
    ]
    if not lines:
        return MISSING_VALUE
    last_line = lines[-1]
    if last_line.startswith("[") and "]" in last_line:
        return last_line[1 : last_line.index("]")]
    return MISSING_VALUE


def _last_status(project_root: Path) -> Mapping[str, Any]:
    """Return the last persisted runtime status when available."""
    status_path = project_root / STATE_DIR_PATH / LAST_STATUS_FILE
    if not status_path.exists():
        return {}
    try:
        status = json.loads(status_path.read_text(encoding=ENCODING))
    except json.JSONDecodeError:
        return {}
    return status if isinstance(status, Mapping) else {}


def _git_log(project_root: Path) -> Optional[subprocess.CompletedProcess[str]]:
    """Return recent ProjectOS authord git log entries without raising."""
    try:
        return subprocess.run(
            [
                GIT_COMMAND,
                "log",
                f"--author={GIT_AUTHOR_FILTER}",
                "--oneline",
                GIT_LOG_LIMIT,
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def _decision_table_row(record: Mapping[str, Any]) -> str:
    """Return one formatted decision table row."""
    return " | ".join(
        [
            str(record.get("timestamp", MISSING_VALUE)),
            str(record.get("event_id", MISSING_VALUE)),
            str(record.get("agent_name", MISSING_VALUE)),
            str(record.get("decision_category", MISSING_VALUE)),
            str(record.get("outcome", MISSING_VALUE)),
            str(record.get("escalated", False)),
            str(record.get("reasoning", MISSING_VALUE)).replace(NEWLINE, " "),
        ]
    )


def _quality_baseline(
    baselines: Mapping[str, Mapping[str, Any]],
    agent_name: str,
    model_version: str,
) -> Optional[float]:
    """Return a baseline score for one agent and model version."""
    baseline_key = QUALITY_BASELINE_KEY_TEMPLATE.format(
        agent_name=agent_name,
        model_version=model_version,
    )
    record = baselines.get(baseline_key)
    if not isinstance(record, Mapping):
        return None
    value = record.get(QUALITY_FIELD_BASELINE_SCORE)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quality_status_row(
    agent_name: str,
    score: Optional[float],
    baseline: Optional[float],
) -> str:
    """Return one quality status table row."""
    score_text = _quality_score_text(score)
    baseline_text = _quality_score_text(baseline)
    delta_text = _quality_delta_text(score, baseline)
    status_text = _quality_status_text(score, baseline)
    return (
        f"{agent_name:<{QUALITY_AGENT_WIDTH}}"
        f"{score_text:<{QUALITY_SCORE_WIDTH}}"
        f"{baseline_text:<{QUALITY_BASELINE_WIDTH}}"
        f"{delta_text:<{QUALITY_DELTA_WIDTH}}"
        f"{status_text}"
    )


def _quality_baseline_row(record: Mapping[str, Any]) -> str:
    """Return one quality baseline table row."""
    agent_name = str(record.get(QUALITY_FIELD_AGENT_NAME, MISSING_VALUE))
    model_version = str(record.get(QUALITY_FIELD_MODEL_VERSION, MISSING_VALUE))
    baseline_score = _quality_score_text(
        _float_or_none(record.get(QUALITY_FIELD_BASELINE_SCORE))
    )
    sample_size = str(record.get(QUALITY_FIELD_SAMPLE_SIZE, 0))
    return (
        f"{agent_name:<{QUALITY_AGENT_WIDTH}}"
        f"{model_version:<{QUALITY_MODEL_WIDTH}}"
        f"{baseline_score:<{QUALITY_BASELINE_WIDTH}}"
        f"{sample_size}"
    )


def _quality_score_text(score: Optional[float]) -> str:
    """Return display text for an optional quality score."""
    if score is None:
        return QUALITY_MISSING_SCORE
    return QUALITY_SCORE_TEMPLATE.format(score=score)


def _quality_delta_text(
    score: Optional[float],
    baseline: Optional[float],
) -> str:
    """Return display text for a quality score delta."""
    if score is None or baseline is None:
        return QUALITY_MISSING_SCORE
    return QUALITY_DELTA_TEMPLATE.format(delta=score - baseline)


def _quality_status_text(
    score: Optional[float],
    baseline: Optional[float],
) -> str:
    """Return quality status text for score and baseline."""
    if score is None or baseline is None:
        return QUALITY_STATUS_NO_DATA
    if score < baseline * QUALITY_STABLE_RATIO:
        return QUALITY_STATUS_REGRESSION
    return QUALITY_STATUS_STABLE


def _gate_agent_names(quality_gate: QualityGate) -> list[str]:
    """Return agent names with policies or gate records."""
    names = {
        agent_name
        for agent_name in quality_gate.policies
        if agent_name != "default"
    }
    names.update(result.agent_name for result in quality_gate.recent_results(limit=100))
    return sorted(names)


def _gate_status_row(quality_gate: QualityGate, agent_name: str) -> str:
    """Return one quality gate status table row."""
    block_rate = quality_gate.get_block_rate(agent_name) * 100.0
    recent_results = quality_gate.recent_results(agent_name, 10)
    status_text = " ".join(_gate_status_symbol(result.decision) for result in recent_results)
    return (
        f"{agent_name:<{GATE_AGENT_WIDTH}}"
        f"{GATE_RATE_TEMPLATE.format(rate=block_rate):<{GATE_RATE_WIDTH}}"
        f"{status_text}"
    )


def _gate_status_symbol(decision: GateDecision) -> str:
    """Return a compact symbol for one gate decision."""
    if decision is GateDecision.PASS:
        return GATE_STATUS_PASS
    if decision is GateDecision.BLOCK:
        return GATE_STATUS_BLOCK
    if decision is GateDecision.ESCALATE:
        return GATE_STATUS_ESCALATE
    return GATE_STATUS_BYPASS


def _gate_policy_row(policy: Any) -> str:
    """Return one quality gate policy table row."""
    return (
        f"{policy.agent_name:<{GATE_AGENT_WIDTH}}"
        f"{GATE_SCORE_TEMPLATE.format(score=policy.min_combined_score):<{GATE_SCORE_WIDTH}}"
        f"{_flag_text(policy.require_llm_evaluation):<{GATE_FLAG_WIDTH}}"
        f"{_flag_text(policy.require_static_analysis):<{GATE_FLAG_WIDTH + 3}}"
        f"{_flag_text(policy.block_on_security_high):<{GATE_SECURITY_WIDTH}}"
        f"{_flag_text(policy.block_on_regression):<{GATE_REGRESSION_WIDTH}}"
    )


def _flag_text(value: bool) -> str:
    """Return display text for a boolean flag."""
    return GATE_TRUE if value else GATE_FALSE


def _echo_markdown(markdown_text: str) -> None:
    """Print markdown with Rich formatting when available."""
    try:
        from rich.console import Console
        from rich.markdown import Markdown
    except ImportError:
        click.echo(markdown_text)
        return
    Console().print(Markdown(markdown_text))


def _float_or_none(value: Any) -> Optional[float]:
    """Return a float value or None on conversion failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _updated_escalation_lines(lines: Iterable[str]) -> list[str]:
    """Return escalation queue lines with pending rows approved or rejected."""
    updated_lines = []
    changed = False
    for line in lines:
        cells = _markdown_cells(line)
        if cells and cells[-1] == PENDING_STATUS:
            event_id = cells[1] if len(cells) > 1 else MISSING_VALUE
            click.echo(line)
            approved = click.confirm(
                CONFIRM_APPROVE_TEMPLATE.format(event_id=event_id),
                default=True,
            )
            cells[-1] = APPROVED_STATUS if approved else REJECTED_STATUS
            updated_lines.append(_markdown_row(cells))
            changed = True
        else:
            updated_lines.append(line)
    return updated_lines if changed else list(lines)


def _markdown_cells(line: str) -> list[str]:
    """Return markdown table cells from a row line."""
    stripped_line = line.strip()
    if not stripped_line.startswith("|") or not stripped_line.endswith("|"):
        return []
    return [cell.strip() for cell in stripped_line.strip("|").split("|")]


def _markdown_row(cells: Iterable[str]) -> str:
    """Return one markdown table row from cell values."""
    return f"| {' | '.join(cells)} |"


def _priority_color(line: str) -> Optional[str]:
    """Return a Click color for a backlog line."""
    if PRIORITY_HIGH in line:
        return COLOR_RED
    if PRIORITY_MEDIUM in line:
        return COLOR_YELLOW
    if PRIORITY_LOW in line:
        return COLOR_GREEN
    return None


@cli.group(name="tokens")
def tokens_group() -> None:
    """Manage and inspect ProjectOS token budgets and usage."""
    pass


@tokens_group.command(name="usage")
@click.pass_context
def tokens_usage(ctx: click.Context) -> None:
    """Show token usage summary for the last 7 days per agent."""
    project_root = _project_root(ctx)
    tb = TokenBudget(project_root / STATE_DIR_PATH)

    config = _load_config(project_root)
    custom_budgets = {}
    agents_cfg = config.get("agents", {})
    for a_name, a_cfg in agents_cfg.items():
        if isinstance(a_cfg, dict) and "token_budget" in a_cfg:
            custom_budgets[a_name] = a_cfg["token_budget"]
    if custom_budgets:
        tb.budgets.update(custom_budgets)

    summary = tb.get_usage_summary(days=7)

    click.echo("Agent          Today    7-day avg  Daily limit  Status")

    agents_to_show = ["code_review", "code_writing", "planning", "architecture", "test", "docs", "clone"]
    for agent_name in agents_to_show:
        today_usage = tb.get_daily_usage(agent_name)

        agent_summary = summary.get(agent_name, {})
        total_tokens = agent_summary.get("total_tokens", 0)
        avg_7_days = int(total_tokens / 7)

        agent_budget = tb.budgets.get(agent_name, tb.budgets["default"])
        daily_limit = agent_budget.get("daily_limit", 50000)

        status_str = "✓ OK" if today_usage <= daily_limit else "✗ Exceeded"

        today_str = f"{today_usage:,}"
        avg_str = f"{avg_7_days:,}"
        limit_str = f"{daily_limit:,}"

        click.echo(
            f"{agent_name:<15}"
            f"{today_str:<9}"
            f"{avg_str:<11}"
            f"{limit_str:<13}"
            f"{status_str}"
        )


@tokens_group.command(name="budget")
@click.option("--agent", "agent_name", required=True)
@click.option("--hard-limit", type=int, required=True)
@click.pass_context
def tokens_budget(ctx: click.Context, agent_name: str, hard_limit: int) -> None:
    """Update hard limit token budget for an agent in config/models.yaml."""
    project_root = _project_root(ctx)
    config = _load_config(project_root)
    agents = config.get("agents", {})
    if agent_name not in agents:
        raise click.ClickException(f"Unknown agent: {agent_name}")

    agent_cfg = agents[agent_name]
    if not isinstance(agent_cfg, dict):
        agent_cfg = {}
        agents[agent_name] = agent_cfg

    if "token_budget" not in agent_cfg:
        agent_cfg["token_budget"] = {}
    agent_cfg["token_budget"]["hard_limit_per_call"] = hard_limit

    _write_config(project_root, config)
    click.echo(f"Updated budget for {agent_name}: hard_limit_per_call = {hard_limit}")


@tokens_group.command(name="reset")
@click.option("--agent", "agent_name", required=True)
@click.pass_context
def tokens_reset(ctx: click.Context, agent_name: str) -> None:
    """Reset the today token usage counter for an agent."""
    project_root = _project_root(ctx)
    tb = TokenBudget(project_root / STATE_DIR_PATH)

    config = _load_config(project_root)
    agents = config.get("agents", {})
    if agent_name not in agents and agent_name != "default":
        raise click.ClickException(f"Unknown agent: {agent_name}")

    tb.reset_agent_usage(agent_name)
    click.echo(f"Reset daily token counter for {agent_name}")


@cli.group(name="cost")
def cost_group() -> None:
    """Track and optimize ProjectOS costs and provider economics."""
    pass


@cost_group.command(name="today")
@click.pass_context
def cost_today(ctx: click.Context) -> None:
    """Show today's cost breakdown."""
    project_root = _project_root(ctx)
    ct = CostTracker(project_root / STATE_DIR_PATH)

    config = _load_config(project_root)
    pricing_cfg = config.get("pricing", {})
    usd_to_inr = float(pricing_cfg.get("usd_to_inr", 83.5))
    ct.usd_to_inr = usd_to_inr

    custom_catalog = pricing_cfg.get("catalog", None)
    if custom_catalog:
        ct = CostTracker(
            project_root / STATE_DIR_PATH,
            usd_to_inr=usd_to_inr,
            pricing_catalog=custom_catalog,
        )

    daily_cost = ct.get_daily_cost()
    today_str = datetime.now(timezone.utc).date().isoformat()
    agent_stats: dict[str, dict[str, Any]] = {}
    agents_to_show = ["code_review", "code_writing", "planning", "architecture", "test", "docs", "clone"]
    for agent_name in agents_to_show:
        agent_stats[agent_name] = {"calls": 0, "tokens": 0, "cost_inr": 0.0, "free_tier": True}

    if ct.log_path.exists():
        with ct._lock:
            try:
                with open(ct.log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            t_date = data.get("timestamp", "")[:10]
                            if t_date == today_str:
                                agent = data.get("agent_name", "unknown")
                                if agent in agent_stats:
                                    agent_stats[agent]["calls"] += 1
                                    agent_stats[agent]["tokens"] += int(data.get("input_tokens", 0)) + int(data.get("output_tokens", 0))
                                    agent_stats[agent]["cost_inr"] += float(data.get("cost_inr", 0.0))
                                    if not bool(data.get("is_free_tier", True)):
                                        agent_stats[agent]["free_tier"] = False
                        except Exception:
                            continue
            except Exception:
                pass

    click.echo("Today's Usage")
    click.echo("Agent          Calls  Tokens   Cost (₹)  Free Tier")
    for agent_name in agents_to_show:
        stats = agent_stats[agent_name]
        if stats["calls"] > 0:
            free_str = "✓ Yes" if stats["free_tier"] else "✗ No"
            tokens_str = f"{stats['tokens']:,}"
            cost_str = f"₹{stats['cost_inr']:.2f}"
            click.echo(
                f"{agent_name:<15}"
                f"{stats['calls']:<7}"
                f"{tokens_str:<9}"
                f"{cost_str:<10}"
                f"{free_str}"
            )

    total_inr = daily_cost["total_inr"]
    proj = ct.get_monthly_projection(days_of_data=7)
    proj_inr = proj["projected_inr"]
    click.echo(f"Total: ₹{total_inr:.2f} | Projected monthly: ₹{proj_inr:.2f}")


@cost_group.command(name="week")
@click.pass_context
def cost_week(ctx: click.Context) -> None:
    """Show last 7 days breakdown with daily ASCII chart."""
    project_root = _project_root(ctx)
    ct = CostTracker(project_root / STATE_DIR_PATH)

    config = _load_config(project_root)
    pricing_cfg = config.get("pricing", {})
    usd_to_inr = float(pricing_cfg.get("usd_to_inr", 83.5))
    ct.usd_to_inr = usd_to_inr

    custom_catalog = pricing_cfg.get("catalog", None)
    if custom_catalog:
        ct = CostTracker(
            project_root / STATE_DIR_PATH,
            usd_to_inr=usd_to_inr,
            pricing_catalog=custom_catalog,
        )

    today = datetime.now(timezone.utc).date()
    import datetime as dt
    days = [today - dt.timedelta(days=i) for i in range(6, -1, -1)]

    costs: list[tuple[date, float]] = []
    for d in days:
        daily_stats = ct.get_daily_cost(d)
        costs.append((d, daily_stats["total_inr"]))

    max_cost = max([c[1] for c in costs])

    click.echo("Last 7 Days Usage:")
    click.echo("Date            Cost (₹)    Chart")
    for d, cost in costs:
        bar = ""
        if max_cost > 0.0:
            bar_len = int((cost / max_cost) * 20)
            bar = "#" * bar_len
        cost_str = f"₹{cost:.2f}"
        click.echo(f"{d.isoformat()}      {cost_str:<11} {bar}")


@cost_group.command(name="optimize")
@click.pass_context
def cost_optimize(ctx: click.Context) -> None:
    """Show model swap recommendations based on usage patterns."""
    project_root = _project_root(ctx)
    ct = CostTracker(project_root / STATE_DIR_PATH)

    config = _load_config(project_root)
    pricing_cfg = config.get("pricing", {})
    usd_to_inr = float(pricing_cfg.get("usd_to_inr", 83.5))
    ct.usd_to_inr = usd_to_inr

    custom_catalog = pricing_cfg.get("catalog", None)
    if custom_catalog:
        ct = CostTracker(
            project_root / STATE_DIR_PATH,
            usd_to_inr=usd_to_inr,
            pricing_catalog=custom_catalog,
        )

    agents_to_show = ["code_review", "code_writing", "planning", "architecture", "test", "docs", "clone"]
    recommendations: list[str] = []
    for agent_name in agents_to_show:
        rec = ct.recommend_model_swap(agent_name)
        if rec:
            recommendations.append(rec)

    click.echo("Cost Optimization Recommendations")
    if recommendations:
        for rec in recommendations:
            click.echo(f"- {rec}")
    else:
        click.echo("All agents are running cost-optimally. No recommendations.")


@cli.group(name="reliability")
def reliability_group() -> None:
    """Manage and inspect ProjectOS rate limiters and circuit breakers."""
    pass


@reliability_group.command(name="status")
@click.pass_context
def reliability_status(ctx: click.Context) -> None:
    """Show rate limiter and circuit breaker state per provider."""
    project_root = _project_root(ctx)
    click.echo("Provider      Circuit    Failures  Last Failure     Rate (req/s)")

    providers = ["gemini", "openrouter", "ollama"]
    from core.observability.rate_limiter import ProviderRateLimits

    for provider_name in providers:
        state_file = project_root / STATE_DIR_PATH / f"circuit_state_{provider_name}.json"
        circuit_state_str = "● CLOSED"
        failures = 0
        last_failure_str = "never"

        if state_file.exists():
            try:
                state_data = json.loads(state_file.read_text(encoding="utf-8"))
                state = state_data.get("state", "closed").upper()
                if state == "OPEN":
                    circuit_state_str = "○ OPEN"
                elif state == "HALF_OPEN":
                    circuit_state_str = "◑ HALF_OPEN"
                else:
                    circuit_state_str = "● CLOSED"

                failures = int(state_data.get("failure_count", 0))
                lf = state_data.get("last_failure_at")
                if lf:
                    lf_dt = datetime.fromisoformat(lf)
                    diff = datetime.now(timezone.utc) - lf_dt
                    secs = int(diff.total_seconds())
                    if secs < 60:
                        last_failure_str = f"{secs}s ago"
                    elif secs < 3600:
                        last_failure_str = f"{secs // 60}m ago"
                    else:
                        last_failure_str = f"{secs // 3600}h ago"
            except Exception:
                pass

        limiter = ProviderRateLimits.get(provider_name)
        rate = limiter.tokens_per_second if limiter else 2.0

        click.echo(
            f"{provider_name:<14}"
            f"{circuit_state_str:<11}"
            f"{failures:<10}"
            f"{last_failure_str:<17}"
            f"{rate:.1f}"
        )


@reliability_group.command(name="reset")
@click.option("--provider", "provider_name", required=True)
@click.pass_context
def reliability_reset(ctx: click.Context, provider_name: str) -> None:
    """Force circuit breaker reset for a provider."""
    project_root = _project_root(ctx)
    from core.observability.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(provider_name, state_dir=project_root / STATE_DIR_PATH)
    cb.reset()
    click.echo(f"Circuit breaker for {provider_name} has been reset to CLOSED.")


@cli.group(name="alerts")
def alerts_group() -> None:
    """Manage and view observability alerts and anomalies."""


@alerts_group.command(name="list")
@click.option("--all", "show_all", is_flag=True, help="Show last 50 alerts including acknowledged.")
@click.pass_context
def alerts_list(ctx: click.Context, show_all: bool) -> None:
    """Show active alerts or last 50 alerts."""
    project_root = _project_root(ctx)
    alert_manager = AlertManager(project_root / STATE_DIR_PATH)

    if show_all:
        alerts = sorted(alert_manager._alerts, key=lambda a: a.timestamp, reverse=True)[:50]
    else:
        alerts = alert_manager.get_active_alerts()

    if not alerts:
        click.echo("No alerts found.")
        return

    click.echo("ID | Severity | Type | Title | Status")
    for alert in alerts:
        status = "ACKNOWLEDGED" if alert.acknowledged else "ACTIVE"
        click.echo(
            f"{alert.alert_id} | {alert.severity.value.upper()} | "
            f"{alert.alert_type.value} | {alert.title} | {status}"
        )


@alerts_group.command(name="acknowledge")
@click.argument("alert_id")
@click.pass_context
def alerts_acknowledge(ctx: click.Context, alert_id: str) -> None:
    """Acknowledge one alert by ID."""
    project_root = _project_root(ctx)
    alert_manager = AlertManager(project_root / STATE_DIR_PATH)
    success = alert_manager.acknowledge(alert_id)
    if success:
        click.echo(f"Alert {alert_id} acknowledged.")
    else:
        raise click.ClickException(f"Alert {alert_id} not found or already acknowledged.")


@alerts_group.command(name="acknowledge-all")
@click.pass_context
def alerts_acknowledge_all(ctx: click.Context) -> None:
    """Acknowledge all active alerts."""
    project_root = _project_root(ctx)
    alert_manager = AlertManager(project_root / STATE_DIR_PATH)
    count = alert_manager.acknowledge_all()
    click.echo(f"Acknowledged {count} active alerts.")


@alerts_group.command(name="anomalies")
@click.pass_context
def alerts_anomalies(ctx: click.Context) -> None:
    """Run anomaly detection right now and show results."""
    project_root = _project_root(ctx)
    from core.observability.anomaly_detector import AnomalyDetector
    detector = AnomalyDetector(project_root / STATE_DIR_PATH)

    click.echo("Running anomaly detection...")
    agents = ["clone", "planning", "code_writing", "code_review", "architecture", "test", "docs"]
    found_any = False

    for agent in agents:
        for check_name, check_fn in [
            ("Latency", detector.check_latency_anomaly),
            ("Token Usage", detector.check_token_anomaly),
            ("Gate Block Rate", detector.check_gate_block_anomaly),
        ]:
            try:
                res = check_fn(agent)
                if res.is_anomaly:
                    found_any = True
                    click.secho(
                        f"⚠️  ANOMALY DETECTED: {agent} {check_name} | "
                        f"value: {res.current_value:.1f} (mean: {res.mean:.1f}, "
                        f"z-score: {res.z_score:.2f})",
                        fg="yellow",
                    )
            except Exception as e:
                click.echo(f"Error checking {agent} {check_name}: {e}")

    if not found_any:
        click.secho("✓ No anomalies detected.", fg="green")


@cli.group(name="config")
def config_group() -> None:
    """Manage ProjectOS configuration."""
    pass


@config_group.command(name="show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Pretty-print the current configuration from projectos.yaml."""
    project_root = _project_root(ctx)
    config_path = project_root / "config" / "projectos.yaml"
    if not config_path.exists():
        click.secho(f"Configuration file not found at {config_path}", fg="red")
        return
    try:
        with config_path.open("r", encoding="utf-8") as f:
            content = f.read()
        click.echo(content)
    except Exception as e:
        raise click.ClickException(f"Error reading configuration: {e}")


@config_group.command(name="validate")
@click.pass_context
def config_validate(ctx: click.Context) -> None:
    """Validate the current projectos.yaml configuration."""
    project_root = _project_root(ctx)
    config_path = project_root / "config" / "projectos.yaml"
    if not config_path.exists():
        click.secho(f"Configuration file not found at {config_path}", fg="red")
        raise click.ClickException("Missing config file")
    try:
        from core.config_loader import ProjectConfig as MasterProjectConfig
        config = MasterProjectConfig.load(config_path)
        errors = config.validate()
        if errors:
            click.secho("Configuration has validation errors:", fg="red")
            for err in errors:
                click.echo(f"- {err}")
            ctx.exit(1)
        else:
            click.secho("Config valid", fg="green")
    except Exception as e:
        click.secho(f"Validation failed: {e}", fg="red")
        ctx.exit(1)


@config_group.command(name="init")
@click.pass_context
def config_init(ctx: click.Context) -> None:
    """Initialize projectos.yaml and prompt for API keys."""
    project_root = _project_root(ctx)
    config_dir = project_root / "config"
    config_path = config_dir / "projectos.yaml"
    env_path = project_root / ".env"
    
    from core.config_loader import ProjectConfig as MasterProjectConfig
    
    if not config_path.exists():
        click.echo(f"Creating default configuration at {config_path}...")
        MasterProjectConfig.create_default(config_path)
    else:
        click.echo(f"Configuration file already exists at {config_path}.")
        
    gemini_key = click.prompt("Enter GEMINI_API_KEY (press Enter to skip)", default="", show_default=False)
    openrouter_key = click.prompt("Enter OPENROUTER_API_KEY (press Enter to skip)", default="", show_default=False)
    
    env_content = ""
    if env_path.exists():
        try:
            env_content = env_path.read_text(encoding="utf-8")
        except Exception:
            pass
            
    lines = env_content.splitlines()
    new_lines = []
    has_gemini = False
    has_or = False
    for line in lines:
        if line.startswith("GEMINI_API_KEY="):
            if gemini_key:
                new_lines.append(f"GEMINI_API_KEY={gemini_key}")
            else:
                new_lines.append(line)
            has_gemini = True
        elif line.startswith("OPENROUTER_API_KEY="):
            if openrouter_key:
                new_lines.append(f"OPENROUTER_API_KEY={openrouter_key}")
            else:
                new_lines.append(line)
            has_or = True
        else:
            new_lines.append(line)
            
    if not has_gemini and gemini_key:
        new_lines.append(f"GEMINI_API_KEY={gemini_key}")
    if not has_or and openrouter_key:
        new_lines.append(f"OPENROUTER_API_KEY={openrouter_key}")
        
    try:
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        click.echo(f"Updated environment variables in {env_path}")
    except Exception as e:
        click.secho(f"Failed to write .env file: {e}", fg="red")


@cli.group(name="template")
def template_group() -> None:
    """Manage project templates."""
    pass


@template_group.command(name="list")
def template_list() -> None:
    """List available templates."""
    from core.template_manager import TemplateManager
    templates = TemplateManager.list_templates()
    if not templates:
        click.echo("No templates available.")
        return
    click.echo("Available templates:")
    for t in templates:
        click.echo(f"- {t['name']}: {t['description']}")


@template_group.command(name="apply")
@click.argument("name")
@click.pass_context
def template_apply(ctx: click.Context, name: str) -> None:
    """Apply template to current project."""
    project_root = _project_root(ctx)
    config_path = project_root / "config" / "projectos.yaml"

    from core.config_loader import ProjectConfig as MasterProjectConfig
    from core.template_manager import TemplateManager

    if not config_path.exists():
        click.secho(f"Configuration file not found at {config_path}", fg="red")
        ctx.exit(1)

    try:
        config = MasterProjectConfig.load(config_path)
        TemplateManager.apply_template(name, config)

        # Save config.raw_config back to disk atomically
        import yaml
        rendered = yaml.safe_dump(config.raw_config, sort_keys=False)
        _write_atomically(config_path, rendered)

        # Copy template files
        TemplateManager.copy_template_files(name, project_root)

        click.echo(f"Template applied: {name}")
    except Exception as e:
        click.secho(f"Failed to apply template: {e}", fg="red")
        ctx.exit(1)


@template_group.command(name="detect")
@click.pass_context
def template_detect(ctx: click.Context) -> None:
    """Detect project type from workspace structure."""
    project_root = _project_root(ctx)
    from core.template_manager import TemplateManager
    detected = TemplateManager.detect_project_type(project_root)
    if detected:
        click.echo(f"Detected project type: {detected}")
    else:
        click.echo("Unknown project type")


if __name__ == "__main__":
    cli()


