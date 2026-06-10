# Performance Profile Report
Date: 2026-06-10T22:30:38.189733+00:00
Source: existing_traces
Provider: mock (no real API keys available)

## Trace Summary
Total spans analyzed: 95
Components profiled: 6

## Component Breakdown
| Component | Avg ms | Max ms | P95 ms | Calls |
|---|---|---|---|---|
| code_review | 1013.0 | 1358 | 1358 | 6 |
| context_retriever | 601.0 | 851 | 851 | 6 |
| memory_manager | 129.0 | 217 | 217 | 6 |
| clone | 44.4 | 145 | 119 | 48 |
| quality_gate | 12.2 | 131 | 72 | 25 |
| code_writing | 6.5 | 8 | 8 | 4 |

## Top 3 Bottlenecks
### 1. code_review (1013.0ms avg)
- Fix: Profile further to identify root cause
- Complexity: HIGH

### 2. context_retriever (601.0ms avg)
- Fix: Reduce top_k from 8 to 5
- Complexity: HIGH

### 3. memory_manager (129.0ms avg)
- Fix: Add in-memory LRU cache for recent recalls
- Complexity: LOW

## Notes
- Timing data is synthetic (mock providers, no real API calls)
- Real bottlenecks will differ when live providers are configured
- Re-run after adding GEMINI_API_KEY for accurate profiling