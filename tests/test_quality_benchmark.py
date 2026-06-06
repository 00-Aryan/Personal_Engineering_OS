"""Tests for the mocked quality benchmark pipeline."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.quality_benchmark import (
    BENCHMARK_HISTORY_PATH,
    BENCHMARK_RESULTS_PATH,
    BenchmarkReport,
    BenchmarkSuite,
    CaseResult,
    exit_code_for_report,
)


BASE_AGENT_CONTENT = '''"""Base agent test fixture."""

from __future__ import annotations


class BaseAgent:
    """Small fixture class."""

    def handle(self, event: object) -> object:
        """Handle a test event."""
        return event
'''


class QualityBenchmarkTestCase(unittest.TestCase):
    """Unit tests for BenchmarkSuite and BenchmarkReport."""

    def setUp(self) -> None:
        """Create an isolated benchmark project root."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        self._write_base_agent_fixture()

    def tearDown(self) -> None:
        """Clean up the isolated benchmark project root."""
        self._temp_dir.cleanup()

    def test_benchmark_suite_runs_all_cases(self) -> None:
        """Verify the suite runs every configured benchmark case."""
        report = BenchmarkSuite(self.project_root).run_all()

        self.assertEqual(report.total_cases, 3)
        self.assertEqual(len(report.case_results), 3)
        self.assertEqual(report.passed_cases, 3)

    def test_failed_case_does_not_crash_suite(self) -> None:
        """Verify one failed case is captured as a result."""
        suite = BenchmarkSuite(self.project_root)
        suite.benchmark_cases = [{"name": "bad_case", "agent": "unknown"}]

        report = suite.run_all()

        self.assertEqual(report.total_cases, 1)
        self.assertEqual(report.passed_cases, 0)
        self.assertFalse(report.case_results[0].passed)

    def test_benchmark_report_pass_rate_computed(self) -> None:
        """Verify report aggregate pass rate and score are computed."""
        report = BenchmarkReport(
            timestamp=datetime.now(timezone.utc),
            total_cases=2,
            passed_cases=1,
            pass_rate=0.5,
            avg_score=0.75,
            case_results=[
                CaseResult("pass", True, 1.0, 1, None),
                CaseResult("fail", False, 0.5, 1, "failed"),
            ],
            git_commit=None,
        )

        payload = json.loads(report.to_json())

        self.assertEqual(payload["pass_rate"], 0.5)
        self.assertEqual(payload["avg_score"], 0.75)

    def test_report_written_to_markdown(self) -> None:
        """Verify benchmark results are appended to markdown output."""
        BenchmarkSuite(self.project_root).run_all()

        markdown_path = self.project_root / BENCHMARK_RESULTS_PATH
        content = markdown_path.read_text(encoding="utf-8")

        self.assertIn("ProjectOS Quality Benchmark", content)
        self.assertIn("code_review_basic", content)

    def test_history_appended_not_overwritten(self) -> None:
        """Verify benchmark history JSONL appends every run."""
        suite = BenchmarkSuite(self.project_root)
        suite.run_all()
        suite.run_all()

        history_path = self.project_root / BENCHMARK_HISTORY_PATH
        lines = history_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 2)
        self.assertTrue(all(json.loads(line)["total_cases"] == 3 for line in lines))

    def test_exit_code_zero_on_high_pass_rate(self) -> None:
        """Verify passing benchmark reports return process exit code zero."""
        report = self._report(pass_rate=1.0)

        self.assertEqual(exit_code_for_report(report), 0)

    def test_exit_code_one_on_low_pass_rate(self) -> None:
        """Verify low pass-rate benchmark reports return process exit code one."""
        report = self._report(pass_rate=0.5)

        self.assertEqual(exit_code_for_report(report), 1)

    def _report(self, pass_rate: float) -> BenchmarkReport:
        """Return a minimal benchmark report with a selected pass rate."""
        return BenchmarkReport(
            timestamp=datetime.now(timezone.utc),
            total_cases=1,
            passed_cases=1 if pass_rate >= 1.0 else 0,
            pass_rate=pass_rate,
            avg_score=pass_rate,
            case_results=[],
            git_commit=None,
        )

    def _write_base_agent_fixture(self) -> None:
        """Write the fixture file expected by the review benchmark."""
        core_dir = self.project_root / "core"
        core_dir.mkdir(parents=True, exist_ok=True)
        (core_dir / "base_agent.py").write_text(
            BASE_AGENT_CONTENT,
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
