"""Smoke checks for Clone Agent persistence behavior."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path
from typing import Iterator

from core.clone_agent import CloneAgent
from core.events import AgentEvent, EventType


TEST_SOURCE_AGENT = "test"
BLOCKER_SANDBOX_RESTRICTION = "sandbox_restriction"
BLOCKED_TASK_NAME = "write_skill_file"
DEPENDENCY_REQUESTS = "requests"
BREAKING_CHANGE_FILE_PATH = "core/base_agent.py"

BLOCKED_TASKS_FILE_NAME = "blocked_tasks.md"
DECISIONS_LOG_FILE_NAME = "decisions.log"
ESCALATION_QUEUE_FILE_NAME = "escalation_queue.md"

BLOCKED_BY_PAYLOAD_KEY = "blocked_by"
TASK_PAYLOAD_KEY = "task"
NEW_DEPENDENCY_PAYLOAD_KEY = "new_dependency"
BREAKING_CHANGE_PAYLOAD_KEY = "breaking_change"
FILE_PATH_PAYLOAD_KEY = "file_path"

DEFER_PARALLEL_ENTRY = "DEFER_PARALLEL"
MARKDOWN_TABLE_ROW_PREFIX = "| "
SMOKE_TEST_FAILED_MESSAGE = "SMOKE TEST FAILED: Clone write logic broken"
SMOKE_TEST_PASSED_MESSAGE = "SMOKE TEST PASSED"
CI_SMOKE_TEST_PASSED_MESSAGE = "CI SMOKE: PASSED"
ENCODING = "utf-8"
LOGGER_NAME = "projectos.smoke_test"
CI_FLAG = "--ci"


class SmokeModelProvider:
    """No-op model provider used because Clone write checks make no model calls."""

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return an empty deterministic completion."""
        return ""

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield no streamed chunks."""
        return iter(())

    def get_model_name(self) -> str:
        """Return a deterministic model name for diagnostics."""
        return "smoke-model"


def main() -> int:
    """Run Clone Agent smoke checks and return a process exit code."""
    args = _parse_args()
    try:
        run_smoke_test()
    except AssertionError as error:
        print(f"{SMOKE_TEST_FAILED_MESSAGE}: {error}", file=sys.stderr)
        return 1
    if args.ci:
        print(CI_SMOKE_TEST_PASSED_MESSAGE)
    else:
        print(SMOKE_TEST_PASSED_MESSAGE)
    return 0


def _parse_args() -> argparse.Namespace:
    """Parse smoke-test command line arguments."""
    parser = argparse.ArgumentParser(description="Run ProjectOS smoke checks.")
    parser.add_argument(
        CI_FLAG,
        action="store_true",
        help="Print a CI-specific success marker.",
    )
    return parser.parse_args()


def run_smoke_test() -> None:
    """Verify Clone writes blocked and escalation artifacts."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.disabled = True
    with tempfile.TemporaryDirectory() as project_root_name:
        project_root = Path(project_root_name)
        clone_agent = CloneAgent(
            model_provider=SmokeModelProvider(),
            logger=logger,
            project_root=project_root,
        )

        force_blocked_task(clone_agent, project_root)
        force_escalation(clone_agent, project_root)


def force_blocked_task(clone_agent: CloneAgent, project_root: Path) -> None:
    """Force a blocked event and verify blocked-task persistence."""
    blocked_event = AgentEvent(
        event_type=EventType.PERMISSION_BLOCKED,
        source_agent=TEST_SOURCE_AGENT,
        payload={
            BLOCKED_BY_PAYLOAD_KEY: BLOCKER_SANDBOX_RESTRICTION,
            TASK_PAYLOAD_KEY: BLOCKED_TASK_NAME,
        },
        blocked_by=BLOCKER_SANDBOX_RESTRICTION,
    )

    clone_agent.handle(blocked_event)

    blocked_tasks = _read_project_file(project_root, BLOCKED_TASKS_FILE_NAME)
    decisions_log = _read_project_file(project_root, DECISIONS_LOG_FILE_NAME)
    assert _markdown_entry_count(blocked_tasks) >= 1, (
        "blocked_tasks.md has no blocked entries"
    )
    assert DEFER_PARALLEL_ENTRY in decisions_log, (
        "decisions.log has no DEFER_PARALLEL entry"
    )


def force_escalation(clone_agent: CloneAgent, project_root: Path) -> None:
    """Force a high-risk code event and verify escalation persistence."""
    escalation_event = AgentEvent(
        event_type=EventType.CODE_CHANGED,
        source_agent=TEST_SOURCE_AGENT,
        payload={
            NEW_DEPENDENCY_PAYLOAD_KEY: DEPENDENCY_REQUESTS,
            BREAKING_CHANGE_PAYLOAD_KEY: True,
            FILE_PATH_PAYLOAD_KEY: BREAKING_CHANGE_FILE_PATH,
        },
    )

    result = clone_agent.handle(escalation_event)

    escalation_queue = _read_project_file(project_root, ESCALATION_QUEUE_FILE_NAME)
    assert _markdown_entry_count(escalation_queue) >= 1, (
        "escalation_queue.md has no escalation entries"
    )
    assert result.escalate is True, "forced escalation result.escalate is not True"


def _read_project_file(project_root: Path, file_name: str) -> str:
    """Read one smoke-test project artifact."""
    return (project_root / file_name).read_text(encoding=ENCODING)


def _markdown_entry_count(content: str) -> int:
    """Return markdown table row count excluding format/help rows."""
    rows = [
        line
        for line in content.splitlines()
        if line.startswith(MARKDOWN_TABLE_ROW_PREFIX)
    ]
    return len(rows)


if __name__ == "__main__":
    raise SystemExit(main())
