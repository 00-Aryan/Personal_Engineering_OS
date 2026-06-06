"""End-to-end mocked smoke test for the ProjectOS evaluation pipeline."""

from __future__ import annotations

import json
import logging
import os
import ast
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import yaml

from core.clone_agent import CloneAgent
from core.evaluation.base_evaluator import EvaluationResult
from core.evaluation.criteria_library import code_writing_criteria
from core.evaluation.evaluation_store import EvaluationStore
from core.evaluation.llm_judge import LLMJudge
from core.evaluation.quality_gate import (
    DEFAULT_POLICIES,
    GATE_LOG_NAME,
    GateDecision,
    QualityGate,
)
from core.evaluation.quality_scorer import QualityScorer
from core.evaluation.regression_detector import RegressionDetector, RegressionReport
from core.evaluation.schema_validator import DEFAULT_SCHEMAS, SchemaValidator
from core.evaluation.static_analyzer import (
    ComplexityMetrics,
    SecurityMetrics,
    StaticAnalysisReport,
    StaticAnalyzer,
    StyleMetrics,
)
from core.events import AgentResult
from core.model_provider import ModelProvider


ENCODING = "utf-8"
NEWLINE = "\n"
FILE_WRITE_MODE = "w"
TEMP_PREFIX = "."
TEMP_SUFFIX = ".tmp"
CONFIG_PATH = "config/models.yaml"
STATE_DIR_NAME = ".projectos_state"
DECISIONS_LOG_NAME = "decisions.log"
ESCALATION_QUEUE_NAME = "escalation_queue.md"
CODE_WRITING_AGENT = "code_writing"
EVALUATOR_NAME = "llm_judge"
SMOKE_SOURCE_AGENT = "evaluation_smoke"
MODEL_UNKNOWN = "unknown"
OUTPUT_FILE_NAME = "smoke_generated.py"
SMOKE_PASS_TEXT = "EVALUATION SMOKE: PASSED"
SMOKE_FAIL_TEMPLATE = "EVALUATION SMOKE: FAILED - {reason}"
OVERRIDE_REASON = "manually reviewed, safe to ship"
REGRESSION_MODEL_VERSION = "smoke-regression-model"

CLEAN_EVENT_ID = "smoke-clean"
BAD_EVENT_ID = "smoke-bad"
REGRESSION_EVENT_ID = "smoke-regression"

CLEAN_CODE = '''"""Smoke test helpers."""


def add_one(value: int) -> int:
    """Return value incremented by one."""
    return value + 1
'''
BAD_CODE = 'def broken(value: int) -> int:\n    return value +\n'


@dataclass(frozen=True)
class SmokeContext:
    """Initialized smoke-test evaluation components."""

    project_root: Path
    state_dir: Path
    evaluation_store: EvaluationStore
    schema_validator: SchemaValidator
    regression_detector: RegressionDetector
    static_analyzer: StaticAnalyzer
    quality_scorer: QualityScorer
    quality_gate: QualityGate
    clone_agent: CloneAgent
    model_version: str


