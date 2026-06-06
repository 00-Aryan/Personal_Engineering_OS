"""Unit tests for the ProjectOS Click CLI."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml
from click.testing import CliRunner

from cli.main import cli
from core.decision_log import DecisionLogger
from core.evaluation.quality_gate import DEFAULT_POLICIES, GateDecision, GateResult
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
EVENT_ID_ONE = "event-1"
EVENT_ID_TWO = "event-2"
CLONE_AGENT = "clone"
PLANNING_AGENT_NAME = "planning"
AUTONOMOUS_CATEGORY = "AUTONOMOUS"
ESCALATE_CATEGORY = "ESCALATE"
REASONING = "reason"
OUTCOME = "outcome"
GATE_EVENT_ID = "gate-event-1"
GATE_OVERRIDE_REASON = "manual review passed"
BENCHMARK_HISTORY_PATH = ".projectos_state/benchmark_history.jsonl"
AUDIT_REPORT_PATH = "audit_report.md"
GATE_LOG_PATH = ".projectos_state/gate_decisions.jsonl"
EVALUATIONS_PATH = ".projectos_state/evaluations.jsonl"


class CapturingTaskQueue:
    """TaskQueue test double for CLI review command."""

    def __init__(self) -> None:
        """Initialize captured submissions."""
        self.submissions: list[tuple[AgentEvent, object]] = []

    def submit(self, event: AgentEvent, target_agent: object) -> None:
        """Capture a submitted event and target agent."""
        self.submissions.append((event, target_agent))


class FakeQualityGate:
    """QualityGate test double for CLI commands."""

    def __init__(self) -> None:
        """Initialize fake gate state."""
        self.policies = DEFAULT_POLICIES
        self.overrides: list[tuple[str, str]] = []
        self.result = GateResult(
            decision=GateDecision.BLOCK,
            agent_name="code_writing",
            event_id=GATE_EVENT_ID,
            combined_score=0.2,
            blocking_reasons=["low score"],
            warnings=[],
            gate_policy="code_writing",
            timestamp=datetime.now(timezone.utc),
            duration_ms=1,
        )

    def recent_results(
        self,
        agent_name: str | None = None,
        limit: int = 100,
    ) -> list[GateResult]:
        """Return one fake recent result."""
        if agent_name is not None and agent_name != self.result.agent_name:
            return []
        return [self.result]

    def get_block_rate(self, agent_name: str, window: int = 100) -> float:
        """Return a deterministic block rate."""
        return 1.0 if agent_name == self.result.agent_name else 0.0

    def override(self, event_id: str, reason: str) -> GateResult:
        """Capture override calls and return a bypass result."""
        self.overrides.append((event_id, reason))
        return GateResult(
            decision=GateDecision.BYPASS,
            agent_name=self.result.agent_name,
            event_id=event_id,
            combined_score=self.result.combined_score,
            blocking_reasons=[],
            warnings=[],
            gate_policy=self.result.gate_policy,
            timestamp=datetime.now(timezone.utc),
            duration_ms=0,
            human_override=True,
            override_reason=reason,
        )


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

    def test_decisions_command_shows_tail(self) -> None:
        """Verify decisions command prints recent JSONL decisions."""
        decision_logger = DecisionLogger(self.project_root)
        decision_logger.log(
            EVENT_ID_ONE,
            None,
            CLONE_AGENT,
            AUTONOMOUS_CATEGORY,
            REASONING,
            OUTCOME,
        )
        decision_logger.log(
            EVENT_ID_TWO,
            None,
            CLONE_AGENT,
            ESCALATE_CATEGORY,
            REASONING,
            OUTCOME,
            escalated=True,
        )

        result = self.runner.invoke(
            cli,
            ["decisions", "--tail", "1"],
            obj={"project_root": self.project_root},
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn(EVENT_ID_TWO, result.output)
        self.assertNotIn(EVENT_ID_ONE, result.output)

    def test_decisions_command_filters_agent(self) -> None:
        """Verify decisions command filters by agent name."""
        decision_logger = DecisionLogger(self.project_root)
        decision_logger.log(
            EVENT_ID_ONE,
            None,
            CLONE_AGENT,
            AUTONOMOUS_CATEGORY,
            REASONING,
            OUTCOME,
        )
        decision_logger.log(
            EVENT_ID_TWO,
            None,
            PLANNING_AGENT_NAME,
            AUTONOMOUS_CATEGORY,
            REASONING,
            OUTCOME,
        )

        result = self.runner.invoke(
            cli,
            ["decisions", "--agent", PLANNING_AGENT_NAME],
            obj={"project_root": self.project_root},
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn(EVENT_ID_TWO, result.output)
        self.assertNotIn(EVENT_ID_ONE, result.output)

    def test_decisions_command_summary(self) -> None:
        """Verify decisions command prints JSON summary output."""
        decision_logger = DecisionLogger(self.project_root)
        decision_logger.log(
            EVENT_ID_ONE,
            None,
            CLONE_AGENT,
            ESCALATE_CATEGORY,
            REASONING,
            OUTCOME,
            escalated=True,
        )

        result = self.runner.invoke(
            cli,
            ["decisions", "--summary"],
            obj={"project_root": self.project_root},
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn('"total_decisions": 1', result.output)
        self.assertIn('"escalation_rate": 1.0', result.output)

    def test_gate_status_command_runs(self) -> None:
        """Verify gate status prints recent gate decisions."""
        result = self.runner.invoke(
            cli,
            ["gate", "status"],
            obj={
                "project_root": self.project_root,
                "quality_gate": FakeQualityGate(),
            },
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Agent", result.output)
        self.assertIn("code_writing", result.output)

    def test_gate_override_command_runs(self) -> None:
        """Verify gate override delegates to the quality gate."""
        quality_gate = FakeQualityGate()

        result = self.runner.invoke(
            cli,
            [
                "gate",
                "override",
                GATE_EVENT_ID,
                "--reason",
                GATE_OVERRIDE_REASON,
            ],
            obj={
                "project_root": self.project_root,
                "quality_gate": quality_gate,
            },
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(quality_gate.overrides, [(GATE_EVENT_ID, GATE_OVERRIDE_REASON)])
        self.assertIn(GATE_EVENT_ID, result.output)

    def test_gate_policies_command_runs(self) -> None:
        """Verify gate policies prints configured policies."""
        result = self.runner.invoke(
            cli,
            ["gate", "policies"],
            obj={
                "project_root": self.project_root,
                "quality_gate": FakeQualityGate(),
            },
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Min Score", result.output)
        self.assertIn("code_review", result.output)

    def test_benchmark_run_command_runs(self) -> None:
        """Verify benchmark run writes reports and exits successfully."""
        self._write_base_agent_fixture()

        result = self.runner.invoke(
            cli,
            ["benchmark", "run"],
            obj={"project_root": self.project_root},
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("ProjectOS Quality Benchmark", result.output)
        self.assertTrue(
            (self.project_root / BENCHMARK_HISTORY_PATH).exists(),
        )

    def test_benchmark_history_command_shows_recent_runs(self) -> None:
        """Verify benchmark history prints formatted JSONL rows."""
        history_path = self.project_root / BENCHMARK_HISTORY_PATH
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-06-06T00:00:00+00:00",
                    "pass_rate": 1.0,
                    "avg_score": 0.9,
                    "git_commit": "abc1234",
                }
            )
            + "\n",
            encoding=TEST_ENCODING,
        )

        result = self.runner.invoke(
            cli,
            ["benchmark", "history"],
            obj={"project_root": self.project_root},
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("timestamp | pass_rate | avg_score | git_commit", result.output)
        self.assertIn("abc1234", result.output)

    def test_audit_command_prints_report(self) -> None:
        """Verify audit command prints a quality audit report."""
        self._write_audit_state()

        result = self.runner.invoke(
            cli,
            ["audit", "--days", "7"],
            obj={"project_root": self.project_root},
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("ProjectOS Quality Audit Report", result.output)
        self.assertIn("Total evaluations", result.output)

    def test_audit_command_saves_report(self) -> None:
        """Verify audit command writes report content to a file."""
        self._write_audit_state()

        result = self.runner.invoke(
            cli,
            ["audit", "--save", AUDIT_REPORT_PATH],
            obj={"project_root": self.project_root},
        )

        report_path = self.project_root / AUDIT_REPORT_PATH
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(report_path.exists())
        self.assertIn("ProjectOS Quality Audit Report", report_path.read_text(encoding=TEST_ENCODING))

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

    def _write_base_agent_fixture(self) -> None:
        """Write the fixture file expected by the benchmark command."""
        core_dir = self.project_root / "core"
        core_dir.mkdir(parents=True, exist_ok=True)
        (core_dir / "base_agent.py").write_text(
            '"""Base agent test fixture."""\n',
            encoding=TEST_ENCODING,
        )

    def _write_audit_state(self) -> None:
        """Write minimal evaluation and gate state for audit commands."""
        timestamp = datetime.now(timezone.utc).isoformat()
        evaluations_path = self.project_root / EVALUATIONS_PATH
        gate_path = self.project_root / GATE_LOG_PATH
        evaluations_path.parent.mkdir(parents=True, exist_ok=True)
        evaluation_payload = {
            "agent_name": "code_writing",
            "criteria_scores": {"score": 0.9},
            "evaluation_duration_ms": 1,
            "evaluator_model": "model",
            "evaluator_name": "llm_judge",
            "event_id": "audit-event",
            "metadata": {},
            "passed": True,
            "raw_output_sample": "raw",
            "reasoning": "ok",
            "timestamp": timestamp,
            "weighted_score": 0.9,
        }
        gate_payload = {
            "agent_name": "code_writing",
            "blocking_reasons": [],
            "combined_score": 0.9,
            "decision": "PASS",
            "duration_ms": 1,
            "event_id": "audit-event",
            "gate_policy": "code_writing",
            "human_override": False,
            "override_reason": None,
            "timestamp": timestamp,
            "warnings": [],
        }
        evaluations_path.write_text(
            json.dumps(evaluation_payload, sort_keys=True) + "\n",
            encoding=TEST_ENCODING,
        )
        gate_path.write_text(
            json.dumps(gate_payload, sort_keys=True) + "\n",
            encoding=TEST_ENCODING,
        )


if __name__ == "__main__":
    unittest.main()
