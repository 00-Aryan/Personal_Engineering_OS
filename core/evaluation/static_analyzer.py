"""Deterministic static analysis for ProjectOS code quality gates."""

from __future__ import annotations

import ast
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


LOGGER_NAME = "projectos.static_analyzer"
SUBPROCESS_TIMEOUT_SECONDS = 30
PYTHON_EXTENSION = ".py"
ENCODING = "utf-8"
EMPTY_TEXT = ""

COMMAND_RADON = "radon"
COMMAND_BANDIT = "bandit"
COMMAND_FLAKE8 = "flake8"
RADON_CC_COMMAND = ["radon", "cc", "-j"]
RADON_MI_COMMAND = ["radon", "mi", "-j"]
BANDIT_COMMAND = ["bandit", "-f", "json"]

RADON_KEY_COMPLEXITY = "complexity"
RADON_KEY_TYPE = "type"
RADON_KEY_MI = "mi"
RADON_TYPE_CLASS = "class"
RADON_TYPE_FUNCTION = "function"
RADON_TYPE_METHOD = "method"

BANDIT_KEY_RESULTS = "results"
BANDIT_KEY_ISSUE_SEVERITY = "issue_severity"
BANDIT_SEVERITY_HIGH = "HIGH"
BANDIT_SEVERITY_MEDIUM = "MEDIUM"
BANDIT_SEVERITY_LOW = "LOW"

LOG_RADON_UNAVAILABLE = "radon not installed, skipping complexity"
LOG_BANDIT_UNAVAILABLE = "bandit not installed, skipping security"
LOG_FLAKE8_UNAVAILABLE = "flake8 not installed, skipping style"

ZERO_SCORE = 0.0
MAX_SCORE = 1.0
QUALITY_GATE_THRESHOLD = 0.6
STYLE_VIOLATION_SCORE_DENOMINATOR = 50.0
WEIGHT_COMPLEXITY = 0.30
WEIGHT_MAINTAINABILITY = 0.25
WEIGHT_SECURITY = 0.30
WEIGHT_STYLE = 0.15

SUMMARY_TEMPLATE = (
    "{file_path}: score={score:.2f}, passed={passed}, "
    "avg_cc={avg_cc:.2f}, high_security={high_security}, style={style}"
)


@dataclass(frozen=True)
class ComplexityMetrics:
    """Complexity and maintainability metrics for one source file."""

    file_path: str
    avg_cyclomatic_complexity: float
    max_cyclomatic_complexity: float
    maintainability_index: float
    lines_of_code: int
    comment_ratio: float
    function_count: int
    class_count: int


@dataclass(frozen=True)
class SecurityMetrics:
    """Bandit security metrics for one source file."""

    file_path: str
    high_severity_count: int
    medium_severity_count: int
    low_severity_count: int
    issues: List[Dict[str, Any]]
    bandit_available: bool


@dataclass(frozen=True)
class StyleMetrics:
    """Flake8 style metrics for one source file."""

    file_path: str
    violation_count: int
    violations: List[str]
    flake8_available: bool


@dataclass(frozen=True)
class StaticAnalysisReport:
    """Complete static analysis report for one source file."""

    file_path: str
    timestamp: datetime
    complexity: ComplexityMetrics
    security: SecurityMetrics
    style: StyleMetrics
    overall_quality_score: float
    passed_quality_gate: bool

    @property
    def summary(self) -> str:
        """Return a one-line human-readable report summary."""
        return SUMMARY_TEMPLATE.format(
            file_path=self.file_path,
            score=self.overall_quality_score,
            passed=self.passed_quality_gate,
            avg_cc=self.complexity.avg_cyclomatic_complexity,
            high_security=self.security.high_severity_count,
            style=self.style.violation_count,
        )


