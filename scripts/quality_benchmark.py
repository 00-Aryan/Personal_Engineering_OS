"""Mocked ProjectOS quality benchmark suite for CI and local checks."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional

from agents.code_review_agent import CodeReviewAgent
from agents.code_writing_agent import CodeWritingAgent
from agents.planning_agent import PlanningAgent
from core.events import AgentEvent, EventType
from core.model_provider import ModelProvider


ENCODING = "utf-8"
NEWLINE = "\n"
FILE_WRITE_MODE = "w"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_RESULTS_PATH = Path("docs/benchmark_results.md")
BENCHMARK_HISTORY_PATH = Path(".projectos_state/benchmark_history.jsonl")
PASS_RATE_THRESHOLD = 0.80
GIT_COMMAND = "git"
GIT_TIMEOUT_SECONDS = 30
PERCENT_MULTIPLIER = 100.0
ZERO_SCORE = 0.0
FULL_SCORE = 1.0

AGENT_CODE_REVIEW = "code_review"
AGENT_PLANNING = "planning"
AGENT_CODE_WRITING = "code_writing"
BENCHMARK_MODEL_NAME = "mock-benchmark"

FIELD_NAME = "name"
FIELD_AGENT = "agent"
FIELD_INPUT_FILE = "input_file"
FIELD_INPUT = "input"
FIELD_EXPECTED_ISSUE_TYPES = "expected_issue_types"
FIELD_MIN_ISSUE_COUNT = "min_issue_count"
FIELD_EXPECTED_TASK_COUNT_RANGE = "expected_task_count_range"
FIELD_REQUIRED_TASK_FIELDS = "required_task_fields"
FIELD_EXPECTED_OUTPUT_CONTAINS = "expected_output_contains"

REPORT_TITLE = "ProjectOS Quality Benchmark"
REPORT_TABLE_HEADER = (
    "| Case | Passed | Score | Duration ms | Failure |\n"
    "| --- | --- | ---: | ---: | --- |"
)
HISTORY_HEADER = "timestamp | pass_rate | avg_score | git_commit"
NO_HISTORY_MESSAGE = "No benchmark history found."

MOCK_REVIEW_OUTPUT = json.dumps(
    [
        {
            "severity": "LOW",
            "category": "style",
            "line_number": 1,
            "description": "Prefer a tighter import boundary.",
            "suggested_fix": "Group related imports consistently.",
        },
        {
            "severity": "LOW",
            "category": "docs",
            "line_number": None,
            "description": "Add a module usage note for future maintainers.",
            "suggested_fix": "Document the key extension point.",
        },
    ]
)
MOCK_PLANNING_OUTPUT = json.dumps(
    [
        {
            "id": "TASK-A",
            "title": "Add request rate limiter",
            "type": "feature",
            "priority": "HIGH",
            "estimated_complexity": "M",
            "dependencies": [],
            "acceptance_criteria": ["Requests above the limit are rejected."],
            "agent_assignment": "code_writing",
            "blocked_by": None,
        },
        {
            "id": "TASK-B",
            "title": "Cover endpoint rate limits",
            "type": "test",
            "priority": "MEDIUM",
            "estimated_complexity": "S",
            "dependencies": ["TASK-A"],
            "acceptance_criteria": ["Tests assert allowed and blocked requests."],
            "agent_assignment": "test",
            "blocked_by": None,
        },
        {
            "id": "TASK-C",
            "title": "Document rate limit behavior",
            "type": "docs",
            "priority": "LOW",
            "estimated_complexity": "S",
            "dependencies": ["TASK-A"],
            "acceptance_criteria": ["API docs describe limits and error shape."],
            "agent_assignment": "docs",
            "blocked_by": None,
        },
    ]
)
MOCK_CODE_OUTPUT = '''"""Email validation helpers."""

import re


EMAIL_PATTERN = r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"


def validate_email(value: str) -> bool:
    """Return whether a string looks like an email address."""
    return bool(re.match(EMAIL_PATTERN, value))
'''


@dataclass(frozen=True)
class CaseResult:
    """Result for one benchmark case."""

    name: str
    passed: bool
    score: float
    duration_ms: int
    failure_reason: Optional[str]


@dataclass(frozen=True)
class BenchmarkReport:
    """Aggregate benchmark report for all cases in one run."""

    timestamp: datetime
    total_cases: int
    passed_cases: int
    pass_rate: float
    avg_score: float
    case_results: list[CaseResult]
    git_commit: Optional[str]

    def to_markdown(self) -> str:
        """Render this report as a human-readable markdown section."""
        lines = [
            f"## {REPORT_TITLE} - {self.timestamp.isoformat()}",
            "",
            f"- Total cases: {self.total_cases}",
            f"- Passed cases: {self.passed_cases}",
            f"- Pass rate: {self.pass_rate:.2f}",
            f"- Average score: {self.avg_score:.2f}",
            f"- Git commit: {self.git_commit or 'unknown'}",
            "",
            REPORT_TABLE_HEADER,
        ]
        for case_result in self.case_results:
            lines.append(
                "| {name} | {passed} | {score:.2f} | {duration_ms} | {failure} |".format(
                    name=case_result.name,
                    passed=str(case_result.passed),
                    score=case_result.score,
                    duration_ms=case_result.duration_ms,
                    failure=case_result.failure_reason or "",
                )
            )
        return NEWLINE.join(lines) + NEWLINE

    def to_json(self) -> str:
        """Serialize this report as one JSON object string."""
        payload = {
            "timestamp": self.timestamp.isoformat(),
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "pass_rate": self.pass_rate,
            "avg_score": self.avg_score,
            "case_results": [asdict(case_result) for case_result in self.case_results],
            "git_commit": self.git_commit,
        }
        return json.dumps(payload, sort_keys=True)


class MockBenchmarkProvider(ModelProvider):
    """ModelProvider test double that returns deterministic benchmark outputs."""

    provider_key = "mock"

    def __init__(self, agent_name: str) -> None:
        """Initialize the mock provider for one benchmarked agent."""
        self.agent_name = agent_name

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """Return a deterministic completion for the configured agent."""
        if self.agent_name == AGENT_CODE_REVIEW:
            return MOCK_REVIEW_OUTPUT
        if self.agent_name == AGENT_PLANNING:
            return MOCK_PLANNING_OUTPUT
        if self.agent_name == AGENT_CODE_WRITING:
            return MOCK_CODE_OUTPUT
        return ""

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield the deterministic completion as one streamed fragment."""
        yield self.complete(prompt, system_prompt, 0)

    def get_model_name(self) -> str:
        """Return the deterministic benchmark model name."""
        return BENCHMARK_MODEL_NAME


