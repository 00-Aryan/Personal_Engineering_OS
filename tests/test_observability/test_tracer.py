import time
import threading
from pathlib import Path
import pytest
from core.observability.tracer import Tracer, TraceStore, SpanStatus, Span

def test_start_span_returns_span(tmp_path):
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    span = tracer.start_span("test_op", "test_comp")
    assert span is not None
    assert span.operation_name == "test_op"
    assert span.component == "test_comp"
    assert span.status == SpanStatus.OK
    span.finish()

def test_span_finish_sets_duration(tmp_path):
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    span = tracer.start_span("test_op", "test_comp")
    time.sleep(0.01)
    span.finish()
    assert span.duration_ms is not None
    assert span.duration_ms >= 10
    assert span.ended_at is not None

def test_context_manager_finishes_span_on_exit(tmp_path):
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    with tracer.span("test_op", "test_comp") as span:
        assert span.ended_at is None
    assert span.ended_at is not None
    assert span.status == SpanStatus.OK

def test_context_manager_sets_error_on_exception(tmp_path):
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    with pytest.raises(ValueError, match="Boom"):
        with tracer.span("test_op", "test_comp") as span:
            raise ValueError("Boom")
    assert span.status == SpanStatus.ERROR
    assert span.error_message == "Boom"

def test_get_trace_returns_all_spans(tmp_path):
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    trace_id = tracer.start_trace("evt-123", "test_event")
    
    with tracer.span("op1", "comp1", trace_id=trace_id) as s1:
        with tracer.span("op2", "comp2", trace_id=trace_id) as s2:
            pass
            
    trace = tracer.get_trace(trace_id)
    assert len(trace) == 2
    assert trace[0].operation_name == "op1"
    assert trace[1].operation_name == "op2"

def test_spans_sorted_by_started_at(tmp_path):
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    trace_id = "trace-123"
    
    s1 = tracer.start_span("op1", "comp1", trace_id=trace_id)
    time.sleep(0.005)
    s2 = tracer.start_span("op2", "comp2", trace_id=trace_id)
    s2.finish()
    s1.finish()
    
    trace = tracer.get_trace(trace_id)
    assert len(trace) == 2
    assert trace[0].started_at < trace[1].started_at
    assert trace[0].operation_name == "op1"

def test_trace_store_persists_and_loads(tmp_path):
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    trace_id = "trace-456"
    
    with tracer.span("op1", "comp1", trace_id=trace_id) as s1:
        pass
        
    store2 = TraceStore(tmp_path)
    trace = store2.load_trace(trace_id)
    assert len(trace) == 1
    assert trace[0].operation_name == "op1"
    
    recent = store2.load_recent_traces()
    assert trace_id in recent

def test_get_slow_traces_filters_correctly(tmp_path):
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    
    # Trace 1: slow
    with tracer.span("slow_op", "comp1", tags={"event_type": "slow_evt"}) as s1:
        time.sleep(0.06)
    
    # Trace 2: fast
    with tracer.span("fast_op", "comp2", tags={"event_type": "fast_evt"}) as s2:
        pass
        
    slow = store.get_slow_traces(threshold_ms=50)
    assert len(slow) >= 1
    assert any(x["trace_id"] == s1.trace_id for x in slow)
    assert not any(x["trace_id"] == s2.trace_id for x in slow)

def test_tracer_disabled_is_noop(tmp_path):
    store = TraceStore(tmp_path)
    tracer = Tracer(store, enabled=False)
    
    trace_id = tracer.start_trace("evt-999", "noop")
    assert trace_id == ""
    
    with tracer.span("noop_op", "comp") as span:
        assert span.trace_id == ""
        
    assert not store.log_path.exists()

def test_thread_safety(tmp_path):
    store = TraceStore(tmp_path)
    tracer = Tracer(store)
    
    def worker(name):
        trace_id = tracer.start_trace(f"evt-{name}", "thread_evt")
        with tracer.span(f"op_{name}", "comp", trace_id=trace_id) as s:
            time.sleep(0.005)
            
    threads = []
    for i in range(10):
        t = threading.Thread(target=worker, args=(f"thread_{i}",))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    recent = store.load_recent_traces(limit=20)
    assert len(recent) == 10

def test_cli_trace_commands(tmp_path):
    from click.testing import CliRunner
    from cli.main import cli
    import json
    
    runner = CliRunner()
    
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    models_yaml = config_dir / "models.yaml"
    models_yaml.write_text("""
providers:
  gemini:
    default_model: gemini-1.5-flash
agents:
  clone:
    provider: gemini
    model: gemini-1.5-flash
""", encoding="utf-8")
    
    state_dir = tmp_path / ".projectos_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    traces_jsonl = state_dir / "traces.jsonl"
    
    span_data = {
        "span_id": "span-123",
        "trace_id": "trace-123456789",
        "parent_span_id": None,
        "operation_name": "clone.handle",
        "component": "clone",
        "started_at": "2026-06-07T00:00:00+00:00",
        "ended_at": "2026-06-07T00:00:00.450000+00:00",
        "duration_ms": 450,
        "status": "ok",
        "tags": {"event_type": "CODE_CHANGED", "event_id": "evt-123"},
        "error_message": None
    }
    
    with open(traces_jsonl, "w", encoding="utf-8") as f:
        f.write(json.dumps(span_data, sort_keys=True) + "\n")
        
    result = runner.invoke(cli, ["--project-root", str(tmp_path), "trace", "list"])
    assert result.exit_code == 0
    assert "trace-12" in result.output
    assert "CODE_CHANGED" in result.output
    assert "450ms" in result.output
    
    result = runner.invoke(cli, ["--project-root", str(tmp_path), "trace", "show", "trace-12"])
    assert result.exit_code == 0
    assert "clone.handle" in result.output
    assert "450ms" in result.output
    
    result = runner.invoke(cli, ["--project-root", str(tmp_path), "trace", "slow", "--threshold", "100"])
    assert result.exit_code == 0
    assert "trace-12" in result.output