class StaticAnalyzer:
    """Run deterministic static analysis tools and compute quality scores."""

    def __init__(
        self,
        complexity_threshold: float = 10.0,
        maintainability_threshold: float = 20.0,
        max_security_high: int = 0,
        max_style_violations: int = 10,
    ) -> None:
        """Initialize static quality gate thresholds."""
        self.complexity_threshold = complexity_threshold
        self.maintainability_threshold = maintainability_threshold
        self.max_security_high = max_security_high
        self.max_style_violations = max_style_violations
        self._logger = logging.getLogger(LOGGER_NAME)

    def analyze(self, file_path: Path) -> StaticAnalysisReport:
        """Analyze one Python file and return a complete static report."""
        resolved_path = Path(file_path)
        complexity = self._complexity_metrics(resolved_path)
        security = self._security_metrics(resolved_path)
        style = self._style_metrics(resolved_path)
        overall_score = self._overall_quality_score(complexity, security, style)
        return StaticAnalysisReport(
            file_path=str(resolved_path),
            timestamp=datetime.now(timezone.utc),
            complexity=complexity,
            security=security,
            style=style,
            overall_quality_score=overall_score,
            passed_quality_gate=overall_score >= QUALITY_GATE_THRESHOLD,
        )

    def batch_analyze(self, file_paths: List[Path]) -> List[StaticAnalysisReport]:
        """Analyze multiple files, skipping files that fail individually."""
        reports: List[StaticAnalysisReport] = []
        for file_path in file_paths:
            try:
                reports.append(self.analyze(file_path))
            except Exception as error:
                self._logger.warning("static analysis failed for %s: %s", file_path, error)
        return reports

    def _complexity_metrics(self, file_path: Path) -> ComplexityMetrics:
        """Return radon complexity metrics, or zeros when radon is unavailable."""
        try:
            cc_process = self._run([*RADON_CC_COMMAND, str(file_path)])
            mi_process = self._run([*RADON_MI_COMMAND, str(file_path)])
        except FileNotFoundError:
            self._logger.warning(LOG_RADON_UNAVAILABLE)
            return self._empty_complexity(file_path)
        except subprocess.TimeoutExpired:
            return self._empty_complexity(file_path)

        if cc_process.returncode != 0 or mi_process.returncode != 0:
            return self._empty_complexity(file_path)

        complexities = self._radon_complexities(cc_process.stdout, file_path)
        maintainability_index = self._radon_maintainability(mi_process.stdout, file_path)
        source_text = self._source_text(file_path)
        function_count, class_count = self._ast_counts(source_text)
        if complexities:
            average_complexity = sum(complexities) / len(complexities)
            max_complexity = max(complexities)
        else:
            average_complexity = ZERO_SCORE
            max_complexity = ZERO_SCORE
        return ComplexityMetrics(
            file_path=str(file_path),
            avg_cyclomatic_complexity=average_complexity,
            max_cyclomatic_complexity=max_complexity,
            maintainability_index=maintainability_index,
            lines_of_code=self._lines_of_code(source_text),
            comment_ratio=self._comment_ratio(source_text),
            function_count=function_count,
            class_count=class_count,
        )

    def _security_metrics(self, file_path: Path) -> SecurityMetrics:
        """Return Bandit security metrics, or unavailable metrics."""
        try:
            completed_process = self._run([*BANDIT_COMMAND, str(file_path)])
        except FileNotFoundError:
            self._logger.warning(LOG_BANDIT_UNAVAILABLE)
            return self._empty_security(file_path, False)
        except subprocess.TimeoutExpired:
            return self._empty_security(file_path, True)

        issues = self._bandit_issues(completed_process.stdout)
        return SecurityMetrics(
            file_path=str(file_path),
            high_severity_count=self._severity_count(issues, BANDIT_SEVERITY_HIGH),
            medium_severity_count=self._severity_count(issues, BANDIT_SEVERITY_MEDIUM),
            low_severity_count=self._severity_count(issues, BANDIT_SEVERITY_LOW),
            issues=issues,
            bandit_available=True,
        )

    def _style_metrics(self, file_path: Path) -> StyleMetrics:
        """Return Flake8 style metrics, or unavailable metrics."""
        try:
            completed_process = self._run([COMMAND_FLAKE8, str(file_path)])
        except FileNotFoundError:
            self._logger.warning(LOG_FLAKE8_UNAVAILABLE)
            return self._empty_style(file_path, False)
        except subprocess.TimeoutExpired:
            return self._empty_style(file_path, True)

        violations = [
            line
            for line in completed_process.stdout.splitlines()
            if line.strip()
        ]
        return StyleMetrics(
            file_path=str(file_path),
            violation_count=len(violations),
            violations=violations,
            flake8_available=True,
        )

    def _overall_quality_score(
        self,
        complexity: ComplexityMetrics,
        security: SecurityMetrics,
        style: StyleMetrics,
    ) -> float:
        """Return the weighted composite quality score."""
        complexity_score = self._complexity_score(
            complexity.avg_cyclomatic_complexity
        )
        maintainability_score = complexity.maintainability_index / 100.0
        security_score = (
            MAX_SCORE
            if security.high_severity_count <= self.max_security_high
            else ZERO_SCORE
        )
        style_score = max(
            ZERO_SCORE,
            MAX_SCORE - (style.violation_count / STYLE_VIOLATION_SCORE_DENOMINATOR),
        )
        return (
            complexity_score * WEIGHT_COMPLEXITY
            + maintainability_score * WEIGHT_MAINTAINABILITY
            + security_score * WEIGHT_SECURITY
            + style_score * WEIGHT_STYLE
        )

    def _complexity_score(self, average_complexity: float) -> float:
        """Return a bounded score for average cyclomatic complexity."""
        if average_complexity <= self.complexity_threshold:
            return MAX_SCORE
        return max(
            ZERO_SCORE,
            MAX_SCORE
            - (
                (average_complexity - self.complexity_threshold)
                / self.complexity_threshold
            ),
        )

    def _run(self, command: List[str]) -> subprocess.CompletedProcess[str]:
        """Run one subprocess command with standard static-analysis settings."""
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )

    def _radon_complexities(self, output: str, file_path: Path) -> List[float]:
        """Parse radon JSON complexity values for one file."""
        try:
            payload = json.loads(output or "{}")
        except json.JSONDecodeError:
            return []
        entries = self._file_entries(payload, file_path)
        complexities: List[float] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            value = entry.get(RADON_KEY_COMPLEXITY)
            try:
                complexities.append(float(value))
            except (TypeError, ValueError):
                continue
        return complexities

    def _radon_maintainability(self, output: str, file_path: Path) -> float:
        """Parse radon JSON maintainability index for one file."""
        try:
            payload = json.loads(output or "{}")
        except json.JSONDecodeError:
            return ZERO_SCORE
        value = self._file_value(payload, file_path)
        if isinstance(value, Mapping):
            value = value.get(RADON_KEY_MI)
        try:
            return float(value)
        except (TypeError, ValueError):
            return ZERO_SCORE

    def _file_entries(self, payload: Any, file_path: Path) -> List[Any]:
        """Return list payload entries for a file from tool JSON output."""
        value = self._file_value(payload, file_path)
        return value if isinstance(value, list) else []

    def _file_value(self, payload: Any, file_path: Path) -> Any:
        """Return one file's value from a tool JSON mapping."""
        if not isinstance(payload, Mapping):
            return None
        for key in (str(file_path), file_path.name):
            if key in payload:
                return payload[key]
        if len(payload) == 1:
            return next(iter(payload.values()))
        return None

    def _bandit_issues(self, output: str) -> List[Dict[str, Any]]:
        """Parse Bandit JSON issues from subprocess output."""
        try:
            payload = json.loads(output or "{}")
        except json.JSONDecodeError:
            return []
        results = payload.get(BANDIT_KEY_RESULTS) if isinstance(payload, Mapping) else []
        if not isinstance(results, list):
            return []
        return [dict(issue) for issue in results if isinstance(issue, Mapping)]

    def _severity_count(self, issues: List[Dict[str, Any]], severity: str) -> int:
        """Return the number of Bandit issues with a given severity."""
        return sum(
            1
            for issue in issues
            if str(issue.get(BANDIT_KEY_ISSUE_SEVERITY, EMPTY_TEXT)).upper()
            == severity
        )

    def _source_text(self, file_path: Path) -> str:
        """Read source text without raising on unavailable files."""
        try:
            return file_path.read_text(encoding=ENCODING)
        except OSError:
            return EMPTY_TEXT

    def _ast_counts(self, source_text: str) -> tuple[int, int]:
        """Return function and class counts from Python AST."""
        try:
            syntax_tree = ast.parse(source_text)
        except SyntaxError:
            return 0, 0
        function_count = 0
        class_count = 0
        for node in ast.walk(syntax_tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_count += 1
            if isinstance(node, ast.ClassDef):
                class_count += 1
        return function_count, class_count

    def _lines_of_code(self, source_text: str) -> int:
        """Return non-empty lines of code in source text."""
        return len([line for line in source_text.splitlines() if line.strip()])

    def _comment_ratio(self, source_text: str) -> float:
        """Return comment lines divided by total physical lines."""
        lines = source_text.splitlines()
        if not lines:
            return ZERO_SCORE
        comment_lines = [
            line for line in lines if line.strip().startswith("#")
        ]
        return len(comment_lines) / len(lines)

    def _empty_complexity(self, file_path: Path) -> ComplexityMetrics:
        """Return zeroed complexity metrics for unavailable analysis."""
        return ComplexityMetrics(
            file_path=str(file_path),
            avg_cyclomatic_complexity=ZERO_SCORE,
            max_cyclomatic_complexity=ZERO_SCORE,
            maintainability_index=ZERO_SCORE,
            lines_of_code=0,
            comment_ratio=ZERO_SCORE,
            function_count=0,
            class_count=0,
        )

    def _empty_security(
        self,
        file_path: Path,
        bandit_available: bool,
    ) -> SecurityMetrics:
        """Return empty security metrics with availability status."""
        return SecurityMetrics(
            file_path=str(file_path),
            high_severity_count=0,
            medium_severity_count=0,
            low_severity_count=0,
            issues=[],
            bandit_available=bandit_available,
        )

    def _empty_style(self, file_path: Path, flake8_available: bool) -> StyleMetrics:
        """Return empty style metrics with availability status."""
        return StyleMetrics(
            file_path=str(file_path),
            violation_count=0,
            violations=[],
            flake8_available=flake8_available,
        )


__all__ = [
    "ComplexityMetrics",
    "SecurityMetrics",
    "StaticAnalysisReport",
    "StaticAnalyzer",
    "StyleMetrics",
]