class BenchmarkSuite:
    """Run deterministic quality benchmarks against ProjectOS agents."""

    BENCHMARK_CASES: list[Dict[str, Any]] = [
        {
            FIELD_NAME: "code_review_basic",
            FIELD_AGENT: AGENT_CODE_REVIEW,
            FIELD_INPUT_FILE: "core/base_agent.py",
            FIELD_EXPECTED_ISSUE_TYPES: ["style", "docs"],
            FIELD_MIN_ISSUE_COUNT: 1,
        },
        {
            FIELD_NAME: "planning_feature",
            FIELD_AGENT: AGENT_PLANNING,
            FIELD_INPUT: "Add rate limiting to all API endpoints",
            FIELD_EXPECTED_TASK_COUNT_RANGE: (2, 8),
            FIELD_REQUIRED_TASK_FIELDS: ["id", "acceptance_criteria"],
        },
        {
            FIELD_NAME: "code_writing_function",
            FIELD_AGENT: AGENT_CODE_WRITING,
            FIELD_INPUT: "Write a function to validate email addresses",
            FIELD_EXPECTED_OUTPUT_CONTAINS: ["def ", "->", '"""'],
        },
    ]

    def __init__(self, project_root: Path | str = DEFAULT_PROJECT_ROOT) -> None:
        """Initialize benchmark paths and logger."""
        self.project_root = Path(project_root)
        self.benchmark_cases = list(self.BENCHMARK_CASES)
        self.logger = logging.getLogger("projectos.quality_benchmark")

    def run_all(self, use_mocks: bool = True) -> BenchmarkReport:
        """Run all benchmark cases, persist results, and return a report."""
        if not use_mocks:
            raise ValueError("Quality benchmark only supports mocked providers.")
        case_results: list[CaseResult] = []
        for case in self.benchmark_cases:
            try:
                case_results.append(self.run_case(case))
            except Exception as error:
                case_results.append(
                    CaseResult(
                        name=str(case.get(FIELD_NAME, "unknown")),
                        passed=False,
                        score=ZERO_SCORE,
                        duration_ms=0,
                        failure_reason=str(error),
                    )
                )
        report = self._report(case_results)
        self._write_report(report)
        return report

    def run_case(self, case: Dict[str, Any]) -> CaseResult:
        """Run one benchmark case and validate its output."""
        started_at = time.perf_counter()
        name = str(case.get(FIELD_NAME, "unknown"))
        agent_name = str(case.get(FIELD_AGENT, ""))
        with tempfile.TemporaryDirectory() as work_dir:
            work_root = Path(work_dir)
            if agent_name == AGENT_CODE_REVIEW:
                passed, score, failure = self._run_code_review_case(case, work_root)
            elif agent_name == AGENT_PLANNING:
                passed, score, failure = self._run_planning_case(case, work_root)
            elif agent_name == AGENT_CODE_WRITING:
                passed, score, failure = self._run_code_writing_case(case, work_root)
            else:
                passed, score, failure = False, ZERO_SCORE, f"Unknown agent: {agent_name}"
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return CaseResult(
            name=name,
            passed=passed,
            score=score,
            duration_ms=duration_ms,
            failure_reason=failure,
        )

    def _run_code_review_case(
        self,
        case: Mapping[str, Any],
        work_root: Path,
    ) -> tuple[bool, float, Optional[str]]:
        """Run and score the code review benchmark case."""
        input_path = self.project_root / str(case[FIELD_INPUT_FILE])
        agent = CodeReviewAgent(
            MockBenchmarkProvider(AGENT_CODE_REVIEW),
            self.logger,
            work_root,
        )
        result = agent.handle(
            AgentEvent(
                event_type=EventType.CODE_CHANGED,
                source_agent="quality_benchmark",
                payload={"file_path": str(input_path), "task_id": case[FIELD_NAME]},
            )
        )
        if not result.success:
            return False, ZERO_SCORE, str(result.output)
        issues = result.output.get("issues", [])
        expected_categories = {
            str(category) for category in case[FIELD_EXPECTED_ISSUE_TYPES]
        }
        actual_categories = {
            str(issue.get("category")) for issue in issues if isinstance(issue, Mapping)
        }
        min_issue_count = int(case[FIELD_MIN_ISSUE_COUNT])
        checks = [
            len(issues) >= min_issue_count,
            expected_categories.issubset(actual_categories),
        ]
        score = _score_from_checks(checks)
        failure = None if all(checks) else "Expected review issue categories/count missing."
        return all(checks), score, failure

    def _run_planning_case(
        self,
        case: Mapping[str, Any],
        work_root: Path,
    ) -> tuple[bool, float, Optional[str]]:
        """Run and score the planning benchmark case."""
        agent = PlanningAgent(
            MockBenchmarkProvider(AGENT_PLANNING),
            self.logger,
            work_root,
        )
        result = agent.handle(
            AgentEvent(
                event_type=EventType.NEW_FEATURE,
                source_agent="quality_benchmark",
                payload={"description": str(case[FIELD_INPUT])},
            )
        )
        if not result.success:
            return False, ZERO_SCORE, str(result.output)
        tasks = result.output.get("tasks", [])
        minimum, maximum = case[FIELD_EXPECTED_TASK_COUNT_RANGE]
        required_fields = [str(field) for field in case[FIELD_REQUIRED_TASK_FIELDS]]
        checks = [
            minimum <= len(tasks) <= maximum,
            all(_task_has_fields(task, required_fields) for task in tasks),
        ]
        score = _score_from_checks(checks)
        failure = None if all(checks) else "Expected planning task shape missing."
        return all(checks), score, failure

    def _run_code_writing_case(
        self,
        case: Mapping[str, Any],
        work_root: Path,
    ) -> tuple[bool, float, Optional[str]]:
        """Run and score the code writing benchmark case."""
        target_path = work_root / "generated_email.py"
        agent = CodeWritingAgent(
            MockBenchmarkProvider(AGENT_CODE_WRITING),
            self.logger,
            work_root,
        )
        result = agent.handle(
            AgentEvent(
                event_type=EventType.BACKLOG_CHANGED,
                source_agent="quality_benchmark",
                payload={
                    "task_id": case[FIELD_NAME],
                    "file_path": str(target_path),
                    "task_description": str(case[FIELD_INPUT]),
                    "acceptance_criteria": ["Validate email-like strings."],
                },
            )
        )
        if not result.success:
            return False, ZERO_SCORE, str(result.output)
        code = target_path.read_text(encoding=ENCODING)
        expected_fragments = [str(fragment) for fragment in case[FIELD_EXPECTED_OUTPUT_CONTAINS]]
        checks = [fragment in code for fragment in expected_fragments]
        score = _score_from_checks(checks)
        failure = None if all(checks) else "Expected generated code fragments missing."
        return all(checks), score, failure

    def _report(self, case_results: list[CaseResult]) -> BenchmarkReport:
        """Build an aggregate report from case results."""
        total_cases = len(case_results)
        passed_cases = sum(1 for case_result in case_results if case_result.passed)
        pass_rate = passed_cases / total_cases if total_cases else ZERO_SCORE
        avg_score = (
            sum(case_result.score for case_result in case_results) / total_cases
            if total_cases
            else ZERO_SCORE
        )
        return BenchmarkReport(
            timestamp=datetime.now(timezone.utc),
            total_cases=total_cases,
            passed_cases=passed_cases,
            pass_rate=pass_rate,
            avg_score=avg_score,
            case_results=case_results,
            git_commit=_git_commit(self.project_root),
        )

    def _write_report(self, report: BenchmarkReport) -> None:
        """Append report output to markdown and JSONL history files."""
        _append_atomically(self.project_root / BENCHMARK_RESULTS_PATH, report.to_markdown())
        _append_jsonl(self.project_root / BENCHMARK_HISTORY_PATH, report.to_json())


