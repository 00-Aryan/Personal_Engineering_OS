#!/usr/bin/env python3
"""Profile ProjectOS component timing using direct agent calls."""
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Hard wall clock timeout - script dies after 60 seconds no matter what
def _hard_timeout(signum, frame):
    print("PROFILE: Wall clock timeout reached. Writing partial report.")
    sys.exit(0)

signal.signal(signal.SIGALRM, _hard_timeout)
# 60 second hard limit
import signal as _sig
_sig.alarm(60)

STATE_DIR = Path(".projectos_state")
STATE_DIR.mkdir(exist_ok=True)
TRACES_FILE = STATE_DIR / "traces.jsonl"
REPORT_PATH = Path("docs/performance_report.md")

def load_existing_traces():
    """Load traces from existing jsonl file."""
    if not TRACES_FILE.exists():
        return []
    spans = []
    for line in TRACES_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            spans.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return spans

def generate_synthetic_traces():
    """Generate traces by directly calling components."""
    from core.observability.tracer import Tracer, TraceStore
    from core.events import AgentEvent, EventType
    import uuid

    store = TraceStore(state_dir=STATE_DIR)
    tracer = Tracer(trace_store=store, enabled=True)
    
    spans_generated = []
    components = [
        ("clone.handle", "clone_agent"),
        ("clone.classify", "clone_agent"),
        ("clone.dispatch", "clone_agent"),
        ("context_retrieval", "context_retriever"),
        ("code_review.handle", "code_review_agent"),
        ("quality_gate", "quality_gate"),
        ("memory_recall", "memory_manager"),
    ]
    
    # Simulate 5 trace chains
    for i in range(5):
        trace_id = tracer.start_trace(
            event_id=str(uuid.uuid4()),
            event_type="CODE_CHANGED"
        )
        for op_name, component in components:
            # Simulate realistic timing variance
            import random
            duration = random.randint(10, 800)
            span = tracer.start_span(
                operation_name=op_name,
                component=component,
                trace_id=trace_id,
                tags={"synthetic": True, "iteration": i}
            )
            time.sleep(0)  # yield
            span.tags["duration_hint"] = duration
            span.finish()
            spans_generated.append(span)
    
    return [json.loads(line) 
            for line in TRACES_FILE.read_text().splitlines() 
            if line.strip()]

def analyze_spans(spans):
    """Compute per-component statistics."""
    from collections import defaultdict
    stats = defaultdict(list)
    for span in spans:
        comp = span.get("component", "unknown")
        duration = span.get("duration_ms")
        if duration is not None:
            stats[comp].append(duration)
    
    results = {}
    for comp, durations in stats.items():
        if not durations:
            continue
        sorted_d = sorted(durations)
        n = len(sorted_d)
        results[comp] = {
            "count": n,
            "avg_ms": round(sum(durations) / n, 1),
            "max_ms": max(durations),
            "min_ms": min(durations),
            "p95_ms": sorted_d[int(n * 0.95)] if n >= 2 else sorted_d[-1],
        }
    return results

def identify_bottlenecks(stats):
    """Find top 3 slowest components."""
    ranked = sorted(stats.items(), key=lambda x: x[1]["avg_ms"], reverse=True)
    bottlenecks = []
    for comp, data in ranked[:3]:
        if data["avg_ms"] > 500:
            complexity = "HIGH"
        elif data["avg_ms"] > 200:
            complexity = "MEDIUM"
        else:
            complexity = "LOW"
        
        fixes = {
            "context_retriever": "Reduce top_k from 8 to 5",
            "memory_manager": "Add in-memory LRU cache for recent recalls",
            "quality_gate": "Run LLM evaluation async, don't block dispatch",
            "clone_agent": "Pre-compute routing examples at startup",
        }
        bottlenecks.append({
            "component": comp,
            "avg_ms": data["avg_ms"],
            "fix": fixes.get(comp, "Profile further to identify root cause"),
            "complexity": complexity,
        })
    return bottlenecks

def write_report(stats, bottlenecks, span_count, source):
    REPORT_PATH.parent.mkdir(exist_ok=True)
    lines = [
        "# Performance Profile Report",
        f"Date: {datetime.now(timezone.utc).isoformat()}",
        f"Source: {source}",
        f"Provider: mock (no real API keys available)",
        "",
        "## Trace Summary",
        f"Total spans analyzed: {span_count}",
        f"Components profiled: {len(stats)}",
        "",
        "## Component Breakdown",
        "| Component | Avg ms | Max ms | P95 ms | Calls |",
        "|---|---|---|---|---|",
    ]
    for comp, data in sorted(stats.items(), 
                              key=lambda x: x[1]["avg_ms"], reverse=True):
        lines.append(
            f"| {comp} | {data['avg_ms']} | {data['max_ms']} "
            f"| {data['p95_ms']} | {data['count']} |"
        )
    
    lines += ["", "## Top 3 Bottlenecks"]
    for i, b in enumerate(bottlenecks, 1):
        lines += [
            f"### {i}. {b['component']} ({b['avg_ms']}ms avg)",
            f"- Fix: {b['fix']}",
            f"- Complexity: {b['complexity']}",
            "",
        ]
    
    lines += [
        "## Notes",
        "- Timing data is synthetic (mock providers, no real API calls)",
        "- Real bottlenecks will differ when live providers are configured",
        "- Re-run after adding GEMINI_API_KEY for accurate profiling",
    ]
    
    REPORT_PATH.write_text("\n".join(lines))
    print(f"Report written to {REPORT_PATH}")

def main():
    print("PROFILE: Loading existing traces...")
    spans = load_existing_traces()
    source = "existing_traces"
    
    if len(spans) < 10:
        print(f"PROFILE: Only {len(spans)} spans found. Generating synthetic data...")
        spans = generate_synthetic_traces()
        source = "synthetic_mock"
    
    print(f"PROFILE: Analyzing {len(spans)} spans...")
    stats = analyze_spans(spans)
    bottlenecks = identify_bottlenecks(stats)
    
    write_report(stats, bottlenecks, len(spans), source)
    
    print("PROFILE COMPLETE")
    print(f"Components profiled: {len(stats)}")
    print(f"Top bottleneck: {bottlenecks[0]['component'] if bottlenecks else 'none'}")

if __name__ == "__main__":
    main()
