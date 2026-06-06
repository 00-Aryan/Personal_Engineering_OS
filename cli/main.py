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


if __name__ == "__main__":
    cli()