def exit_code_for_report(report: BenchmarkReport) -> int:
    """Return the process exit code for a benchmark report."""
    return 0 if report.pass_rate >= PASS_RATE_THRESHOLD else 1


def history_rows(project_root: Path | str, limit: int = 10) -> list[str]:
    """Return formatted benchmark history rows for CLI display."""
    history_path = Path(project_root) / BENCHMARK_HISTORY_PATH
    if not history_path.exists():
        return []
    records = [_history_record(line) for line in history_path.read_text(encoding=ENCODING).splitlines()]
    valid_records = [record for record in records if record is not None]
    return [_history_row(record) for record in valid_records[-limit:]]


def main() -> int:
    """Run the benchmark suite and return an appropriate process exit code."""
    report = BenchmarkSuite().run_all(use_mocks=True)
    print(report.to_markdown())
    return exit_code_for_report(report)


def _task_has_fields(task: Any, required_fields: list[str]) -> bool:
    """Return whether a task mapping contains all required fields."""
    if not isinstance(task, Mapping):
        return False
    return all(field in task and task[field] for field in required_fields)


def _score_from_checks(checks: list[bool]) -> float:
    """Return the fraction of passing checks."""
    if not checks:
        return ZERO_SCORE
    return sum(1 for check in checks if check) / len(checks)