class MockJudgeProvider(ModelProvider):
    """Mock judge model provider returning deterministic score JSON."""

    provider_key = "mock"

    def __init__(self, score: float, model_name: str) -> None:
        """Initialize a mock judge response score and model label."""
        self.score = score
        self.model_name = model_name

    def complete(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """Return valid LLM-judge JSON for all code-writing criteria."""
        scores = {criterion.name: self.score for criterion in code_writing_criteria()}
        return json.dumps(
            {
                "criteria_scores": scores,
                "reasoning": "mocked smoke evaluation",
                "overall_assessment": "mocked quality signal",
            },
            sort_keys=True,
        )

    def stream(self, prompt: str, system_prompt: str) -> Iterator[str]:
        """Yield the deterministic completion as one streamed fragment."""
        yield self.complete(prompt, system_prompt, 0)

    def get_model_name(self) -> str:
        """Return the configured model name used for auditability."""
        return self.model_name


class SmokeStaticAnalyzer(StaticAnalyzer):
    """Deterministic static analyzer for smoke-test source files."""

    def analyze(self, file_path: Path) -> StaticAnalysisReport:
        """Return a deterministic report based on source syntax validity."""
        source_text = Path(file_path).read_text(encoding=ENCODING)
        is_bad = self._has_syntax_error(source_text)
        score = 0.10 if is_bad else 0.95
        maintainability = 10.0 if is_bad else 95.0
        style_count = 20 if is_bad else 0
        return StaticAnalysisReport(
            file_path=str(file_path),
            timestamp=datetime.now(timezone.utc),
            complexity=ComplexityMetrics(
                file_path=str(file_path),
                avg_cyclomatic_complexity=1.0,
                max_cyclomatic_complexity=1.0,
                maintainability_index=maintainability,
                lines_of_code=len([line for line in source_text.splitlines() if line.strip()]),
                comment_ratio=0.0,
                function_count=0 if is_bad else 1,
                class_count=0,
            ),
            security=SecurityMetrics(
                file_path=str(file_path),
                high_severity_count=0,
                medium_severity_count=0,
                low_severity_count=0,
                issues=[],
                bandit_available=True,
            ),
            style=StyleMetrics(
                file_path=str(file_path),
                violation_count=style_count,
                violations=[],
                flake8_available=True,
            ),
            overall_quality_score=score,
            passed_quality_gate=score >= 0.60,
        )

    def _has_syntax_error(self, source_text: str) -> bool:
        """Return whether source text fails Python syntax parsing."""
        try:
            ast.parse(source_text)
        except SyntaxError:
            return True
        return False


def run_smoke(project_root: Optional[Path] = None) -> tuple[bool, str]:
    """Run all smoke scenarios and return success plus reason text."""
    try:
        with tempfile.TemporaryDirectory() as temporary_dir:
            smoke_root = Path(project_root) if project_root is not None else Path(temporary_dir)
            context = _context(smoke_root)
            _scenario_clean_code(context)
            bad_result = _scenario_bad_code(context)
            _scenario_regression(context)
            _scenario_override(context, str(bad_result.event_id))
        return True, SMOKE_PASS_TEXT
    except Exception as error:
        return False, SMOKE_FAIL_TEMPLATE.format(reason=error)


def main() -> int:
    """Run the smoke test and print the required status line."""
    passed, message = run_smoke()
    print(message)
    return 0 if passed else 1


def _context(project_root: Path) -> SmokeContext:
    """Initialize evaluation components for one smoke-test project root."""
    project_root.mkdir(parents=True, exist_ok=True)
    state_dir = project_root / STATE_DIR_NAME
    evaluation_store = EvaluationStore(state_dir)
    schema_validator = SchemaValidator(DEFAULT_SCHEMAS)
    regression_detector = RegressionDetector(evaluation_store, state_dir)
    static_analyzer = SmokeStaticAnalyzer()
    quality_scorer = QualityScorer(
        static_analyzer,
        evaluation_store,
        llm_weight=0.6,
        static_weight=0.4,
    )
    quality_gate = QualityGate(
        DEFAULT_POLICIES,
        quality_scorer,
        regression_detector,
        state_dir / GATE_LOG_NAME,
    )
    smoke_logger = logging.getLogger(SMOKE_SOURCE_AGENT)
    smoke_logger.disabled = True
    clone_agent = CloneAgent(
        model_provider=MockJudgeProvider(1.0, _model_version()),
        logger=smoke_logger,
        project_root=project_root,
        schema_validator=schema_validator,
        regression_detector=regression_detector,
        evaluation_store=evaluation_store,
        quality_gate=quality_gate,
    )
    return SmokeContext(
        project_root=project_root,
        state_dir=state_dir,
        evaluation_store=evaluation_store,
        schema_validator=schema_validator,
        regression_detector=regression_detector,
        static_analyzer=static_analyzer,
        quality_scorer=quality_scorer,
        quality_gate=quality_gate,
        clone_agent=clone_agent,
        model_version=_model_version(),
    )


def _scenario_clean_code(context: SmokeContext) -> None:
    """Assert the clean code path passes the full evaluation gate."""
    result = _evaluated_agent_result(
        context,
        CLEAN_EVENT_ID,
        CLEAN_CODE,
        llm_score=0.95,
    )
    validation = context.schema_validator.validate(CODE_WRITING_AGENT, result.output)
    _assert(validation.valid, "clean schema validation failed")
    context.clone_agent.process_agent_result(result, CODE_WRITING_AGENT, CLEAN_EVENT_ID)
    gate_result = context.quality_gate.recent_results(CODE_WRITING_AGENT, 1)[0]
    _assert(gate_result.decision is GateDecision.PASS, "clean gate did not pass")
    _assert(
        bool(context.evaluation_store.load_for_event(CLEAN_EVENT_ID)),
        "clean evaluation was not stored",
    )
    decisions_log = (context.project_root / DECISIONS_LOG_NAME).read_text(encoding=ENCODING)
    _assert("quality_gate PASS" in decisions_log, "clean gate decision missing")


def _scenario_bad_code(context: SmokeContext) -> object:
    """Assert the bad code path blocks and escalates."""
    result = _evaluated_agent_result(
        context,
        BAD_EVENT_ID,
        BAD_CODE,
        llm_score=0.20,
    )
    validation = context.schema_validator.validate(CODE_WRITING_AGENT, result.output)
    _assert(validation.valid, "bad schema validation failed unexpectedly")
    context.clone_agent.process_agent_result(result, CODE_WRITING_AGENT, BAD_EVENT_ID)
    gate_result = context.quality_gate.recent_results(CODE_WRITING_AGENT, 1)[0]
    _assert(gate_result.decision is GateDecision.BLOCK, "bad gate did not block")
    _assert(bool(gate_result.blocking_reasons), "bad gate had no blocking reason")
    escalation_queue = (context.project_root / ESCALATION_QUEUE_NAME).read_text(encoding=ENCODING)
    _assert(BAD_EVENT_ID in escalation_queue, "bad gate did not escalate")
    return gate_result


def _scenario_regression(context: SmokeContext) -> None:
    """Assert a seeded baseline detects regression and escalates."""
    for index in range(10):
        context.regression_detector.check_regression(
            CODE_WRITING_AGENT,
            _evaluation(0.85, f"seed-{index}", context.model_version),
            REGRESSION_MODEL_VERSION,
        )
    regression_evaluation = _evaluation(0.65, REGRESSION_EVENT_ID, context.model_version)
    regression_report = context.regression_detector.check_regression(
        CODE_WRITING_AGENT,
        regression_evaluation,
        REGRESSION_MODEL_VERSION,
    )
    _assert(regression_report.regression_detected is True, "regression not detected")
    gate = _fresh_gate_with_seeded_baseline(context)
    file_path = _write_source(context.project_root / "regression.py", CLEAN_CODE)
    gate_result = gate.evaluate(
        _agent_result(file_path, REGRESSION_EVENT_ID, regression_evaluation),
        CODE_WRITING_AGENT,
        llm_evaluation=regression_evaluation,
        file_path=file_path,
        model_version=REGRESSION_MODEL_VERSION,
    )
    _assert(gate_result.decision is GateDecision.ESCALATE, "regression gate did not escalate")


def _scenario_override(context: SmokeContext, event_id: str) -> None:
    """Assert a human override appends a BYPASS gate decision."""
    override_result = context.quality_gate.override(event_id, OVERRIDE_REASON)
    _assert(override_result.decision is GateDecision.BYPASS, "override did not bypass")
    gate_log = (context.state_dir / GATE_LOG_NAME).read_text(encoding=ENCODING)
    _assert(GateDecision.BYPASS.value in gate_log, "override missing from gate log")


def _evaluated_agent_result(
    context: SmokeContext,
    event_id: str,
    source_code: str,
    llm_score: float,
) -> AgentResult:
    """Write source, run judge, persist evaluation, and return AgentResult."""
    file_path = _write_source(context.project_root / f"{event_id}_{OUTPUT_FILE_NAME}", source_code)
    evaluation = LLMJudge(
        MockJudgeProvider(llm_score, context.model_version),
        code_writing_criteria(),
    ).evaluate(
        _agent_result(file_path, event_id, None),
        {"agent_name": CODE_WRITING_AGENT, "event_id": event_id},
    )
    context.evaluation_store.save(evaluation)
    return _agent_result(file_path, event_id, evaluation)


def _agent_result(
    file_path: Path,
    event_id: str,
    evaluation: Optional[EvaluationResult],
) -> AgentResult:
    """Return a simulated CodeWritingAgent result."""
    metadata = {"model_version": _model_version(), "event_id": event_id}
    if evaluation is not None:
        metadata["llm_evaluation"] = evaluation
    return AgentResult(
        success=True,
        output={
            "file_path": str(file_path),
            "line_count": len(file_path.read_text(encoding=ENCODING).splitlines()),
        },
        metadata=metadata,
    )


def _evaluation(score: float, event_id: str, model_version: str) -> EvaluationResult:
    """Return a deterministic EvaluationResult for regression checks."""
    return EvaluationResult(
        evaluator_name=EVALUATOR_NAME,
        agent_name=CODE_WRITING_AGENT,
        event_id=event_id,
        timestamp=datetime.now(timezone.utc),
        criteria_scores={"score": score},
        weighted_score=score,
        passed=score >= 0.70,
        reasoning="mocked regression signal",
        raw_output_sample="{}",
        evaluation_duration_ms=1,
        evaluator_model=model_version,
        metadata={},
    )


def _fresh_gate_with_seeded_baseline(context: SmokeContext) -> QualityGate:
    """Return a gate with an already-seeded regression detector."""
    seeded_detector = RegressionDetector(context.evaluation_store, context.project_root / "regression_state")
    for index in range(10):
        seeded_detector.check_regression(
            CODE_WRITING_AGENT,
            _evaluation(0.85, f"gate-seed-{index}", context.model_version),
            REGRESSION_MODEL_VERSION,
        )
    return QualityGate(
        DEFAULT_POLICIES,
        context.quality_scorer,
        seeded_detector,
        context.state_dir / GATE_LOG_NAME,
    )


def _write_source(path: Path, content: str) -> Path:
    """Write source text atomically and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{TEMP_PREFIX}{path.name}.",
        suffix=TEMP_SUFFIX,
        dir=str(path.parent),
    )
    try:
        with os.fdopen(file_descriptor, FILE_WRITE_MODE, encoding=ENCODING) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise
    return path


def _model_version() -> str:
    """Return the configured code-writing model version for smoke metadata."""
    config_path = Path(CONFIG_PATH)
    if not config_path.exists():
        return MODEL_UNKNOWN
    with config_path.open("r", encoding=ENCODING) as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict):
        return MODEL_UNKNOWN
    agents = config.get("agents")
    if not isinstance(agents, dict):
        return MODEL_UNKNOWN
    code_writing_config = agents.get(CODE_WRITING_AGENT)
    if not isinstance(code_writing_config, dict):
        return MODEL_UNKNOWN
    model_name = code_writing_config.get("model")
    return model_name if isinstance(model_name, str) and model_name else MODEL_UNKNOWN


def _assert(condition: bool, reason: str) -> None:
    """Raise AssertionError with a smoke-specific reason."""
    if not condition:
        raise AssertionError(reason)


__all__ = ["main", "run_smoke"]


if __name__ == "__main__":
    raise SystemExit(main())
