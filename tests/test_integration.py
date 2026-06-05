"""Integration tests for ProjectOS orchestration."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Iterator

from core.events import AgentEvent, EventType
from core.projectos import ProjectOS


TEST_ENCODING = "utf-8"
CONFIG_DIR = "config"
CONFIG_FILE = "models.yaml"
TARGET_AGENT_KEY = "target_agent"
TASK_ID_KEY = "task_id"
FILE_PATH_KEY = "file_path"
TASK_DESCRIPTION_KEY = "task_description"
ACCEPTANCE_CRITERIA_KEY = "acceptance_criteria"
DESCRIPTION_KEY = "description"
SOURCE_AGENT = "integration_test"
CODE_WRITING_AGENT_ALIAS = "code_writing_agent"
PLANNING_AGENT_ALIAS = "planning_agent"
BLOCKED_CORRELATION_ID = "blocked-flow"
PERMISSION_BLOCKER = "permission"

SOURCE_CODE = (
    "def existing() -> int:\n"
    "    \"\"\"Return an existing value.\"\"\"\n"
    "    return 1\n"
)
GENERATED_CODE = (
    "def generated() -> int:\n"
    "    \"\"\"Return a generated value.\"\"\"\n"
    "    return 2\n"
)
GENERATED_TESTS = (
    "def test_generated() -> None:\n"
    "    \"\"\"Verify generated behavior.\"\"\"\n"
    "    assert True\n"
)
PASSING_PYTEST_OUTPUT = "1 passed in 0.01s"
FEATURE_DESCRIPTION = "Create a generated helper."
FEATURE_FILE = "agents/generated_feature.py"
BLOCKED_FILE = "agents/generated_blocked.py"
INDEPENDENT_FILE = "independent.py"


def test_code_change_triggers_review_and_tests(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Verify CODE_CHANGED flows through Clone to review and test agents."""
    _patch_pytest_run(monkeypatch)
    project_os = _project_os(tmp_path)
    source_path = tmp_path / "example.py"
    source_path.write_text(SOURCE_CODE, encoding=TEST_ENCODING)

    try:
        project_os.submit_event(
            AgentEvent(
                event_type=EventType.CODE_CHANGED,
                source_agent=SOURCE_AGENT,
                payload={FILE_PATH_KEY: str(source_path)},
            )
        )
        _wait_for_idle(project_os)

        assert _review_report_count(tmp_path) >= 1
        assert (tmp_path / "tests" / "test_example.py").exists()
    finally:
        project_os.stop()


