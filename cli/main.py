"""Click command line interface for ProjectOS."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

import click
import yaml

from core.events import AgentEvent, AgentResult, EventType
from core.projectos import ProjectOS
from core.task_queue import TaskQueue


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

CONFIG_KEY_AGENTS = "agents"
CONFIG_KEY_MODEL = "model"
SOURCE_AGENT_REVIEW_COMMAND = "cli_review"
PAYLOAD_KEY_FILE_PATH = "file_path"
PAYLOAD_KEY_MANUAL = "manual"

STATUS_LABEL_AGENTS = "Agents"
STATUS_LABEL_PENDING = "Pending tasks count"
STATUS_LABEL_LAST_ACTIVITY = "Last activity"
MISSING_VALUE = "none"
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
SHUTDOWN_MESSAGE = "ProjectOS daemon stopped."

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
@click.pass_context
def run(ctx: click.Context) -> None:
    """Run the trigger system, Clone Agent, and task queue until interrupted."""
    project_root = _project_root(ctx)
    project_os = ProjectOS(project_root / CONFIG_PATH)
    project_os.start()
    click.echo(RUNNING_MESSAGE)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        project_os.stop()
        click.echo(SHUTDOWN_MESSAGE)


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
