"""Unit tests for the ProjectOS Click CLI."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml
from click.testing import CliRunner

from cli.main import cli
from core.events import AgentEvent


TEST_ENCODING = "utf-8"
CONFIG_DIR = "config"
CONFIG_FILE = "models.yaml"
TASKS_DIR = "tasks"
TASKS_README = "README.md"
BACKLOG_FILE = "backlog.md"
PLANNING_AGENT = "planning"
UPDATED_MODEL = "test-model"
SOURCE_FILE = "example.py"
SOURCE_CODE = "value = 1\n"


class CapturingTaskQueue:
    """TaskQueue test double for CLI review command."""

    def __init__(self) -> None:
        """Initialize captured submissions."""
        self.submissions: list[tuple[AgentEvent, object]] = []

    def submit(self, event: AgentEvent, target_agent: object) -> None:
        """Capture a submitted event and target agent."""
        self.submissions.append((event, target_agent))


class CliTestCase(unittest.TestCase):
    """Tests Click commands exposed by cli.main."""

    def setUp(self) -> None:
        """Create an isolated ProjectOS project root."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self.runner = CliRunner()
        self._write_config()
        self._write_tasks_readme()

    def tearDown(self) -> None:
        """Remove the isolated project root."""
        self._temp_dir.cleanup()

    def test_status_command_runs(self) -> None:
        """Verify status prints configured agents and pending task count."""
        result = self.runner.invoke(
            cli,
            ["status"],
            obj={"project_root": self.project_root},
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Agents:", result.output)
        self.assertIn("planning: deepseek-v3", result.output)
        self.assertIn("Pending tasks count: 1", result.output)

    def test_model_command_updates_config(self) -> None:
        """Verify model command updates config/models.yaml."""
        result = self.runner.invoke(
            cli,
            ["model", PLANNING_AGENT, UPDATED_MODEL],
            obj={"project_root": self.project_root},
        )

        updated_config = self._read_config()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            updated_config["agents"][PLANNING_AGENT]["model"],
            UPDATED_MODEL,
        )
        self.assertIn(
            f"Agent {PLANNING_AGENT} now uses {UPDATED_MODEL}",
            result.output,
        )

    def test_backlog_command_prints_markdown(self) -> None:
        """Verify backlog command prints existing backlog markdown."""
        backlog_content = "# ProjectOS Backlog\n## HIGH Priority\n- Status: PENDING\n"
        (self.project_root / BACKLOG_FILE).write_text(
            backlog_content,
            encoding=TEST_ENCODING,
        )

        result = self.runner.invoke(
            cli,
            ["backlog"],
            obj={"project_root": self.project_root},
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("# ProjectOS Backlog", result.output)
        self.assertIn("## HIGH Priority", result.output)

    def test_review_command_emits_event(self) -> None:
        """Verify review command submits a CODE_CHANGED event to TaskQueue."""
        task_queue = CapturingTaskQueue()
        source_path = self.project_root / SOURCE_FILE
        source_path.write_text(SOURCE_CODE, encoding=TEST_ENCODING)

        result = self.runner.invoke(
            cli,
            ["review", SOURCE_FILE],
            obj={
                "project_root": self.project_root,
                "task_queue": task_queue,
                "review_target_agent": object(),
            },
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(len(task_queue.submissions), 1)
        event, target_agent = task_queue.submissions[0]
        self.assertEqual(event.payload["file_path"], str(source_path))
        self.assertEqual(event.event_type.value, "CODE_CHANGED")
        self.assertIsNotNone(target_agent)

    def _write_config(self) -> None:
        """Write a minimal model config."""
        config_dir = self.project_root / CONFIG_DIR
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / CONFIG_FILE).write_text(
            "\n".join(
                [
                    "providers:",
                    "  openrouter:",
                    "    completion_url: https://openrouter.test/chat",
                    "    stream_url: https://openrouter.test/chat",
                    "    default_model: openrouter-free",
                    "  gemini:",
                    "    completion_url_template: https://gemini.test/{model}?key={api_key}",
                    "    stream_url_template: https://gemini.test/{model}?key={api_key}",
                    "    default_model: gemini-flash",
                    "agents:",
                    "  clone:",
                    "    provider: gemini",
                    "    model: gemini-flash",
                    "  planning:",
                    "    provider: openrouter",
                    "    model: deepseek-v3",
                ]
            )
            + "\n",
            encoding=TEST_ENCODING,
        )

    def _write_tasks_readme(self) -> None:
        """Write a minimal tasks README with one pending task."""
        tasks_dir = self.project_root / TASKS_DIR
        tasks_dir.mkdir(parents=True, exist_ok=True)
        (tasks_dir / TASKS_README).write_text(
            "- TASK_01: DONE\n- TASK_02: PENDING\n",
            encoding=TEST_ENCODING,
        )

    def _read_config(self) -> dict[str, object]:
        """Read the isolated model config."""
        config_path = self.project_root / CONFIG_DIR / CONFIG_FILE
        return yaml.safe_load(config_path.read_text(encoding=TEST_ENCODING))


if __name__ == "__main__":
    unittest.main()