def test_blocked_task_resumes_after_permission(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Verify blocked work resumes after PERMISSION_GRANTED."""
    _patch_pytest_run(monkeypatch)
    project_os = _project_os(tmp_path)
    independent_path = tmp_path / INDEPENDENT_FILE
    independent_path.write_text(SOURCE_CODE, encoding=TEST_ENCODING)
    blocked_path = tmp_path / BLOCKED_FILE
    project_os.clone_agent.event_queue = [
        AgentEvent(
            event_type=EventType.CODE_CHANGED,
            source_agent=SOURCE_AGENT,
            payload={FILE_PATH_KEY: str(independent_path)},
        )
    ]

    try:
        project_os.submit_event(
            AgentEvent(
                event_type=EventType.PERMISSION_BLOCKED,
                source_agent=SOURCE_AGENT,
                payload={
                    TARGET_AGENT_KEY: CODE_WRITING_AGENT_ALIAS,
                    TASK_ID_KEY: "PLAN-20260605-900",
                    FILE_PATH_KEY: str(blocked_path),
                    TASK_DESCRIPTION_KEY: "Write blocked file.",
                    ACCEPTANCE_CRITERIA_KEY: ["File is written"],
                },
                correlation_id=BLOCKED_CORRELATION_ID,
                blocked_by=PERMISSION_BLOCKER,
            )
        )
        _wait_for_idle(project_os)

        assert project_os.task_queue.get_blocked()
        assert _review_report_count(tmp_path) >= 1

        project_os.submit_event(
            AgentEvent(
                event_type=EventType.PERMISSION_GRANTED,
                source_agent=SOURCE_AGENT,
                payload={},
                correlation_id=BLOCKED_CORRELATION_ID,
            )
        )
        _wait_for_idle(project_os)

        assert blocked_path.exists()
        assert GENERATED_CODE in blocked_path.read_text(encoding=TEST_ENCODING)
    finally:
        project_os.stop()


def test_full_feature_flow(tmp_path: Path, monkeypatch: Any) -> None:
    """Verify manual feature planning routes backlog work to CodeWriting."""
    _patch_pytest_run(monkeypatch)
    project_os = _project_os(tmp_path)
    generated_path = tmp_path / FEATURE_FILE

    try:
        project_os.submit_event(
            AgentEvent(
                event_type=EventType.MANUAL_TRIGGER,
                source_agent=SOURCE_AGENT,
                payload={
                    DESCRIPTION_KEY: FEATURE_DESCRIPTION,
                    TARGET_AGENT_KEY: PLANNING_AGENT_ALIAS,
                },
            )
        )
        _wait_for_idle(project_os)

        assert (tmp_path / "backlog.md").exists()
        assert generated_path.exists()
        assert GENERATED_CODE in generated_path.read_text(encoding=TEST_ENCODING)
    finally:
        project_os.stop()


def _project_os(project_root: Path) -> ProjectOS:
    """Create a ProjectOS instance with mocked providers."""
    config_path = _write_config(project_root)
    return ProjectOS(
        config_path=config_path,
        provider_factory=lambda agent_name, path: MockModelProvider(agent_name),
    )


def _write_config(project_root: Path) -> Path:
    """Write a complete model config for integration tests."""
    config_dir = project_root / CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / CONFIG_FILE
    config_path.write_text(
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
                "  code_writing:",
                "    provider: openrouter",
                "    model: openrouter-free",
                "  code_review:",
                "    provider: openrouter",
                "    model: openrouter-free",
                "  architecture:",
                "    provider: openrouter",
                "    model: deepseek-v3",
                "  test:",
                "    provider: openrouter",
                "    model: openrouter-free",
                "  docs:",
                "    provider: gemini",
                "    model: gemini-flash",
            ]
        )
        + "\n",
        encoding=TEST_ENCODING,
    )
    return config_path


def _patch_pytest_run(monkeypatch: Any) -> None:
    """Patch TestAgent subprocess pytest execution."""

    def fake_run(
        command: list[str],
        cwd: Path,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        """Return a successful pytest process result."""
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=PASSING_PYTEST_OUTPUT,
            stderr="",
        )

    monkeypatch.setattr("agents.test_agent.subprocess.run", fake_run)


def _wait_for_idle(project_os: ProjectOS, timeout_seconds: float = 5.0) -> None:
    """Wait until the ProjectOS task queue is idle."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if project_os.task_queue.get_pending_count() == 0:
            return
        time.sleep(0.01)
    raise AssertionError("ProjectOS task queue did not become idle.")


def _review_report_count(project_root: Path) -> int:
    """Return the number of generated review reports."""
    reviews_dir = project_root / "reviews"
    if not reviews_dir.exists():
        return 0
    return len([path for path in reviews_dir.iterdir() if path.name.endswith("_review.md")])


class MockModelProvider:
    """Mock model provider used by ProjectOS integration tests."""

    def __init__(self, agent_name: str) -> None:
        """Initialize the mock provider for one agent."""
        self.agent_name = agent_name
        self.calls: list[tuple[str, str, int]] = []

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return deterministic model output for one agent."""
        self.calls.append((prompt, system_prompt, max_tokens))
        if self.agent_name == "planning":
            return json.dumps(
                [
                    {
                        "id": "write-feature",
                        "title": "Write generated helper",
                        "type": "implementation",
                        "priority": "HIGH",
                        "estimated_complexity": "S",
                        "dependencies": [],
                        "acceptance_criteria": ["Helper file is generated"],
                        "agent_assignment": CODE_WRITING_AGENT_ALIAS,
                        "blocked_by": None,
                        "file_path": FEATURE_FILE,
                    }
                ]
            )
        if self.agent_name == "code_review":
            return "[]"
        if self.agent_name == "code_writing":
            return GENERATED_CODE
        if self.agent_name == "test":
            return GENERATED_TESTS
        if self.agent_name == "docs":
            return SOURCE_CODE
        return "{}"

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield no streamed model fragments."""
        return iter(())

    def get_model_name(self) -> str:
        """Return a deterministic mock model name."""
        return f"mock-{self.agent_name}"
