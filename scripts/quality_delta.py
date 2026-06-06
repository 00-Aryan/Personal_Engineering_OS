"""Measure Phase 4 quality delta with and without intelligence context."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from agents.code_review_agent import CodeReviewAgent
from agents.code_writing_agent import CodeWritingAgent
from agents.planning_agent import PlanningAgent
from core.events import AgentEvent, EventType
from core.intelligence.code_indexer import CodeIndexer
from core.intelligence.context_retriever import ContextRetriever
from core.intelligence.embedder import TFIDFEmbedder
from core.intelligence.memory_manager import MemoryManager
from core.intelligence.memory_store import MemoryStore
from core.intelligence.vector_store import BaseVectorStore, NumpyVectorStore
try:
    from scripts.quality_benchmark import (
        AGENT_CODE_REVIEW,
        AGENT_CODE_WRITING,
        AGENT_PLANNING,
        FIELD_AGENT,
        FIELD_EXPECTED_ISSUE_TYPES,
        FIELD_EXPECTED_OUTPUT_CONTAINS,
        FIELD_EXPECTED_TASK_COUNT_RANGE,
        FIELD_INPUT,
        FIELD_INPUT_FILE,
        FIELD_MIN_ISSUE_COUNT,
        FIELD_NAME,
        FIELD_REQUIRED_TASK_FIELDS,
        BenchmarkSuite,
        MockBenchmarkProvider,
        _score_from_checks,
        _task_has_fields,
    )
except ModuleNotFoundError:
    from quality_benchmark import (  # type: ignore[no-redef]
        AGENT_CODE_REVIEW,
        AGENT_CODE_WRITING,
        AGENT_PLANNING,
        FIELD_AGENT,
        FIELD_EXPECTED_ISSUE_TYPES,
        FIELD_EXPECTED_OUTPUT_CONTAINS,
        FIELD_EXPECTED_TASK_COUNT_RANGE,
        FIELD_INPUT,
        FIELD_INPUT_FILE,
        FIELD_MIN_ISSUE_COUNT,
        FIELD_NAME,
        FIELD_REQUIRED_TASK_FIELDS,
        BenchmarkSuite,
        MockBenchmarkProvider,
        _score_from_checks,
        _task_has_fields,
    )


ENCODING = "utf-8"
NEWLINE = "\n"
FILE_WRITE_MODE = "w"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"
STATE_DIR_NAME = ".projectos_state"
CODE_INDEX_COLLECTION = "code_index"
QUALITY_DELTA_DOC = Path("docs/phase4_quality_delta.md")
QUALITY_DELTA_JSONL = Path(".projectos_state/quality_deltas.jsonl")
REPORT_TITLE = "# Phase 4 Quality Delta"
REPORT_TABLE_HEADER = (
    "| agent | baseline | enhanced | delta | improvement pct |\n"
    "| --- | ---: | ---: | ---: | ---: |"
)
PASS_THRESHOLD = 0.0
PERCENT_MULTIPLIER = 100.0
ZERO_SCORE = 0.0


@dataclass(frozen=True)
class QualityDeltaReport:
    """Quality comparison between baseline and intelligence-enhanced agents."""

    baseline_scores: Dict[str, float]
    enhanced_scores: Dict[str, float]
    deltas: Dict[str, float]
    improvement_pct: Dict[str, float]
    overall_improvement: float
    passed: bool
    timestamp: str

    def to_markdown(self) -> str:
        """Render the quality delta report as markdown."""
        lines = [
            REPORT_TITLE,
            "",
            f"- Generated: {self.timestamp}",
            f"- Overall improvement: {self.overall_improvement:.4f}",
            f"- Passed: {self.passed}",
            "",
            REPORT_TABLE_HEADER,
        ]
        for agent_name in sorted(self.baseline_scores):
            lines.append(
                "| {agent} | {baseline:.2f} | {enhanced:.2f} | {delta:.2f} | {pct:.1f}% |".format(
                    agent=agent_name,
                    baseline=self.baseline_scores.get(agent_name, ZERO_SCORE),
                    enhanced=self.enhanced_scores.get(agent_name, ZERO_SCORE),
                    delta=self.deltas.get(agent_name, ZERO_SCORE),
                    pct=self.improvement_pct.get(agent_name, ZERO_SCORE),
                )
            )
        return NEWLINE.join(lines).rstrip() + NEWLINE

    def to_json(self) -> str:
        """Return the report as one JSON object."""
        return json.dumps(asdict(self), sort_keys=True)


class EnhancedBenchmarkSuite(BenchmarkSuite):
    """Benchmark suite that wires Phase 4 intelligence into agents."""

    def __init__(self, project_root: Path | str) -> None:
        """Initialize benchmark and deterministic intelligence components."""
        super().__init__(project_root)
        self.project_root = Path(project_root)
        self._temp_dir = tempfile.TemporaryDirectory()
        self.intelligence_root = Path(self._temp_dir.name)
        self.state_dir = self.intelligence_root / STATE_DIR_NAME
        self.embedder = TFIDFEmbedder(state_dir=self.state_dir)
        self.vector_store = NumpyVectorStore(CODE_INDEX_COLLECTION, self.state_dir)
        self.context_retriever = ContextRetriever(self.vector_store, self.embedder)
        self.memory_store = MemoryStore(_numpy_store_factory, self.embedder, self.state_dir)
        self.memory_manager = MemoryManager(self.memory_store, self.embedder)
        self._index_project()
        self._seed_memories()

    def close(self) -> None:
        """Release temporary intelligence state."""
        self._temp_dir.cleanup()

    def _run_code_review_case(
        self,
        case: Mapping[str, Any],
        work_root: Path,
    ) -> tuple[bool, float, Optional[str]]:
        """Run the code review benchmark with retrieval and memory context."""
        input_path = self.project_root / str(case[FIELD_INPUT_FILE])
        agent = CodeReviewAgent(
            MockBenchmarkProvider(AGENT_CODE_REVIEW),
            self.logger,
            work_root,
            context_retriever=self.context_retriever,
            memory_manager=self.memory_manager,
        )
        result = agent.handle(
            AgentEvent(
                event_type=EventType.CODE_CHANGED,
                source_agent="quality_delta",
                payload={
                    "file_path": str(input_path),
                    "task_id": case[FIELD_NAME],
                    "task_description": "review base agent quality",
                },
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
        checks = [
            len(issues) >= int(case[FIELD_MIN_ISSUE_COUNT]),
            expected_categories.issubset(actual_categories),
        ]
        return all(checks), _score_from_checks(checks), (
            None if all(checks) else "Expected review issue categories/count missing."
        )

    def _run_planning_case(
        self,
        case: Mapping[str, Any],
        work_root: Path,
    ) -> tuple[bool, float, Optional[str]]:
        """Run the planning benchmark with retrieval and memory context."""
        agent = PlanningAgent(
            MockBenchmarkProvider(AGENT_PLANNING),
            self.logger,
            work_root,
            context_retriever=self.context_retriever,
            memory_manager=self.memory_manager,
        )
        result = agent.handle(
            AgentEvent(
                event_type=EventType.NEW_FEATURE,
                source_agent="quality_delta",
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
        return all(checks), _score_from_checks(checks), (
            None if all(checks) else "Expected planning task shape missing."
        )

    def _run_code_writing_case(
        self,
        case: Mapping[str, Any],
        work_root: Path,
    ) -> tuple[bool, float, Optional[str]]:
        """Run the code-writing benchmark with retrieval and memory context."""
        target_path = work_root / "generated_email.py"
        agent = CodeWritingAgent(
            MockBenchmarkProvider(AGENT_CODE_WRITING),
            self.logger,
            work_root,
            context_retriever=self.context_retriever,
            memory_manager=self.memory_manager,
        )
        result = agent.handle(
            AgentEvent(
                event_type=EventType.BACKLOG_CHANGED,
                source_agent="quality_delta",
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
        fragments = [str(fragment) for fragment in case[FIELD_EXPECTED_OUTPUT_CONTAINS]]
        checks = [fragment in code for fragment in fragments]
        return all(checks), _score_from_checks(checks), (
            None if all(checks) else "Expected generated code fragments missing."
        )

    def _index_project(self) -> None:
        """Index the current project into the local vector store."""
        CodeIndexer(self.vector_store, self.embedder).index_directory(self.project_root)

    def _seed_memories(self) -> None:
        """Seed deterministic memories for enhanced benchmark agents."""
        self.memory_manager.remember_decision(
            AGENT_CODE_REVIEW,
            "Review code for style and docs findings",
            "review base_agent imports and documentation",
            "Found low severity issues",
            0.9,
        )
        self.memory_manager.remember_workflow(
            AGENT_PLANNING,
            "rate limiting decomposition",
            ["identify endpoints", "implement limiter", "add tests"],
            0.9,
        )
        self.memory_manager.remember_decision(
            AGENT_CODE_WRITING,
            "Generate typed helper with docstring",
            "write email validation helper",
            "Produced typed Python function",
            0.9,
        )


def run_quality_delta(project_root: Path | str = Path.cwd()) -> QualityDeltaReport:
    """Run baseline and enhanced quality benchmark rounds."""
    root = Path(project_root)
    baseline_report = BenchmarkSuite(root).run_all(use_mocks=True)
    enhanced_suite = EnhancedBenchmarkSuite(root)
    try:
        enhanced_report = enhanced_suite.run_all(use_mocks=True)
    finally:
        enhanced_suite.close()

    baseline_scores = _scores_by_agent(baseline_report.case_results)
    enhanced_scores = _scores_by_agent(enhanced_report.case_results)
    agents = sorted(set(baseline_scores) | set(enhanced_scores))
    deltas = {
        agent_name: enhanced_scores.get(agent_name, ZERO_SCORE)
        - baseline_scores.get(agent_name, ZERO_SCORE)
        for agent_name in agents
    }
    improvement_pct = {
        agent_name: _improvement_pct(
            baseline_scores.get(agent_name, ZERO_SCORE),
            deltas[agent_name],
        )
        for agent_name in agents
    }
    overall_improvement = (
        sum(deltas.values()) / len(deltas) if deltas else ZERO_SCORE
    )
    report = QualityDeltaReport(
        baseline_scores=baseline_scores,
        enhanced_scores=enhanced_scores,
        deltas=deltas,
        improvement_pct=improvement_pct,
        overall_improvement=overall_improvement,
        passed=overall_improvement >= PASS_THRESHOLD,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    _write_report(root, report)
    return report


def main() -> int:
    """Run quality delta measurement and print the markdown report."""
    logging.getLogger("projectos.quality_benchmark").disabled = True
    report = run_quality_delta(Path.cwd())
    print(report.to_markdown())
    return 0 if report.passed else 1


def _scores_by_agent(case_results: list[Any]) -> Dict[str, float]:
    """Return average benchmark score by agent."""
    scores: dict[str, list[float]] = {}
    for case, case_result in zip(BenchmarkSuite.BENCHMARK_CASES, case_results):
        agent_name = str(case[FIELD_AGENT])
        scores.setdefault(agent_name, []).append(float(case_result.score))
    return {
        agent_name: sum(values) / len(values)
        for agent_name, values in scores.items()
        if values
    }


def _improvement_pct(baseline: float, delta: float) -> float:
    """Return percent improvement, handling zero baseline safely."""
    if baseline == ZERO_SCORE:
        return ZERO_SCORE if delta == ZERO_SCORE else PERCENT_MULTIPLIER
    return (delta / baseline) * PERCENT_MULTIPLIER


def _write_report(root: Path, report: QualityDeltaReport) -> None:
    """Write markdown and JSONL quality delta artifacts."""
    _write_atomically(root / QUALITY_DELTA_DOC, report.to_markdown())
    _append_jsonl(root / QUALITY_DELTA_JSONL, report.to_json())


def _numpy_store_factory(
    collection_name: str,
    state_dir: Path,
    _embedder: Any,
) -> BaseVectorStore:
    """Return a deterministic local vector store."""
    return NumpyVectorStore(collection_name, state_dir)


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


if __name__ == "__main__":
    raise SystemExit(main())
