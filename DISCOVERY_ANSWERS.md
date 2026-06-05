# DISCOVERY_ANSWERS.md
# Project: ProjectOS
# Author: Aryan Kumar | June 2026

---

## VISION

**Classification:** Personal Engineering OS — autonomous multi-agent 
system handling full SDLC for my projects without requiring me to 
context-switch between engineering roles.

**Current Users:** Only me (Aryan Kumar)

**Long-term:** Open-source → contributor community → potential product

---

## CORE PROBLEM

I cannot simultaneously maintain:
- Academic focus (IIT Madras final year)
- Project development (content creation pipeline, DS projects)
- Startup ideation

Current AI tools are REACTIVE (do what you ask, once).
I need a PROACTIVE system that runs continuously without me.

### Specific Pain Points
1. No continuous code quality enforcement
2. No architecture challenge before building wrong
3. Tests get skipped because painful — then break production
4. Context loss across sessions — why was this decision made?
5. Can't hold multiple engineering mindsets simultaneously
6. Multiple tasks at once cause hallucination or shallow output
7. One blocked permission halts entire workflow

---

## THE CLONE (Meta-Agent)

A supervisor agent that:
- Observes ALL other agents continuously
- Makes autonomous decisions for small/routine matters
- Escalates ONLY important decisions (architecture, breaking changes, 
  new dependencies) to me
- If Task A needs permission → Clone starts Task B immediately
- Plans reconnection between blocked and parallel tasks
- Represents my engineering judgment when I'm unavailable

---

## AGENT ROSTER

All 5 required. Phased delivery acceptable.

| Agent | Trigger | Output |
|---|---|---|
| Planning Agent | New idea / sprint start | Backlog, tasks, constraints |
| Code Review Agent | Any code change | Review report, issues flagged |
| Architecture Agent | New feature / design decision | ADR, risk flags |
| Test Agent | Any code change | Tests written + run automatically |
| Documentation Agent | Any code change | Docs updated automatically |

---

## PLUGGABLE MODEL ARCHITECTURE

CRITICAL REQUIREMENT: Swapping the model for any single agent must 
require changing ONE config value only.

### Initial Model Assignments (by benchmark)
- Planning → DeepSeek V4 (strong reasoning)
- Coding/Implementation → Minimax 2.5 (free, strong code)
- Review → TBD (benchmark first)

### Model Switch Interface
/model <agent_name> <model_name>
Example: /model code-review deepseek-v4

### Supported Providers (launch)
- OpenRouter (free tier — DeepSeek V4, Minimax 2.5)
- Ollama (local fallback)
- Future: paid APIs as drop-in replacements

### Data Structure Rule
All model calls go through a single ModelProvider interface.
No agent hardcodes any model or API format.

---

## AUTONOMY RULES

- Routine fixes → fully autonomous, no interruption
- Important decisions → Clone decides or pings me
- Blocked task → never stops other tasks, Clone queues reconnection
- Code change → auto-triggers: tests + docs + backlog update
- Continuous enforcement of: deliverables, constraints, standards

---

## INTERACTION

- Primary: CLI
- Background: daemon process (runs while I study)
- Key commands: /model, /status, /approve, /backlog, /review

---

## SCOPE

### In Scope
- Python projects (DS, RAG, LLM pipelines, some frontend)
- My personal projects only at launch
- Single machine deployment

### Explicitly OUT of Scope (v1)
- Multi-user support
- Web dashboard  
- Self-modifying agents
- Enterprise features
- Non-Python projects at launch

---

## BUDGET CONSTRAINTS

- ₹0 for first 3-4 months — free models only
- Architecture must allow paid API drop-in with zero refactoring
- Ollama as offline fallback

---

## 30-DAY SUCCESS DEFINITION

Minimum: Clone + Planning Agent + Code Review Agent working end-to-end
Stretch: All 5 agents scaffolded, 3 fully functional
Must-have: /model switch working, daemon running in background