def _git_commit(project_root: Path) -> Optional[str]:
    """Return the current short git commit when available."""
    try:
        completed_process = subprocess.run(
            [GIT_COMMAND, "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if completed_process.returncode != 0:
        return None
    commit = completed_process.stdout.strip()
    return commit or None


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


def _append_atomically(path: Path, content: str) -> None:
    """Append content to a file through atomic replacement."""
    existing_content = path.read_text(encoding=ENCODING) if path.exists() else ""
    _write_atomically(path, f"{existing_content}{content}")


def _append_jsonl(path: Path, json_text: str) -> None:
    """Append one JSONL record using append-only file semantics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor = os.open(
        str(path),
        os.O_CREAT | os.O_APPEND | os.O_WRONLY,
        0o644,
    )
    try:
        os.write(file_descriptor, f"{json_text}{NEWLINE}".encode(ENCODING))
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)


def _history_record(line: str) -> Optional[Mapping[str, Any]]:
    """Parse one history JSONL line, returning None for malformed lines."""
    if not line.strip():
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, Mapping) else None


def _history_row(record: Mapping[str, Any]) -> str:
    """Return one formatted benchmark history row."""
    return " | ".join(
        [
            str(record.get("timestamp", "")),
            f"{float(record.get('pass_rate', 0.0)):.2f}",
            f"{float(record.get('avg_score', 0.0)):.2f}",
            str(record.get("git_commit") or "unknown"),
        ]
    )


BENCHMARK_CASES = BenchmarkSuite.BENCHMARK_CASES


if __name__ == "__main__":
    raise SystemExit(main())
