"""Tests for PerformanceMonitor."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from core.observability.tracer import Tracer, TraceStore, Span, SpanStatus
from core.observability.performance_monitor import (
    PerformanceMonitor,
    SUGGEST_REDUCING_TOP_K,
    SUGGEST_MEMORY_CACHE,
    SUGGEST_ASYNC_EVAL,
)


def test_get_component_stats_from_traces(tmp_path: Path) -> None:
    """Test component stats calculation from traces.jsonl."""
    store = TraceStore(tmp_path)
    tracer = Tracer(store)

    # Manually append to traces.jsonl to control durations exactly
    trace_file = tmp_path / "traces.jsonl"
    span_data = {
        "span_id": "span-1",
        "trace_id": "trace-1",
        "parent_span_id": None,
        "operation_name": "op",
        "component": "comp2",
        "started_at": "2026-06-07T00:00:00+00:00",
        "ended_at": "2026-06-07T00:00:00.100000+00:00",
        "duration_ms": 100,
        "status": "ok",
        "tags": {},
        "error_message": None,
    }
    with open(trace_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(span_data) + "\n")
        span_data_2 = dict(span_data, component="comp2", duration_ms=200, span_id="span-2")
        f.write(json.dumps(span_data_2) + "\n")

    monitor = PerformanceMonitor(tracer, tmp_path)
    stats = monitor.get_component_stats()

    assert "comp2" in stats
    comp2_stats = stats["comp2"]
    assert comp2_stats.call_count == 2
    assert comp2_stats.avg_duration_ms == 150.0
    assert comp2_stats.max_duration_ms == 200.0
    assert comp2_stats.p50_duration_ms == 150.0
    assert comp2_stats.p95_duration_ms == 195.0


def test_p95_computed_correctly() -> None:
    """Test linear interpolation logic for p95."""
    data = [float(x * 10) for x in range(1, 11)]
    p95 = PerformanceMonitor._percentile(data, 95.0)
    assert abs(p95 - 95.5) < 1e-9

    p95_small = PerformanceMonitor._percentile([10.0, 20.0, 30.0], 95.0)
    assert abs(p95_small - 29.0) < 1e-9


def test_get_slow_operations_filters_threshold(tmp_path: Path) -> None:
    """Test slow operations filtering."""
    store = TraceStore(tmp_path)
    tracer = Tracer(store)

    trace_file = tmp_path / "traces.jsonl"
    spans = [
        {
            "component": "comp1",
            "duration_ms": 100,
            "span_id": "s1",
            "trace_id": "t1",
            "operation_name": "op",
            "started_at": "2026-06-07T00:00:00+00:00",
            "ended_at": "2026-06-07T00:00:00.100+00:00",
            "status": "ok",
            "tags": {},
            "error_message": None,
        },
        {
            "component": "comp2",
            "duration_ms": 600,
            "span_id": "s2",
            "trace_id": "t1",
            "operation_name": "op",
            "started_at": "2026-06-07T00:00:00+00:00",
            "ended_at": "2026-06-07T00:00:00.600+00:00",
            "status": "ok",
            "tags": {},
            "error_message": None,
        },
        {
            "component": "comp3",
            "duration_ms": 500,
            "span_id": "s3",
            "trace_id": "t1",
            "operation_name": "op",
            "started_at": "2026-06-07T00:00:00+00:00",
            "ended_at": "2026-06-07T00:00:00.500+00:00",
            "status": "ok",
            "tags": {},
            "error_message": None,
        },
    ]
    with open(trace_file, "w", encoding="utf-8") as f:
        for s in spans:
            f.write(json.dumps(s) + "\n")

    monitor = PerformanceMonitor(tracer, tmp_path)
    slow = monitor.get_slow_operations(threshold_ms=500)
    assert len(slow) == 2
    ops_components = {s.component for s in slow}
    assert "comp2" in ops_components
    assert "comp3" in ops_components
    assert "comp1" not in ops_components


def test_suggest_optimizations_triggers_on_slow_retrieval(tmp_path: Path) -> None:
    """Test optimization suggestion rules."""
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    trace_file = tmp_path / "traces.jsonl"

    s_data = {
        "span_id": "s1",
        "trace_id": "t1",
        "operation_name": "context_retrieval",
        "component": "context_retriever",
        "started_at": "2026-06-07T00:00:00+00:00",
        "ended_at": "2026-06-07T00:00:00.600+00:00",
        "duration_ms": 600,
        "status": "ok",
        "tags": {},
        "error_message": None,
    }
    with open(trace_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(s_data) + "\n")

    monitor = PerformanceMonitor(tracer, tmp_path)
    suggestions = monitor.suggest_optimizations()
    assert SUGGEST_REDUCING_TOP_K in suggestions
    assert SUGGEST_MEMORY_CACHE not in suggestions
    assert SUGGEST_ASYNC_EVAL not in suggestions

    s_data_2 = {
        "span_id": "s2",
        "trace_id": "t1",
        "operation_name": "memory.recall",
        "component": "memory_manager",
        "started_at": "2026-06-07T00:00:00+00:00",
        "ended_at": "2026-06-07T00:00:00.300+00:00",
        "duration_ms": 300,
        "status": "ok",
        "tags": {},
        "error_message": None,
    }
    s_data_3 = {
        "span_id": "s3",
        "trace_id": "t1",
        "operation_name": "quality_gate.evaluate",
        "component": "quality_gate",
        "started_at": "2026-06-07T00:00:00+00:00",
        "ended_at": "2026-06-07T00:00:01.200+00:00",
        "duration_ms": 1200,
        "status": "ok",
        "tags": {},
        "error_message": None,
    }
    with open(trace_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(s_data_2) + "\n")
        f.write(json.dumps(s_data_3) + "\n")

    suggestions_all = monitor.suggest_optimizations()
    assert SUGGEST_REDUCING_TOP_K in suggestions_all
    assert SUGGEST_MEMORY_CACHE in suggestions_all
    assert SUGGEST_ASYNC_EVAL in suggestions_all


def test_cli_perf_commands(tmp_path: Path) -> None:
    """Test the perf Click CLI commands."""
    from click.testing import CliRunner
    from cli.main import cli

    # Set up some dummy trace data in .projectos_state/traces.jsonl
    state_dir = tmp_path / ".projectos_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    traces_jsonl = state_dir / "traces.jsonl"

    span_data = {
        "span_id": "span-123",
        "trace_id": "trace-123456789",
        "parent_span_id": None,
        "operation_name": "context_retrieval",
        "component": "context_retriever",
        "started_at": "2026-06-07T00:00:00+00:00",
        "ended_at": "2026-06-07T00:00:00.600000+00:00",
        "duration_ms": 600,
        "status": "ok",
        "tags": {},
        "error_message": None,
    }

    with open(traces_jsonl, "w", encoding="utf-8") as f:
        f.write(json.dumps(span_data) + "\n")

    runner = CliRunner()

    # 1. Test projectos perf stats
    result = runner.invoke(cli, ["--project-root", str(tmp_path), "perf", "stats"])
    assert result.exit_code == 0, f"Command failed: {result.output}"
    assert "context_retriever" in result.output
    assert "600.0" in result.output

    # 2. Test projectos perf slow --threshold 500
    result = runner.invoke(cli, ["--project-root", str(tmp_path), "perf", "slow", "--threshold", "500"])
    assert result.exit_code == 0, f"Command failed: {result.output}"
    assert "context_retriever" in result.output
    assert "600ms" in result.output

    # 3. Test projectos perf suggest
    result = runner.invoke(cli, ["--project-root", str(tmp_path), "perf", "suggest"])
    assert result.exit_code == 0, f"Command failed: {result.output}"
    assert SUGGEST_REDUCING_TOP_K in result.output


def test_profile_script_exits_cleanly() -> None:
    """Verify scripts/profile_session.py runs and exits cleanly within a reasonable time."""
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "scripts/profile_session.py"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "PROFILE COMPLETE" in result.stdout or "PROFILE: Wall clock timeout reached" in result.stdout


def test_report_written_after_profile_run() -> None:
    """Verify performance_report.md is successfully generated in docs/."""
    import subprocess
    import sys
    report_file = Path("docs/performance_report.md")
    
    if report_file.exists():
        report_file.unlink()
        
    result = subprocess.run(
        [sys.executable, "scripts/profile_session.py"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    
    assert result.returncode == 0
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "# Performance Profile Report" in content
